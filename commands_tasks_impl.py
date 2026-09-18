"""后台任务命令实现。"""

from __future__ import annotations

from typing import Any

from command_registry import command


async def _send(bridge: Any, user_id: str, text: str) -> None:
    await bridge._send_private(user_id, text)


@command(
    name="任务",
    aliases=("bg", "后台任务"),
    help_text="提交后台任务：/任务 帮我做xxx",
    usage="/任务 <任务描述>",
)
async def cmd_task_submit(bridge: Any, user_id: str, args: str) -> None:
    if not args.strip():
        await _send(bridge, user_id, "用法：/任务 <任务描述>，例如 /任务 帮我整理笔记")
        return
    task_id = bridge.task_manager.submit(user_id, args.strip(), kind="task")
    await _send(bridge, user_id, f"任务已加入后台队列 #{task_id}，完成后会主动推送。")


@command(
    name="任务列表",
    aliases=("tasks",),
    help_text="查看后台任务状态",
    usage="/任务列表",
)
async def cmd_task_list(bridge: Any, user_id: str, args: str) -> None:
    tasks = bridge.task_manager.list_tasks(user_id)
    if not tasks:
        await _send(bridge, user_id, "（暂无后台任务）")
        return
    lines = ["📋 后台任务："]
    for t in tasks:
        lines.append(f"#{t['id']} [{t['status']}] {t['prompt'][:40]}")
    await _send(bridge, user_id, "\n".join(lines))


@command(
    name="任务取消",
    aliases=("canceltask",),
    help_text="取消后台任务，如：/任务取消 1",
    usage="/任务取消 <id>",
)
async def cmd_task_cancel(bridge: Any, user_id: str, args: str) -> None:
    try:
        task_id = int(args.strip())
    except ValueError:
        await _send(bridge, user_id, "用法：/任务取消 <id>")
        return
    if bridge.task_manager.cancel(task_id):
        await _send(bridge, user_id, f"已取消任务 #{task_id}。")
    else:
        await _send(bridge, user_id, f"未找到任务 #{task_id}。")
