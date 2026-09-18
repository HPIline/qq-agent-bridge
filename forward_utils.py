from __future__ import annotations

from typing import Any


def build_forward_nodes(
    messages: list[str], sender_name: str = "AI 助手", sender_uin: str = "10000"
) -> list[dict[str, Any]]:
    nodes = []
    for msg in messages:
        nodes.append(
            {
                "type": "node",
                "data": {
                    "name": sender_name,
                    "uin": sender_uin,
                    "content": [{"type": "text", "data": {"text": msg}}],
                },
            }
        )
    return nodes


def should_forward(segments: list[str], threshold: int = 5) -> bool:
    return len(segments) >= threshold


async def send_forward(
    bridge: Any,
    user_id: str,
    messages: list[str],
    threshold: int = 5,
    sender_name: str = "AI 助手",
    sender_uin: str = "10000",
) -> bool:
    if not should_forward(messages, threshold=threshold):
        return False
    try:
        try:
            user_id_num = int(user_id)
        except ValueError:
            user_id_num = user_id
        await bridge._call_action(
            "send_private_forward_msg",
            {
                "user_id": user_id_num,
                "messages": build_forward_nodes(
                    messages, sender_name=sender_name, sender_uin=sender_uin
                ),
            },
            timeout=30.0,
        )
        return True
    except Exception:
        return False
