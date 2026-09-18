"""提醒类命令实现。"""

from __future__ import annotations

from typing import Any

from command_registry import command
from scheduler import add_reminder_from_text


async def _send(bridge: Any, user_id: str, text: str) -> None:
    await bridge._send_private(user_id, text)


@command(
    name="提醒",
    aliases=("remind", "reminder"),
    help_text="设置定时提醒，如：/提醒 喝水 明天9点",
    usage="/提醒 <内容> <时间>",
)
async def cmd_remind_add(bridge: Any, user_id: str, args: str) -> None:
    if not args.strip():
        await _send(bridge, user_id, "用法：/提醒 <内容> <时间>，例如 /提醒 喝水 明天9点")
        return
    await _send(bridge, user_id, add_reminder_from_text(bridge.state_db, user_id, args.strip()))


@command(
    name="提醒列表",
    aliases=("reminds",),
    help_text="查看当前所有提醒",
    usage="/提醒列表",
)
async def cmd_remind_list(bridge: Any, user_id: str, args: str) -> None:
    reminders = bridge.state_db.list_reminders(user_id)
    if not reminders:
        await _send(bridge, user_id, "（暂无提醒）")
        return
    lines = ["⏰ 提醒列表："]
    for r in reminders:
        status = r["status"]
        repeat = f"（{r['repeat']}）" if r["repeat"] != "none" else ""
        lines.append(f"#{r['id']} {r['text']} @ {r['remind_at']} {repeat} [{status}]")
    await _send(bridge, user_id, "\n".join(lines))


@command(
    name="取消提醒",
    aliases=("rmremind",),
    help_text="取消指定提醒，如：/取消提醒 1",
    usage="/取消提醒 <id>",
)
async def cmd_remind_cancel(bridge: Any, user_id: str, args: str) -> None:
    try:
        rid = int(args.strip())
    except ValueError:
        await _send(bridge, user_id, "用法：/取消提醒 <id>")
        return
    bridge.state_db.cancel_reminder(rid)
    await _send(bridge, user_id, f"已取消提醒 #{rid}。")
