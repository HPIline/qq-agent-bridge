import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proactive import (
    class_reminder_due,
    format_now,
    in_windows,
    mark_triggered,
    prepare_state,
    should_initiate,
)


def test_in_windows():
    now = dt.datetime(2026, 8, 6, 10, 0)
    assert in_windows(now, ["09:00-23:30"]) is True
    assert in_windows(now, ["07:00-09:59"]) is False
    assert in_windows(now, []) is True


def test_prepare_state_resets_day():
    now = dt.datetime(2026, 8, 6, 10, 0)
    state = {
        "day": "2026-08-05",
        "count": 3,
        "fixed_done": ["2026-08-05|09:30"],
        "reminded_classes": ["x"],
    }
    prepare_state(state, now)
    assert state["day"] == "2026-08-06"
    assert state["count"] == 0
    assert state["fixed_done"] == []
    assert state["reminded_classes"] == []


def test_should_initiate_fixed_slot():
    now = dt.datetime(2026, 8, 6, 9, 30)
    cfg = {
        "proactive_enabled": True,
        "proactive_fixed_times": ["09:30"],
        "proactive_windows": ["09:00-23:30"],
        "proactive_cooldown_minutes": 240,
        "proactive_idle_minutes": 180,
        "proactive_max_per_day": 4,
    }
    state = {}
    ok, source, slot = should_initiate(state, cfg, now)
    assert ok is True
    assert source == "fixed"
    assert slot == "09:30"


def test_should_initiate_idle():
    now = dt.datetime(2026, 8, 6, 14, 0)
    cfg = {
        "proactive_enabled": True,
        "proactive_fixed_times": [],
        "proactive_windows": ["09:00-23:30"],
        "proactive_cooldown_minutes": 240,
        "proactive_idle_minutes": 180,
        "proactive_max_per_day": 4,
    }
    state = {"last_active_ts": (now - dt.timedelta(hours=4)).timestamp()}
    ok, source, slot = should_initiate(state, cfg, now)
    assert ok is True
    assert source == "idle"
    assert slot is None


def test_should_initiate_blocked_by_paused_busy_window_cooldown():
    now = dt.datetime(2026, 8, 6, 8, 0)
    cfg = {
        "proactive_enabled": True,
        "proactive_fixed_times": [],
        "proactive_windows": ["09:00-23:30"],
        "proactive_cooldown_minutes": 240,
        "proactive_idle_minutes": 0,
        "proactive_max_per_day": 4,
    }
    state = {"last_active_ts": (now - dt.timedelta(hours=4)).timestamp()}
    ok, _, _ = should_initiate(state, cfg, now)
    assert ok is False  # 窗口外
    ok, _, _ = should_initiate(state, cfg, now.replace(hour=12), busy=True)
    assert ok is False  # 忙碌
    state["paused"] = True
    ok, _, _ = should_initiate(state, cfg, now.replace(hour=12))
    assert ok is False  # 暂停
    state["paused"] = False
    state["last_ts"] = now.replace(hour=12).timestamp()
    ok, _, _ = should_initiate(state, cfg, now.replace(hour=12))
    assert ok is False  # 冷却中
    state = {"count": 4}
    ok, _, _ = should_initiate(state, cfg, now.replace(hour=12))
    assert ok is False  # 当天上限


def test_class_reminder_due_dedupes():
    now = dt.datetime(2026, 8, 6, 10, 0)
    next_class = {"day": now.isoweekday(), "start": "10:15", "name": "高等数学"}
    cfg = {
        "proactive_enabled": True,
        "proactive_class_windows": ["07:00-23:30"],
        "proactive_class_lead_minutes": 15,
        "proactive_max_per_day": 4,
    }
    state = {}
    ok, key = class_reminder_due(next_class, now, cfg, state)
    assert ok is True
    assert key == "2026-08-06|10:15|高等数学"
    state["reminded_classes"] = [key]
    ok, _ = class_reminder_due(next_class, now, cfg, state)
    assert ok is False


def test_mark_triggered_and_format_now():
    now = dt.datetime(2026, 8, 6, 9, 30)
    state = mark_triggered({}, {}, now, "fixed", slot="09:30")
    assert state["last_ts"] == now.timestamp()
    assert state["last_active_ts"] == now.timestamp()
    assert state["count"] == 1
    assert state["fixed_done"] == ["2026-08-06|09:30"]
    state = mark_triggered(state, {}, now, "manual", count=False)
    assert state["count"] == 1
    assert format_now(now) == "2026-08-06 09:30 星期" + "四"


def test_reject_proactive_reply_ignores_leading_meta():
    from message_utils import sanitize_persona_reply
    from proactive import _reject_proactive_reply

    raw = (
        "技能已加载完毕，读取了 SKILL.md。\n"
        "---\n"
        "下午好 (￣▽￣)。今天一整天没有你的动静，课应该上完了吧。"
    )
    assert _reject_proactive_reply(raw) is False
    cleaned = sanitize_persona_reply(raw)
    assert "技能已" not in cleaned
    assert "下午好" in cleaned


def test_filter_memory_for_proactive_keeps_preferences_and_removes_projects():
    from message_utils import filter_memory_for_proactive

    memory = """**用户身份与关系**
- 主人是某大学本科生
- 可视为女友

**偏好**
- 喜欢用颜文字

**进行中的事情/项目**
- OpenCode 会话头修复
- 某个私人项目代号
"""
    out = filter_memory_for_proactive(memory)
    assert "某大学" in out
    assert "喜欢用颜文字" in out
    assert "可视为女友" not in out
    assert "OpenCode" not in out
    assert "私人项目代号" not in out


def test_filter_memory_for_proactive_no_headings_returns_original():
    from message_utils import filter_memory_for_proactive

    assert filter_memory_for_proactive("记得：下午有课。") == "记得：下午有课。"


def test_build_proactive_prompt_includes_trending_topics_and_style_evolution():
    from message_utils import build_proactive_prompt

    prompt = build_proactive_prompt(
        "test-persona",
        "2026-09-08 10:00 星期一",
        trending_text="热梗：爱你老己，活人感",
        topic_directions=["动漫/游戏", "近期热梗/热搜趣闻"],
    )
    assert "近期热梗" in prompt
    assert "爱你老己" in prompt
    assert "动漫/游戏" in prompt
    assert "不要主动聊" in prompt
    assert "语言风格可以自然变化" in prompt


def test_extract_topic_markers():
    from message_utils import extract_topic_markers

    text, markers = extract_topic_markers(
        "今天聊牛来[TOPIC:event|热梗|牛来]\n顺便说说AI[TOPIC:category|AI/科技|]"
    )
    assert text == "今天聊牛来\n顺便说说AI"
    assert markers == [
        {"kind": "event", "category": "热梗", "specific": "牛来"},
        {"kind": "category", "category": "AI/科技", "specific": ""},
    ]


def test_build_proactive_prompt_includes_topic_history():
    from message_utils import build_proactive_prompt

    prompt = build_proactive_prompt(
        "test-persona",
        "2026-09-08 10:00 星期一",
        topic_history={
            "avoid_events": ["AI/科技|Mistral融资", "热梗|牛来"],
            "categories": {"AI/科技": 2, "二次元画师": 1},
        },
    )
    assert "Mistral融资" in prompt
    assert "牛来" in prompt
    assert "AI/科技" in prompt
    assert "二次元画师" in prompt


def test_build_persona_prompt_asks_to_use_configured_image_search_tool():
    from message_utils import build_persona_prompt

    # 没配找图工具时不应该编造工具名
    plain = build_persona_prompt("test-persona", "给我看看这个画师的新图")
    assert "image_search" not in plain
    assert "[IMAGE:URL]" in plain
    # 配了工具名才注入调用提示
    cfg = {"image_search_tool": "my_image_search"}
    prompt = build_persona_prompt("test-persona", "给我看看这个画师的新图", cfg=cfg)
    assert "my_image_search" in prompt
    assert "[IMAGE:URL]" in prompt


def test_build_persona_prompt_includes_image_suggestions():
    from message_utils import build_persona_prompt

    prompt = build_persona_prompt(
        "test-persona",
        "给我看新图",
        image_suggestions="https://example.com/art.jpg",
    )
    assert "https://example.com/art.jpg" in prompt
    assert "[IMAGE:URL]" in prompt
