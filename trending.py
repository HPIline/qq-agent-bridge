"""主动会话的“近期热梗/热搜”素材抓取（可选功能）。

通过子进程调用一个外部搜索脚本（默认 ~/.agents/skills/grok-search/scripts/grok_search.py）
抓取实时素材，再把结果注入主动会话提示词。

脚本路径可用 config 的 grok_search_script / grok_search_python 覆盖；
没有配置或脚本不存在时，会安静地降级为空素材，不影响正常聊天。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def _default_skills_dir() -> Path:
    """外部技能目录：环境变量 QQBOT_SKILLS_DIR 优先，其次 ~/.agents/skills。"""
    custom = os.environ.get("QQBOT_SKILLS_DIR", "").strip()
    if custom:
        return Path(custom).expanduser()
    return Path.home() / ".agents" / "skills"


SEARCH_SKILL_DIR = _default_skills_dir() / "grok-search"
DEFAULT_QUERY = "最近有什么网络热梗/热搜，适合日常聊天的轻松话题"
DEFAULT_NEWS_QUERY = "今日 AI 与科技领域值得关注的新闻和进展"
DEFAULT_ART_QUERY = "推荐3-5位近期活跃的二次元画师，直接列出名字和Pixiv/推特账号，每个人一句话介绍"
DEFAULT_ART_IMAGE_QUERY = "今日Pixiv/推特 二次元画师 新作 图片"

# 进程内缓存：同一进程短时间内多次主动开口只搜索一次。
_CACHE: dict[str, Any] = {}
_PREFETCH_TASK: asyncio.Task[Any] | None = None

_IMAGE_URL_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def extract_image_urls(text: str) -> list[str]:
    """从 grok 返回的 Markdown 图片里提取 URL。"""
    if not text:
        return []
    urls: list[str] = []
    seen: set[str] = set()
    for match in _IMAGE_URL_RE.finditer(text):
        url = match.group(1).strip().rstrip(".,;")
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def parse_grok_json(raw: str) -> dict[str, Any]:
    """从脚本 stdout 中解析 JSON；容忍前后有日志噪音。"""
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(f"grok-search 输出不是 JSON：{raw[:200]}")
    data = json.loads(raw[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("grok-search JSON 不是对象")
    return data


def load_search_api_key() -> str:
    """按 grok-search skill 的约定读取 API key，不打印明文。"""
    key = os.environ.get("GROK_API_KEY", "").strip()
    if key:
        return key
    key = os.environ.get("XAI_API_KEY", "").strip()
    if key:
        return key
    config_path = Path(
        os.environ.get("QQBOT_GROK_CONFIG", "") or (Path.home() / ".grok" / "config.toml")
    )
    try:
        import tomllib

        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
        key = str(data["model"]["grok-4.5"]["api_key"] or "").strip()
        if key:
            return key
    except Exception:
        pass
    raise ValueError(
        "未找到 GROK_API_KEY（设置环境变量 GROK_API_KEY / XAI_API_KEY，"
        "或 QQBOT_GROK_CONFIG 指向 grok config.toml）"
    )


def run_search_sync(
    query: str,
    image_search: bool = False,
    timeout: float = 90.0,
    script_path: str = "",
    python_path: str = "",
) -> dict[str, Any]:
    """同步运行 grok_search.py，返回 text / citations / image_urls。"""
    script = Path(script_path).expanduser() if script_path else (
        SEARCH_SKILL_DIR / "scripts" / "grok_search.py"
    )
    if not script.is_file():
        raise FileNotFoundError(f"未找到 grok-search 脚本：{script}")
    cmd = [
        python_path or sys.executable,
        str(script),
        query,
        "--web",
        "--effort",
        "low",
        "--json",
    ]
    if image_search:
        cmd.append("--image-search")
    env = os.environ.copy()
    # grok-search skill 要求不走本地注入代理；launchd 环境常带 127.0.0.1 代理，
    # 这里显式移除，避免连接被代理拒绝。
    for proxy_key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
    ):
        env.pop(proxy_key, None)
    env.setdefault("GROK_API_KEY", load_search_api_key())
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(SEARCH_SKILL_DIR),
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"grok-search 退出码 {proc.returncode}: {proc.stderr[-500:]}")
    data = parse_grok_json(proc.stdout or "")
    text = str(data.get("text") or "").strip()
    citations = [str(x) for x in (data.get("citations") or []) if str(x).strip()]
    image_urls = [str(x) for x in (data.get("image_urls") or []) if str(x).strip()]
    if not image_urls:
        image_urls = extract_image_urls(text)
    return {"text": text, "citations": citations, "image_urls": image_urls}


def run_search_from_cfg(
    cfg: dict[str, Any],
    query: str,
    image_search: bool = False,
    timeout: float | None = None,
) -> dict[str, Any]:
    """按配置调用外部搜索脚本（脚本路径 / Python 解释器 / 超时都可配）。"""
    return run_search_sync(
        query,
        image_search=image_search,
        timeout=float(timeout if timeout is not None else cfg.get("proactive_trending_timeout_sec", 60)),
        script_path=str(cfg.get("web_search_script") or ""),
        python_path=str(cfg.get("web_search_python") or ""),
    )


def format_trending_context(data: dict[str, Any], include_images: bool = True) -> str:
    """把搜索结果拼成可注入提示词的素材块。"""
    text = str(data.get("text") or "").strip()
    if not text:
        return ""
    lines = [text]
    citations = [str(x) for x in (data.get("citations") or []) if str(x).strip()]
    if citations:
        lines.append("来源：" + " ".join(citations[:5]))
    if include_images:
        image_urls = [str(x) for x in (data.get("image_urls") or []) if str(x).strip()]
        if image_urls:
            lines.append("可选的梗图 URL（如果合适可以发一张，用 [IMAGE:URL] 标记）：")
            lines.extend(f"- {url}" for url in image_urls[:5])
    return "\n".join(lines)


def get_cached_trending_context(
    cfg: dict[str, Any],
    cache: dict[str, Any] | None = None,
    now: Any | None = None,
) -> str:
    """只读当前热梗缓存；未命中/过期/禁用时返回空字符串，绝不触发网络。"""
    if not cfg.get("proactive_trending_enabled", True):
        return ""
    cache_obj = cache if cache is not None else _CACHE
    now_ts = float(now.timestamp()) if now is not None else time.time()
    ttl = float(cfg.get("proactive_trending_ttl_hours", 6)) * 3600.0
    if cache_obj.get("ts") and now_ts - float(cache_obj["ts"]) < ttl:
        return str(cache_obj.get("text") or "")
    return ""


def prefetch_trending(
    cfg: dict[str, Any],
    cache: dict[str, Any] | None = None,
) -> None:
    """在后台预热热梗缓存，避免主动开口时等待搜索。

    调用方必须是异步上下文；缓存已新鲜或已有后台任务在跑时直接返回。
    """
    global _PREFETCH_TASK
    if not cfg.get("proactive_trending_enabled", True):
        return
    if get_cached_trending_context(cfg, cache=cache):
        return
    if _PREFETCH_TASK is not None and not _PREFETCH_TASK.done():
        return
    cache_obj = cache if cache is not None else _CACHE
    _PREFETCH_TASK = asyncio.create_task(fetch_trending_context(cfg, cache=cache_obj))


async def fetch_trending_context(
    cfg: dict[str, Any],
    cache: dict[str, Any] | None = None,
    now: Any | None = None,
) -> str:
    """抓取“今日内容池”素材：热梗/梗图 + AI科技要闻 + 二次元画师新作。

    带 TTL 缓存，各类搜索独立容错：某一路失败不拖垮其他路。
    """
    if not cfg.get("proactive_trending_enabled", True):
        return ""
    cache_obj = cache if cache is not None else _CACHE
    now_ts = float(now.timestamp()) if now is not None else time.time()
    ttl = float(cfg.get("proactive_trending_ttl_hours", 6)) * 3600.0
    if cache_obj.get("ts") and now_ts - float(cache_obj["ts"]) < ttl:
        return str(cache_obj.get("text") or "")
    timeout = float(cfg.get("proactive_trending_timeout_sec", 60))

    async def _search(query: str, image_search: bool, label: str) -> str | None:
        try:
            data = await asyncio.to_thread(
                run_search_sync,
                query,
                image_search,
                timeout,
                str(cfg.get("web_search_script") or ""),
                str(cfg.get("web_search_python") or ""),
            )
            body = format_trending_context(data, include_images=image_search)
            if not body:
                return None
            return f"【{label}】\n{body}"
        except Exception:
            logging.warning("%s 搜索失败，跳过该路素材", label, exc_info=True)
            return None

    tasks: list[asyncio.Task[str | None]] = []
    # 热梗/梗图
    meme_query = str(cfg.get("proactive_trending_query") or DEFAULT_QUERY)
    meme_image_search = bool(cfg.get("proactive_trending_image_search_enabled", True))
    tasks.append(asyncio.create_task(_search(meme_query, meme_image_search, "今日热梗/梗图")))

    # AI/科技要闻
    if cfg.get("proactive_news_enabled", True):
        news_query = str(cfg.get("proactive_news_query") or DEFAULT_NEWS_QUERY)
        tasks.append(asyncio.create_task(_search(news_query, False, "AI/科技要闻")))

    # 二次元画师：自动发现画师 + 找新作/图片
    if cfg.get("proactive_art_enabled", True):
        art_query = str(cfg.get("proactive_art_query") or DEFAULT_ART_QUERY)
        art_image_query = str(
            cfg.get("proactive_art_image_query") or DEFAULT_ART_IMAGE_QUERY
        )
        artists = cfg.get("proactive_artists") or []
        if artists:
            artist_text = "、".join(str(a).strip() for a in artists if str(a).strip())
            art_query = f"{art_query}（已关注画师：{artist_text}；同时再自动推荐其他活跃画师）"
            art_image_query = f"{art_image_query}（关注画师：{artist_text}）"
        tasks.append(asyncio.create_task(_search(art_query, False, "二次元画师推荐")))
        tasks.append(asyncio.create_task(_search(art_image_query, True, "画师新作/新图")))

    results = await asyncio.gather(*tasks)
    sections = [r for r in results if r]
    result = "\n\n".join(sections)
    if not result:
        logging.warning("主动话题内容池为空（热梗/AI要闻/画师新作均未返回）")
        return ""
    cache_obj["ts"] = now_ts
    cache_obj["text"] = result
    return result