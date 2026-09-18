import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from image_utils import download_images


def test_download_images_writes_local_files(tmp_path, monkeypatch):
    class FakeResp:
        status_code = 200
        content = b"fake-image-bytes"
        headers = {"content-type": "image/jpeg"}

        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr("image_utils.httpx.get", lambda *args, **kwargs: FakeResp())
    paths = download_images(["https://example.com/a.jpg"], tmp_path)
    assert len(paths) == 1
    assert Path(paths[0]).exists()
    assert Path(paths[0]).read_bytes() == b"fake-image-bytes"


def test_download_images_skips_failures(tmp_path, monkeypatch):
    class FakeResp:
        status_code = 403
        content = b""
        headers = {}

        def __init__(self, *args, **kwargs):
            pass

    monkeypatch.setattr("image_utils.httpx.get", lambda *args, **kwargs: FakeResp())
    assert download_images(["https://example.com/b.jpg"], tmp_path) == []