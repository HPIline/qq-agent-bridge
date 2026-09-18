import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from forward_utils import build_forward_nodes, send_forward, should_forward


def test_build_forward_nodes():
    nodes = build_forward_nodes(["第一段", "第二段"])
    assert len(nodes) == 2
    assert nodes[0]["type"] == "node"
    assert nodes[0]["data"]["name"] == "AI 助手"
    named = build_forward_nodes(["x"], sender_name="我的机器人", sender_uin="12345")
    assert named[0]["data"]["name"] == "我的机器人"
    assert named[0]["data"]["uin"] == "12345"
    content = nodes[0]["data"]["content"]
    assert content[0]["type"] == "text"
    assert content[0]["data"]["text"] == "第一段"


def test_should_forward_threshold():
    assert should_forward(["a"] * 5, threshold=5) is True
    assert should_forward(["a"] * 4, threshold=5) is False


def test_send_forward_calls_action_and_returns_true(tmp_path):
    class FakeBridge:
        def __init__(self):
            self.calls = []

        async def _call_action(self, action, params, timeout=60):
            self.calls.append((action, params))
            return {"status": "ok"}

    bridge = FakeBridge()
    ok = asyncio.run(send_forward(bridge, "10001", ["a", "b"], threshold=2))
    assert ok is True
    assert bridge.calls[0][0] == "send_private_forward_msg"
    assert bridge.calls[0][1]["user_id"] == 10001
    assert len(bridge.calls[0][1]["messages"]) == 2


def test_send_forward_returns_false_when_below_threshold(tmp_path):
    class FakeBridge:
        async def _call_action(self, action, params, timeout=60):
            raise AssertionError("不应该调用")

    bridge = FakeBridge()
    assert asyncio.run(send_forward(bridge, "10001", ["a"], threshold=5)) is False


def test_send_forward_returns_false_on_error(tmp_path):
    class FakeBridge:
        async def _call_action(self, action, params, timeout=60):
            raise RuntimeError("unsupported")

    bridge = FakeBridge()
    assert asyncio.run(send_forward(bridge, "10001", ["a"] * 5, threshold=5)) is False
