"""AstrBot 事件与 filter 装饰器兼容层。"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from enum import Enum, Flag
from typing import Any

from ..message_components import Image, Plain
from ..platform import (
    AstrBotMessage,
)
from ..platform import (
    MessageMember as MessageMember,
)
from ..platform import (
    MessageType as MessageType,
)


class EventMessageType(Enum):
    ALL = "all"
    PRIVATE_MESSAGE = "private_message"
    GROUP_MESSAGE = "group_message"


class PlatformAdapterType(Flag):
    AIOCQHTTP = 1
    QQOFFICIAL = 2
    TELEGRAM = 4
    WECHAT = 8
    WECOM = 16
    LARK = 32
    DINGTALK = 64
    DISCORD = 128
    ALL = AIOCQHTTP | QQOFFICIAL | TELEGRAM | WECHAT | WECOM | LARK | DINGTALK | DISCORD


class PermissionType(Enum):
    ADMIN = "admin"
    MEMBER = "member"
    ALL = "all"


class _CommandGroup:
    def __init__(self, path: str):
        self.path = path
        self.subcommands: list[dict[str, Any]] = []
        self.fn: Any = None

    def __call__(self, fn: Any) -> _CommandGroup:
        self.fn = fn
        return self

    def command(
        self,
        name: str,
        alias: set[str] | list[str] | tuple[str, ...] | None = None,
        priority: int = 0,
    ):
        def deco(fn: Any) -> Any:
            self.subcommands.append(
                {
                    "path": f"{self.path}.{name}".strip("."),
                    "name": name,
                    "alias": set(alias or []),
                    "priority": priority,
                    "fn": fn,
                }
            )
            return fn

        return deco

    def group(self, name: str):
        sub = _CommandGroup(f"{self.path}.{name}".strip("."))
        self.subcommands.append(sub)
        return sub


def command(
    name: str, alias: set[str] | list[str] | tuple[str, ...] | None = None, priority: int = 0
):
    def deco(fn: Any) -> Any:
        fn._astrbot_cmd = {"name": name, "alias": set(alias or []), "priority": priority}
        return fn

    return deco


def command_group(name: str):
    return _CommandGroup(name)


def event_message_type(message_type: EventMessageType):
    def deco(fn: Any) -> Any:
        fn._astrbot_event_type = message_type
        return fn

    return deco


def platform_adapter_type(platform_type: PlatformAdapterType):
    def deco(fn: Any) -> Any:
        fn._astrbot_platform_type = platform_type
        return fn

    return deco


def permission_type(permission_type: PermissionType):
    def deco(fn: Any) -> Any:
        fn._astrbot_permission = permission_type
        return fn

    return deco


# 事件钩子：本兼容层不触发 LLM 相关钩子，仅保留装饰器让插件可以加载。
def on_llm_request(priority: int = 0):
    def deco(fn: Any) -> Any:
        fn._astrbot_hook = "on_llm_request"
        fn._astrbot_priority = priority
        return fn

    return deco


def on_llm_response(priority: int = 0):
    def deco(fn: Any) -> Any:
        fn._astrbot_hook = "on_llm_response"
        fn._astrbot_priority = priority
        return fn

    return deco


def on_astrbot_loaded(priority: int = 0):
    def deco(fn: Any) -> Any:
        fn._astrbot_hook = "on_astrbot_loaded"
        fn._astrbot_priority = priority
        return fn

    return deco


def on_decorating_result(priority: int = 0):
    def deco(fn: Any) -> Any:
        fn._astrbot_hook = "on_decorating_result"
        fn._astrbot_priority = priority
        return fn

    return deco


def after_message_sent(priority: int = 0):
    def deco(fn: Any) -> Any:
        fn._astrbot_hook = "after_message_sent"
        fn._astrbot_priority = priority
        return fn

    return deco


def on_agent_begin(priority: int = 0):
    def deco(fn: Any) -> Any:
        fn._astrbot_hook = "on_agent_begin"
        fn._astrbot_priority = priority
        return fn

    return deco


def on_using_llm_tool(priority: int = 0):
    def deco(fn: Any) -> Any:
        fn._astrbot_hook = "on_using_llm_tool"
        fn._astrbot_priority = priority
        return fn

    return deco


def on_llm_tool_respond(priority: int = 0):
    def deco(fn: Any) -> Any:
        fn._astrbot_hook = "on_llm_tool_respond"
        fn._astrbot_priority = priority
        return fn

    return deco


def on_agent_done(priority: int = 0):
    def deco(fn: Any) -> Any:
        fn._astrbot_hook = "on_agent_done"
        fn._astrbot_priority = priority
        return fn

    return deco


class _FilterNamespace:
    """让 `from astrbot.api.event import filter` 与生态用法一致。"""

    EventMessageType = EventMessageType
    PlatformAdapterType = PlatformAdapterType
    PermissionType = PermissionType

    command = staticmethod(command)
    command_group = staticmethod(command_group)
    event_message_type = staticmethod(event_message_type)
    platform_adapter_type = staticmethod(platform_adapter_type)
    permission_type = staticmethod(permission_type)
    on_llm_request = staticmethod(on_llm_request)
    on_llm_response = staticmethod(on_llm_response)
    on_astrbot_loaded = staticmethod(on_astrbot_loaded)
    on_decorating_result = staticmethod(on_decorating_result)
    after_message_sent = staticmethod(after_message_sent)
    on_agent_begin = staticmethod(on_agent_begin)
    on_using_llm_tool = staticmethod(on_using_llm_tool)
    on_llm_tool_respond = staticmethod(on_llm_tool_respond)
    on_agent_done = staticmethod(on_agent_done)


filter = _FilterNamespace()


@dataclass
class MessageEventResult:
    chain: list[Any] = field(default_factory=list)

    def send(self, event: AstrMessageEvent) -> None:
        pass

    def is_empty(self) -> bool:
        return not bool(self.chain)


class AstrMessageEvent:
    def __init__(self, bridge: Any, user_id: str, message_obj: AstrBotMessage):
        self.bridge = bridge
        self.user_id = user_id
        self.message_obj = message_obj
        self.message_str = message_obj.message_str
        self.session_id = message_obj.session_id
        self.unified_msg_origin = f"aiocqhttp:private:{user_id}"
        self.bot = bridge
        self._stopped = False
        self._result = MessageEventResult()

    def get_sender_id(self) -> str:
        return self.message_obj.sender.user_id or self.user_id

    def get_sender_name(self) -> str:
        return self.message_obj.sender.nickname or self.user_id

    def get_platform_name(self) -> str:
        return "aiocqhttp"

    def get_message_obj(self) -> AstrBotMessage:
        return self.message_obj

    def make_result(self) -> MessageEventResult:
        self._result = MessageEventResult()
        return self._result

    def get_result(self) -> MessageEventResult:
        return self._result

    def set_result(self, result: MessageEventResult) -> None:
        self._result = result

    def plain_result(self, text: str) -> MessageEventResult:
        return MessageEventResult(chain=[Plain(str(text))])

    def image_result(self, target: str) -> MessageEventResult:
        return MessageEventResult(
            chain=[
                Image.fromURL(target)
                if str(target).startswith(("http://", "https://"))
                else Image.fromFileSystem(str(target))
            ]
        )

    def chain_result(self, chain: list[Any]) -> MessageEventResult:
        return MessageEventResult(chain=list(chain or []))

    def stop_event(self) -> None:
        self._stopped = True

    def is_stopped(self) -> bool:
        return self._stopped

    async def send(self, result: MessageEventResult | str) -> None:
        if isinstance(result, str):
            result = MessageEventResult(chain=[Plain(result)])
        if result is None or result.is_empty():
            return
        from . import _send_chain

        await _send_chain(self.bridge, self.user_id, result.chain)


async def _send_chain(bridge: Any, user_id: str, chain: list[Any]) -> None:
    """把消息链组件逐个发送到 QQ。"""
    text_parts: list[str] = []
    for comp in chain:
        comp_type = getattr(comp, "type", None)
        if comp_type == "plain":
            text_parts.append(str(getattr(comp, "text", "")))
            continue
        if text_parts:
            await bridge._send_private(user_id, "".join(text_parts))
            text_parts = []
        if comp_type == "image":
            target = getattr(comp, "file", "") or getattr(comp, "url", "")
            await bridge._send_private_image(user_id, target)
        elif comp_type == "video":
            target = getattr(comp, "file", "") or getattr(comp, "url", "")
            await bridge._send_private_video(user_id, target)
        elif comp_type == "face":
            await bridge._send_private_face(user_id, str(getattr(comp, "id", "")))
        elif comp_type == "file":
            target = getattr(comp, "file", "")
            name = getattr(comp, "name", "") or Path(target).name
            await bridge._send_private_file(user_id, target, name)
        elif comp_type == "record":
            target = getattr(comp, "file", "") or getattr(comp, "url", "")
            await bridge._send_private_record(user_id, target)
        else:
            # 不支持的组件退化为文本描述
            await bridge._send_private(user_id, str(comp))
    if text_parts:
        await bridge._send_private(user_id, "".join(text_parts))


from pathlib import Path  # noqa: E402  (供 _send_chain 使用)


def _coerce_arg(value: str, annotation: Any) -> Any:
    if annotation is inspect.Parameter.empty:
        return value
    if annotation is int:
        try:
            return int(value)
        except ValueError:
            return value
    if annotation is float:
        try:
            return float(value)
        except ValueError:
            return value
    return value
