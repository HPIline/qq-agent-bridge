from __future__ import annotations

import asyncio
import base64
import os
import re
import time
import urllib.request
from pathlib import Path

#: Windows 上不能作为文件名的保留设备名
_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def safe_filename(name: str, fallback: str = "file") -> str:
    """把任意名称收敛成跨平台安全的文件名（Windows 非法字符 / 保留名都处理）。"""
    name = (name or "").strip().replace("\\", "/").split("/")[-1]
    # 非法字符统一替换成下划线（: * ? " < > | 以及控制字符都会被 \w 之外的规则命中）
    name = re.sub(r"[^\w.\-\u4e00-\u9fff]+", "_", name)
    name = name.strip("._") or fallback
    stem = name.split(".")[0].lower()
    if stem in _RESERVED_NAMES:
        name = f"_{name}"
    return name[:120]


def _unique_dest(dest_dir: Path, filename: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{time.time_ns()}_{filename}"
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{time.time_ns()}_{counter}_{filename}"
        counter += 1
    return dest


async def download_file(url: str, dest_dir: str | os.PathLike[str], name: str | None = None) -> str:
    dest_dir_path = Path(dest_dir)
    filename = safe_filename(name or Path(url.split("?")[0]).name, fallback="file")
    dest = _unique_dest(dest_dir_path, filename)

    def _download() -> None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=60) as resp, open(dest, "wb") as out:
            out.write(resp.read())

    await asyncio.to_thread(_download)
    return str(dest)


async def save_base64_data(
    data: str | bytes, dest_dir: str | os.PathLike[str], name: str | None = None
) -> str:
    dest_dir_path = Path(dest_dir)
    filename = safe_filename(name or "file", fallback="file")
    dest = _unique_dest(dest_dir_path, filename)
    if isinstance(data, bytes):
        data = data.decode("ascii", errors="ignore")
    raw = data.split(",", 1)[-1]
    payload = base64.b64decode(raw)
    await asyncio.to_thread(dest.write_bytes, payload)
    return str(dest)
