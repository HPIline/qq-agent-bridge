import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from command_registry import registry
from state_db import StateDB
from task_manager import TaskManager


class FakeBridge:
    def __init__(self, tmp_path):
        self.cfg = {"rag_dirs": [str(tmp_path / "docs")]}
        self.state_db = StateDB(tmp_path / "state.db")
        self.task_manager = TaskManager(self, self.state_db)
        self.sent = []
        self.timetable_path = tmp_path / "timetable.json"
        self.pending_path = tmp_path / "pending.json"

    async def _send_private(self, user_id, text):
        self.sent.append((user_id, text))


def test_remind_command_registered_and_sends(tmp_path):
    bridge = FakeBridge(tmp_path)
    m = registry.match("/提醒 喝水 明天9点")
    assert m is not None
    assert m.name == "提醒"
    asyncio.run(m.handler(bridge, "10001", m.args_str))
    assert bridge.sent[0][1].startswith("已设置提醒")


def test_todo_add_command(tmp_path):
    bridge = FakeBridge(tmp_path)
    m = registry.match("/待办 添加 交作业 截止:2026-09-02")
    assert m is not None
    asyncio.run(m.handler(bridge, "10001", m.args_str))
    assert len(bridge.state_db.list_todos("10001")) == 1


def test_task_submit_command(tmp_path):
    bridge = FakeBridge(tmp_path)
    m = registry.match("/任务 帮我处理数据")
    assert m is not None
    asyncio.run(m.handler(bridge, "10001", m.args_str))
    assert len(bridge.state_db.list_tasks("10001")) == 1


def test_knowledge_search_command(tmp_path):
    bridge = FakeBridge(tmp_path)
    docs = Path(bridge.cfg["rag_dirs"][0])
    docs.mkdir(parents=True)
    (docs / "a.md").write_text("测试助手是外星人。", encoding="utf-8")
    rebuild = registry.match("/知识库 重建")
    assert rebuild is not None
    asyncio.run(rebuild.handler(bridge, "10001", rebuild.args_str))
    m = registry.match("/知识库 搜 外星人")
    assert m is not None
    asyncio.run(m.handler(bridge, "10001", m.args_str))
    assert "a.md" in bridge.sent[-1][1]


def test_skills_command_registered(tmp_path):
    bridge = FakeBridge(tmp_path)
    m = registry.match("/技能")
    assert m is not None
    asyncio.run(m.handler(bridge, "10001", m.args_str))
    assert "weather" in bridge.sent[0][1]


def test_digest_command_registered(tmp_path):
    bridge = FakeBridge(tmp_path)
    m = registry.match("/晨报")
    assert m is not None
    asyncio.run(m.handler(bridge, "10001", m.args_str))
    assert "晨报" in bridge.sent[0][1]


def test_help_command_registered(tmp_path):
    bridge = FakeBridge(tmp_path)
    m = registry.match("/help")
    assert m is not None
    asyncio.run(m.handler(bridge, "10001", m.args_str))
    assert "可用命令" in bridge.sent[0][1]
