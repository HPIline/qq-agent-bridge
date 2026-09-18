import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rag import RagIndex, scan_docs, search_knowledge
from state_db import StateDB


def _write_sample(tmp_path):
    (tmp_path / "a.md").write_text("测试助手是统合思念体的外星人，负责观察地球。", encoding="utf-8")
    (tmp_path / "b.txt").write_text("阿布量化交易系统每天输出净值表。", encoding="utf-8")
    return tmp_path


def test_scan_and_search(tmp_path):
    src = _write_sample(tmp_path)
    db = StateDB(tmp_path / "state.db")
    count = asyncio.run(scan_docs([src], db))
    assert count >= 2
    hits = db.search_documents("外星人")
    assert len(hits) >= 1
    assert "a.md" in hits[0]["title"]


def test_rag_index_rebuild(tmp_path):
    src = _write_sample(tmp_path)
    db = StateDB(tmp_path / "state.db")
    index = RagIndex(db)
    count = asyncio.run(index.rebuild([src]))
    assert count >= 2
    assert len(index.query("外星人")) >= 1


def test_search_formatted_text(tmp_path):
    src = _write_sample(tmp_path)
    db = StateDB(tmp_path / "state.db")
    asyncio.run(scan_docs([src], db))
    text = search_knowledge(db, "外星人")
    assert "a.md" in text
    assert "没有找到" not in text


def test_search_knowledge_empty(tmp_path):
    db = StateDB(tmp_path / "state.db")
    text = search_knowledge(db, "不存在的内容")
    assert "没有找到" in text


def test_agent_client_builds_knowledge_tool(tmp_path):
    from agent_client import AgentClient

    cfg = {
        "api_key": "test-key",
        "api_base_url": "http://127.0.0.1:9/v1",
        "tools_enabled": True,
        "shell_enabled": False,
        "file_tools_enabled": False,
        "web_search_enabled": False,
        "knowledge_tool_enabled": True,
        "state_db_file": str(tmp_path / "state.db"),
    }
    client = AgentClient(cfg)
    tools = client._build_tools()
    assert any(getattr(t, "name", None) == "search_knowledge" for t in tools)
