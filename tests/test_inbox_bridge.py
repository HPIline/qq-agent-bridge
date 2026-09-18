import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_client import AgentClient
from bridge import Bridge
from sessions import SessionStore


def make_bridge(tmp: str, **overrides) -> Bridge:
    fake_agent = Path(__file__).resolve().parent / "fake_agent.py"
    os.chmod(fake_agent, 0o755)
    cfg = {
        "onebot_ws_url": "ws://127.0.0.1:1",
        "full_access_qq": ["10001"],
        "agent_path": str(fake_agent),
        "workdir": tmp,
        "request_timeout": 10,
        "inbox_dir": "inbox",
        "inbox_log_file": "feedback.log",
        "inbox_log_max_lines": 200,
        "decisions_dir": "decisions",
        "pending_file": "pending.json",
    }
    cfg.update(overrides)
    store = SessionStore(Path(tmp) / "sessions.json")
    bridge = Bridge(cfg, store, AgentClient(cfg))
    bridge.inbox_dir = Path(tmp) / "inbox"
    bridge.feedback_log_path = bridge.inbox_dir / "feedback.log"
    bridge.decisions_dir = Path(tmp) / "decisions"
    bridge.pending_path = bridge.decisions_dir / "pending.json"
    bridge.inbox_dir.mkdir(parents=True, exist_ok=True)
    bridge.decisions_dir.mkdir(parents=True, exist_ok=True)
    return bridge


def test_feedback_log_appends_message():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = make_bridge(tmp)
        bridge._log_feedback("10001", "继续干活")
        entries = [
            json.loads(line)
            for line in bridge.from_qq_log_path.read_text(encoding="utf-8").splitlines()
        ]
        assert entries[-1]["user_id"] == "10001"
        assert entries[-1]["text"] == "继续干活"
        assert entries[-1]["ts"]


def test_feedback_log_caps_lines():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = make_bridge(tmp, inbox_log_max_lines=3, inbox_log_max_bytes=0)
        for i in range(5):
            bridge._log_feedback("10001", f"消息{i}")
        lines = bridge.from_qq_log_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 3
        assert json.loads(lines[-1])["text"] == "消息4"


def test_pending_decision_captures_next_reply():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = make_bridge(tmp)
        bridge.pending_path.write_text(
            json.dumps(
                {
                    "id": "d1",
                    "question": "继续还是暂停？",
                    "status": "waiting",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        captured = bridge._maybe_capture_pending_reply("10001", "继续")
        data = json.loads(bridge.pending_path.read_text(encoding="utf-8"))
        assert captured is not None
        assert captured["reply"] == "继续"
        assert data["status"] == "answered"
        assert data["reply"] == "继续"
        assert data["replied_at"]


def test_pending_decision_ignored_without_waiting():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = make_bridge(tmp)
        bridge.pending_path.write_text(
            json.dumps(
                {
                    "id": "d1",
                    "status": "answered",
                    "reply": "旧回复",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        assert bridge._maybe_capture_pending_reply("10001", "新回复") is None
        data = json.loads(bridge.pending_path.read_text(encoding="utf-8"))
        assert data["reply"] == "旧回复"
