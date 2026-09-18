import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sessions import SessionStore


def test_session_store_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp) / "sessions.json")
        assert store.get_thread("10001") is None
        store.set_thread("10001", "thread-abc")
        store2 = SessionStore(Path(tmp) / "sessions.json")
        assert store2.get_thread("10001") == "thread-abc"
        assert store2.reset("10001") is True
        assert store2.get_thread("10001") is None


def test_proactive_state_roundtrip_and_touch():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp) / "sessions.json")
        assert store.get_proactive_state("10001") == {}
        state = {"paused": True, "count": 2, "fixed_done": ["2026-08-06|09:30"]}
        store.save_proactive_state("10001", state)
        store2 = SessionStore(Path(tmp) / "sessions.json")
        assert store2.get_proactive_state("10001") == state
        store2.touch_activity("10001")
        loaded = store2.get_proactive_state("10001")
        assert loaded["paused"] is True
        assert "last_active_ts" in loaded


def test_persona_turns_and_started_ts():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp) / "sessions.json")
        store.set_persona_thread("10001", "rp-1")
        assert store.get_persona_turns("10001") == 0
        assert store.increment_persona_turns("10001") == 1
        assert store.get_persona_turns("10001") == 1
        store.set_persona_thread("10001", "rp-1")
        assert store.get_persona_turns("10001") == 1
        assert store.get_persona_started_ts("10001") is not None
        store.set_persona_thread("10001", "rp-2")
        assert store.get_persona_turns("10001") == 0
        store.reset_persona("10001")
        assert store.get_persona_thread("10001") is None
        assert store.get_persona_turns("10001") == 0


def test_task_follow_state_roundtrip_and_reset():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp) / "sessions.json")
        assert store.get_task_follow("10001") == {"active": False, "last_task_ts": 0.0}
        store.mark_task_follow("10001", now=1234.5)
        loaded = store.get_task_follow("10001")
        assert loaded["active"] is True
        assert loaded["last_task_ts"] == 1234.5
        store2 = SessionStore(Path(tmp) / "sessions.json")
        loaded2 = store2.get_task_follow("10001")
        assert loaded2["active"] is True
        assert loaded2["last_task_ts"] == 1234.5
        store2.clear_task_follow("10001")
        assert store2.get_task_follow("10001")["active"] is False
        store2.mark_task_follow("10001", now=2000.0)
        store2.reset_persona("10001")
        assert store2.get_task_follow("10001")["active"] is False
