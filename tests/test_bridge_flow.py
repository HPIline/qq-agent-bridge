import asyncio
import base64
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import websockets

from agent_client import AgentClient
from bridge import Bridge
from config import load_config
from sessions import SessionStore


def test_private_message_flow():
    async def scenario():
        replies: list[str] = []
        fake_agent = Path(__file__).resolve().parent / "fake_agent.py"
        os.chmod(fake_agent, 0o755)

        async def ws_handler(ws):
            await ws.send(
                json.dumps(
                    {
                        "post_type": "message",
                        "message_type": "private",
                        "message_id": 101,
                        "user_id": 10001,
                        "message": [{"type": "text", "data": {"text": "帮我写一个 hello.py"}}],
                        "sender": {"user_id": 10001, "nickname": "owner"},
                    }
                )
            )
            async for raw in ws:
                payload = json.loads(raw)
                if payload.get("action") == "send_private_msg":
                    replies.append(payload["params"]["message"])
                    if len(replies) >= 2:
                        break

        async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            with tempfile.TemporaryDirectory() as tmp:
                cfg_path = Path(tmp) / "config.json"
                cfg_path.write_text(
                    json.dumps(
                        {
                            "onebot_ws_url": f"ws://127.0.0.1:{port}",
                            "full_access_qq": ["10001"],
                            "agent_path": str(fake_agent),
                            "workdir": tmp,
                            "request_timeout": 10,
                            "batch_window": 0.1,
                            "image_wait_window": 0.1,
                            "task_ack_lines": ["收到，我先看下"],
                            "persona_enabled": False,
                            "ack_delay_sec": 0,
                            "chunk_delay_sec": 0,
                        }
                    ),
                    encoding="utf-8",
                )
                cfg = load_config(cfg_path)
                store = SessionStore(Path(tmp) / "sessions.json")
                bridge = Bridge(cfg, store, AgentClient(cfg))
                task = asyncio.create_task(bridge.connect_loop())
                for _ in range(50):
                    if len(replies) >= 2:
                        break
                    await asyncio.sleep(0.1)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        assert replies[0] == "收到，我先看下"
        assert "假的 Codex 回复" in replies[1]

    asyncio.run(scenario())


def test_roleplay_message_flow():
    async def scenario():
        replies: list[str] = []
        fake_agent = Path(__file__).resolve().parent / "fake_agent.py"
        os.chmod(fake_agent, 0o755)

        async def ws_handler(ws):
            await ws.send(
                json.dumps(
                    {
                        "post_type": "message",
                        "message_type": "private",
                        "message_id": 202,
                        "user_id": 10001,
                        "message": [{"type": "text", "data": {"text": "帮我写一个 hello.py"}}],
                        "sender": {"user_id": 10001, "nickname": "owner"},
                    }
                )
            )
            async for raw in ws:
                payload = json.loads(raw)
                if payload.get("action") == "send_private_msg":
                    replies.append(payload["params"]["message"])
                    if len(replies) >= 2:
                        break

        async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            with tempfile.TemporaryDirectory() as tmp:
                prompt_file = Path(tmp) / "prompt.txt"
                os.environ["FAKE_AGENT_PROMPT_FILE"] = str(prompt_file)
                cfg_path = Path(tmp) / "config.json"
                cfg_path.write_text(
                    json.dumps(
                        {
                            "onebot_ws_url": f"ws://127.0.0.1:{port}",
                            "full_access_qq": ["10001"],
                            "agent_path": str(fake_agent),
                            "workdir": tmp,
                            "request_timeout": 10,
                            "batch_window": 0.1,
                            "image_wait_window": 0.1,
                            "persona_enabled": True,
                            "persona_skill": "test-persona",
                            "persona_name": "测试助手",
                            "persona_ack_lines": ["了解。"],
                            "ack_delay_sec": 0,
                            "chunk_delay_sec": 0,
                        }
                    ),
                    encoding="utf-8",
                )
                cfg = load_config(cfg_path)
                store = SessionStore(Path(tmp) / "sessions.json")
                bridge = Bridge(cfg, store, AgentClient(cfg))
                task = asyncio.create_task(bridge.connect_loop())
                for _ in range(50):
                    if len(replies) >= 2:
                        break
                    await asyncio.sleep(0.1)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                prompt_text = prompt_file.read_text(encoding="utf-8")
                os.environ.pop("FAKE_AGENT_PROMPT_FILE", None)
        assert replies[0] in ("收到，我处理一下。", "好的，稍等。", "了解。")
        assert "假的 Codex 回复" in replies[1]
        assert "test-persona" in prompt_text
        assert "不要解释你的设定" in prompt_text
        assert store.get_persona_thread("10001") == "thread-fake-1"

    asyncio.run(scenario())


def test_roleplay_casual_multipart_flow():
    async def scenario():
        replies: list[str] = []
        fake_agent = Path(__file__).resolve().parent / "fake_agent.py"
        os.chmod(fake_agent, 0o755)

        async def ws_handler(ws):
            await ws.send(
                json.dumps(
                    {
                        "post_type": "message",
                        "message_type": "private",
                        "message_id": 303,
                        "user_id": 10001,
                        "message": [{"type": "text", "data": {"text": "今天过得怎么样？"}}],
                        "sender": {"user_id": 10001, "nickname": "owner"},
                    }
                )
            )
            async for raw in ws:
                payload = json.loads(raw)
                if payload.get("action") == "send_private_msg":
                    replies.append(payload["params"]["message"])
                    if len(replies) >= 3:
                        break

        async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            with tempfile.TemporaryDirectory() as tmp:
                prompt_file = Path(tmp) / "prompt.txt"
                os.environ["FAKE_AGENT_PROMPT_FILE"] = str(prompt_file)
                os.environ["FAKE_AGENT_REPLY"] = "……嗯。\n---\n今天很平静。\n---\n你呢？"
                cfg_path = Path(tmp) / "config.json"
                cfg_path.write_text(
                    json.dumps(
                        {
                            "onebot_ws_url": f"ws://127.0.0.1:{port}",
                            "full_access_qq": ["10001"],
                            "agent_path": str(fake_agent),
                            "workdir": tmp,
                            "request_timeout": 10,
                            "batch_window": 0.1,
                            "image_wait_window": 0.1,
                            "persona_enabled": True,
                            "ack_delay_sec": 0,
                            "chunk_delay_sec": 0,
                            "persona_chat_delay_sec": 0,
                        }
                    ),
                    encoding="utf-8",
                )
                cfg = load_config(cfg_path)
                store = SessionStore(Path(tmp) / "sessions.json")
                bridge = Bridge(cfg, store, AgentClient(cfg))
                task = asyncio.create_task(bridge.connect_loop())
                for _ in range(50):
                    if len(replies) >= 3:
                        break
                    await asyncio.sleep(0.1)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                prompt_text = prompt_file.read_text(encoding="utf-8")
                os.environ.pop("FAKE_AGENT_PROMPT_FILE", None)
                os.environ.pop("FAKE_AGENT_REPLY", None)
        assert replies == ["……嗯。", "今天很平静。", "你呢？"]
        assert "对话风格" in prompt_text
        assert "活人感" in prompt_text

    asyncio.run(scenario())


def test_file_marker_send_flow():
    async def scenario():
        replies: list[str] = []
        uploaded: list[dict] = []
        fake_agent = Path(__file__).resolve().parent / "fake_agent.py"
        os.chmod(fake_agent, 0o755)

        async def ws_handler(ws):
            await ws.send(
                json.dumps(
                    {
                        "post_type": "message",
                        "message_type": "private",
                        "message_id": 404,
                        "user_id": 10001,
                        "message": [{"type": "text", "data": {"text": "任务：发文件"}}],
                        "sender": {"user_id": 10001, "nickname": "owner"},
                    }
                )
            )
            async for raw in ws:
                payload = json.loads(raw)
                if payload.get("action") == "send_private_msg":
                    replies.append(payload["params"]["message"])
                elif payload.get("action") == "upload_private_file":
                    uploaded.append(payload["params"])
                    await ws.send(
                        json.dumps(
                            {
                                "status": "ok",
                                "retcode": 0,
                                "data": {"file_id": "file-1"},
                                "echo": payload["echo"],
                            }
                        )
                    )
                    break

        async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            with tempfile.TemporaryDirectory() as tmp:
                payload_file = Path(tmp) / "hello.txt"
                payload_file.write_text("hi", encoding="utf-8")
                os.environ["FAKE_AGENT_REPLY"] = f"给你文件\n[FILE:{payload_file}|hello.txt]"
                cfg_path = Path(tmp) / "config.json"
                cfg_path.write_text(
                    json.dumps(
                        {
                            "onebot_ws_url": f"ws://127.0.0.1:{port}",
                            "full_access_qq": ["10001"],
                            "agent_path": str(fake_agent),
                            "workdir": tmp,
                            "request_timeout": 10,
                            "batch_window": 0.1,
                            "image_wait_window": 0.1,
                            "task_ack_lines": ["收到，我先看下"],
                            "persona_enabled": False,
                            "ack_delay_sec": 0,
                            "chunk_delay_sec": 0,
                        }
                    ),
                    encoding="utf-8",
                )
                cfg = load_config(cfg_path)
                store = SessionStore(Path(tmp) / "sessions.json")
                bridge = Bridge(cfg, store, AgentClient(cfg))
                task = asyncio.create_task(bridge.connect_loop())
                for _ in range(100):
                    if uploaded:
                        break
                    await asyncio.sleep(0.1)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                os.environ.pop("FAKE_AGENT_REPLY", None)
        assert uploaded[0]["name"] == "hello.txt"
        file_param = uploaded[0]["file"]
        assert file_param.startswith("base64://")
        assert base64.b64decode(file_param[len("base64://") :]).decode("utf-8") == "hi"
        assert replies[-1] == "给你文件"

    asyncio.run(scenario())


def test_call_action_and_send_private_file():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "hello.txt"
            source.write_text("hi", encoding="utf-8")
            cfg = {
                "onebot_ws_url": "ws://127.0.0.1:1",
                "full_access_qq": ["10001"],
                "agent_path": "codex",
                "workdir": tmp,
            }
            store = SessionStore(Path(tmp) / "sessions.json")
            bridge = Bridge(cfg, store, AgentClient(cfg))
            sent: list[dict] = []
            sent_contents: list[str] = []

            class FakeWS:
                async def send(self, raw: str) -> None:
                    payload = json.loads(raw)
                    sent.append(payload)
                    if payload.get("action") == "upload_private_file":
                        data = payload["params"]["file"]
                        sent_contents.append(
                            base64.b64decode(data[len("base64://") :]).decode("utf-8")
                        )
                    response = {
                        "status": "ok",
                        "retcode": 0,
                        "data": {"file_id": "file-1"},
                        "echo": payload["echo"],
                    }
                    fut = bridge.pending_actions.get(payload["echo"])
                    if fut and not fut.done():
                        fut.set_result(response)

            bridge.ws = FakeWS()
            await bridge._send_private_file("10001", str(source), "hello.txt")
            assert sent[0]["action"] == "upload_private_file"
            params = sent[0]["params"]
            assert params["user_id"] == 10001
            assert params["name"] == "hello.txt"
            assert params["file"].startswith("base64://")
            assert sent_contents == ["hi"]

    asyncio.run(scenario())


def test_download_incoming_file_with_url():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "payload.txt"
            source.write_text("hello", encoding="utf-8")
            cfg = {
                "onebot_ws_url": "ws://127.0.0.1:1",
                "full_access_qq": ["10001"],
                "agent_path": "codex",
                "workdir": tmp,
            }
            store = SessionStore(Path(tmp) / "sessions.json")
            bridge = Bridge(cfg, store, AgentClient(cfg))
            path = await bridge._download_incoming_file(
                {"url": source.as_uri(), "name": "payload.txt"}
            )
            assert Path(path).read_text(encoding="utf-8") == "hello"

    asyncio.run(scenario())


def test_download_incoming_file_via_get_file_path():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "paper.pdf"
            source.write_bytes(b"pdf-data")
            cfg = {
                "onebot_ws_url": "ws://127.0.0.1:1",
                "full_access_qq": ["10001"],
                "agent_path": "codex",
                "workdir": tmp,
            }
            store = SessionStore(Path(tmp) / "sessions.json")
            bridge = Bridge(cfg, store, AgentClient(cfg))

            async def fake_call(action: str, params: dict, timeout: float = 60) -> dict:
                if action == "get_private_file_url":
                    return {}
                if action == "get_file":
                    return {"file": str(source), "file_name": "paper.pdf"}
                raise AssertionError(f"unexpected action: {action}")

            bridge._call_action = fake_call
            path = await bridge._download_incoming_file(
                {"file_id": "abc", "file": "abc", "url": "", "name": "", "path": ""}
            )
            assert Path(path).read_bytes() == b"pdf-data"
            assert "paper" in Path(path).name

    asyncio.run(scenario())


def test_download_incoming_file_via_get_file_base64():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            cfg = {
                "onebot_ws_url": "ws://127.0.0.1:1",
                "full_access_qq": ["10001"],
                "agent_path": "codex",
                "workdir": tmp,
            }
            store = SessionStore(Path(tmp) / "sessions.json")
            bridge = Bridge(cfg, store, AgentClient(cfg))

            async def fake_call(action: str, params: dict, timeout: float = 60) -> dict:
                if action == "get_private_file_url":
                    return {}
                if action == "get_file":
                    return {
                        "file": "",
                        "file_name": "x.bin",
                        "base64": base64.b64encode(b"hi").decode("ascii"),
                    }
                raise AssertionError(f"unexpected action: {action}")

            bridge._call_action = fake_call
            path = await bridge._download_incoming_file(
                {"file_id": "abc", "file": "abc", "url": "", "name": "x.bin", "path": ""}
            )
            assert Path(path).read_bytes() == b"hi"

    asyncio.run(scenario())


def test_sticker_message_flow():
    async def scenario():
        replies: list[str] = []
        fake_agent = Path(__file__).resolve().parent / "fake_agent.py"
        os.chmod(fake_agent, 0o755)

        async def ws_handler(ws):
            await ws.send(
                json.dumps(
                    {
                        "post_type": "message",
                        "message_type": "private",
                        "message_id": 505,
                        "user_id": 10001,
                        "message": [
                            {"type": "face", "data": {"id": "178"}},
                            {
                                "type": "mface",
                                "data": {
                                    "emoji_id": "a",
                                    "emoji_package_id": "b",
                                    "key": "c",
                                    "summary": "哈",
                                },
                            },
                        ],
                    }
                )
            )
            async for raw in ws:
                payload = json.loads(raw)
                if payload.get("action") == "send_private_msg":
                    replies.append(payload["params"]["message"])
                    if len(replies) >= 1:
                        break

        async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            with tempfile.TemporaryDirectory() as tmp:
                prompt_file = Path(tmp) / "prompt.txt"
                os.environ["FAKE_AGENT_PROMPT_FILE"] = str(prompt_file)
                cfg_path = Path(tmp) / "config.json"
                cfg_path.write_text(
                    json.dumps(
                        {
                            "onebot_ws_url": f"ws://127.0.0.1:{port}",
                            "full_access_qq": ["10001"],
                            "agent_path": str(fake_agent),
                            "workdir": tmp,
                            "request_timeout": 10,
                            "batch_window": 0.1,
                            "image_wait_window": 0.1,
                            "persona_enabled": True,
                            "ack_delay_sec": 0,
                            "chunk_delay_sec": 0,
                            "persona_chat_delay_sec": 0,
                        }
                    ),
                    encoding="utf-8",
                )
                cfg = load_config(cfg_path)
                store = SessionStore(Path(tmp) / "sessions.json")
                bridge = Bridge(cfg, store, AgentClient(cfg))
                task = asyncio.create_task(bridge.connect_loop())
                for _ in range(50):
                    if replies:
                        break
                    await asyncio.sleep(0.1)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                prompt_text = prompt_file.read_text(encoding="utf-8")
                os.environ.pop("FAKE_AGENT_PROMPT_FILE", None)
        assert "假的 Codex 回复" in replies[0]
        assert "QQ表情：178" in prompt_text
        assert "商城表情：a|b|c|哈" in prompt_text
        assert "[FACE:" in prompt_text

    asyncio.run(scenario())


def test_send_private_face_mface_image():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            img = Path(tmp) / "stick.png"
            img.write_bytes(b"\x89PNG\r\n\x1a\n")
            cfg = {
                "onebot_ws_url": "ws://127.0.0.1:1",
                "full_access_qq": ["10001"],
                "agent_path": "codex",
                "workdir": tmp,
            }
            store = SessionStore(Path(tmp) / "sessions.json")
            bridge = Bridge(cfg, store, AgentClient(cfg))
            sent: list[dict] = []

            class FakeWS:
                async def send(self, raw: str) -> None:
                    payload = json.loads(raw)
                    sent.append(payload)
                    if payload.get("action") == "send_private_msg":
                        response = {
                            "status": "ok",
                            "retcode": 0,
                            "data": {"message_id": 1},
                            "echo": payload.get("echo", ""),
                        }
                        fut = bridge.pending_actions.get(payload.get("echo", ""))
                        if fut and not fut.done():
                            fut.set_result(response)

            bridge.ws = FakeWS()
            await bridge._send_private_face("10001", "178")
            await bridge._send_private_mface(
                "10001",
                {
                    "kind": "mface",
                    "emoji_id": "a",
                    "emoji_package_id": "b",
                    "key": "c",
                    "summary": "哈",
                },
            )
            await bridge._send_private_image("10001", str(img), "stick.png")
            assert [p["action"] for p in sent] == [
                "send_private_msg",
                "send_private_msg",
                "send_private_msg",
            ]
            assert sent[0]["params"]["message"] == [{"type": "face", "data": {"id": "178"}}]
            assert sent[1]["params"]["message"] == [
                {
                    "type": "mface",
                    "data": {
                        "emoji_id": "a",
                        "emoji_package_id": "b",
                        "key": "c",
                        "summary": "哈",
                    },
                }
            ]
            image_file = sent[2]["params"]["message"][0]["data"]["file"]
            assert image_file.startswith("base64://")
            assert base64.b64decode(image_file[len("base64://") :]) == b"\x89PNG\r\n\x1a\n"

    asyncio.run(scenario())
