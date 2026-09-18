import asyncio
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vision_client import (
    _load_api_key,
    build_timetable_payload,
    build_vision_payload,
    build_vision_prompt,
    call_opencode_chat,
    describe_image,
    download_image,
    extract_timetable_text,
)


class FakeResp:
    def __init__(self, text: str):
        self._text = text

    def read(self) -> bytes:
        return self._text.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _make_png(tmp_path) -> str:
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    return str(img)


def test_build_vision_payload_contains_data_url(tmp_path):
    path = _make_png(tmp_path)
    payload = build_vision_payload(path, "mimo-v2.5", "描述")
    assert payload["model"] == "mimo-v2.5"
    part = payload["messages"][0]["content"][0]
    assert part["type"] == "image_url"
    assert part["image_url"]["url"].startswith("data:image/png;base64,")


def test_vision_prompt_includes_user_text_and_uncertainty():
    prompt = build_vision_prompt("这是什么角色？")
    assert "用户发来的文字是：这是什么角色？" in prompt
    assert "【不确定项】" in prompt
    assert "只描述事实" in prompt


def test_call_opencode_chat_uses_browser_ua_and_auth(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        headers = dict(req.header_items())
        captured["ua"] = headers.get("User-agent")
        captured["auth"] = headers.get("Authorization")
        return FakeResp(json.dumps({"choices": [{"message": {"content": "ok"}}]}))

    class FakeOpener:
        def open(self, req, timeout=None):
            return fake_urlopen(req, timeout=timeout)

    monkeypatch.setattr("vision_client.urllib.request.build_opener", lambda *a, **kw: FakeOpener())
    data = asyncio.run(
        call_opencode_chat(
            "https://opencode.ai/zen/go/v1/chat/completions",
            {"model": "mimo-v2.5"},
            "sk-test",
            timeout=5,
        )
    )
    assert captured["url"].endswith("/chat/completions")
    assert "Mozilla/5.0" in captured["ua"]
    assert captured["auth"] == "Bearer sk-test"
    assert data["choices"][0]["message"]["content"] == "ok"


def test_describe_image_returns_content(monkeypatch, tmp_path):
    path = _make_png(tmp_path)

    async def fake_call(url, payload, key, timeout=150):
        return {"choices": [{"message": {"content": "一只猫"}}]}

    monkeypatch.setattr("vision_client.call_opencode_chat", fake_call)
    result = asyncio.run(
        describe_image(
            path,
            "https://opencode.ai/zen/go/v1/chat/completions",
            "mimo-v2.5",
            api_key="k",
        )
    )
    assert result == "一只猫"


def test_describe_image_failure_is_graceful(monkeypatch, tmp_path):
    path = _make_png(tmp_path)

    async def fake_call(url, payload, key, timeout=150):
        raise RuntimeError("boom")

    monkeypatch.setattr("vision_client.call_opencode_chat", fake_call)
    result = asyncio.run(
        describe_image(
            path,
            "https://opencode.ai/zen/go/v1/chat/completions",
            "mimo-v2.5",
            api_key="k",
        )
    )
    assert "识图失败" in result


def test_api_key_priority_and_auth_json(monkeypatch, tmp_path):
    assert _load_api_key("explicit") == "explicit"
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "env-key")
    assert _load_api_key() == "env-key"
    monkeypatch.delenv("OPENCODE_GO_API_KEY")
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"OPENAI_API_KEY": "file-key"}), encoding="utf-8")
    monkeypatch.setenv("QQBOT_AUTH_FILE", str(auth))
    assert _load_api_key() == "file-key"


def test_build_timetable_payload(tmp_path):
    path = _make_png(tmp_path)
    payload = build_timetable_payload(path, "mimo-v2.5")
    assert payload["model"] == "mimo-v2.5"
    text = payload["messages"][0]["content"][1]["text"]
    assert "day,start,end,name,location,weeks" in text


def test_extract_timetable_text_parses_content(monkeypatch, tmp_path):
    path = _make_png(tmp_path)

    async def fake_call(url, payload, key, timeout=150):
        return {
            "choices": [
                {
                    "message": {
                        "content": "day,start,end,name,location,weeks\n1,08:00,09:40,数学,A101,"
                    }
                }
            ]
        }

    monkeypatch.setattr("vision_client.call_opencode_chat", fake_call)
    result = asyncio.run(
        extract_timetable_text(
            path,
            "https://opencode.ai/zen/go/v1/chat/completions",
            "mimo-v2.5",
            api_key="k",
        )
    )
    assert "day,start,end,name" in result


def test_download_image_bypasses_proxy_and_sets_headers(monkeypatch, tmp_path):
    captured: dict = {}

    class FakeOpener:
        def __init__(self, handlers):
            captured["handlers"] = handlers

        def open(self, req, timeout=None):
            captured["req"] = req
            captured["timeout"] = timeout

            class Resp:
                def __enter__(self_):
                    return self_

                def __exit__(self_, *args):
                    return False

                def read(self_):
                    return b"\x89PNG\r\n\x1a\n"

            return Resp()

    monkeypatch.setattr(
        "vision_client.urllib.request.build_opener", lambda *handlers: FakeOpener(handlers)
    )
    result = asyncio.run(download_image("https://example.com/a.png", tmp_path))
    assert result.startswith(str(tmp_path / "img_"))
    assert result.endswith(".png")
    assert any(
        isinstance(h, urllib.request.ProxyHandler) and h.proxies == {} for h in captured["handlers"]
    )
    headers = dict(captured["req"].header_items())
    assert "Mozilla/5.0" in headers.get("User-agent", "")
    assert "image" in headers.get("Accept", "")
    assert captured["timeout"] == 30


def test_download_image_http_error_includes_body(monkeypatch, tmp_path):
    body = '{"retcode":-5503007,"retmsg":"download url has expired"}'

    class FakeOpener:
        def open(self, req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {}, io.StringIO(body))

    monkeypatch.setattr("vision_client.urllib.request.build_opener", lambda *handlers: FakeOpener())
    try:
        asyncio.run(download_image("https://example.com/a.png", tmp_path))
        raise AssertionError("应当抛出 RuntimeError")
    except RuntimeError as exc:
        assert "400" in str(exc)
        assert "download url has expired" in str(exc)


def test_vision_settings_follows_main_model_by_default():
    from vision_client import vision_settings

    settings = vision_settings({"model": "test-model", "api_key": "k"})
    assert settings.model == "test-model"
    assert settings.url.endswith("/chat/completions")
    assert settings.api_key == "k"


def test_vision_settings_prefers_explicit_and_legacy_keys():
    from vision_client import vision_settings

    settings = vision_settings(
        {
            "model": "main-model",
            "vision_model": "vision-model",
            "vision_url": "https://example.com/v1",
            "vision_max_tokens": 1234,
        }
    )
    assert settings.model == "vision-model"
    assert settings.url == "https://example.com/v1/chat/completions"
    assert settings.max_tokens == 1234
    assert vision_settings({"model": "main", "mimo_vision_model": "legacy-vision"}).model == "legacy-vision"
    assert vision_settings({}).model
