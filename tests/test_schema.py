import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import schema
from sessions import SessionStore


def test_normalize_pending_decision_defaults():
    data = schema.normalize_pending({"id": "d1", "question": "继续？"})
    assert data["version"] == 1
    assert data["kind"] == "decision"
    assert data["status"] == "waiting"
    assert data["created_at"]
    assert "thread_id" not in data


def test_normalize_pending_task_stage_fields():
    data = schema.normalize_pending(
        {
            "id": "ts-1",
            "kind": "task_stage",
            "status": "waiting",
            "thread_id": "t-1",
            "original_prompt": "干活",
            "stage": "2",
        }
    )
    assert data["kind"] == "task_stage"
    assert data["stage"] == 2


def test_normalize_pending_answered_keeps_reply():
    data = schema.normalize_pending({"id": "d1", "status": "answered", "reply": "继续"})
    assert data["status"] == "answered"
    assert data["reply"] == "继续"
    assert data["replied_at"]


def test_normalize_pending_invalid_returns_none():
    assert schema.normalize_pending([]) is None
    assert schema.normalize_pending("x") is None


def test_normalize_sessions_coerces_types():
    data = schema.normalize_sessions(
        {
            "10001": {
                "persona_turns": "3",
                "persona_started_ts": "123.5",
                "task_follow": {"active": 1, "last_task_ts": "88.5"},
                "proactive": {
                    "count": "2",
                    "fixed_done": "x",
                    "reminded_classes": None,
                    "last_ts": "9.5",
                    "paused": 1,
                },
            }
        }
    )
    user = data["10001"]
    assert user["persona_turns"] == 3
    assert user["persona_started_ts"] == 123.5
    assert user["task_follow"]["active"] is True
    assert user["task_follow"]["last_task_ts"] == 88.5
    assert user["proactive"]["count"] == 2
    assert user["proactive"]["fixed_done"] == []
    assert user["proactive"]["reminded_classes"] == []
    assert user["proactive"]["last_ts"] == 9.5
    assert user["proactive"]["paused"] is True


def test_self_check_sessions_fixes_and_saves():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp) / "sessions.json")
        store._data = {"10001": {"persona_turns": "abc"}}
        assert schema.self_check_sessions(store) is True
        reloaded = SessionStore(Path(tmp) / "sessions.json")
        assert reloaded._data["10001"]["persona_turns"] == 0


def test_self_check_pending_normalizes_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pending.json"
        path.write_text(json.dumps({"id": "d1"}), encoding="utf-8")
        assert schema.self_check_pending(path) is True
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["version"] == 1


def test_self_check_pending_quarantines_corrupt_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pending.json"
        path.write_text("{not-json", encoding="utf-8")
        assert schema.self_check_pending(path) is True
        assert not path.exists()
        assert list(Path(tmp).glob("pending.json.corrupt-*"))
