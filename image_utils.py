"""图片 URL 下载为本地文件，避免 QQ 无法加载外链图。"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Iterable
from pathlib import Path

import httpx

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _ext_from_content_type(content_type: str) -> str:
    ctype = (content_type or "").lower()
    if "png" in ctype:
        return ".png"
    if "gif" in ctype:
        return ".gif"
    if "webp" in ctype:
        return ".webp"
    if "avif" in ctype:
        return ".avif"
    return ".jpg"


def download_images(
    urls: Iterable[str],
    dest_dir: Path,
    limit: int = 3,
    timeout: float = 20.0,
) -> list[str]:
    """下载最多 limit 张图片到本地，返回可发送的本地路径列表。"""
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    for url in urls:
        if len(paths) >= limit:
            break
        try:
            resp = httpx.get(
                url,
                timeout=timeout,
                trust_env=False,
                follow_redirects=True,
                headers={
                    "User-Agent": _USER_AGENT,
                    "Referer": "https://www.pixiv.net/",
                },
            )
            if resp.status_code != 200 or not resp.content:
                continue
            ext = _ext_from_content_type(resp.headers.get("content-type", ""))
            name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16] + ext
            target = dest_dir / name
            target.write_bytes(resp.content)
            if target.stat().st_size > 0:
                paths.append(str(target))
        except Exception as exc:
            logging.warning("图片下载失败 %s: %s", url, exc)
    return paths