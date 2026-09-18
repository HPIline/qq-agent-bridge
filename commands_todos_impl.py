"""待办与日历类命令实现。"""

from __future__ import annotations

from typing import Any

from calendar_todos import format_calendar, format_todos, normalize_todo_text
from command_registry import command


async def _send(bridge: Any, user_id: str, text: str) -> None:
    await bridge._send_private(user_id, text)


@command(
    name="待办",
    aliases=("todo",),
    help_text="添加待办：/待办 添加 <内容> [截止:日期]；查看：/待办",
    usage="/待办 [添加 <内容> | 列表]",
)
async def cmd_todo_add_or_list(bridge: Any, user_id: str, args: str) -> None:
    text = args.strip()
    if not text:
        await _send(bridge, user_id, format_todos(bridge.state_db.list_todos(user_id)))
        return
    if text.startswith("添加 "):
        payload = text[len("添加 ") :].strip()
    elif text.startswith("新增 "):
        payload = text[len("新增 ") :].strip()
    else:
        payload = text
    cleaned, due_at = normalize_todo_text(payload)
    if not cleaned:
        await _send(bridge, user_id, "待办内容不能为空。")
        return
    bridge.state_db.add_todo(user_id, cleaned, due_at)
    await _send(bridge, user_id, f"已添加待办：{cleaned}")


@command(
    name="完成",
    aliases=("done",),
    help_text="完成待办，如：/完成 1",
    usage="/完成 <id>",
)
async def cmd_todo_complete(bridge: Any, user_id: str, args: str) -> None:
    try:
        tid = int(args.strip())
    except ValueError:
        await _send(bridge, user_id, "用法：/完成 <id>")
        return
    bridge.state_db.complete_todo(tid)
    await _send(bridge, user_id, f"已完成待办 #{tid}。")


@command(
    name="删除待办",
    aliases=("rmtodo",),
    help_text="删除待办，如：/删除待办 1",
    usage="/删除待办 <id>",
)
async def cmd_todo_delete(bridge: Any, user_id: str, args: str) -> None:
    try:
        tid = int(args.strip())
    except ValueError:
        await _send(bridge, user_id, "用法：/删除待办 <id>")
        return
    bridge.state_db.delete_todo(tid)
    await _send(bridge, user_id, f"已删除待办 #{tid}。")


@command(
    name="日历",
    aliases=("calendar",),
    help_text="查看今天/近期日历：课程、提醒与待办",
    usage="/日历",
)
async def cmd_calendar(bridge: Any, user_id: str, args: str) -> None:
    try:
        from timetable import load_timetable

        classes = load_timetable(bridge.timetable_path)
    except Exception:
        classes = []
    events = [
        {
            "name": c.get("name", ""),
            "start": str(c.get("start", "")),
            "end": str(c.get("end", "")),
            "location": str(c.get("location", "")),
        }
        for c in classes
    ]
    await _send(
        bridge,
        user_id,
        format_calendar(events, bridge.state_db.list_todos(user_id)),
    )
