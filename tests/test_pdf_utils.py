import asyncio
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdf_utils import extract_pdf_text


def test_extract_pdf_text_returns_text_for_fixture():
    """需要一个本地 PDF 才能跑；用环境变量 QQBOT_TEST_PDF 指定，缺省跳过。"""
    import os

    candidate = os.environ.get("QQBOT_TEST_PDF", "")
    fixture = Path(candidate).expanduser() if candidate else Path()
    if not candidate or not fixture.is_file():
        import pytest

        pytest.skip("未设置 QQBOT_TEST_PDF（PDF 测试文件不存在）")
    if shutil.which("tesseract") is None:
        import pytest

        pytest.skip("tesseract 未安装")
    result = asyncio.run(extract_pdf_text(str(fixture), max_pages=1, timeout=60))
    assert isinstance(result, str)
    assert result.strip()


def test_extract_pdf_text_returns_empty_without_tools(monkeypatch):
    import pdf_utils

    monkeypatch.setattr(pdf_utils, "_find_tool", lambda name: None)
    result = asyncio.run(extract_pdf_text("any.pdf", max_pages=1, timeout=5))
    assert result == ""
