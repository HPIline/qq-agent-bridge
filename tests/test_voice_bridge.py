import asyncio
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


class FakeVoiceTTS:
    async def synthesize(self, text: str) -> bytes:
        return b"FAKE-VOICE-WAV"


def test_voice_marker_sends_record():
    async def scenario():
        replies = []
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_AGENT_REPLY"] = (
                "……嗯。\n---\n[VOICE:こんにちは。]\n---\n要一起看书吗。"
            )
            fake_agent = Path(tmp) / "fake_agent_voice.py"
            fake_agent.write_text(
                "#!/usr/bin/env python3\n"
                "import sys, time\n"
                "args = sys.argv[1:]\n"
                "out = args[args.index('-o') + 1]\n"
                'print(\'{"type":"thread.started","payload":{"id":"t-v"}}\', flush=True)\n'
                "time.sleep(0.2)\n"
                "open(out, 'w', encoding='utf-8').write('……嗯。\\n---\\n[VOICE:こんにちは。]\\n---\\n要一起看书吗。')\n",
                encoding="utf-8",
            )
            os.chmod(fake_agent, 0o755)

            async def ws_handler(ws):
                await ws.send(
                    json.dumps(
                        {
                            "post_type": "message",
                            "message_type": "private",
                            "message_id": 201,
                            "user_id": 10001,
                            "message": [{"type": "text", "data": {"text": "在吗"}}],
                        }
                    )
                )
                async for raw in ws:
                    payload = json.loads(raw)
                    if payload.get("action") == "send_private_msg":
                        replies.append(payload["params"]["message"])
                        echo = payload.get("echo")
                        if echo:
                            await ws.send(
                                json.dumps(
                                    {
                                        "status": "ok",
                                        "retcode": 0,
                                        "data": {"message_id": 1},
                                        "echo": echo,
                                    }
                                )
                            )
                        if len(replies) >= 3:
                            break

            async with websockets.serve(ws_handler, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
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
                            "persona_chat_max_chars": 40,
                            "persona_chat_max_segments": 4,
                            "persona_chat_delay_sec": 0,
                            "voice_max_chars": 120,
                            "voice_cache_dir": tmp,
                        }
                    ),
                    encoding="utf-8",
                )
                cfg = load_config(cfg_path)
                store = SessionStore(Path(tmp) / "sessions.json")
                bridge = Bridge(
                    cfg,
                    store,
                    AgentClient(cfg),
                    tts_client=FakeVoiceTTS(),
                    silk_encoder=lambda data: b"SILK-" + data,
                )
                task = asyncio.create_task(bridge.connect_loop())
                for _ in range(100):
                    if len(replies) >= 3:
                        break
                    await asyncio.sleep(0.1)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        assert len(replies) == 3
        assert replies[0] == "……嗯。"
        assert replies[1] == "要一起看书吗。"
        voice = replies[2]
        assert isinstance(voice, list) and voice[0]["type"] == "record"
        file_data = voice[0]["data"]["file"]
        assert file_data.startswith("base64://")
        import base64

        assert base64.b64decode(file_data[len("base64://") :]) == b"SILK-FAKE-VOICE-WAV"

    asyncio.run(scenario())
    os.environ.pop("FAKE_AGENT_REPLY", None)
