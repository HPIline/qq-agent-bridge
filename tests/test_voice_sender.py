import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice_sender import VoiceSender


class FakeTTS:
    def __init__(self):
        self.calls = 0

    async def synthesize(self, text: str) -> bytes:
        self.calls += 1
        return b"FAKE-WAV-" + text.encode()


def test_voice_sender_sends_and_caches():
    sent = []

    async def send_record(user_id: str, path: str):
        sent.append((user_id, path))

    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "tts_character": "测试角色",
                "tts_ref": "01_平静",
                "voice_max_chars": 120,
                "voice_cache_dir": tmp,
            }
            tts = FakeTTS()
            sender = VoiceSender(cfg, tts, silk_encoder=lambda data: b"SILK-" + data)
            ok1 = await sender.send_voice("10001", "こんにちは。", send_record)
            ok2 = await sender.send_voice("10001", "こんにちは。", send_record)
            assert ok1 and ok2
            assert len(sent) == 2
            assert sent[0][1].startswith("base64://")
            assert tts.calls == 1

    asyncio.run(scenario())


def test_voice_sender_rejects_long_text():
    async def send_record(user_id: str, path: str):
        raise AssertionError("不应发送")

    async def scenario():
        cfg = {
            "tts_character": "测试角色",
            "tts_ref": "01_平静",
            "voice_max_chars": 5,
            "voice_cache_dir": tempfile.gettempdir(),
        }
        sender = VoiceSender(cfg, FakeTTS(), silk_encoder=lambda data: b"SILK-" + data)
        ok = await sender.send_voice("10001", "こんにちはこんにちは", send_record)
        assert ok is False

    asyncio.run(scenario())
