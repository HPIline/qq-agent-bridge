import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from media import download_incoming_image


class FakeBridge:
    def __init__(self, action_result, tmp):
        self.action_result = action_result
        self.calls = []
        self.tmp_dir = Path(tmp)

    async def _call_action(self, action, params, timeout=60):
        self.calls.append((action, params))
        return self.action_result


def test_download_incoming_image_prefers_napcat_local_path(monkeypatch, tmp_path):
    local = tmp_path / "napcat_cache.png"
    local.write_bytes(b"png")
    bridge = FakeBridge({"file": str(local), "url": "http://fresh"}, tmp_path)
    captured: dict = {}

    async def fake_download(url, dest_dir):
        captured["url"] = url
        return str(dest_dir / "downloaded.png")

    monkeypatch.setattr("media.download_image", fake_download)
    result = asyncio.run(
        download_incoming_image(bridge, {"url": "http://old", "file": "abc.image"})
    )
    assert result == str(local)
    assert bridge.calls == [("get_image", {"file": "abc.image"})]
    assert "url" not in captured


def test_download_incoming_image_uses_fresh_url_from_get_image(monkeypatch, tmp_path):
    bridge = FakeBridge({"url": "http://fresh"}, tmp_path)
    captured: dict = {}

    async def fake_download(url, dest_dir):
        captured["url"] = url
        return str(dest_dir / "downloaded.png")

    monkeypatch.setattr("media.download_image", fake_download)
    asyncio.run(download_incoming_image(bridge, {"url": "http://old", "file": "abc.image"}))
    assert captured["url"] == "http://fresh"


def test_download_incoming_image_falls_back_to_event_url(monkeypatch, tmp_path):
    bridge = FakeBridge({}, tmp_path)
    captured: dict = {}

    async def fake_download(url, dest_dir):
        captured["url"] = url
        return str(dest_dir / "downloaded.png")

    monkeypatch.setattr("media.download_image", fake_download)
    asyncio.run(download_incoming_image(bridge, {"url": "http://old", "file": "abc.image"}))
    assert captured["url"] == "http://old"


def test_download_incoming_image_raises_without_url_or_file(tmp_path):
    bridge = FakeBridge({}, tmp_path)
    try:
        asyncio.run(download_incoming_image(bridge, {}))
        raise AssertionError("应当抛出 RuntimeError")
    except RuntimeError as exc:
        assert "缺少" in str(exc)
