from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: 中性浏览器 UA（部分上游会拦截默认 python UA）
BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

# OpenCode Go 要求每个会话一个稳定的 x-opencode-session 头。
# 同一进程内固定一个 ID，保证看图/课表请求稳定可归属。
OPENCODE_SESSION_HEADER = f"vision-{uuid.uuid4().hex}"


def _load_api_key(api_key: str | None = None) -> str:
    if api_key and str(api_key).strip():
        return str(api_key).strip()
    for env_name in ("QQBOT_API_KEY", "OPENAI_API_KEY", "OPENCODE_GO_API_KEY"):
        env_key = os.environ.get(env_name, "").strip()
        if env_key:
            return env_key
    # 可选：从任意 JSON 凭据文件里读 OPENAI_API_KEY（QQBOT_AUTH_FILE）
    auth_file = os.environ.get("QQBOT_AUTH_FILE", "").strip()
    if auth_file:
        try:
            data = json.loads(Path(auth_file).expanduser().read_text(encoding="utf-8"))
            key = str(data.get("OPENAI_API_KEY") or data.get("api_key") or "").strip()
            if key:
                return key
        except Exception:
            pass
    raise ValueError(
        "未配置视觉 API key：请设置 config.json 的 vision_api_key / api_key，"
        "或环境变量 QQBOT_API_KEY / OPENAI_API_KEY"
    )


DEFAULT_CHAT_URL = "https://api.openai.com/v1/chat/completions"


@dataclass(frozen=True)
class VisionSettings:
    """辅助视觉调用的解析结果（识图/课表/视频帧描述/找图过滤）。

    默认直接复用主模型：主模型是多模态的，就不再单列一个识图模型。
    旧配置里的 `mimo_vision_*` 仍然可读，仅作兼容。
    """

    url: str
    model: str
    api_key: str
    timeout: int
    max_tokens: int


def _chat_completions_url(value: str) -> str:
    url = str(value or "").strip().rstrip("/")
    if not url:
        return DEFAULT_CHAT_URL
    return url if url.endswith("/chat/completions") else f"{url}/chat/completions"


def _as_int(value: object, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def vision_settings(cfg: dict[str, Any] | None = None) -> VisionSettings:
    """解析视觉调用参数：vision_* > 主模型（model）。"""
    cfg = cfg or {}
    model = str(
        cfg.get("vision_model") or cfg.get("mimo_vision_model") or cfg.get("model") or ""
    ).strip() or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
    base_url = str(
        cfg.get("vision_url")
        or cfg.get("mimo_vision_url")
        or cfg.get("api_base_url")
        or ""
    ).strip()
    api_key = str(
        cfg.get("vision_api_key")
        or cfg.get("mimo_vision_api_key")
        or cfg.get("api_key")
        or ""
    ).strip()
    return VisionSettings(
        url=_chat_completions_url(base_url),
        model=model,
        api_key=api_key,
        timeout=_as_int(cfg.get("vision_timeout_sec"), 150),
        max_tokens=_as_int(
            cfg.get("vision_max_tokens") or cfg.get("mimo_vision_max_tokens"), 2000
        ),
    )


def _image_data_url(image_path: str) -> str:
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    suffix = Path(image_path).suffix.lower().lstrip(".")
    mime = {
        "jpg": "jpeg",
        "jpeg": "jpeg",
        "png": "png",
        "gif": "gif",
        "webp": "webp",
        "bmp": "bmp",
    }.get(suffix, "jpeg")
    return f"data:image/{mime};base64,{b64}"


def build_vision_payload(
    image_path: str,
    model: str,
    prompt: str,
    max_tokens: int = 2000,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_data_url(image_path)},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "stream": False,
        "max_tokens": max_tokens,
    }


async def call_opencode_chat(
    api_url: str,
    payload: dict[str, Any],
    api_key: str,
    timeout: int = 150,
) -> dict[str, Any]:
    def _call() -> dict[str, Any]:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": BROWSER_UA,
            "Accept": "application/json",
        }
        if "opencode" in api_url:
            # opencode-go 要求每个会话一个稳定的 x-opencode-session 头
            headers["x-opencode-session"] = OPENCODE_SESSION_HEADER
        req = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
        )
        with opener.open(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return await asyncio.to_thread(_call)


def build_vision_prompt(user_text: str = "") -> str:
    user_part = f"用户发来的文字是：{user_text}\n\n" if str(user_text or "").strip() else ""
    return (
        user_part + "你是图片扫描器，只描述事实，不推测、不评价、不给建议。\n"
        "先用一句话判断这张图片最可能是什么（物品、角色、场景、截图类型等），并说明置信度。\n"
        "然后按条目列出可确认的事实：\n"
        "- 主体与数量\n"
        "- 人物/生物：身份线索、动作、表情\n"
        "- 文字内容（尽量逐字输出原文）\n"
        "- 颜色、布局、空间关系\n"
        "- 风格、材质、品牌、角色等可辨认标识\n"
        "最后【不确定项】必须列出：图片里你无法确认身份/名称/含义、需要联网查证的内容，"
        "逐条写清楚外观线索；如果角色、物品、场景的名字或身份无法确认，必须写进这一项；"
        "没有则写“无”。\n"
        "不要寒暄，不要重复，控制在 800 字以内，不要凭样子瞎猜。"
    )


async def describe_image(
    image_path: str,
    api_url: str,
    model: str,
    api_key: str | None = None,
    timeout: int = 150,
    max_tokens: int = 1200,
    prompt: str | None = None,
) -> str:
    payload = build_vision_payload(
        image_path,
        model,
        prompt or build_vision_prompt(),
        max_tokens=max_tokens,
    )
    try:
        data = await call_opencode_chat(
            api_url,
            payload,
            _load_api_key(api_key),
            timeout=timeout,
        )
        content = str(
            (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
        ).strip()
        if not content:
            raise ValueError("视觉模型返回空内容")
        return content
    except Exception as exc:
        return f"（图片已收到，但识图失败：{exc}）"


async def download_image(url: str, dest_dir: str | os.PathLike[str]) -> str:
    dest_dir_path = Path(dest_dir)
    dest_dir_path.mkdir(parents=True, exist_ok=True)
    ext = ".img"
    for candidate in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"):
        if candidate in url.lower():
            ext = candidate
            break
    dest = dest_dir_path / f"img_{os.getpid()}_{len(list(dest_dir_path.iterdir()))}{ext}"

    def _download() -> None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
            },
        )
        try:
            with opener.open(req, timeout=30) as resp, open(dest, "wb") as out:
                out.write(resp.read())
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                raw = exc.read()
                if isinstance(raw, bytes):
                    detail = raw.decode("utf-8", errors="replace")[:200]
                else:
                    detail = str(raw)[:200]
            except Exception:
                pass
            raise RuntimeError(
                f"图片下载失败：HTTP {exc.code} {exc.reason} {detail}".strip()
            ) from exc

    await asyncio.to_thread(_download)
    return str(dest)


async def ocr_image(
    image_path: str,
    lang: str = "chi_sim+eng",
    timeout: int = 30,
) -> str:
    """用 Tesseract 提取图片文字；首选配置语言，失败时回退英文。"""
    if shutil.which("tesseract") is None:
        return ""

    def _run() -> str:
        for candidate in (lang, "eng"):
            cmd = ["tesseract", str(image_path), "stdout", "-l", candidate, "--psm", "6"]
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
            except Exception:
                continue
            if proc.returncode == 0:
                text = proc.stdout.strip()
                if text:
                    return text
        return ""

    return await asyncio.to_thread(_run)


def build_timetable_payload(
    image_path: str,
    model: str,
    max_tokens: int = 1024,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": _image_data_url(image_path)},
                    },
                    {
                        "type": "text",
                        "text": (
                            "识别图片中的课程表，输出为 CSV 文本，第一行是表头："
                            "day,start,end,name,location,weeks。"
                            "day 用 1-7 表示周一到周日；start/end 用 HH:MM；"
                            "weeks 留空表示每周，“单周”或“双周”表示单双周；"
                            "每行一门课，字段用英文逗号分隔，不加引号；无法确定的字段留空。"
                            "只输出 CSV，不要解释。"
                        ),
                    },
                ],
            }
        ],
        "stream": False,
        "max_tokens": max_tokens,
    }


async def extract_timetable_text(
    image_path: str,
    api_url: str,
    model: str,
    api_key: str | None = None,
    timeout: int = 150,
    max_tokens: int = 1024,
) -> str:
    payload = build_timetable_payload(image_path, model, max_tokens=max_tokens)
    data = await call_opencode_chat(
        api_url,
        payload,
        _load_api_key(api_key),
        timeout=timeout,
    )
    content = str(
        (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    ).strip()
    if not content:
        raise RuntimeError("课表识别失败：模型返回空内容")
    return content