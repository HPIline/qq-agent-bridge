from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any

from state_db import StateDB

_DAILY_RE = re.compile(
    r"(每天|每日)\s*(?:早上|上午|中午|下午|晚上)?\s*"
    r"(\d{1,2})\s*[点时:：](?:\s*(\d{1,2}))?"
)
_WEEKLY_RE = re.compile(
    r"(每周|每个)\s*(?:周|星期)?\s*([一二三四五六日天])\s*"
    r"(\d{1,2})\s*[点时:：](?:\s*(\d{1,2}))?"
)
_ONCE_RE = re.compile(
    r"(?:明天|明早|明天早上|明天上午|明天下午|明天晚上|明晚|"
    r"今天|今晚|今天早上|今天上午|今天下午|今天晚上)\s*"
    r"(\d{1,2})\s*[点时:：](?:\s*(\d{1,2}))?"
)
_MINUTES_RE = re.compile(r"(\d+)\s*分钟\s*后")

_WEEK_CN = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def _parse_time(when_text: str) -> tuple[int, int]:
    for pattern in (_DAILY_RE, _WEEKLY_RE, _ONCE_RE):
        m = pattern.search(when_text)
        if m:
            groups = m.groups()
            numbers = [int(x) for x in groups if x and x.isdigit()]
            if len(numbers) >= 1:
                hour = numbers[0]
                minute = numbers[1] if len(numbers) >= 2 else 0
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    return hour, minute
    return 9, 0


def parse_remind_when(text: str) -> tuple[str, str]:
    for pattern, repeat in (
        (_DAILY_RE, "daily"),
        (_WEEKLY_RE, "weekly"),
        (_ONCE_RE, "none"),
        (_MINUTES_RE, "none"),
    ):
        m = pattern.search(text)
        if m:
            return m.group(0).strip(), repeat
    return "", "none"


def next_run_from_text(when_text: str, now: datetime) -> datetime:
    if "分钟" in when_text:
        m = _MINUTES_RE.search(when_text)
        if m:
            return now + timedelta(minutes=int(m.group(1)))
    hour, minute = _parse_time(when_text)
    if when_text.startswith(("每天", "每日")):
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate
    if when_text.startswith(("每周", "每个")):
        m = _WEEKLY_RE.search(when_text)
        if m:
            target = _WEEK_CN[m.group(2)]
            days_ahead = (target - now.weekday() + 7) % 7
            if days_ahead == 0 and (now.hour, now.minute) >= (hour, minute):
                days_ahead = 7
            candidate = (now + timedelta(days=days_ahead)).replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            return candidate
    if "明天" in when_text or "明早" in when_text or "明晚" in when_text:
        return (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if "今天" in when_text or "今晚" in when_text:
        candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate
    return (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)


def add_reminder_from_text(
    db: StateDB,
    user_id: str,
    raw: str,
    now: datetime | None = None,
) -> str:
    when_text, repeat = parse_remind_when(raw)
    content = raw.replace(when_text, "").strip()
    if not content:
        content = "提醒"
    if not when_text:
        return "没看懂时间，试试“明天9点”或“每天8点”。"
    remind_at = next_run_from_text(when_text, now or datetime.now())
    db.create_reminder(user_id, content, remind_at.isoformat(timespec="seconds"), repeat)
    return (
        f"已设置提醒：{content}，时间 {when_text}（{remind_at.strftime('%m-%d %H:%M')}，{repeat}）"
    )


class Scheduler:
    def __init__(self, bridge: Any, db: StateDB):
        self.bridge = bridge
        self.db = db

    async def tick(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        now_iso = now.isoformat(timespec="seconds")
        for reminder in self.db.list_due_reminders(now_iso):
            await self.bridge._send_private(reminder["user_id"], f"⏰ 提醒：{reminder['text']}")
            if reminder["repeat"] == "daily":
                next_at = datetime.fromisoformat(reminder["remind_at"]) + timedelta(days=1)
                self.db.set_reminder_next(reminder["id"], next_at.isoformat(timespec="seconds"))
            elif reminder["repeat"] == "weekly":
                next_at = datetime.fromisoformat(reminder["remind_at"]) + timedelta(days=7)
                self.db.set_reminder_next(reminder["id"], next_at.isoformat(timespec="seconds"))
            else:
                self.db.mark_reminder_done(reminder["id"])

        for job in self.db.list_due_jobs(now_iso):
            if job["name"] == "digest":
                from digest import build_digest

                payload = job.get("payload") or {}
                user_id = str(payload.get("user_id") or "")
                if user_id:
                    text = build_digest(self.bridge, self.db, user_id, now=now)
                    await self.bridge._send_private(user_id, text)
                time_str = str(payload.get("time") or "08:30")
                try:
                    hour, minute = (int(x) for x in time_str.strip().split(":", 1))
                except Exception:
                    hour, minute = 8, 30
                next_at = (now + timedelta(days=1)).replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
                self.db.set_job_next_run(int(job["id"]), next_at.isoformat(timespec="seconds"))


async def run_scheduler(bridge: Any, interval: float = 15.0, now: datetime | None = None) -> None:
    sched = Scheduler(bridge, bridge.state_db)
    while True:
        await sched.tick(now=now)
        await asyncio.sleep(interval)
