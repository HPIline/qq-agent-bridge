from __future__ import annotations

import re
from typing import Any

_DUE_RE = re.compile(
    r"(?:截止|ddl|deadline|DDL)[:：]\s*([0-9]{4}[-/][0-9]{1,2}[-/][0-9]{1,2}(?:\s+[0-9]{1,2}:[0-9]{2})?)"
)


def normalize_todo_text(text: str) -> tuple[str, str]:
    cleaned = text.strip()
    m = _DUE_RE.search(cleaned)
    due_at = ""
    if m:
        due_at = m.group(1).replace("/", "-")
        cleaned = cleaned[: m.start()].strip()
    return cleaned, due_at


def format_todos(todos: list[dict[str, Any]]) -> str:
    if not todos:
        return "（暂无待办）"
    lines = []
    for todo in todos:
        done = "[x]" if todo.get("done") else "[ ]"
        due = f"（截止 {todo['due_at']}）" if todo.get("due_at") else ""
        lines.append(f"{todo['id']}. {done} {todo['text']}{due}")
    return "\n".join(lines)


def format_calendar(events: list[dict[str, Any]], todos: list[dict[str, Any]]) -> str:
    parts = ["📅 日历"]
    if events:
        parts.append("\n【课程/事件】")
        for event in events:
            start = event.get("start", "")
            end = event.get("end", "")
            location = event.get("location", "")
            loc = f" @ {location}" if location else ""
            parts.append(f"- {start}-{end} {event.get('name', '')}{loc}")
    else:
        parts.append("\n【课程/事件】\n（暂无）")
    parts.append("\n【待办】")
    parts.append(format_todos(todos))
    return "\n".join(parts)
