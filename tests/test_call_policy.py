import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import call_policy


def _cfg(**overrides) -> dict:
    cfg = {
        "task_stage_enabled": True,
        "task_stage_timeout": 900,
        "task_timeout": 900,
        "task_effort": "max",
        "chat_timeout": 240,
        "chat_effort": "low",
        "search_timeout": 240,
        "search_effort": "low",
    }
    cfg.update(overrides)
    return cfg


def test_resolve_casual_policy():
    policy = call_policy.resolve_policy(_cfg(), "casual")
    assert policy.reasoning_effort == "low"
    assert policy.timeout == 240


def test_resolve_task_policy_with_stage():
    policy = call_policy.resolve_policy(_cfg(task_stage_timeout=777), "task")
    assert policy.reasoning_effort == "max"
    assert policy.timeout == 777


def test_resolve_task_policy_without_stage():
    policy = call_policy.resolve_policy(
        _cfg(task_stage_enabled=False, task_timeout=600), "task"
    )
    assert policy.timeout == 600


def test_resolve_enrich_policy():
    policy = call_policy.resolve_policy(_cfg(), "enrich")
    assert policy.reasoning_effort == "low"
    assert policy.timeout == 240


def test_resolve_summary_policy():
    policy = call_policy.resolve_policy(_cfg(), "summary")
    assert policy.reasoning_effort == "max"
    assert policy.timeout == 900


def test_run_with_policy_delegates(monkeypatch):
    async def scenario():
        captured = {}

        class FakeBridge:
            async def _run_agent_with_retry(
                self,
                prompt,
                thread_id,
                reasoning_effort=None,
                timeout=None,
                image_paths=None,
                model=None,
                model_provider=None,
                bypass_proxy=False,
            ):
                captured["prompt"] = prompt
                captured["thread_id"] = thread_id
                captured["effort"] = reasoning_effort
                captured["timeout"] = timeout
                captured["image_paths"] = image_paths
                captured["model"] = model
                captured["model_provider"] = model_provider
                captured["bypass_proxy"] = bypass_proxy
                return "回复", "t-1"

        policy = call_policy.CallPolicy(reasoning_effort="low", timeout=123)
        reply, tid = await call_policy.run_with_policy(FakeBridge(), "干活", "t-0", policy)
        assert reply == "回复"
        assert tid == "t-1"
        assert captured["effort"] == "low"
        assert captured["timeout"] == 123
        assert captured["image_paths"] is None
        assert captured["model"] is None
        assert captured["model_provider"] is None
        assert captured["bypass_proxy"] is False

        reply, tid = await call_policy.run_with_policy(
            FakeBridge(),
            "干活",
            "t-0",
            policy,
            model="deepseek-v4-flash",
            model_provider="opencode-go",
        )
        assert captured["model"] == "deepseek-v4-flash"
        assert captured["model_provider"] == "opencode-go"

        reply, tid = await call_policy.run_with_policy(
            FakeBridge(),
            "干活",
            "t-0",
            policy,
            model="deepseek-v4-flash",
            bypass_proxy=True,
        )
        assert captured["model"] == "deepseek-v4-flash"
        assert captured["bypass_proxy"] is True

    asyncio.run(scenario())
