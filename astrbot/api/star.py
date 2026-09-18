"""AstrBot Star 基类与 Context 兼容层。"""

from __future__ import annotations

import logging
from typing import Any


class Context:
    """提供给插件的上下文，目前仅绑定 qq-agent-bridge。"""

    def __init__(self, bridge: Any):
        self.bridge = bridge

    async def send_message(self, unified_msg_origin: str, chain: Any) -> None:
        from .event import _send_chain

        user_id = unified_msg_origin.rsplit(":", 1)[-1]
        await _send_chain(self.bridge, user_id, list(chain or []))


class StarTools:
    """占位：生态插件里偶尔作为 mixin 被继承。"""

    pass


class Star(StarTools):
    def __init__(self, context: Context, config: Any | None = None):
        self.context = context
        self.config = config
        self.logger = logging.getLogger(f"astrbot.plugin.{self.__class__.__name__}")

    async def text_to_image(self, text: str, return_url: bool = True) -> str:
        """qq-agent-bridge 简化实现：不渲染图片，直接返回文本。"""
        return text

    async def html_render(
        self,
        template: str,
        data: dict[str, Any] | None = None,
        options: dict[str, Any] | None = None,
    ) -> str:
        return template

    async def terminate(self) -> None:
        pass
