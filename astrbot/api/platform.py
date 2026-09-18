"""AstrBot 平台消息对象兼容层。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageType(Enum):
    PRIVATE_MESSAGE = "private_message"
    GROUP_MESSAGE = "group_message"


@dataclass
class MessageMember:
    user_id: str = ""
    nickname: str = ""


@dataclass
class AstrBotMessage:
    type: MessageType = MessageType.PRIVATE_MESSAGE
    self_id: str = ""
    session_id: str = ""
    message_id: str = ""
    group_id: str = ""
    sender: MessageMember = field(default_factory=MessageMember)
    message: list[Any] = field(default_factory=list)
    message_str: str = ""
    raw_message: Any = None
    timestamp: int = 0
