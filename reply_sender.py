"""统一回复发送器：分块 / 角色扮演分段 / 合并转发 / 媒体标记 / 语音。

handlers 与 proactive 共用，避免两套几乎一样的发送逻辑。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from forward_utils import send_forward
from message_utils import chunk_reply, extract_media_markers, split_persona_reply


async def send_reply(
    bridge: Any,
    user_id: str,
    reply: str,
    *,
    persona_mode: bool = False,
    task_mode: bool = False,
) -> None:
    reply, media_markers = extract_media_markers(reply)
    if persona_mode and not task_mode:
        segments = split_persona_reply(
            reply,
            max_chars=int(bridge.cfg.get("persona_chat_max_chars", 40)),
            max_segments=int(bridge.cfg.get("persona_chat_max_segments", 4)),
        )
        delay = float(bridge.cfg.get("persona_chat_delay_sec", 1.0))
    else:
        segments = chunk_reply(reply, int(bridge.cfg.get("chunk_limit", 3800)))
        delay = float(bridge.cfg.get("chunk_delay_sec", 0.5))

    threshold = int(bridge.cfg.get("forward_threshold", 5))
    if not media_markers and len(segments) >= threshold:
        sender_name = str(
            bridge.cfg.get("persona_name") or bridge.cfg.get("forward_sender_name") or "AI 助手"
        )
        if await send_forward(
            bridge,
            user_id,
            segments,
            threshold=threshold,
            sender_name=sender_name,
            sender_uin=str(bridge.cfg.get("forward_sender_uin") or "10000"),
        ):
            logging.info("长回复已使用合并转发：%s", user_id)
            return

    for segment in segments:
        await bridge._send_private(user_id, segment)
        await asyncio.sleep(delay)

    voice_sent = 0
    for marker in media_markers:
        if marker["kind"] == "voice":
            if voice_sent >= int(bridge.cfg.get("voice_max_per_reply", 1)):
                logging.warning("忽略超出数量限制的语音标记")
                continue
            if bridge.voice_sender is not None:
                ok = await bridge.voice_sender.send_voice(
                    user_id, marker["text"], bridge._send_private_record
                )
                if not ok:
                    await bridge._send_private(
                        user_id, bridge.cfg.get("voice_fallback_text", "（语音合成失败）")
                    )
                else:
                    voice_sent += 1
            continue
        try:
            await bridge._send_media_marker(user_id, marker)
        except Exception as exc:
            await bridge._send_private(user_id, f"发送失败：{exc}")
            await asyncio.sleep(delay)
