from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class CommandMatch:
    name: str
    handler: Callable[..., Awaitable[Any]]
    args_str: str = ""


class CommandRegistry:
    """命令注册表：统一管理斜杠命令、别名、帮助文本。"""

    def __init__(self) -> None:
        self._commands: dict[str, dict[str, Any]] = {}
        self._aliases: dict[str, str] = {}

    def register(
        self,
        fn: Callable[..., Awaitable[Any]],
        name: str,
        aliases: tuple[str, ...] = (),
        permission: str = "owner",
        help_text: str = "",
        usage: str = "",
    ) -> None:
        self._commands[name] = {
            "name": name,
            "handler": fn,
            "permission": permission,
            "help_text": help_text,
            "usage": usage or f"/{name}",
            "aliases": tuple(aliases),
        }
        for alias in aliases:
            self._aliases[alias] = name

    def match(self, text: str) -> CommandMatch | None:
        stripped = text.strip()
        if not stripped.startswith("/"):
            return None
        parts = stripped[1:].split(None, 1)
        if not parts:
            return None
        token = parts[0].strip()
        name = self._aliases.get(token, token) if token in self._aliases else token
        spec = self._commands.get(name)
        if spec is None:
            return None
        return CommandMatch(
            name=spec["name"],
            handler=spec["handler"],
            args_str=parts[1].strip() if len(parts) > 1 else "",
        )

    def help_text(self) -> str:
        lines = []
        for spec in self._commands.values():
            alias = f"（别名：{'/'.join(spec['aliases'])}）" if spec["aliases"] else ""
            lines.append(f"{spec['usage']} {alias} - {spec['help_text']}")
        return "\n".join(lines)


# 模块级默认注册表，装饰器用法直接写入这里。
registry = CommandRegistry()


def command(
    name: str,
    aliases: tuple[str, ...] = (),
    permission: str = "owner",
    help_text: str = "",
    usage: str = "",
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        registry.register(
            fn,
            name=name,
            aliases=aliases,
            permission=permission,
            help_text=help_text,
            usage=usage,
        )
        return fn

    return decorator
