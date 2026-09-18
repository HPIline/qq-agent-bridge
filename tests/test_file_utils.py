import asyncio
import base64
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from file_utils import download_file, safe_filename, save_base64_data


def test_safe_filename():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename("a/b/c.txt") == "c.txt"
    assert safe_filename("") == "file"
    assert safe_filename("中文 名称.txt") == "中文_名称.txt"


def test_download_file():
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "data.zip"
        source.write_bytes(b"file-content")
        path = asyncio.run(download_file(source.as_uri(), tmp, "data.zip"))
        assert Path(path).read_bytes() == b"file-content"
        assert path.endswith("data.zip")


def test_save_base64_data():
    with tempfile.TemporaryDirectory() as tmp:
        path = asyncio.run(save_base64_data(base64.b64encode(b"abc"), tmp, "x.bin"))
        assert Path(path).read_bytes() == b"abc"
