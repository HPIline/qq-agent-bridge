"""AstrBot 插件加载与分发（qq-agent-bridge 轻量兼容层）。

支持的插件形态：
- 插件目录下必须有 main.py；
- main.py 里定义继承 astrbot.api.star.Star 的类；
- 支持 @filter.command / @filter.command_group / @filter.event_message_type /
  @filter.platform_adapter_type / @filter.permission_type；
- 支持 _conf_schema.json 自动生成默认配置；
- 简单相对导入（如 from .utils import ...）通过包化加载支持。

不支持的插件：深度依赖 astrbot.core 内部实现、WebUI、平台 adapter 的插件。
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from astrbot.api import AstrBotConfig
from astrbot.api.event import (
    AstrMessageEvent,
    EventMessageType,
    PermissionType,
    PlatformAdapterType,
    _CommandGroup,
)
from astrbot.api.platform import AstrBotMessage, MessageMember, MessageType
from astrbot.api.star import Context, Star


@dataclass
class PluginHandler:
    plugin: Any
    handler: Any
    kind: str  # "command" | "event"
    command_path: str = ""
    command_name: str = ""
    alias: set[str] = field(default_factory=set)
    event_type: EventMessageType = EventMessageType.ALL
    platform_type: PlatformAdapterType = PlatformAdapterType.AIOCQHTTP
    permission: PermissionType = PermissionType.ALL
    priority: int = 0


@dataclass
class LoadedPlugin:
    name: str
    module: ModuleType
    instance: Any
    handlers: list[PluginHandler] = field(default_factory=list)


def _load_plugin_config(bridge: Any, plugin_dir: Path, plugin_name: str) -> AstrBotConfig:
    schema_path = plugin_dir / "_conf_schema.json"
    defaults: dict[str, Any] = {}
    if schema_path.exists():
        try:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            for key, item in schema.items():
                if isinstance(item, dict) and "default" in item:
                    defaults[key] = item["default"]
        except Exception as exc:
            logging.warning("解析插件配置 schema 失败：%s", exc)
    config_dir = bridge.bridge_dir / "data" / "astrbot_configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / f"{plugin_name}_config.json"
    merged = dict(defaults)
    if config_path.exists():
        try:
            merged.update(json.loads(config_path.read_text(encoding="utf-8")))
        except Exception as exc:
            logging.warning("读取插件配置失败：%s", exc)
    return AstrBotConfig(merged, _path=str(config_path))


def _collect_command_group_handlers(
    plugin: Any,
    group: _CommandGroup,
    out: list[PluginHandler],
) -> None:
    for item in group.subcommands:
        if isinstance(item, _CommandGroup):
            _collect_command_group_handlers(plugin, item, out)
            continue
        fn = item.get("fn")
        if fn is None:
            continue
        bound_fn = getattr(plugin, getattr(fn, "__name__", ""), fn)
        out.append(
            PluginHandler(
                plugin=plugin,
                handler=bound_fn,
                kind="command",
                command_path=item.get("path", ""),
                command_name=item.get("name", ""),
                alias=item.get("alias", set()),
                priority=item.get("priority", 0),
            )
        )


def _load_plugin(bridge: Any, plugin_dir: Path) -> LoadedPlugin | None:
    main_path = plugin_dir / "main.py"
    if not main_path.exists():
        return None
    plugin_name = plugin_dir.name
    module_name = f"astrbot_plugin_{plugin_name}"
    try:
        spec = importlib.util.spec_from_file_location(
            module_name,
            main_path,
            submodule_search_locations=[str(plugin_dir)],
        )
        if spec is None or spec.loader is None:
            logging.warning("无法为插件创建模块：%s", plugin_dir)
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except Exception as exc:
        logging.warning("加载 AstrBot 插件失败：%s（%s）", plugin_dir, exc)
        return None

    plugin_cls: type[Star] | None = None
    for obj in vars(module).values():
        if (
            inspect.isclass(obj)
            and issubclass(obj, Star)
            and obj is not Star
            and obj.__module__ == module_name
        ):
            plugin_cls = obj
            break
    if plugin_cls is None:
        logging.warning("插件 %s 没有 Star 子类", plugin_name)
        return None

    config = _load_plugin_config(bridge, plugin_dir, plugin_name)
    try:
        sig = inspect.signature(plugin_cls.__init__)
        params = list(sig.parameters.values())[1:]  # 跳过 self
        args: list[Any] = [Context(bridge)]
        if len(params) >= 2:
            args.append(config)
        instance = plugin_cls(*args)
    except Exception as exc:
        logging.warning("实例化 AstrBot 插件失败：%s（%s）", plugin_name, exc)
        return None

    handlers: list[PluginHandler] = []
    for attr_name in dir(instance):
        try:
            attr = getattr(instance, attr_name)
        except Exception:
            continue
        if isinstance(attr, _CommandGroup):
            _collect_command_group_handlers(instance, attr, handlers)
            continue
        if not callable(attr):
            continue
        if hasattr(attr, "_astrbot_cmd"):
            meta = attr._astrbot_cmd
            handlers.append(
                PluginHandler(
                    plugin=instance,
                    handler=attr,
                    kind="command",
                    command_path=meta.get("name", ""),
                    command_name=meta.get("name", ""),
                    alias=meta.get("alias", set()),
                    priority=meta.get("priority", 0),
                )
            )
        elif hasattr(attr, "_astrbot_event_type") or hasattr(attr, "_astrbot_platform_type"):
            handlers.append(
                PluginHandler(
                    plugin=instance,
                    handler=attr,
                    kind="event",
                    event_type=getattr(attr, "_astrbot_event_type", EventMessageType.ALL),
                    platform_type=getattr(
                        attr, "_astrbot_platform_type", PlatformAdapterType.AIOCQHTTP
                    ),
                    permission=getattr(attr, "_astrbot_permission", PermissionType.ALL),
                    priority=getattr(attr, "_astrbot_priority", 0),
                )
            )
    handlers.sort(key=lambda h: h.priority, reverse=True)
    logging.info(
        "已加载 AstrBot 插件 %s（%s 个 handler）",
        plugin_name,
        len(handlers),
    )
    return LoadedPlugin(name=plugin_name, module=module, instance=instance, handlers=handlers)


def load_plugins(bridge: Any) -> list[LoadedPlugin]:
    plugins_dir = bridge.bridge_dir / str(bridge.cfg.get("plugins_dir", "astrbot_plugins"))
    plugins_dir.mkdir(parents=True, exist_ok=True)
    loaded: list[LoadedPlugin] = []
    for child in sorted(plugins_dir.iterdir()):
        if not child.is_dir():
            continue
        plugin = _load_plugin(bridge, child)
        if plugin is not None:
            loaded.append(plugin)
    return loaded


def build_astr_message(bridge: Any, user_id: str, buf: Any, text: str) -> AstrBotMessage:
    from astrbot.api import message_components as Comp

    chain: list[Any] = []
    if text:
        chain.append(Comp.Plain(text))
    for image in buf.images:
        target = image.get("url") or image.get("file") or ""
        if target:
            chain.append(
                Comp.Image.fromURL(target)
                if target.startswith(("http://", "https://"))
                else Comp.Image.fromFileSystem(target)
            )
    for video in buf.videos:
        target = video.get("url") or video.get("path") or video.get("file") or ""
        if target:
            chain.append(
                Comp.Video.fromURL(target)
                if target.startswith(("http://", "https://"))
                else Comp.Video.fromFileSystem(target)
            )
    for file in buf.files:
        target = file.get("url") or file.get("path") or file.get("file") or ""
        if target:
            chain.append(Comp.File(target, name=file.get("name") or ""))
    for face in buf.faces:
        chain.append(Comp.Face(id=face.get("id", "")))
    return AstrBotMessage(
        type=MessageType.PRIVATE_MESSAGE,
        self_id=str(bridge.cfg.get("self_id", "")),
        session_id=user_id,
        message_id="",
        group_id="",
        sender=MessageMember(user_id=user_id, nickname=user_id),
        message=chain,
        message_str=text,
        raw_message=None,
        timestamp=0,
    )


def _match_command(text: str, handler: PluginHandler) -> tuple[bool, list[str]]:
    name = handler.command_name
    path = handler.command_path
    stripped = text.strip()
    candidates = [candidate for candidate in (name, path) if candidate]
    for candidate in list(candidates):
        spaced = candidate.replace(".", " ")
        if spaced != candidate:
            candidates.append(spaced)
    for candidate in candidates:
        if not candidate:
            continue
        if stripped == f"/{candidate}" or stripped == candidate:
            return True, []
        prefix = f"/{candidate} "
        if stripped.startswith(prefix):
            return True, stripped[len(prefix) :].split()
        if stripped.startswith(f"{candidate} ") and "/" not in candidate:
            return True, stripped[len(candidate) + 1 :].split()
    for alias in handler.alias:
        if stripped == f"/{alias}" or stripped == alias:
            return True, []
        prefix = f"/{alias} "
        if stripped.startswith(prefix):
            return True, stripped[len(prefix) :].split()
    return False, []


async def _invoke_handler(
    handler: PluginHandler, event: AstrMessageEvent, args: list[str]
) -> list[Any]:
    handler_fn = handler.handler
    if handler.kind == "command":
        sig = inspect.signature(handler_fn)
        params = [p for p in sig.parameters.values() if p.name not in ("self", "event")]
        call_args: list[Any] = [event]
        for i, param in enumerate(params):
            if i < len(args):
                from astrbot.api.event import _coerce_arg

                call_args.append(_coerce_arg(args[i], param.annotation))
            elif param.default is inspect.Parameter.empty:
                call_args.append("")
            else:
                call_args.append(param.default)
    else:
        call_args = [event]
    result = handler_fn(*call_args)
    outputs: list[Any] = []
    if inspect.isasyncgen(result):
        async for item in result:
            outputs.append(item)
    else:
        maybe = await result if inspect.isawaitable(result) else result
        outputs.append(maybe)
    return [o for o in outputs if o is not None]


async def dispatch_plugins(bridge: Any, user_id: str, buf: Any, text: str) -> str | None:
    """把消息分发给 AstrBot 插件。返回 "stop" 表示终止本消息的后续处理。"""
    if not bridge.astrbot_plugins:
        return None
    event = AstrMessageEvent(bridge, user_id, build_astr_message(bridge, user_id, buf, text))
    for loaded in bridge.astrbot_plugins:
        for handler in loaded.handlers:
            if handler.kind == "command":
                matched, args = _match_command(text, handler)
                if not matched:
                    continue
            else:
                if handler.event_type == EventMessageType.GROUP_MESSAGE:
                    continue
                if handler.event_type not in (
                    EventMessageType.ALL,
                    EventMessageType.PRIVATE_MESSAGE,
                ):
                    continue
                if not (handler.platform_type & PlatformAdapterType.AIOCQHTTP):
                    continue
                args = []
            try:
                outputs = await _invoke_handler(handler, event, args)
                for output in outputs:
                    if isinstance(output, str):
                        await bridge._send_private(user_id, output)
                    else:
                        await event.send(output)
            except Exception as exc:
                logging.warning("AstrBot 插件 handler 执行失败：%s", exc)
            if event.is_stopped():
                return "stop"
    return None
