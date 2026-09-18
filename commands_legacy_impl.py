"""原桥接硬编码命令迁移实现。"""

from __future__ import annotations

from typing import Any

from command_registry import command, registry


async def _send(bridge: Any, user_id: str, text: str) -> None:
    await bridge._send_private(user_id, text)


@command(
    name="new",
    aliases=("重置",),
    help_text="重置当前会话",
    usage="/new",
)
async def cmd_new(bridge: Any, user_id: str, args: str) -> None:
    persona_mode = bool(bridge.cfg.get("persona_enabled", True))
    if persona_mode:
        existed = bridge.store.reset_persona(user_id)
        await _send(
            bridge, user_id, "角色扮演会话已重置。" if existed else "当前没有角色扮演会话记录。"
        )
    else:
        existed = bridge.store.reset(user_id)
        await _send(bridge, user_id, "会话已重置。" if existed else "当前没有会话记录。")


@command(
    name="id",
    help_text="查看当前会话线程 ID",
    usage="/id",
)
async def cmd_id(bridge: Any, user_id: str, args: str) -> None:
    persona_mode = bool(bridge.cfg.get("persona_enabled", True))
    thread_id = (
        bridge.store.get_persona_thread(user_id)
        if persona_mode
        else bridge.store.get_thread(user_id)
    )
    await _send(bridge, user_id, f"当前 thread：{thread_id or '（无）'}")


@command(
    name="help",
    aliases=("帮助",),
    help_text="显示帮助",
    usage="/help",
)
async def cmd_help(bridge: Any, user_id: str, args: str) -> None:
    await _send(bridge, user_id, "可用命令：\n" + registry.help_text())


@command(
    name="restart",
    help_text="重启桥接",
    usage="/restart",
)
async def cmd_restart(bridge: Any, user_id: str, args: str) -> None:
    await _send(bridge, user_id, "重启中……")
    import asyncio

    asyncio.create_task(bridge._restart_bridge())


@command(
    name="静默",
    help_text="暂停主动开口",
    usage="/静默",
)
async def cmd_silent(bridge: Any, user_id: str, args: str) -> None:
    if not bool(bridge.cfg.get("persona_enabled", True)):
        await _send(bridge, user_id, "该命令仅角色扮演模式可用。")
        return
    state = bridge.store.get_proactive_state(user_id)
    state["paused"] = True
    bridge.store.save_proactive_state(user_id, state)
    await _send(bridge, user_id, "……好。")


@command(
    name="唤醒",
    help_text="恢复主动开口",
    usage="/唤醒",
)
async def cmd_wake(bridge: Any, user_id: str, args: str) -> None:
    if not bool(bridge.cfg.get("persona_enabled", True)):
        await _send(bridge, user_id, "该命令仅角色扮演模式可用。")
        return
    state = bridge.store.get_proactive_state(user_id)
    state["paused"] = False
    bridge.store.save_proactive_state(user_id, state)
    await _send(bridge, user_id, "嗯。")


@command(
    name="话题",
    help_text="立即触发一次主动开口",
    usage="/话题",
)
async def cmd_topic(bridge: Any, user_id: str, args: str) -> None:
    if not bool(bridge.cfg.get("persona_enabled", True)):
        await _send(bridge, user_id, "该命令仅角色扮演模式可用。")
        return
    await bridge._run_proactive_impl(user_id, "manual", record=False)


@command(
    name="课表",
    help_text="导入课表：/课表 后发送图片/CSV/Excel",
    usage="/课表",
)
async def cmd_timetable_import(bridge: Any, user_id: str, args: str) -> None:
    bridge.timetable_pending.pop(user_id, None)
    bridge.timetable_mode_users.add(user_id)
    await _send(bridge, user_id, "把课表图片、CSV 或 Excel 发给我。")


@command(
    name="课表查看",
    help_text="查看当前课表",
    usage="/课表查看",
)
async def cmd_timetable_show(bridge: Any, user_id: str, args: str) -> None:
    from timetable import format_preview, load_timetable

    try:
        classes = load_timetable(bridge.timetable_path)
    except Exception as exc:
        await _send(bridge, user_id, f"课表读取失败：{exc}")
        return
    await _send(bridge, user_id, format_preview(classes) if classes else "还没有课表。")


@command(
    name="课表清除",
    help_text="清除课表",
    usage="/课表清除",
)
async def cmd_timetable_clear(bridge: Any, user_id: str, args: str) -> None:
    if bridge.timetable_path.exists():
        bridge.timetable_path.unlink()
        state = bridge.store.get_proactive_state(user_id)
        state["reminded_classes"] = []
        bridge.store.save_proactive_state(user_id, state)
        await _send(bridge, user_id, "课表已清除。")
    else:
        await _send(bridge, user_id, "当前没有课表。")
