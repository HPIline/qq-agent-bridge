import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scheduler import (
    Scheduler,
    add_reminder_from_text,
    next_run_from_text,
    parse_remind_when,
    run_scheduler,
)
from state_db import StateDB


def test_parse_remind_when():
    assert parse_remind_when("明天9点") == ("明天9点", "none")
    assert parse_remind_when("每天8点") == ("每天8点", "daily")
    assert parse_remind_when("每周五9点") == ("每周五9点", "weekly")


def test_next_run_from_text():
    now = datetime(2026, 9, 1, 10, 0)
    nxt = next_run_from_text("明天9点", now)
    assert nxt == datetime(2026, 9, 2, 9, 0)
    nxt = next_run_from_text("每天9点", now)
    assert nxt == datetime(2026, 9, 2, 9, 0)
    nxt = next_run_from_text("10分钟后", now)
    assert nxt == datetime(2026, 9, 1, 10, 10)


def test_add_reminder_from_text(tmp_path):
    db = StateDB(tmp_path / "state.db")
    msg = add_reminder_from_text(
        db, "10001", "喝水 明天9点", now=datetime(2026, 9, 1, 10, 0)
    )
    assert "明天" in msg
    assert len(db.list_due_reminders("2026-09-02T09:00:00")) == 1


def test_scheduler_tick_sends_and_marks_done(tmp_path):
    db = StateDB(tmp_path / "state.db")

    class FakeBridge:
        def __init__(self):
            self.sent = []

        async def _send_private(self, user_id, text):
            self.sent.append((user_id, text))

    bridge = FakeBridge()
    db.create_reminder("10001", "喝水", "2026-09-01T09:00:00", repeat="none")
    sched = Scheduler(bridge, db)
    asyncio.run(sched.tick(datetime(2026, 9, 1, 9, 0)))
    assert bridge.sent == [("10001", "⏰ 提醒：喝水")]
    assert db.list_due_reminders("2026-09-01T09:00:00") == []


def test_scheduler_tick_reschedules_daily(tmp_path):
    db = StateDB(tmp_path / "state.db")

    class FakeBridge:
        async def _send_private(self, user_id, text):
            pass

    bridge = FakeBridge()
    db.create_reminder("10001", "吃药", "2026-09-01T09:00:00", repeat="daily")
    sched = Scheduler(bridge, db)
    asyncio.run(sched.tick(datetime(2026, 9, 1, 9, 0)))
    due = db.list_due_reminders("2026-09-02T09:00:00")
    assert len(due) == 1
    assert due[0]["text"] == "吃药"


def test_run_scheduler_loop(tmp_path):
    db = StateDB(tmp_path / "state.db")

    class FakeBridge:
        def __init__(self):
            self.sent = []
            self.state_db = db

        async def _send_private(self, user_id, text):
            self.sent.append(text)

    bridge = FakeBridge()
    db.create_reminder("10001", "喝水", "2026-09-01T08:00:00")

    async def scenario():
        task = asyncio.create_task(
            run_scheduler(bridge, interval=0.01, now=datetime(2026, 9, 1, 8, 1))
        )
        for _ in range(20):
            if bridge.sent:
                task.cancel()
                break
            await asyncio.sleep(0.01)
        else:
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, RuntimeError):
            pass

    asyncio.run(scenario())
    assert bridge.sent == ["⏰ 提醒：喝水"]
