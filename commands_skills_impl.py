"""晨报、外部技能与知识库命令实现。"""

from __future__ import annotations

from typing import Any

from command_registry import command
from digest import build_digest, register_digest_job
from rag import RagIndex, search_knowledge
from skills_registry import get_skill_index


async def _send(bridge: Any, user_id: str, text: str) -> None:
    await bridge._send_private(user_id, text)


@command(
    name="晨报",
    aliases=("digest",),
    help_text="立即生成并发送每日晨报",
    usage="/晨报",
)
async def cmd_digest(bridge: Any, user_id: str, args: str) -> None:
    await _send(bridge, user_id, build_digest(bridge, bridge.state_db, user_id))


@command(
    name="晨报设置",
    aliases=("setdigest",),
    help_text="设置每日晨报时间，如：/晨报设置 08:30",
    usage="/晨报设置 <HH:MM>",
)
async def cmd_digest_set(bridge: Any, user_id: str, args: str) -> None:
    time_str = args.strip() or "08:30"
    register_digest_job(bridge.state_db, user_id, time=time_str)
    await _send(bridge, user_id, f"已设置每日晨报 {time_str}。")


@command(
    name="天气",
    aliases=("weather",),
    help_text="查询天气，如：/天气 北京",
    usage="/天气 <城市>",
)
async def cmd_weather(bridge: Any, user_id: str, args: str) -> None:
    from skills.weather import skill_weather

    await _send(bridge, user_id, skill_weather(args.strip() or "北京"))


@command(
    name="技能",
    aliases=("skills",),
    help_text="查看当前可用的外部技能",
    usage="/技能",
)
async def cmd_skills(bridge: Any, user_id: str, args: str) -> None:
    await _send(bridge, user_id, get_skill_index())


@command(
    name="知识库",
    aliases=("kb",),
    help_text="知识库操作：/知识库 重建 或 /知识库 搜 <关键词>",
    usage="/知识库 [重建|搜 <关键词>]",
)
async def cmd_knowledge(bridge: Any, user_id: str, args: str) -> None:
    text = args.strip()
    if not text:
        await _send(bridge, user_id, "用法：/知识库 重建 或 /知识库 搜 <关键词>")
        return
    if text.startswith("重建") or text in ("rebuild",):
        dirs = bridge.cfg.get("rag_dirs", [])
        index = RagIndex(bridge.state_db)
        count = await index.rebuild(dirs)
        await _send(bridge, user_id, f"知识库重建完成，共索引 {count} 个文本块。")
        return
    if text.startswith("搜 ") or text.startswith("搜索 "):
        query = text[2:].strip()
        if not query:
            await _send(bridge, user_id, "用法：/知识库 搜 <关键词>")
            return
        await _send(bridge, user_id, search_knowledge(bridge.state_db, query))
        return
    await _send(bridge, user_id, search_knowledge(bridge.state_db, text))
