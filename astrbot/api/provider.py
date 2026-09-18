"""AstrBot Provider 对象占位（本兼容层不驱动 LLM 钩子）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderRequest:
    system_prompt: str = ""
    user_content: str = ""
    extra_user_content_parts: list[Any] = field(default_factory=list)
    provider: Any = None


@dataclass
class LLMResponse:
    completion_text: str = ""
    raw_response: Any = None
