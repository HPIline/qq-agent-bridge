import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from digest import build_digest, register_digest_job
from scheduler import Scheduler
from state_db import StateDB


class FakeBridge:
    def __init__(self, tmp_path):
        self.timetable_path = tmp_path / "timetable.json"
        self.pending_path = tmp_path / "pending.json"
        self.sent = []

    async def _send_private(self, user_id, text):
        self.sent.append((user_id, text))


def test_build_digest_includes_todos_and_reminders(tmp_path):
    db = StateDB(tmp_path / "state.db")
    db.add_todo("10001", "交作业", "2026-09-02 23:59")
    db.create_reminder("10001", "吃药", "2026-09-02T08:00:00")
    bridge = FakeBridge(tmp_path)
    text = build_digest(bridge, db, "10001")
    assert "晨报" in text
    assert "交作业" in text
    assert "吃药" in text


def test_register_digest_job_creates_daily_job(tmp_path):
    db = StateDB(tmp_path / "state.db")
    jid = register_digest_job(db, "10001", time="08:30", now=datetime(2026, 9, 1, 7, 0))
    assert jid > 0
    jobs = db.list_due_jobs("2026-09-01T08:30:00")
    assert len(jobs) == 1
    assert jobs[0]["name"] == "digest"
    assert jobs[0]["payload"]["user_id"] == "10001"


def test_scheduler_tick_runs_digest_job_and_reschedules(tmp_path):
    db = StateDB(tmp_path / "state.db")
    bridge = FakeBridge(tmp_path)
    register_digest_job(db, "10001", time="08:30", now=datetime(2026, 9, 1, 8, 0))
    sched = Scheduler(bridge, db)
    asyncio.run(sched.tick(datetime(2026, 9, 1, 8, 30)))
    assert bridge.sent
    assert "晨报" in bridge.sent[0][1]
    # 当天已执行，下一天 08:30 再次到期
    assert len(db.list_due_jobs("2026-09-02T08:30:00")) == 1
