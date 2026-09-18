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
        "outbox_dir": "outbox",
        "outbox_sent_dir": "sent",
    }
    store = SessionStore(Path(tmp) / "sessions.json")
    bridge = Bridge(cfg, store, AgentClient(cfg))
    bridge.ws = FakeWS()
    bridge.outbox_dir = Path(tmp) / "outbox"
    bridge.outbox_sent_dir = bridge.outbox_dir / "sent"
    bridge.outbox_dir.mkdir(parents=True, exist_ok=True)
    bridge.outbox_sent_dir.mkdir(exist_ok=True)
    bridge.memory_path = Path(tmp) / "memory.md"
    return bridge


def test_outbox_flush_sends_and_archives():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge = make_bridge(tmp)
            (bridge.outbox_dir / "report-1.txt").write_text("项目已完成测试。", encoding="utf-8")
            await bridge._flush_outbox()
            assert len(bridge.ws.sent) == 1
            assert bridge.ws.sent[0]["params"]["message"] == "项目已完成测试。"
            assert not list(bridge.outbox_dir.glob("*.txt"))
            assert list(bridge.outbox_sent_dir.glob("*report-1.txt"))

    asyncio.run(scenario())


def test_outbox_keeps_file_when_ws_disconnected():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge = make_bridge(tmp)
            target = bridge.outbox_dir / "report-2.txt"
            target.write_text("待发送", encoding="utf-8")
            bridge.ws = None
            await bridge._flush_outbox()
            assert target.exists()
            assert list(bridge.outbox_sent_dir.iterdir()) == []

    asyncio.run(scenario())
