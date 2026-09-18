import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from calendar_todos import format_calendar, format_todos, normalize_todo_text
from state_db import StateDB


def test_normalize_todo_text_with_due():
    cleaned, due_at = normalize_todo_text("交作业 截止:2026-09-02 23:59")
    assert cleaned == "交作业"
    assert due_at == "2026-09-02 23:59"
    cleaned, due_at = normalize_todo_text("买牛奶")
    assert cleaned == "买牛奶"
    assert due_at == ""


def test_format_todos():
    todos = [
        {"id": 1, "text": "交作业", "due_at": "2026-09-02 23:59", "done": 0},
        {"id": 2, "text": "买牛奶", "due_at": "", "done": 1},
    ]
    text = format_todos(todos)
    assert "1. [ ] 交作业" in text
    assert "2. [x] 买牛奶" in text


def test_format_calendar_combines_events_and_todos(tmp_path):
    db = StateDB(tmp_path / "state.db")
    db.add_todo("10001", "开会", "2026-09-02 14:00")
    events = [{"name": "数学", "start": "09:00", "end": "10:00", "location": "A"}]
    text = format_calendar(events, db.list_todos("10001"))
    assert "数学" in text
    assert "开会" in text
