"""astrbot.api 兼容层。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("astrbot")


class AstrBotConfig(dict):
    """类似 AstrBot 的插件配置字典。"""

    def __init__(self, *args: Any, _path: str | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._path = _path

    def save_config(self) -> None:
        if not self._path:
            return
        Path(self._path).write_text(
            json.dumps(self, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


class FunctionTool:
    """极简 FunctionTool 占位，够插件声明工具使用。"""

    def __init__(
        self,
        name: str = "",
        description: str = "",
        parameters: dict[str, Any] | None = None,
        handler: Any = None,
    ):
        self.name = name
        self.description = description
        self.parameters = parameters or {}
        self.handler = handler

    async def call(self, *args: Any, **kwargs: Any) -> Any:
        if self.handler is None:
            raise NotImplementedError(f"FunctionTool {self.name} 未在 qq-agent-bridge 中实现")
        return await self.handler(*args, **kwargs)
