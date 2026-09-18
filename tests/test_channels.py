import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bridge_io
from agent_client import AgentClient
from bridge import Bridge
from sessions import SessionStore


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


def make_bridge(tmp: str) -> Bridge:
    fake_agent = Path(__file__).resolve().parent / "fake_agent.py"
    fake_agent.chmod(0o755)
    cfg = {
        "onebot_ws_url": "ws://127.0.0.1:1",
        "full_access_qq": ["10001"],
        "agent_path": str(fake_agent),
        "workdir": tmp,
        "request_timeout": 10,
    }
    store = SessionStore(Path(tmp) / "sessions.json")
    bridge = Bridge(cfg, store, AgentClient(cfg))
    bridge.ws = FakeWS()
    bridge.to_qq_dir = Path(tmp) / "channels/to_qq"
    bridge.to_qq_sent_dir = bridge.to_qq_dir / "sent"
    bridge.to_qq_dir.mkdir(parents=True, exist_ok=True)
    bridge.to_qq_sent_dir.mkdir(exist_ok=True)
    bridge.from_qq_log_path = Path(tmp) / "channels/from_qq/feedback.jsonl"
    bridge.agent_status_path = Path(tmp) / "channels/state/agent-status.md"
    bridge.legacy_agent_status_path = Path(tmp) / "legacy-agent-status.md"
    bridge.outbox_dir = Path(tmp) / "legacy-outbox"
    bridge.outbox_sent_dir = bridge.outbox_dir / "sent"
    bridge.outbox_dir.mkdir(exist_ok=True)
    bridge.outbox_sent_dir.mkdir(exist_ok=True)
    bridge.feedback_log_path = Path(tmp) / "legacy-inbox/feedback.log"
    bridge.decisions_dir = Path(tmp) / "legacy-decisions"
    bridge.decisions_dir.mkdir(exist_ok=True)
    bridge.pending_path = Path(tmp) / "channels/state/pending.json"
    bridge.pending_path.parent.mkdir(parents=True, exist_ok=True)
    return bridge


def test_envelope_flush_sends_and_archives():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge = make_bridge(tmp)
            path = bridge_io.write_report_envelope(
                bridge.to_qq_dir, "项目已完成。", recipients=["10001"]
            )
            await bridge._flush_outbox()
            assert len(bridge.ws.sent) == 1
            assert bridge.ws.sent[0]["params"]["message"] == "项目已完成。"
            assert not path.exists()
            assert list(bridge.to_qq_sent_dir.glob("*.json"))

    asyncio.run(scenario())


def test_envelope_flush_sends_media_markers_and_cleans_text():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge = make_bridge(tmp)
            bridge_io.write_report_envelope(
                bridge.to_qq_dir,
                "文件来了\n[FILE:/tmp/x.pdf|x.pdf]",
                recipients=["10001"],
            )
            sent_markers: list[tuple[str, dict]] = []

            async def fake_send_marker(user_id: str, marker: dict) -> None:
                sent_markers.append((user_id, marker))

            bridge._send_media_marker = fake_send_marker
            await bridge_io.flush_outbox(bridge)
            assert sent_markers
            assert sent_markers[0][1]["kind"] == "file"
            text_sent = " ".join(
                s["params"]["message"] for s in bridge.ws.sent if s.get("params", {}).get("message")
            )
            assert "[FILE:" not in text_sent
            assert "文件来了" in text_sent

    asyncio.run(scenario())


def test_envelope_flush_parses_file_marker():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge = make_bridge(tmp)
            source = Path(tmp) / "answer.txt"
            source.write_text("answer", encoding="utf-8")
            responses: list[dict] = []

            class EchoWS:
                async def send(self, raw: str) -> None:
                    payload = json.loads(raw)
                    responses.append(payload)
                    if "echo" not in payload:
                        return
                    response = {
                        "status": "ok",
                        "retcode": 0,
                        "data": {"file_id": "file-1"},
                        "echo": payload["echo"],
                    }
                    fut = bridge.pending_actions.get(payload["echo"])
                    if fut and not fut.done():
                        fut.set_result(response)

            bridge.ws = EchoWS()
            text = f"答案如下：\n[FILE:{source}|answer.txt]"
            path = bridge_io.write_report_envelope(bridge.to_qq_dir, text, recipients=["10001"])
            await bridge._flush_outbox()
            sent_texts = [
                p["params"]["message"]
                for p in responses
                if p.get("action") == "send_private_msg" and isinstance(p["params"]["message"], str)
            ]
            assert sent_texts == ["答案如下："]
            uploads = [p for p in responses if p.get("action") == "upload_private_file"]
            assert len(uploads) == 1
            assert uploads[0]["params"]["name"] == "answer.txt"
            assert not path.exists()
            assert list(bridge.to_qq_sent_dir.glob("*.json"))

    asyncio.run(scenario())


def test_route_main_agent_message_strips_prefix():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = make_bridge(tmp)
        bridge.main_agent_inbox_path = Path(tmp) / "channels/from_qq/main.jsonl"
        ok = bridge_io.route_main_agent_message(bridge, "10001", "/本机 下一步优化方向选A")
        assert ok is True
        lines = bridge.main_agent_inbox_path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["text"] == "下一步优化方向选A"
        assert entry["user_id"] == "10001"


def test_route_main_agent_message_ignores_normal_text():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = make_bridge(tmp)
        bridge.main_agent_inbox_path = Path(tmp) / "channels/from_qq/main.jsonl"
        assert bridge_io.route_main_agent_message(bridge, "10001", "你好") is False
        assert not bridge.main_agent_inbox_path.exists()


def test_envelope_flush_keeps_invalid_file():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge = make_bridge(tmp)
            bad = bridge.to_qq_dir / "bad.json"
            bad.write_text("{not-json", encoding="utf-8")
            await bridge._flush_outbox()
            assert bridge.ws.sent == []
            assert not bad.exists()
            assert list(bridge.to_qq_dir.glob("bad.json.invalid-*"))

    asyncio.run(scenario())


def test_legacy_migration_moves_files_into_channels():
    with tempfile.TemporaryDirectory() as tmp:
        bridge = make_bridge(tmp)
        (bridge.outbox_dir / "report-1.txt").write_text("旧汇报", encoding="utf-8")
        bridge.feedback_log_path.parent.mkdir(parents=True, exist_ok=True)
        bridge.feedback_log_path.write_text("[2026-08-10 01:00:00] 10001: 你好\n", encoding="utf-8")
        (bridge.decisions_dir / "pending.json").write_text(
            json.dumps({"id": "old-1", "kind": "task_stage"}), encoding="utf-8"
        )
        bridge.legacy_agent_status_path.write_text("旧状态", encoding="utf-8")
        counts = bridge_io.migrate_legacy_channels(bridge)
        assert counts["outbox"] == 1
        assert counts["feedback"] == 1
        assert counts["pending"] == 1
        assert counts["status"] == 1
        assert list(bridge.to_qq_dir.glob("*.json"))
        assert bridge.from_qq_log_path.exists()
        assert bridge.pending_path.exists()
        assert json.loads(bridge.pending_path.read_text(encoding="utf-8"))["kind"] == "task_stage"
        assert not bridge.feedback_log_path.exists()
        assert not (bridge.decisions_dir / "pending.json").exists()
        assert not bridge.legacy_agent_status_path.exists()
        assert bridge.agent_status_path.read_text(encoding="utf-8") == "旧状态"
