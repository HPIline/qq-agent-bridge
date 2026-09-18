import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from bridge import Bridge
from sessions import SessionStore
from state_db import StateDB
from task_manager import TaskManager
from web_panel import WebPanel


class FakeBridge:
    def __init__(self, tmp_path):
        self.cfg = {
            "web_token": "test-token",
            "web_host": "127.0.0.1",
            "web_port": 18080,
            "full_access_qq": ["10001"],
        }
        self.state_db = StateDB(tmp_path / "state.db")
        self.task_manager = TaskManager(self, self.state_db)
        self.store = None
        self.ws = None
        self.web_replies = {}

    async def process_web_message(self, user_id, text, timeout=900):
        return [f"echo:{text}"]


def test_root_serves_page_without_token(tmp_path):
    panel = WebPanel(FakeBridge(tmp_path))
    client = TestClient(panel.app)
    r = client.get("/")
    assert r.status_code == 200
    assert "QQ AI 助手" in r.text


def test_requires_token(tmp_path):
    panel = WebPanel(FakeBridge(tmp_path))
    client = TestClient(panel.app)
    r = client.get("/api/status")
    assert r.status_code == 401
    r = client.get("/api/status", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_status_authed(tmp_path):
    panel = WebPanel(FakeBridge(tmp_path))
    client = TestClient(panel.app)
    r = client.get("/api/status", headers={"Authorization": "Bearer test-token"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["bot"] == "qq-agent-bridge"


def test_chat_endpoint(tmp_path):
    panel = WebPanel(FakeBridge(tmp_path))
    client = TestClient(panel.app)
    headers = {"Authorization": "Bearer test-token"}
    r = client.post("/api/chat", json={"text": "你好"}, headers=headers)
    assert r.status_code == 200
    assert r.json()["replies"] == ["echo:你好"]


def test_reminders_post(tmp_path):
    bridge = FakeBridge(tmp_path)
    panel = WebPanel(bridge)
    client = TestClient(panel.app)
    headers = {"Authorization": "Bearer test-token"}
    r = client.post("/api/reminders", json={"text": "喝水 明天9点"}, headers=headers)
    assert r.status_code == 200
    assert "已设置提醒" in r.json()["message"]


def test_web_chat_uses_bridge_pipeline(tmp_path):
    class FakeCodex:
        async def run(
            self,
            prompt,
            thread_id=None,
            timeout=None,
            reasoning_effort=None,
            image_paths=None,
            model=None,
            model_provider=None,
            bypass_proxy=False,
        ):
            return "网页回复", "thread-web"

    cfg = {
        "full_access_qq": ["10001"],
        "workdir": str(tmp_path),
        "persona_enabled": False,
        "plugins_enabled": False,
        "batch_window": 0.1,
        "image_wait_window": 0.1,
        "chunk_delay_sec": 0,
        "ack_delay_sec": 0,
        "forward_threshold": 99,
    }
    store = SessionStore(tmp_path / "sessions.json")
    bridge = Bridge(cfg, store, FakeCodex())
    replies = asyncio.run(bridge.process_web_message("web-main", "你好"))
    assert any("网页回复" in r for r in replies)
