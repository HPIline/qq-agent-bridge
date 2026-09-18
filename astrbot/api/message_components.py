"""AstrBot 消息链组件兼容层（仅保留常用类型）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Plain:
    text: str = ""
    type: str = "plain"

    def to_onebot(self) -> dict[str, Any]:
        return {"type": "text", "data": {"text": self.text}}


@dataclass
class Image:
    file: str = ""
    url: str = ""
    type: str = "image"

    @classmethod
    def fromURL(cls, url: str) -> Image:
        return cls(file=url, url=url)

    @classmethod
    def fromFileSystem(cls, path: str) -> Image:
        return cls(file=str(path))


@dataclass
class Video:
    file: str = ""
    url: str = ""
    type: str = "video"

    @classmethod
    def fromURL(cls, url: str) -> Video:
        return cls(file=url, url=url)

    @classmethod
    def fromFileSystem(cls, path: str) -> Video:
        return cls(file=str(path))


@dataclass
class Record:
    file: str = ""
    url: str = ""
    type: str = "record"

    @classmethod
    def fromFileSystem(cls, path: str) -> Record:
        return cls(file=str(path))


@dataclass
class Face:
    id: str = ""
    type: str = "face"


@dataclass
class At:
    qq: str = ""
    type: str = "at"


@dataclass
class File:
    file: str = ""
    name: str = ""
    type: str = "file"

    @classmethod
    def fromFileSystem(cls, path: str, name: str = "") -> File:
        return cls(file=str(path), name=name or Path(path).name)


@dataclass
class Reply:
    id: str = ""
    type: str = "reply"


@dataclass
class Poke:
    qq: str = ""
    type: str = "poke"


@dataclass
class Node:
    uin: str = ""
    name: str = ""
    content: list[Any] = field(default_factory=list)
    type: str = "node"


@dataclass
class Nodes:
    nodes: list[Node] = field(default_factory=list)
    type: str = "nodes"


class MessageChain(list):
    """AstrBot 风格的消息链构造器。"""

    def message(self, text: str) -> MessageChain:
        self.append(Plain(text))
        return self

    def file_image(self, path: str) -> MessageChain:
        self.append(Image.fromFileSystem(path))
        return self

    def file_video(self, path: str) -> MessageChain:
        self.append(Video.fromFileSystem(path))
        return self

    def image(self, url: str) -> MessageChain:
        self.append(Image.fromURL(url))
        return self
