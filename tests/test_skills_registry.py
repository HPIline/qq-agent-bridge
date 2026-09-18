import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from skills_registry import get_skill_index, load_skills


def test_load_skills_returns_tools():
    cfg = {"skills_enabled": ["weather", "rss", "github"]}
    tools = load_skills(cfg)
    names = {getattr(t, "name", None) for t in tools}
    assert {"weather", "rss_headlines", "github_repo"} <= names


def test_get_skill_index():
    text = get_skill_index()
    assert "weather" in text
    assert "github_repo" in text
    assert "rss_headlines" in text
    assert "skills_enabled" in text


def test_only_enabled_skills_loaded():
    cfg = {"skills_enabled": ["weather"]}
    tools = load_skills(cfg)
    names = {getattr(t, "name", None) for t in tools}
    assert names == {"weather"}


def test_agent_client_builds_skill_tools(tmp_path):
    from agent_client import AgentClient

    cfg = {
        "api_key": "test-key",
        "api_base_url": "http://127.0.0.1:9/v1",
        "tools_enabled": True,
        "shell_enabled": False,
        "file_tools_enabled": False,
        "web_search_enabled": False,
        "knowledge_tool_enabled": False,
        "skills_tool_enabled": True,
        "skills_enabled": ["weather"],
        "state_db_file": str(tmp_path / "state.db"),
    }
    client = AgentClient(cfg)
    tools = client._build_tools()
    assert any(getattr(t, "name", None) == "weather" for t in tools)
