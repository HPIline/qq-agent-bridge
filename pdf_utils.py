from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from vision_client import ocr_image

#: 可选：poppler / tesseract 所在目录（Windows 上没有全局 PATH 时很有用）。
#: 通过环境变量 QQBOT_PDF_TOOL_DIR 指定，例如 C:\Program Files\poppler\Library\bin
_PDFTOOL_ENV = os.environ.get("QQBOT_PDF_TOOL_DIR", "").strip()
PDFTOOL_DIR = Path(_PDFTOOL_ENV) if _PDFTOOL_ENV else None


def _find_tool(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if PDFTOOL_DIR:
        for suffix in ("", ".exe", ".cmd", ".bat"):
            candidate = PDFTOOL_DIR / f"{name}{suffix}"
            if candidate.is_file():
                return str(candidate)
    return None


async def extract_pdf_text(
    pdf_path: str,
    max_pages: int = 10,
    timeout: int = 120,
    lang: str = "chi_sim+eng",
) -> str:
    """提取 PDF 文字：优先 pdftotext，缺失时用 pdftoppm 渲染 + Tesseract OCR。"""
    if _find_tool("tesseract") is None:
        return ""

    pdftotext = _find_tool("pdftotext")
    if pdftotext:
        try:
            proc = subprocess.run(
                [pdftotext, str(pdf_path), "-"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            if proc.returncode == 0 and len(proc.stdout.strip()) >= 50:
                return proc.stdout.strip()
        except Exception:
            pass

    pdftoppm = _find_tool("pdftoppm")
    if pdftoppm is None:
        return ""

    pages: list[str] = []
    real_tmp = str(Path(tempfile.gettempdir()).resolve())
    with tempfile.TemporaryDirectory(prefix="pdf-ocr-", dir=real_tmp) as tmp:
        prefix = str(Path(tmp) / "page")
        cmd = [
            pdftoppm,
            "-png",
            "-r",
            "200",
            "-f",
            "1",
            "-l",
            str(max_pages),
            str(pdf_path),
            prefix,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except Exception:
            return ""
        if proc.returncode != 0:
            return ""
        images = sorted(Path(tmp).glob("page-*.png"))
        for image in images:
            try:
                text = await ocr_image(str(image), lang=lang, timeout=timeout)
            except Exception:
                text = ""
            if text:
                pages.append(text)
    return "\n\n".join(pages).strip()
