import asyncio
import base64
import json
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tts_client import LocalGPTSoVITSClient, find_character, find_ref, load_characters


def _write_characters_json(root: Path) -> None:
    (root / "GPT_weights_v2").mkdir(parents=True)
    data = [
        {
            "name": "测试角色",
            "gpt": "GPT_weights_v2/TestVoice_A_20241002-e10.ckpt",
            "sovits": "SoVITS_weights_v2/TestVoice_A_20241002_e12_s108.pth",
            "refs": [
                {
                    "name": "01_default",
                    "file": "predef_ref/ref_a/01_ref.wav",
                    "text": "私が再び異常動作を起こさないという確証はない。",
                }
            ],
        }
    ]
    (root / "GPT_weights_v2" / "characters.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    ref = root / "predef_ref" / "ref_a"
    ref.mkdir(parents=True)
    (ref / "01_ref.wav").write_bytes(b"REFWAV")


class FakeTTSHandler(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def log_message(self, *args):
        pass

    def _send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        FakeTTSHandler.calls.append({"method": "GET", "path": self.path})
        if self.path.startswith("/set_gpt_weights") or self.path.startswith("/set_sovits_weights"):
            self._send_json({"code": 0, "msg": "ok"})
        else:
            self._send_json({"code": 1, "msg": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        FakeTTSHandler.calls.append({"method": "POST", "path": self.path, "payload": payload})
        wav = b"RIFF-test-wav"
        body = json.dumps(
            {"code": 0, "msg": "成功", "data": {"audio": base64.b64encode(wav).decode()}}
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_load_characters_and_find():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_characters_json(root)
        chars = load_characters(root / "GPT_weights_v2" / "characters.json")
        char = find_character(chars, "测试角色")
        assert char is not None
        ref = find_ref(char, "01_default")
        assert ref["text"].startswith("私が再び")


def test_local_client_synthesizes_wav():
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeTTSHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_characters_json(root)
            cfg = {
                "tts_local_url": f"http://127.0.0.1:{server.server_port}/tts",
                "tts_models_dir": str(root),
                "tts_character": "测试角色",
                "tts_ref": "01_default",
                "tts_timeout_sec": 10,
            }
            client = LocalGPTSoVITSClient(cfg)
            wav = asyncio.run(client.synthesize("こんにちは。"))
            assert wav == b"RIFF-test-wav"
            post_calls = [c for c in FakeTTSHandler.calls if c["method"] == "POST"]
            assert post_calls
            payload = post_calls[0]["payload"]
            assert payload["text"] == "こんにちは。"
            assert payload["text_lang"] == "all_ja"
            assert payload["prompt_text"].startswith("私が再び")
            assert payload["ref_audio_path"].endswith("01_ref.wav")
            assert any("set_gpt_weights" in c["path"] for c in FakeTTSHandler.calls)
    finally:
        server.shutdown()
