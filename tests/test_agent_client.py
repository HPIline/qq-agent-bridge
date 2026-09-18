import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from agent_client import AgentClient, AgentError


class FakeRunOutput:
    def __init__(self, content: str = "回复", session_id: str = "s-1"):
        self.content = content
        self.session_id = session_id

    def get_content_as_string(self) -> str:
        return str(self.content)


class FakeAgent:
    def __init__(
        self,
        delay: float = 0.0,
        error: Exception | None = None,
        content: str = "回复",
    ):
        self.delay = delay
        self.error = error
        self.content = content
        self.calls: list[dict] = []
        self.model = SimpleNamespace(extra_headers=None)

    async def arun(self, prompt, **kwargs):
        self.calls.append({"prompt": prompt, **kwargs})
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return FakeRunOutput(content=self.content, session_id="s-1")


def make_client(tmp_path, monkeypatch, **cfg_overrides):
    cfg = {
        "api_key": "test-key",
        "api_base_url": "https://opencode.ai/zen/go/v1",
        "model": "deepseek-v4-flash",
        "workdir": str(tmp_path),
        "memory_db": str(tmp_path / "agno_test.db"),
        "request_timeout": 10,
    }
    cfg.update(cfg_overrides)
    client = AgentClient(cfg)
    return client


def test_agent_client_is_agno_alias():
    assert AgentClient is AgentClient
    assert AgentError is AgentError


def test_agno_error_fields():
    err = AgentError("超时", timeout=True, thread_id="t-1")
    assert err.timeout is True
    assert err.thread_id == "t-1"


def test_agent_client_run_returns_content_and_session(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    fake_agent = FakeAgent()
    monkeypatch.setattr(client, "_get_agent", lambda *a, **kw: fake_agent)
    text, thread_id = asyncio.run(client.run("你好"))
    assert text == "回复"
    assert thread_id == "s-1"
    assert fake_agent.calls[0]["prompt"] == "你好"
    # 会话头应带上 x-opencode-session
    assert "x-opencode-session" in fake_agent.model.extra_headers


def test_agent_client_generates_session_id_when_missing(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    fake_agent = FakeAgent()
    monkeypatch.setattr(client, "_get_agent", lambda *a, **kw: fake_agent)
    _, thread_id = asyncio.run(client.run("你好"))
    assert thread_id == "s-1"  # FakeAgent 固定返回 s-1
    assert fake_agent.calls[0]["session_id"].startswith("session-")


def test_agent_client_reuses_given_session_id(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    fake_agent = FakeAgent()
    monkeypatch.setattr(client, "_get_agent", lambda *a, **kw: fake_agent)
    _, thread_id = asyncio.run(client.run("你好", thread_id="my-session"))
    assert fake_agent.calls[0]["session_id"] == "my-session"
    assert thread_id == "s-1"  # FakeAgent 固定返回 s-1


def test_agent_client_passes_images(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    fake_agent = FakeAgent()
    monkeypatch.setattr(client, "_get_agent", lambda *a, **kw: fake_agent)
    asyncio.run(client.run("看图", image_paths=["/tmp/a.png"]))
    images = fake_agent.calls[0]["images"]
    assert len(images) == 1
    assert images[0].filepath == "/tmp/a.png"


def test_agent_client_timeout_raises_with_flag_and_thread_id(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    fake_agent = FakeAgent(delay=1.0)
    monkeypatch.setattr(client, "_get_agent", lambda *a, **kw: fake_agent)
    with pytest.raises(AgentError) as exc_info:
        asyncio.run(client.run("你好", thread_id="t-1", timeout=0.05))
    assert exc_info.value.timeout is True
    assert exc_info.value.thread_id == "t-1"


def test_agent_client_wraps_agent_errors(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    fake_agent = FakeAgent(error=RuntimeError("model exploded"))
    monkeypatch.setattr(client, "_get_agent", lambda *a, **kw: fake_agent)
    with pytest.raises(AgentError) as exc_info:
        asyncio.run(client.run("你好", thread_id="t-1"))
    assert "model exploded" in str(exc_info.value)
    assert exc_info.value.thread_id == "t-1"
    assert exc_info.value.timeout is False


def test_agent_client_raises_when_empty_reply(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    fake_agent = FakeAgent(content="   ")
    monkeypatch.setattr(client, "_get_agent", lambda *a, **kw: fake_agent)
    with pytest.raises(AgentError):
        asyncio.run(client.run("你好", thread_id="t-1"))


def test_agent_client_close(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    assert asyncio.run(client.close()) is None


def test_agent_client_build_grok_search_tool(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    tool = client._build_grok_search_tool()
    assert tool is not None
    assert tool.name == "web_search"
    assert "image_search" in tool.parameters["properties"]
    assert tool.parameters["required"] == ["query"]


def test_agent_client_build_cn_search_tool(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    tool = client._build_cn_search_tool()
    assert tool is not None
    assert tool.name == "cn_web_search"
    assert tool.parameters["required"] == ["query"]


def test_agent_client_build_grok_image_tool(tmp_path, monkeypatch):
    client = make_client(tmp_path, monkeypatch)
    tool = client._build_grok_image_tool()
    assert tool is not None
    assert tool.name == "image_search"
    assert tool.parameters["required"] == ["query"]