"""每日晨报：聚合课表、待办、提醒、未决断事项，并通过 scheduler 每日推送。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from calendar_todos import format_todos
from state_db import StateDB


def _next_daily_time(time_str: str, now: datetime) -> datetime:
    try:
        hour, minute = (int(x) for x in time_str.strip().split(":", 1))
    except Exception:
        hour, minute = 8, 30
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def register_digest_job(
    db: StateDB,
    user_id: str,
    time: str = "08:30",
    now: datetime | None = None,
) -> int:
    now = now or datetime.now()
    next_run = _next_daily_time(time, now).isoformat(timespec="seconds")
    return db.add_job(
        "digest",
        "daily",
        {"user_id": user_id, "time": time},
        next_run=next_run,
    )


def build_digest(bridge: Any, db: StateDB, user_id: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    parts = [f"📮 每日晨报 {now.strftime('%m-%d %H:%M')}"]

    # 课程/事件
    classes: list[dict[str, Any]] = []
    try:
        from timetable import load_timetable

        classes = load_timetable(bridge.timetable_path)
    except Exception:
        classes = []
    if classes:
        lines = []
        for c in classes:
            name = c.get("name", "")
            start = c.get("start", "")
            end = c.get("end", "")
            location = c.get("location", "")
            loc = f" @ {location}" if location else ""
            lines.append(f"- {start}-{end} {name}{loc}")
        parts.append("【课程/事件】\n" + "\n".join(lines))
    else:
        parts.append("【课程/事件】\n（暂无课表）")

    # 待办
    todos = db.list_todos(user_id)
    parts.append("【待办】\n" + format_todos(todos))

    # 有效提醒
    reminders = [r for r in db.list_reminders(user_id) if r["status"] == "active"]
    if reminders:
        lines = [f"- {r['text']} @ {r['remind_at']}" for r in reminders]
        parts.append("【提醒】\n" + "\n".join(lines))
    else:
        parts.append("【提醒】\n（暂无提醒）")

    # 未决断事项
    pending_text = ""
    pending_path = getattr(bridge, "pending_path", None)
    if pending_path is not None and Path(pending_path).exists():
        try:
            data = json.loads(Path(pending_path).read_text(encoding="utf-8"))
            if data.get("status") == "waiting":
                pending_text = str(data.get("question") or "有一项等待你决断")
        except Exception:
            pending_text = ""
    if pending_text:
        parts.append("【待决断】\n" + pending_text)
    else:
        parts.append("【待决断】\n（无）")

    return "\n\n".join(parts)
