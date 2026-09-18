"""AstrBot 兼容层插件加载与分发测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from astrbot_plugins import dispatch_plugins, load_plugins


class FakeBuf:
    def __init__(self):
        self.images: list = []
        self.videos: list = []
        self.files: list = []
        self.faces: list = []
        self.mfaces: list = []


class FakeBridge:
    def __init__(self, bridge_dir: Path, plugins_dir: Path):
        self.bridge_dir = bridge_dir
        self.cfg = {
            "plugins_dir": str(plugins_dir),
            "plugins_enabled": True,
            "self_id": "123",
        }
        self.astrbot_plugins = load_plugins(self)
        self.sent: list[tuple] = []

    async def _send_private(self, user_id: str, text: str) -> None:
        self.sent.append(("text", user_id, text))

    async def _send_private_image(self, user_id: str, target: str) -> None:
        self.sent.append(("image", user_id, target))

    async def _send_private_video(self, user_id: str, target: str) -> None:
        self.sent.append(("video", user_id, target))

    async def _send_private_file(self, user_id: str, target: str, name: str = "") -> None:
        self.sent.append(("file", user_id, target, name))

    async def _send_private_face(self, user_id: str, face_id: str) -> None:
        self.sent.append(("face", user_id, face_id))

    async def _send_private_record(self, user_id: str, path: str) -> None:
        self.sent.append(("record", user_id, path))


def _write_plugin(plugins_dir: Path, name: str, source: str) -> None:
    plugin_dir = plugins_dir / name
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "main.py").write_text(source, encoding="utf-8")


def test_load_and_dispatch_command(tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    _write_plugin(
        plugins_dir,
        "hello_plugin",
        """from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star

class HelloPlugin(Star):
    @filter.command("hello")
    async def hello(self, event: AstrMessageEvent):
        yield event.plain_result("你好呀")
""",
    )
    bridge = FakeBridge(bridge_dir, plugins_dir)
    assert len(bridge.astrbot_plugins) == 1
    outcome = asyncio.run(dispatch_plugins(bridge, "10001", FakeBuf(), "/hello"))
    assert outcome is None
    assert ("text", "10001", "你好呀") in bridge.sent


def test_event_listener_can_stop_propagation(tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    _write_plugin(
        plugins_dir,
        "stop_plugin",
        """from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star

class StopPlugin(Star):
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_msg(self, event: AstrMessageEvent):
        yield event.plain_result("已截获")
        event.stop_event()
""",
    )
    bridge = FakeBridge(bridge_dir, plugins_dir)
    outcome = asyncio.run(dispatch_plugins(bridge, "10001", FakeBuf(), "随便说点"))
    assert outcome == "stop"
    assert ("text", "10001", "已截获") in bridge.sent


def test_command_group(tmp_path: Path):
    plugins_dir = tmp_path / "plugins"
    bridge_dir = tmp_path / "bridge"
    bridge_dir.mkdir()
    _write_plugin(
        plugins_dir,
        "math_plugin",
        """from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star

class MathPlugin(Star):
    @filter.command_group("math")
    def math(self):
        pass

    @math.command("add")
    async def add(self, event: AstrMessageEvent, a: int, b: int):
        yield event.plain_result(f"{a + b}")
""",
    )
    bridge = FakeBridge(bridge_dir, plugins_dir)
    outcome = asyncio.run(dispatch_plugins(bridge, "10001", FakeBuf(), "/math add 1 2"))
    assert outcome is None
    assert ("text", "10001", "3") in bridge.sent
