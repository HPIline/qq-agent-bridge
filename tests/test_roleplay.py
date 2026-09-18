import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import load_config
from message_utils import (
    build_persona_prompt,
    is_persona_command,
    should_treat_as_task,
    split_persona_reply,
)
from sessions import SessionStore


def test_roleplay_session_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp) / "sessions.json")
        store.set_thread("10001", "work-thread")
        store.set_persona_thread("10001", "rp-thread")
        assert store.get_thread("10001") == "work-thread"
        assert store.get_persona_thread("10001") == "rp-thread"


def test_roleplay_session_reset():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp) / "sessions.json")
        store.set_persona_thread("10001", "rp-thread")
        assert store.reset_persona("10001") is True
        assert store.get_persona_thread("10001") is None


def test_roleplay_flag_default_true():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(json.dumps({"full_access_qq": ["10001"]}), encoding="utf-8")
        cfg = load_config(path)
        assert cfg["persona_enabled"] is True
        # 白板默认不绑定任何人设技能
        assert cfg["persona_skill"] == ""
        assert cfg["persona_name"] == ""


def test_persona_mode_switch():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(Path(tmp) / "sessions.json")
        assert store.is_persona("10001") is True
        store.set_persona("10001", False)
        assert store.is_persona("10001") is False
        store.set_persona("10001", True)
        assert store.is_persona("10001") is True


def test_is_persona_command():
    assert is_persona_command("/角色") == "enter"
    assert is_persona_command("/roleplay") == "enter"
    assert is_persona_command("/退出") is None
    assert is_persona_command("/exit") is None
    assert is_persona_command("你好") is None


def test_build_persona_prompt_extra_skill_trigger():
    """自定义技能触发：命中关键词时把技能提示注入提示词。"""
    cfg = {
        "persona_skill_home": "/opt/skills",
        "extra_skill_triggers": [
            {
                "keywords": ["记账", "买入"],
                "skill": "my-ledger",
                "hint": "先用账本命令更新后再回话。",
            }
        ],
    }
    prompt = build_persona_prompt(skill="", text="我买入了示例股票100股，6块。", cfg=cfg)
    assert "my-ledger" in prompt
    assert "/opt/skills/my-ledger/SKILL.md" in prompt
    assert "先用账本命令更新后再回话。" in prompt
    # 没命中关键词时不注入
    plain = build_persona_prompt(skill="", text="今天天气不错", cfg=cfg)
    assert "my-ledger" not in plain


def test_build_persona_prompt():
    prompt = build_persona_prompt(
        skill="test-persona",
        text="今天过得怎么样？",
        image_descriptions=["图片：一个书架"],
        casual_multipart=True,
    )
    assert "test-persona" in prompt
    assert "不要解释你的设定" in prompt
    assert "今天过得怎么样？" in prompt
    assert "图片：一个书架" in prompt
    assert "每条说一个完整的意思" in prompt


def test_build_persona_prompt_native_image_attachment_note():
    prompt = build_persona_prompt(
        skill="test-persona",
        text="",
        image_count=2,
    )
    assert "2 张图片" in prompt
    assert "附件" in prompt
    assert "图片分析规则" in prompt


def test_split_persona_reply():
    reply = "……嗯。\n---\n今天很平静。\n---\n你呢？"
    segments = split_persona_reply(reply)
    assert segments == ["……嗯。", "今天很平静。", "你呢？"]


def test_split_persona_reply_single_long():
    segments = split_persona_reply("这句话特别特别长。" * 8, max_chars=20)
    assert len(segments) > 1
    assert all(len(s) <= 20 for s in segments)


def test_split_persona_reply_drops_skill_loading_and_decision_meta():
    reply = (
        "技能已加载（SKILL.md 与资源文件在会话内仍有效）。当前 09:00 周三早晨，"
        "处于主动时段，主人早上要给小孩上课，适合开口问候并顺带问出题。\n"
        "---\n"
        "早安 (￣ω￣)。这个点，应该正准备出门上课吧。\n"
        "---\n"
        "别空腹出门，早饭先吃两口 (._.)。上午的课也慢慢来。\n"
        "---\n"
        "对了，今天的计算题还出吗？老规矩按昨天的难度 (・_・)。要的话我这就准备。"
    )
    segments = split_persona_reply(reply)
    assert segments == [
        "早安 (￣ω￣)。这个点，应该正准备出门上课吧。",
        "别空腹出门，早饭先吃两口 (._.)。上午的课也慢慢来。",
        "对了，今天的计算题还出吗？老规矩按昨天的难度 (・_・)。要的话我这就准备。",
    ]


def test_split_persona_reply_strips_think_blocks_and_keeps_character_lines():
    reply = (
        "<think>先判断现在适不适合开口，技能已加载完毕。</think>\n"
        "晚上好 (￣ω￣)。这个点，一天的课应该都结束了吧。\n"
        "---\n"
        "忙完就歇着吧，别一直盯着电脑。"
    )
    segments = split_persona_reply(reply)
    assert segments == [
        "晚上好 (￣ω￣)。这个点，一天的课应该都结束了吧。",
        "忙完就歇着吧，别一直盯着电脑。",
    ]


def test_sanitize_persona_reply_drops_internal_monologue_without_dashes():
    from message_utils import sanitize_persona_reply

    cleaned = sanitize_persona_reply(
        "技能已在会话内加载生效。当前 13:14 周三午后，距上次主动已过 4 小时余，符合冷却；"
        "内容上有可关心的点（上午没回话、午饭、今天的题还没出），判断适合开口。\n"
        "中午好 (・_・)。上午没见你冒泡，课应该顺利吧，午饭吃了没。"
    )
    assert "技能已" not in cleaned
    assert "判断适合开口" not in cleaned
    assert "中午好" in cleaned


def test_sanitize_persona_reply_keeps_greeting_after_same_line_meta():
    from message_utils import sanitize_persona_reply

    cleaned = sanitize_persona_reply("技能已加载。当前适合开口。中午好 (・_・)。午饭吃了没。")
    assert "技能已" not in cleaned
    assert "适合开口" not in cleaned
    assert "中午好 (・_・)。午饭吃了没。" == cleaned


def test_image_only_not_task():
    cfg = {"task_prefixes": ["任务："], "task_keywords": ["帮我"], "task_auto_length": 60}
    assert should_treat_as_task("", has_images=True, cfg=cfg) is False
    assert should_treat_as_task("帮我看看", has_images=True, cfg=cfg) is True
