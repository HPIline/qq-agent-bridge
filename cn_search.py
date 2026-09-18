"""国内直连中文搜索：走 Bing 中国（cn.bing.com），无需代理、无需外网。

用于满足“国内网络直接 web search 直连”的检索需求：中文资料、热梗、新闻、
产品口碑等走这里；真正需要外网内容时再走 web_search。
"""

from __future__ import annotations

import html as _html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import httpx

#: 中性 UA：不暴露宿主机操作系统
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

def _skills_dir() -> Path:
    custom = os.environ.get("QQBOT_SKILLS_DIR", "").strip()
    return Path(custom).expanduser() if custom else Path.home() / ".agents" / "skills"


_BAIDU_SKILL_DIR = _skills_dir() / "baidu-api-search"


def extract_results(html_text: str, max_results: int = 8) -> list[dict[str, str]]:
    """从 cn.bing 的 HTML 里抽出结果块：标题 / URL / 摘要。"""
    blocks = re.split(r'<li class="b_algo"', html_text or "")[1:]
    results: list[dict[str, str]] = []
    for block in blocks[:max_results]:
        match = re.search(
            r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            block,
            re.S,
        )
        if not match:
            continue
        url = match.group(1).strip()
        title = re.sub(r"<[^>]+>", "", match.group(2))
        snippet_match = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        snippet = ""
        if snippet_match:
            snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1))
        results.append(
            {
                "title": _html.unescape(title).strip(),
                "url": url,
                "snippet": _html.unescape(snippet).strip(),
            }
        )
    return results


def format_results(results: list[dict[str, str]]) -> str:
    if not results:
        return "（国内直连搜索没有返回结果）"
    lines: list[str] = []
    for index, result in enumerate(results, start=1):
        snippet = result.get("snippet") or ""
        if len(snippet) > 200:
            snippet = snippet[:200] + "…"
        lines.append(f"{index}. {result['title']}\n   {result['url']}\n   {snippet}")
    return "\n".join(lines)


def search_cn(query: str, timeout: float = 15.0, max_results: int = 8) -> str:
    """国内直连搜索，返回格式化结果文本。"""
    resp = httpx.get(
        "https://cn.bing.com/search",
        params={"q": query, "mkt": "zh-CN", "setlang": "zh-hans"},
        headers={
            "User-Agent": _USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        timeout=timeout,
        trust_env=False,
        follow_redirects=True,
    )
    resp.raise_for_status()
    return format_results(extract_results(resp.text, max_results))


def search_cn_images(query: str, timeout: float = 15.0, max_results: int = 8) -> list[str]:
    """国内直连搜图：从 cn.bing 图片搜索里提取原图 URL（murl）。"""
    resp = httpx.get(
        "https://cn.bing.com/images/search",
        params={"q": query, "mkt": "zh-CN"},
        headers={
            "User-Agent": _USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9",
        },
        timeout=timeout,
        trust_env=False,
        follow_redirects=True,
    )
    resp.raise_for_status()
    urls: list[str] = []
    seen: set[str] = set()
    # cn.bing 的 HTML 里通常形如 murl&quot;:&quot;http://...&quot;
    for match in re.finditer(r'murl&quot;:&quot;(.*?)&quot;', resp.text):
        url = _html.unescape(match.group(1)).strip()
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= max_results:
            break
    return urls


def _baidu_search(query: str, timeout: float = 60.0) -> str:
    """用 GitHub 抓来的 baidu-api-search skill 做中文检索（需要 BAIDU_AI_SEARCH_API_KEYS）。"""
    script = _BAIDU_SKILL_DIR / "scripts" / "search.py"
    if not script.is_file():
        raise FileNotFoundError(f"未找到 baidu-api-search 脚本：{script}")
    cmd = [
        sys.executable,
        str(script),
        "--topic",
        query,
        "--mode",
        "fast",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(_BAIDU_SKILL_DIR),
        env=os.environ.copy(),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"baidu-api-search 退出码 {proc.returncode}: {proc.stderr[-500:]}")
    try:
        data = json.loads(proc.stdout or "")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"baidu-api-search 输出不是 JSON：{exc}") from exc
    pack_path = data.get("research_pack")
    if pack_path and Path(pack_path).is_file():
        content = Path(pack_path).read_text(encoding="utf-8", errors="replace")
        if content.strip():
            return content.strip()[:3000]
    return str(proc.stdout or "").strip()[:3000]


def search_domestic(query: str, timeout: float = 60.0) -> str:
    """国内搜索统一入口：有百度 API Key 用 baidu-api-search skill，否则用 cn.bing 直连。"""
    if os.environ.get("BAIDU_AI_SEARCH_API_KEYS", "").strip():
        try:
            return _baidu_search(query, timeout=timeout)
        except Exception:
            # 百度 skill 失败时降级到 cn.bing 直连，不让搜索断掉
            return search_cn(query, timeout=15.0)
    return search_cn(query, timeout=15.0)
