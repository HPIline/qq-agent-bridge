import asyncio
import os
from pathlib import Path

import pytest

from agent_client import AgentClient, AgentError
from bridge import Bridge

_ORIGINAL_INIT = Bridge.__init__


@pytest.fixture(autouse=True)
def tolerate_chmod_permission_errors(monkeypatch):
    """测试沙箱可能禁止 chmod；这些测试不再依赖 fake_agent 脚本，chmod 失败可忽略。"""
    original_chmod = os.chmod

    def _chmod(path, mode, *args, **kwargs):
        try:
            return original_chmod(path, mode, *args, **kwargs)
        except PermissionError:
            return None

    monkeypatch.setattr(os, "chmod", _chmod)


@pytest.fixture(autouse=True)
def isolate_bridge_runtime_dirs(tmp_path, monkeypatch):
    """把桥接运行时目录隔离到测试临时目录，避免测试写入真实 qq-agent-bridge 目录。"""

    def patched_init(self, cfg, store, codex, *args, **kwargs):
        cfg["state_db_file"] = str(tmp_path / "state.db")
        _ORIGINAL_INIT(self, cfg, store, codex, *args, **kwargs)
        self.tmp_dir = tmp_path / "tmp"
        self.incoming_dir = self.tmp_dir / "incoming"
        self.incoming_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir = tmp_path / "inbox"
        self.feedback_log_path = self.inbox_dir / "feedback.log"
        self.decisions_dir = tmp_path / "decisions"
        self.pending_path = self.decisions_dir / "pending.json"
        self.outbox_dir = tmp_path / "outbox"
        self.outbox_sent_dir = self.outbox_dir / "sent"
        self.memory_path = tmp_path / "memory.md"
        self.messages_dir = tmp_path / "channels"
        self.to_qq_dir = tmp_path / "channels/to_qq"
        self.to_qq_sent_dir = tmp_path / "channels/to_qq/sent"
        self.from_qq_log_path = tmp_path / "channels/from_qq/feedback.jsonl"
        self.main_agent_inbox_path = tmp_path / "channels/from_qq/main.jsonl"
        self.agent_status_path = tmp_path / "channels/state/agent-status.md"
        self.legacy_agent_status_path = tmp_path / "legacy-agent-status.md"
        for directory in (
            self.inbox_dir,
            self.decisions_dir,
            self.outbox_dir,
            self.outbox_sent_dir,
            self.messages_dir,
            self.to_qq_dir,
            self.to_qq_sent_dir,
            self.from_qq_log_path.parent,
            self.main_agent_inbox_path.parent,
            self.agent_status_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(Bridge, "__init__", patched_init)


@pytest.fixture(autouse=True)
def fake_agent_core_for_bridge_tests(monkeypatch, request):
    """给桥接集成测试打上假的 agno 核心，避免测试真的走网络。

    只对 bridges/channels 集成测试生效；test_agent_client.py 需要测真实 AgentClient，
    不在本 fixture 的作用范围内。
    """
    module_name = getattr(request.node, "module", None)
    module_name = getattr(module_name, "__name__", "")
    short_name = module_name.rsplit(".", 1)[-1]
    if short_name not in {
        "test_bridge_flow",
        "test_proactive_bridge",
        "test_voice_bridge",
        "test_channels",
    }:
        yield
        return

    async def fake_run(
        self,
        prompt,
        thread_id=None,
        timeout=None,
        reasoning_effort=None,
        image_paths=None,
        model=None,
        model_provider=None,
        bypass_proxy=False,
    ):
        exit_code = os.environ.get("FAKE_AGENT_EXIT_CODE")
        if exit_code:
            raise AgentError(f"Codex 提前退出（退出码 {exit_code}）：空回复")
        prompt_file = os.environ.get("FAKE_AGENT_PROMPT_FILE")
        if prompt_file:
            Path(prompt_file).write_text(prompt, encoding="utf-8")
        sleep_seconds = float(os.environ.get("FAKE_AGENT_SLEEP", "0") or "0")
        if sleep_seconds:
            await asyncio.sleep(sleep_seconds)
        reply = os.environ.get("FAKE_AGENT_REPLY", "这是假的 Codex 回复")
        return reply, thread_id or "thread-fake-1"

    monkeypatch.setattr(AgentClient, "run", fake_run)
    yield


@pytest.fixture(autouse=True)
def fake_api_key(monkeypatch):
    """测试环境统一使用假 key，不读取任何本机凭据文件。"""
    import agent_client

    monkeypatch.setattr(agent_client, "_load_api_key", lambda cfg=None: "test-key")
    yield
