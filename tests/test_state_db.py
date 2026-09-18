import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from state_db import StateDB


def test_create_and_list_due_reminders(tmp_path):
    db = StateDB(tmp_path / "state.db")
    rid = db.create_reminder("10001", "喝水", "2026-09-01T09:00:00")
    assert rid > 0
    due = db.list_due_reminders("2026-09-01T09:00:00")
    assert len(due) == 1
    assert due[0]["text"] == "喝水"
    assert len(db.list_due_reminders("2026-09-01T08:59:59")) == 0


def test_mark_reminder_done_and_reschedule(tmp_path):
    db = StateDB(tmp_path / "state.db")
    rid = db.create_reminder("10001", "喝水", "2026-09-01T09:00:00", repeat="daily")
    db.mark_reminder_done(rid)
    assert db.list_due_reminders("2026-09-02T09:00:00") == []
    rid2 = db.create_reminder("10001", "喝水", "2026-09-01T09:00:00", repeat="daily")
    db.set_reminder_next(rid2, "2026-09-02T09:00:00")
    due = db.list_due_reminders("2026-09-02T09:00:00")
    assert len(due) == 1
    assert due[0]["remind_at"] == "2026-09-02T09:00:00"


def test_list_reminders(tmp_path):
    db = StateDB(tmp_path / "state.db")
    db.create_reminder("10001", "喝水", "2026-09-01T09:00:00", repeat="daily")
    db.create_reminder("10001", "吃药", "2026-09-02T09:00:00")
    db.create_reminder("10002", "别人的提醒", "2026-09-02T09:00:00")
    assert len(db.list_reminders("10001")) == 2
    assert db.list_reminders("10002")[0]["text"] == "别人的提醒"


def test_todos_crud(tmp_path):
    db = StateDB(tmp_path / "state.db")
    tid = db.add_todo("10001", "交作业", "2026-09-02T23:59:59")
    assert tid > 0
    assert len(db.list_todos("10001")) == 1
    db.complete_todo(tid)
    todos = db.list_todos("10001")
    assert todos[0]["done"] == 1
    db.delete_todo(tid)
    assert db.list_todos("10001") == []


def test_jobs(tmp_path):
    db = StateDB(tmp_path / "state.db")
    jid = db.add_job("digest", "daily", {"user_id": "10001"}, "2026-09-02T08:30:00")
    assert jid > 0
    due = db.list_due_jobs("2026-09-02T08:30:00")
    assert len(due) == 1
    db.set_job_next_run(jid, "2026-09-03T08:30:00")
    assert db.list_due_jobs("2026-09-02T08:31:00") == []


def test_tasks_status(tmp_path):
    db = StateDB(tmp_path / "state.db")
    tid = db.add_task("10001", "task", "帮我写报告", "queued")
    db.update_task(tid, status="running", thread_id="task-1")
    db.update_task(tid, status="done", result="完成")
    tasks = db.list_tasks("10001")
    assert len(tasks) == 1
    assert tasks[0]["status"] == "done"
    assert tasks[0]["result"] == "完成"


def test_knowledge_search(tmp_path):
    db = StateDB(tmp_path / "state.db")
    db.clear_documents()
    db.add_document("/docs/a.md", 0, "a.md", "测试助手是外星人")
    db.add_document("/docs/b.md", 0, "b.md", "阿布量化交易系统")
    hits = db.search_documents("外星人", limit=5)
    assert len(hits) == 1
    assert "a.md" in hits[0]["title"]
    db.clear_documents()
    assert db.search_documents("外星人") == []


def test_context_manager_and_idempotent_close(tmp_path):
    path = tmp_path / "state.db"
    with StateDB(path) as db:
        db.add_todo("10001", "用上下文管理器")
    # 退出 with 后连接已关闭，再次 close 不报错
    db.close()
    db.close()


def test_state_db_uses_indexes(tmp_path):
    import sqlite3

    db = StateDB(tmp_path / "state.db")
    db.create_reminder("10001", "喝水", "2026-09-01T09:00:00")
    conn = sqlite3.connect(tmp_path / "state.db")
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()
    assert "idx_reminders_due" in indexes
    assert "idx_todos_user" in indexes
    assert "idx_tasks_user_status" in indexes
