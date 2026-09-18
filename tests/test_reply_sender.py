import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reply_sender import send_reply


class FakeBridge:
    def __init__(self, cfg=None):
        self.cfg = cfg or {
            "persona_chat_max_chars": 40,
            "persona_chat_max_segments": 4,
            "persona_chat_delay_sec": 0,
            "chunk_limit": 3800,
            "chunk_delay_sec": 0,
            "forward_threshold": 5,
            "voice_max_per_reply": 1,
            "voice_fallback_text": "（语音合成失败）",
        }
        self.sent = []
        self.media_sent = []
        self.voice_sender = None

    async def _send_private(self, user_id, text):
        self.sent.append((user_id, text))

    async def _send_private_record(self, user_id, path):
        self.sent.append((user_id, path))

    async def _send_media_marker(self, user_id, marker):
        self.media_sent.append((user_id, marker))


def test_send_reply_sends_chunked_text(tmp_path):
    bridge = FakeBridge()
    asyncio.run(send_reply(bridge, "10001", "你好"))
    assert bridge.sent == [("10001", "你好")]


def test_send_reply_roleplay_splits(tmp_path):
    bridge = FakeBridge()
    asyncio.run(send_reply(bridge, "10001", "这是一段很长的话。" * 10, persona_mode=True))
    assert len(bridge.sent) > 1


def test_send_reply_handles_media_marker(tmp_path):
    bridge = FakeBridge()
    asyncio.run(send_reply(bridge, "10001", "看图\n[IMAGE:/tmp/a.png]"))
    assert bridge.media_sent[0][1]["kind"] == "image"
