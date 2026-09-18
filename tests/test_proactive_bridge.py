import asyncio
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import handlers
from agent_client import AgentClient, AgentError
from bridge import Bridge, MessageBuffer
from sessions import SessionStore
from timetable import save_timetable


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


def make_bridge(tmp: str, **overrides) -> tuple[Bridge, SessionStore]:
    fake_agent = Path(__file__).resolve().parent / "fake_agent.py"
    os.chmod(fake_agent, 0o755)
    cfg = {
        "onebot_ws_url": "ws://127.0.0.1:1",
        "full_access_qq": ["10001"],
        "agent_path": str(fake_agent),
        "workdir": tmp,
        "request_timeout": 10,
        "fallback_enabled": True,
        "fallback_model": "deepseek-v4-flash",
        "mimo_vision_url": "https://opencode.ai/zen/go/v1/chat/completions",
        "mimo_vision_model": "mimo-v2.5",
        "mimo_vision_api_key": "",
        "mimo_vision_max_tokens": 1200,
        "vision_timeout_sec": 90,
        "task_prefixes": ["任务：", "任务:", "/task", "task:"],
        "task_keywords": [
            "帮我",
            "请帮我",
            "执行",
            "运行",
            "写一个",
            "修改",
            "创建",
            "部署",
            "翻译",
            "总结",
            "整理",
            "分析",
            "把",
        ],
        "task_auto_length": 60,
        "task_ack_lines": ["收到，我先看下"],
        "ack_delay_sec": 0,
        "chunk_delay_sec": 0,
        "persona_enabled": True,
        "proactive_enabled": True,
        "proactive_fixed_times": [],
        "proactive_windows": ["00:00-23:59"],
        "proactive_class_windows": ["00:00-23:59"],
        "proactive_idle_minutes": 180,
        "proactive_cooldown_minutes": 240,
        "proactive_max_per_day": 4,
        "proactive_trending_enabled": False,
        "proactive_notes_file": "proactive-notes.md",
        "timetable_file": "timetable.json",
        "proactive_class_lead_minutes": 15,
        "persona_chat_max_chars": 40,
        "persona_chat_max_segments": 4,
        "persona_chat_delay_sec": 0,
    }
    cfg.update(overrides)
    store = SessionStore(Path(tmp) / "sessions.json")
    bridge = Bridge(cfg, store, AgentClient(cfg))
    bridge.ws = FakeWS()
    bridge.tmp_dir = Path(tmp)
    bridge.incoming_dir = Path(tmp) / "incoming"
    bridge.incoming_dir.mkdir(exist_ok=True)
    bridge.timetable_path = Path(tmp) / "timetable.json"
    bridge.notes_path = Path(tmp) / "proactive-notes.md"
    return bridge, store


class RecordingCodex(AgentClient):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.calls: list[dict] = []

    async def run(
        self,
        prompt: str,
        thread_id: str | None = None,
        timeout: float | None = None,
        reasoning_effort: str | None = None,
        image_paths: list[str] | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        bypass_proxy: bool = False,
    ) -> tuple[str, str | None]:
        self.calls.append(
            {
                "prompt": prompt,
                "thread_id": thread_id,
                "image_paths": image_paths,
                "model": model,
                "model_provider": model_provider,
                "bypass_proxy": bypass_proxy,
            }
        )
        return "……看到了。", "t-1"


def test_proactive_tick_fixed_slot():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            now = dt.datetime(2026, 8, 6, 9, 30)
            slot = f"{now:%H:%M}"
            os.environ["FAKE_AGENT_REPLY"] = "……今天也要好好休息。"
            bridge, store = make_bridge(tmp, proactive_fixed_times=[slot])
            await bridge._proactive_tick(now=now)
            os.environ.pop("FAKE_AGENT_REPLY", None)
            assert len(bridge.ws.sent) == 1
            assert bridge.ws.sent[0]["action"] == "send_private_msg"
            assert bridge.ws.sent[0]["params"]["message"] == "……今天也要好好休息。"
            state = store.get_proactive_state("10001")
            assert state["count"] == 1
            assert state["fixed_done"] == [f"{now:%Y-%m-%d}|{slot}"]

    asyncio.run(scenario())


def test_proactive_tick_idle_and_cooldown():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            now = dt.datetime(2026, 8, 6, 14, 0)
            os.environ["FAKE_AGENT_REPLY"] = "……在忙吗。"
            bridge, store = make_bridge(
                tmp,
                proactive_idle_minutes=0,
                proactive_cooldown_minutes=60,
            )
            state = store.get_proactive_state("10001")
            state["last_active_ts"] = (now - dt.timedelta(minutes=1)).timestamp()
            store.save_proactive_state("10001", state)
            await bridge._proactive_tick(now=now)
            await bridge._proactive_tick(now=now + dt.timedelta(seconds=30))
            os.environ.pop("FAKE_AGENT_REPLY", None)
            assert len(bridge.ws.sent) == 1

    asyncio.run(scenario())


def test_proactive_tick_skips_busy_paused_non_roleplay():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            now = dt.datetime(2026, 8, 6, 14, 0)
            os.environ["FAKE_AGENT_REPLY"] = "……不该发。"
            bridge, store = make_bridge(tmp, proactive_idle_minutes=0, proactive_cooldown_minutes=0)
            bridge.busy_users.add("10001")
            await bridge._proactive_tick(now=now)
            bridge.busy_users.clear()
            state = store.get_proactive_state("10001")
            state["paused"] = True
            store.save_proactive_state("10001", state)
            await bridge._proactive_tick(now=now)
            state["paused"] = False
            store.save_proactive_state("10001", state)
            store.set_persona("10001", False)
            await bridge._proactive_tick(now=now)
            os.environ.pop("FAKE_AGENT_REPLY", None)
            assert bridge.ws.sent == []

    asyncio.run(scenario())


def test_proactive_tick_class_reminder_dedupes():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            now = dt.datetime(2026, 8, 6, 10, 0)
            day = now.isoweekday()
            start = (now + dt.timedelta(minutes=5)).strftime("%H:%M")
            end = (now + dt.timedelta(minutes=100)).strftime("%H:%M")
            os.environ["FAKE_AGENT_REPLY"] = "……十分钟后有课。"
            bridge, store = make_bridge(tmp, proactive_class_lead_minutes=15)
            save_timetable(
                bridge.timetable_path,
                [
                    {
                        "day": day,
                        "start": start,
                        "end": end,
                        "name": "高等数学",
                        "location": "教1-101",
                        "weeks": "",
                    }
                ],
            )
            await bridge._proactive_tick(now=now)
            await bridge._proactive_tick(now=now + dt.timedelta(minutes=1))
            os.environ.pop("FAKE_AGENT_REPLY", None)
            assert len(bridge.ws.sent) == 1
            state = store.get_proactive_state("10001")
            assert len(state.get("reminded_classes", [])) == 1

    asyncio.run(scenario())


def test_proactive_commands():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_AGENT_REPLY"] = "……在吗。"
            bridge, store = make_bridge(tmp, proactive_cooldown_minutes=240)
            for text in ("/静默", "/唤醒", "/话题"):
                buf = MessageBuffer("10001", bridge.cfg)
                buf.add_text(text)
                await bridge._process_buffer("10001", buf)
            os.environ.pop("FAKE_AGENT_REPLY", None)
            state = store.get_proactive_state("10001")
            assert state["paused"] is False
            assert state["count"] == 0  # /话题 不计入当天次数
            assert state["last_ts"] is not None  # /话题 会刷新上次主动时间
            messages = [s["params"]["message"] for s in bridge.ws.sent]
            assert messages[0] == "……好。"
            assert messages[1] == "嗯。"
            assert messages[2] == "……在吗。"

    asyncio.run(scenario())


def test_proactive_commands_rejected_in_normal_mode():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp, persona_enabled=False)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("/话题")
            await bridge._process_buffer("10001", buf)
            assert bridge.ws.sent[0]["params"]["message"] == "该命令仅角色扮演模式可用。"

    asyncio.run(scenario())


def test_timetable_csv_import_and_confirm():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            csv_path = Path(tmp) / "timetable.csv"
            csv_path.write_text(
                "day,start,end,name,location,weeks\n1,08:00,09:40,高等数学,教1-101,\n",
                encoding="utf-8",
            )
            bridge.timetable_mode_users.add("10001")
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_file({"url": csv_path.as_uri(), "name": "timetable.csv"})
            await bridge._process_buffer("10001", buf)
            assert "识别结果" in bridge.ws.sent[0]["params"]["message"]
            assert "高等数学" in bridge.ws.sent[0]["params"]["message"]
            confirm = MessageBuffer("10001", bridge.cfg)
            confirm.add_text("确认")
            await bridge._process_buffer("10001", confirm)
            assert bridge.timetable_path.exists()
            assert store.get_proactive_state("10001")["reminded_classes"] == []
            assert "已保存" in bridge.ws.sent[1]["params"]["message"]

    asyncio.run(scenario())


def test_timetable_view_and_clear():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            save_timetable(
                bridge.timetable_path,
                [
                    {
                        "day": 1,
                        "start": "08:00",
                        "end": "09:40",
                        "name": "高等数学",
                        "location": "教1-101",
                        "weeks": "",
                    }
                ],
            )
            view = MessageBuffer("10001", bridge.cfg)
            view.add_text("/课表查看")
            await bridge._process_buffer("10001", view)
            assert "高等数学" in bridge.ws.sent[0]["params"]["message"]
            clear = MessageBuffer("10001", bridge.cfg)
            clear.add_text("/课表清除")
            await bridge._process_buffer("10001", clear)
            assert not bridge.timetable_path.exists()
            assert bridge.ws.sent[1]["params"]["message"] == "课表已清除。"

    asyncio.run(scenario())


def test_roleplay_turn_count_increments_after_reply():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_AGENT_REPLY"] = "……嗯。"
            bridge, store = make_bridge(tmp)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("你好")
            await bridge._process_buffer("10001", buf)
            os.environ.pop("FAKE_AGENT_REPLY", None)
            assert store.get_persona_turns("10001") == 1

    asyncio.run(scenario())


def test_roleplay_prompt_injects_memory_file():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            prompt_file = Path(tmp) / "prompt.txt"
            os.environ["FAKE_AGENT_PROMPT_FILE"] = str(prompt_file)
            os.environ["FAKE_AGENT_REPLY"] = "……嗯。"
            bridge, store = make_bridge(tmp)
            bridge.memory_path = Path(tmp) / "memory.md"
            bridge.memory_path.write_text("记得：主人喜欢看书。", encoding="utf-8")
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("你好")
            await bridge._process_buffer("10001", buf)
            os.environ.pop("FAKE_AGENT_PROMPT_FILE", None)
            os.environ.pop("FAKE_AGENT_REPLY", None)
            prompt = prompt_file.read_text(encoding="utf-8")
            assert "长期记忆" in prompt
            assert "记得：主人喜欢看书。" in prompt

    asyncio.run(scenario())


def test_roleplay_rotation_writes_memory_and_resets_thread():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_AGENT_REPLY"] = "长期记忆：主人喜欢在晚上看书。"
            bridge, store = make_bridge(
                tmp,
                persona_reset_turns=3,
                persona_memory_file="memory.md",
            )
            bridge.memory_path = Path(tmp) / "memory.md"
            store.set_persona_thread("10001", "thread-old")
            store.set_persona_turns("10001", 3)
            await bridge._maybe_rotate_persona("10001")
            os.environ.pop("FAKE_AGENT_REPLY", None)
            assert store.get_persona_thread("10001") is None
            assert "主人喜欢在晚上看书" in bridge.memory_path.read_text(encoding="utf-8")

    asyncio.run(scenario())


def test_roleplay_rotation_skips_below_threshold():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            args_file = Path(tmp) / "args.json"
            os.environ["FAKE_AGENT_ARGS_FILE"] = str(args_file)
            bridge, store = make_bridge(tmp, persona_reset_turns=5)
            bridge.memory_path = Path(tmp) / "memory.md"
            store.set_persona_thread("10001", "thread-old")
            store.set_persona_turns("10001", 2)
            await bridge._maybe_rotate_persona("10001")
            os.environ.pop("FAKE_AGENT_ARGS_FILE", None)
            assert store.get_persona_thread("10001") == "thread-old"
            assert not args_file.exists()
            assert not bridge.memory_path.exists()

    asyncio.run(scenario())


def test_roleplay_rotation_continues_when_summary_fails():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_AGENT_EXIT_CODE"] = "2"
            try:
                bridge, store = make_bridge(tmp, persona_reset_turns=3)
                bridge.memory_path = Path(tmp) / "memory.md"
                store.set_persona_thread("10001", "thread-old")
                store.set_persona_turns("10001", 3)
                await bridge._maybe_rotate_persona("10001")
                assert store.get_persona_thread("10001") is None
            finally:
                os.environ.pop("FAKE_AGENT_EXIT_CODE", None)

    asyncio.run(scenario())


def test_proactive_strips_skill_loading_meta_from_sent_messages(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                return (
                    "技能已在此会话加载（SKILL.md 及 resource 资源均已读取）。当前时间 21:01，处于可主动时段（09:00–23:30），距上一次开口已过 4 小时。\n"
                    "---\n"
                    "晚上好 (￣ω￣)。这个点，一天的课应该都结束了吧。\n"
                    "---\n"
                    "忙完就歇着吧，别一直盯着电脑。今晚的题想做的话，我随时在 (・_・)。"
                ), "t-meta"

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            store.set_persona_thread("10001", "thread-old")
            await bridge._run_proactive("10001", "manual", record=False)
            messages = [
                s["params"]["message"]
                for s in bridge.ws.sent
                if s.get("action") == "send_private_msg"
            ]
            assert messages
            assert all(
                "技能已" not in m and "SKILL.md" not in m and "主动时段" not in m for m in messages
            )
            assert any("晚上好" in m for m in messages)

    asyncio.run(scenario())


def test_proactive_prompt_injects_memory_file():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            prompt_file = Path(tmp) / "prompt.txt"
            os.environ["FAKE_AGENT_PROMPT_FILE"] = str(prompt_file)
            os.environ["FAKE_AGENT_REPLY"] = "……有安排。"
            bridge, store = make_bridge(tmp)
            bridge.memory_path = Path(tmp) / "memory.md"
            bridge.memory_path.write_text("记得：下午有课。", encoding="utf-8")
            store.set_persona_thread("10001", "thread-old")
            await bridge._run_proactive("10001", "manual", record=False)
            os.environ.pop("FAKE_AGENT_PROMPT_FILE", None)
            os.environ.pop("FAKE_AGENT_REPLY", None)
            prompt = prompt_file.read_text(encoding="utf-8")
            assert "长期记忆" in prompt
            assert "记得：下午有课。" in prompt

    asyncio.run(scenario())


def test_proactive_prompt_injects_trending_and_filtered_memory(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            prompt_file = Path(tmp) / "prompt.txt"
            os.environ["FAKE_AGENT_PROMPT_FILE"] = str(prompt_file)
            os.environ["FAKE_AGENT_REPLY"] = "……热梗有意思。"
            bridge, store = make_bridge(tmp, proactive_trending_enabled=True)
            bridge.memory_path = Path(tmp) / "memory.md"
            bridge.memory_path.write_text(
                "**用户身份与关系**\n"
                "- 主人是西安交大学生\n"
                "- 可视为女友\n\n"
                "**偏好**\n"
                "- 喜欢颜文字\n\n"
                "**进行中的事情/项目**\n"
                "- OpenCode 修复\n",
                encoding="utf-8",
            )

            def fake_fetch(cfg, cache=None, now=None):
                return "热梗：爱你老己"

            monkeypatch.setattr("proactive.get_cached_trending_context", fake_fetch)
            store.set_persona_thread("10001", "thread-old")
            await bridge._run_proactive("10001", "manual", record=False)
            os.environ.pop("FAKE_AGENT_PROMPT_FILE", None)
            os.environ.pop("FAKE_AGENT_REPLY", None)
            prompt = prompt_file.read_text(encoding="utf-8")
            assert "热梗：爱你老己" in prompt
            assert "西安交大学生" in prompt
            assert "喜欢颜文字" in prompt
            assert "OpenCode" not in prompt
            assert "可视为女友" not in prompt

    asyncio.run(scenario())


def test_proactive_topic_markers_update_state_and_hidden(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_AGENT_REPLY"] = (
                "聊个热梗[TOPIC:event|热梗|牛来]\n"
                "再说说AI[TOPIC:category|AI/科技|]"
            )
            bridge, store = make_bridge(tmp)
            store.set_persona_thread("10001", "thread-old")
            await bridge._run_proactive("10001", "manual", record=False)
            os.environ.pop("FAKE_AGENT_REPLY", None)
            state = store.get_proactive_state("10001")
            assert "热梗|牛来" in state.get("avoid_events", [])
            assert state.get("category_counts", {}).get("AI/科技") == 1
            sent_texts = [
                s["params"]["message"]
                for s in bridge.ws.sent
                if s.get("action") == "send_private_msg"
            ]
            assert all("[TOPIC:" not in text for text in sent_texts)

    asyncio.run(scenario())


def test_describe_image_skips_ocr(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)

            async def fake_describe(path, *args, **kwargs):
                return "画面描述"

            monkeypatch.setattr("bridge.describe_image", fake_describe)
            result = await bridge._describe_image("x.png")
            assert "画面描述" in result
            assert "OCR 文字提取" not in result

    asyncio.run(scenario())


def test_describe_image_still_enriches_on_uncertainty(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)

            async def fake_describe(path, *args, **kwargs):
                return "画面描述。\n【不确定项】：身份未知"

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                return "补充结论", None

            monkeypatch.setattr("bridge.describe_image", fake_describe)
            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            result = await bridge._describe_image("x.png")
            assert "补充查证（联网）" in result
            assert "补充结论" in result

    asyncio.run(scenario())


def test_vision_enrichment_triggers_on_uncertainty(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp, vision_enrich_enabled=True)

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                assert thread_id is None
                return "这是 LINE 布朗熊", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            result = await bridge._enrich_vision(
                "画面描述。\n【不确定项】：该角色的具体身份无法确认"
            )
            assert "补充查证（联网）" in result
            assert "这是 LINE 布朗熊" in result

    asyncio.run(scenario())


def test_vision_enrichment_skips_empty_uncertainty_section(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp, vision_enrich_enabled=True)
            called = False

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                nonlocal called
                called = True
                return "不应调用", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            result = await bridge._enrich_vision("画面清晰。\n【不确定项】无")
            assert result == "画面清晰。\n【不确定项】无"
            assert called is False

    asyncio.run(scenario())


def test_vision_enrichment_skips_clear_description(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp, vision_enrich_enabled=True)
            called = False

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                nonlocal called
                called = True
                return "不应调用", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            result = await bridge._enrich_vision("画面清晰：一只棕色熊")
            assert result == "画面清晰：一只棕色熊"
            assert called is False

    asyncio.run(scenario())


def test_vision_enrichment_disabled(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp, vision_enrich_enabled=False)
            called = False

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                nonlocal called
                called = True
                return "不应调用", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            result = await bridge._enrich_vision("【不确定项】：不知道这是谁")
            assert result == "【不确定项】：不知道这是谁"
            assert called is False

    asyncio.run(scenario())


def test_enrich_vision_uses_enrich_timeout(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(
                tmp,
                vision_enrich_enabled=True,
                search_timeout=7,
            )
            captured: dict[str, int] = {}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                captured["timeout"] = timeout
                return "结论", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            result = await bridge._enrich_vision("【不确定项】：身份未知")
            assert "结论" in result
            assert captured["timeout"] == 7

    asyncio.run(scenario())


def test_process_buffer_serializes_concurrent_calls(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            state = {"active": 0, "max": 0, "calls": 0}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                state["active"] += 1
                state["calls"] += 1
                state["max"] = max(state["max"], state["active"])
                await asyncio.sleep(0.05)
                state["active"] -= 1
                return "……嗯。", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            b1 = MessageBuffer("10001", bridge.cfg)
            b1.add_text("消息一")
            b2 = MessageBuffer("10001", bridge.cfg)
            b2.add_text("消息二")
            await asyncio.gather(
                bridge._process_buffer("10001", b1),
                bridge._process_buffer("10001", b2),
            )
            assert state["calls"] == 2
            assert state["max"] == 1

    asyncio.run(scenario())


def test_enrich_vision_uses_low_reasoning_and_timeout(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(
                tmp,
                vision_enrich_enabled=True,
                search_timeout=11,
            )
            captured: dict[str, object] = {}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                captured["timeout"] = timeout
                captured["reasoning_effort"] = reasoning_effort
                return "结论", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            await bridge._enrich_vision("【不确定项】：身份未知")
            assert captured["timeout"] == 11
            assert captured["reasoning_effort"] == "low"

    asyncio.run(scenario())


def test_roleplay_casual_uses_low_reasoning_effort(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            captured: dict[str, object] = {}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                captured["reasoning_effort"] = reasoning_effort
                return "……嗯。", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("你好")
            await bridge._process_buffer("10001", buf)
            assert captured["reasoning_effort"] == "low"

    asyncio.run(scenario())


def test_task_uses_max_reasoning_effort(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            captured: dict[str, object] = {}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                captured["reasoning_effort"] = reasoning_effort
                return "收到，任务完成。", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("帮我写一个 hello.py")
            await bridge._process_buffer("10001", buf)
            assert captured["reasoning_effort"] == "max"

    asyncio.run(scenario())


def test_process_buffer_retries_then_friendly_on_persistent_error(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp, fallback_enabled=False)
            calls = {"n": 0}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                calls["n"] += 1
                raise AgentError("Codex 提前退出（退出码 0）：空回复")

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("你好")
            await bridge._process_buffer("10001", buf)
            assert calls["n"] == 2
            messages = [s["params"]["message"] for s in bridge.ws.sent]
            assert messages[-1] == "……刚才处理中断了，请再发一次。"
            assert not any("提前退出" in m for m in messages)

    asyncio.run(scenario())


def test_process_buffer_retry_succeeds_second_time(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            calls = {"n": 0}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                calls["n"] += 1
                if calls["n"] == 1:
                    raise AgentError("Codex 提前退出（退出码 0）：空回复")
                return "……重试成功。", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("你好")
            await bridge._process_buffer("10001", buf)
            assert calls["n"] == 2
            messages = [s["params"]["message"] for s in bridge.ws.sent]
            assert messages[-1] == "……重试成功。"

    asyncio.run(scenario())


def test_process_buffer_resets_persona_thread_on_codex_error(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp, fallback_enabled=False)
            store.set_persona_thread("10001", "thread-old")

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                raise AgentError("Codex 提前退出（退出码 0）：空回复")

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("你好")
            await bridge._process_buffer("10001", buf)
            assert store.get_persona_thread("10001") is None
            messages = [s["params"]["message"] for s in bridge.ws.sent]
            assert messages[-1] == "……刚才处理中断了，请再发一次。"

    asyncio.run(scenario())


def test_roleplay_casual_uses_roleplay_timeout(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            captured: dict[str, object] = {}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                captured["timeout"] = timeout
                return "……嗯。", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("你好")
            await bridge._process_buffer("10001", buf)
            assert captured["timeout"] == 240

    asyncio.run(scenario())


def test_followup_after_task_uses_task_timeout(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            captured: dict[str, object] = {}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                captured["timeout"] = timeout
                return "收到，任务完成。", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            first = MessageBuffer("10001", bridge.cfg)
            first.add_text("帮我写一个 hello.py")
            await bridge._process_buffer("10001", first)
            assert captured["timeout"] == 900
            assert store.get_task_follow("10001")["active"] is True

            second = MessageBuffer("10001", bridge.cfg)
            second.add_text("就这个模式与难度")
            await bridge._process_buffer("10001", second)
            assert captured["timeout"] == 900

    asyncio.run(scenario())


def test_greeting_after_task_stays_casual(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            captured: dict[str, object] = {}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                captured["timeout"] = timeout
                return "……嗯。", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            first = MessageBuffer("10001", bridge.cfg)
            first.add_text("帮我写一个 hello.py")
            await bridge._process_buffer("10001", first)
            second = MessageBuffer("10001", bridge.cfg)
            second.add_text("早")
            await bridge._process_buffer("10001", second)
            assert captured["timeout"] == 240

    asyncio.run(scenario())


def test_task_uses_task_timeout(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            captured: dict[str, object] = {}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                captured["timeout"] = timeout
                return "收到，任务完成。", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("帮我写一个 hello.py")
            await bridge._process_buffer("10001", buf)
            assert captured["timeout"] == 900

    asyncio.run(scenario())


def test_task_stage_on_timeout_writes_pending_and_keeps_thread(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp, task_stage_enabled=True)

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                raise AgentError(
                    "Codex 处理超时，已终止任务",
                    timeout=True,
                    thread_id="thread-new",
                )

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("帮我写一个 hello.py")
            await bridge._process_buffer("10001", buf)
            assert store.get_persona_thread("10001") == "thread-new"
            data = json.loads(bridge.pending_path.read_text(encoding="utf-8"))
            assert data["kind"] == "task_stage"
            assert data["status"] == "waiting"
            messages = [s["params"]["message"] for s in bridge.ws.sent]
            assert any("回复“继续”" in m for m in messages)
            assert not any("刚才处理中断了" in m for m in messages)

    asyncio.run(scenario())


def test_casual_timeout_resets_thread_not_stage(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(
                tmp,
                task_stage_enabled=True,
                fallback_enabled=False,
            )
            store.set_persona_thread("10001", "thread-old")

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                raise AgentError("Codex 处理超时，已终止任务", timeout=True)

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("你好")
            await bridge._process_buffer("10001", buf)
            assert store.get_persona_thread("10001") is None
            assert not bridge.pending_path.exists()
            messages = [s["params"]["message"] for s in bridge.ws.sent]
            assert messages[-1] == "……刚才处理中断了，请再发一次。"

    asyncio.run(scenario())


def test_resume_task_stage_continues_on_confirm(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            bridge.pending_path.write_text(
                json.dumps(
                    {
                        "id": "ts-1",
                        "kind": "task_stage",
                        "status": "answered",
                        "reply": "继续",
                        "thread_id": "thread-task",
                        "original_prompt": "帮我写 hello.py",
                        "stage": 1,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            calls = {"n": 0}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                calls["n"] += 1
                return "任务完成。", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            await bridge._resume_task_stage("10001")
            assert calls["n"] == 1
            messages = [s["params"]["message"] for s in bridge.ws.sent]
            assert messages[-1] == "任务完成。"
            assert not bridge.pending_path.exists()

    asyncio.run(scenario())


def test_resume_task_stage_stops_on_stop(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            bridge.pending_path.write_text(
                json.dumps(
                    {
                        "id": "ts-1",
                        "kind": "task_stage",
                        "status": "answered",
                        "reply": "停止",
                        "thread_id": "thread-task",
                        "original_prompt": "帮我写 hello.py",
                        "stage": 1,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            calls = {"n": 0}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                calls["n"] += 1
                return "不应调用", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            await bridge._resume_task_stage("10001")
            assert calls["n"] == 0
            messages = [s["params"]["message"] for s in bridge.ws.sent]
            assert messages[-1] == "……好，任务先到这里。"
            assert not bridge.pending_path.exists()

    asyncio.run(scenario())


def test_pending_task_stage_blocks_other_messages(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            bridge.pending_path.write_text(
                json.dumps(
                    {
                        "id": "ts-1",
                        "kind": "task_stage",
                        "status": "waiting",
                        "thread_id": "thread-task",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            calls = {"n": 0}

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                calls["n"] += 1
                return "不应调用", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("你好")
            await bridge._process_buffer("10001", buf)
            assert calls["n"] == 0
            messages = [s["params"]["message"] for s in bridge.ws.sent]
            assert "等待确认中" in messages[0]

    asyncio.run(scenario())


def test_proactive_skips_when_user_lock_held(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)
            lock = bridge._user_lock("10001")
            await lock.acquire()
            called = False

            async def fake_agent_run(
                prompt, thread_id, timeout=None, reasoning_effort=None, image_paths=None
            ):
                nonlocal called
                called = True
                return "不应调用", None

            monkeypatch.setattr(bridge.agent, "run", fake_agent_run)
            await asyncio.wait_for(
                bridge._run_proactive("10001", "manual", record=False),
                timeout=1,
            )
            assert called is False
            lock.release()

    asyncio.run(scenario())


def test_roleplay_rotation_due_when_started_ts_missing():
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["FAKE_AGENT_REPLY"] = "长期记忆：旧会话内容已保留。"
            bridge, store = make_bridge(
                tmp,
                persona_reset_turns=999,
                persona_memory_file="memory.md",
            )
            bridge.memory_path = Path(tmp) / "memory.md"
            store.set_persona_thread("10001", "thread-old")
            store._data["10001"].pop("persona_started_ts", None)
            store.save()
            await bridge._maybe_rotate_persona("10001")
            os.environ.pop("FAKE_AGENT_REPLY", None)
            assert store.get_persona_thread("10001") is None
            assert "旧会话内容已保留" in bridge.memory_path.read_text(encoding="utf-8")

    asyncio.run(scenario())


def test_native_vision_skips_local_describe_and_attaches_image(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp, vision_native=True)
            fake_img = Path(tmp) / "photo.png"
            fake_img.write_bytes(b"\x89PNG\r\n\x1a\n")

            async def fake_download(bridge, image):
                return str(fake_img)

            local_describe_calls: list[str] = []

            async def fake_describe(path):
                local_describe_calls.append(path)
                return "本地描述"

            monkeypatch.setattr("handlers.download_incoming_image", fake_download)
            monkeypatch.setattr(bridge, "_describe_image", fake_describe)
            codex = RecordingCodex(bridge.cfg)
            bridge.agent = codex
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_image({"url": "https://example.com/photo.png", "file": "x"})
            await bridge._process_buffer_impl("10001", buf)
            call = codex.calls[-1]
            assert local_describe_calls == []
            assert call["image_paths"] == [str(fake_img)]
            assert "附件" in call["prompt"]
            assert "图片分析规则" in call["prompt"]

    asyncio.run(scenario())


def test_image_download_failure_short_circuits(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)

            async def fake_download(bridge, image):
                raise RuntimeError("HTTP Error 400: Bad Request")

            monkeypatch.setattr("handlers.download_incoming_image", fake_download)
            codex = RecordingCodex(bridge.cfg)
            bridge.agent = codex
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_image({"url": "https://example.com/photo.png", "file": "x"})
            await bridge._process_buffer_impl("10001", buf)
            assert codex.calls == []
            assert any(
                "图片下载失败" in s.get("params", {}).get("message", "") for s in bridge.ws.sent
            )

    asyncio.run(scenario())


def test_timetable_image_uses_native_codex_attachment(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp, vision_native=True)
            bridge.timetable_mode_users.add("10001")
            fake_img = Path(tmp) / "timetable.png"
            fake_img.write_bytes(b"\x89PNG\r\n\x1a\n")
            calls: dict = {}

            async def fake_download(bridge, image):
                return str(fake_img)

            async def fake_run_with_policy(b, prompt, thread_id, policy, image_paths=None):
                calls["prompt"] = prompt
                calls["image_paths"] = image_paths
                return "day,start,end,name,location,weeks\n1,08:00,09:00,数学,A101,\n", None

            monkeypatch.setattr("handlers.download_incoming_image", fake_download)
            monkeypatch.setattr("handlers.run_with_policy", fake_run_with_policy)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_image({"url": "https://example.com/timetable.png", "file": "x"})
            await handlers.ingest_timetable(bridge, "10001", buf)
            assert calls["image_paths"] == [str(fake_img)]
            assert "day,start,end,name,location,weeks" in calls["prompt"]
            assert "10001" in bridge.timetable_pending

    asyncio.run(scenario())


def test_native_vision_falls_back_to_local_vision_and_flash(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp, vision_native=True)
            fake_img = Path(tmp) / "photo.png"
            fake_img.write_bytes(b"\x89PNG\r\n\x1a\n")

            async def fake_download(bridge, image):
                return str(fake_img)

            async def fake_describe(
                path,
                api_url,
                model,
                api_key=None,
                timeout=150,
                max_tokens=1200,
                prompt=None,
            ):
                return "mimo 描述"

            monkeypatch.setattr("handlers.download_incoming_image", fake_download)
            monkeypatch.setattr("handlers.describe_image", fake_describe)

            class FailingThenOkCodex(RecordingCodex):
                def __init__(self, cfg):
                    super().__init__(cfg)
                    self.fail_next = True

                async def run(
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
                    self.calls.append(
                        {
                            "prompt": prompt,
                            "thread_id": thread_id,
                            "image_paths": image_paths,
                            "model": model,
                            "model_provider": model_provider,
                            "bypass_proxy": bypass_proxy,
                        }
                    )
                    if self.fail_next:
                        self.fail_next = False
                        raise AgentError("proxy down", timeout=True)
                    return "兜底回复", "t-fb"

            bridge.agent = FailingThenOkCodex(bridge.cfg)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_image({"url": "https://example.com/photo.png", "file": "x"})
            await bridge._process_buffer_impl("10001", buf)
            assert len(bridge.agent.calls) == 2
            assert bridge.agent.calls[0]["image_paths"] == [str(fake_img)]
            assert bridge.agent.calls[0]["model"] is None
            assert bridge.agent.calls[1]["image_paths"] is None
            assert bridge.agent.calls[1]["model"] == "deepseek-v4-flash"
            assert bridge.agent.calls[1]["bypass_proxy"] is True
            assert "mimo 描述" in bridge.agent.calls[1]["prompt"]
            assert "不要调用任何工具或联网搜索" in bridge.agent.calls[1]["prompt"]
            assert any(s.get("params", {}).get("message") == "兜底回复" for s in bridge.ws.sent)

    asyncio.run(scenario())


def test_text_only_fallback_uses_fallback_model(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp)

            class FailingThenOkCodex(RecordingCodex):
                def __init__(self, cfg):
                    super().__init__(cfg)
                    self.fail_next = True

                async def run(
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
                    self.calls.append(
                        {
                            "prompt": prompt,
                            "thread_id": thread_id,
                            "image_paths": image_paths,
                            "model": model,
                            "model_provider": model_provider,
                            "bypass_proxy": bypass_proxy,
                        }
                    )
                    if self.fail_next:
                        self.fail_next = False
                        raise AgentError("proxy down", timeout=True)
                    return "兜底回复", "t-fb"

            bridge.agent = FailingThenOkCodex(bridge.cfg)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("你好")
            await bridge._process_buffer_impl("10001", buf)
            assert len(bridge.agent.calls) == 2
            assert bridge.agent.calls[1]["model"] == "deepseek-v4-flash"
            assert bridge.agent.calls[1]["bypass_proxy"] is True
            assert any(s.get("params", {}).get("message") == "兜底回复" for s in bridge.ws.sent)

    asyncio.run(scenario())


def test_fallback_disabled_keeps_original_error(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp, fallback_enabled=False)

            class AlwaysFailCodex(RecordingCodex):
                async def run(
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
                    self.calls.append(
                        {
                            "prompt": prompt,
                            "thread_id": thread_id,
                            "image_paths": image_paths,
                            "model": model,
                            "model_provider": model_provider,
                            "bypass_proxy": bypass_proxy,
                        }
                    )
                    raise AgentError("proxy down", timeout=True)

            bridge.agent = AlwaysFailCodex(bridge.cfg)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_text("你好")
            await bridge._process_buffer_impl("10001", buf)
            assert len(bridge.agent.calls) == 1
            assert any(
                "刚才处理中断了" in s.get("params", {}).get("message", "") for s in bridge.ws.sent
            )

    asyncio.run(scenario())


def test_timetable_native_failure_falls_back_to_local_ocr(monkeypatch):
    async def scenario():
        with tempfile.TemporaryDirectory() as tmp:
            bridge, store = make_bridge(tmp, vision_native=True)
            bridge.timetable_mode_users.add("10001")
            fake_img = Path(tmp) / "timetable.png"
            fake_img.write_bytes(b"\x89PNG\r\n\x1a\n")

            async def fake_download(bridge, image):
                return str(fake_img)

            async def fake_run_with_policy(b, prompt, thread_id, policy, image_paths=None):
                raise AgentError("proxy down", timeout=True)

            async def fake_extract_timetable_text(
                path,
                api_url,
                model,
                api_key=None,
                timeout=150,
                max_tokens=1024,
            ):
                return "day,start,end,name,location,weeks\n1,08:00,09:00,数学,A101,\n"

            monkeypatch.setattr("handlers.download_incoming_image", fake_download)
            monkeypatch.setattr("handlers.run_with_policy", fake_run_with_policy)
            monkeypatch.setattr("handlers.extract_timetable_text", fake_extract_timetable_text)
            buf = MessageBuffer("10001", bridge.cfg)
            buf.add_image({"url": "https://example.com/timetable.png", "file": "x"})
            await handlers.ingest_timetable(bridge, "10001", buf)
            assert "10001" in bridge.timetable_pending
            assert any("识别结果" in s.get("params", {}).get("message", "") for s in bridge.ws.sent)

    asyncio.run(scenario())
