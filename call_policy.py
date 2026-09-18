"""Codex 调用策略：按场景统一推理强度、超时与重试入口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CallPolicy:
    reasoning_effort: str = "low"
    timeout: int = 150


def _int(cfg: dict[str, Any], key: str, default: int) -> int:
    try:
        return int(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


def resolve_policy(cfg: dict[str, Any], kind: str) -> CallPolicy:
    """按场景解析调用策略。

    kind: casual / proactive（闲聊）、task / stage_continue（任务）、
          enrich（联网补查）、summary（记忆总结/轮换）。
    """
    if kind in ("task", "stage_continue"):
        if cfg.get("task_stage_enabled", True):
            timeout = _int(cfg, "task_stage_timeout", 900)
        else:
            timeout = _int(cfg, "task_timeout", 900)
        return CallPolicy(
            reasoning_effort=str(cfg.get("task_effort", "max")),
            timeout=timeout,
        )
    if kind == "enrich":
        return CallPolicy(
            reasoning_effort=str(cfg.get("search_effort", "low")),
            timeout=_int(cfg, "search_timeout", 240),
        )
    if kind == "summary":
        return CallPolicy(
            reasoning_effort=str(cfg.get("task_effort", "max")),
            timeout=_int(cfg, "task_timeout", 900),
        )
    return CallPolicy(
        reasoning_effort=str(cfg.get("chat_effort", "low")),
        timeout=_int(cfg, "chat_timeout", 240),
    )


async def run_with_policy(
    bridge: Any,
    prompt: str,
    thread_id: str | None,
    policy: CallPolicy,
    image_paths: list[str] | None = None,
    model: str | None = None,
    model_provider: str | None = None,
    bypass_proxy: bool = False,
) -> tuple[str, str | None]:
    """统一入口：按策略调用桥接的 Codex 重试封装。"""
    return await bridge._run_agent_with_retry(
        prompt,
        thread_id,
        reasoning_effort=policy.reasoning_effort,
        timeout=policy.timeout,
        image_paths=image_paths,
        model=model,
        model_provider=model_provider,
        bypass_proxy=bypass_proxy,
    )
