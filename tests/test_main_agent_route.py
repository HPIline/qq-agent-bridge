import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_client import AgentClient
from bridge import Bridge
from sessions import SessionStore


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


def make_bridge(tmp: str) -> Bridge:
    fake_agent = Path(__file__).resolve().parent / "fake_agent.py"
    os.chmod(fake_agent, 0o755)
    cfg = {
        "onebot_ws_url": "ws://127.0.0.1:1",
        "full_access_qq": ["10001"],
        "agent_path": str(fake_agent),
        "workdir": tmp,
        "request_timeout": 10,
        "main_agent_prefixes": ["/本机"],
        "main_agent_inbox_file": "channels/from_qq/main.jsonl",
    }
    store = SessionStore(Path(tmp) / "sessions.json")
    bridge = Bridge(cfg, store, AgentClient(cfg))
    bridge.ws = FakeWS()
    bridge.main_agent_inbox_path = Path(tmp) / "channels/from_qq/main.jsonl"
    bridge.main_agent_inbox_path.parent.mkdir(parents=True, exist_ok=True)
    return bridge


def test_on_event_routes_main_agent_message_and_acks():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge = make_bridge(tmp)
            event = {
                "post_type": "message",
                "message_type": "private",
                "message_id": "9001",
                "user_id": 10001,
                "message": [{"type": "text", "data": {"text": "/本机 测试转交"}}],
                "sender": {"user_id": 10001, "nickname": "owner"},
            }
            await bridge._on_event(event)
            lines = bridge.main_agent_inbox_path.read_text(encoding="utf-8").splitlines()
            assert len(lines) == 1
            assert json.loads(lines[0])["text"] == "测试转交"
            assert bridge.ws.sent[-1]["params"]["message"] == "……收到，已转给主控。"
            assert bridge.buffer_tasks.get("10001") is None

    asyncio.run(scenario())


def test_on_event_normal_message_not_routed():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge = make_bridge(tmp)
            event = {
                "post_type": "message",
                "message_type": "private",
                "message_id": "9002",
                "user_id": 10001,
                "message": [{"type": "text", "data": {"text": "你好"}}],
                "sender": {"user_id": 10001, "nickname": "owner"},
            }
            await bridge._on_event(event)
            assert not bridge.main_agent_inbox_path.exists()
            assert bridge.buffer_tasks.get("10001") is not None

    asyncio.run(scenario())
