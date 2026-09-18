import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from message_utils import (
    MEDIA_MARKER_GUIDE,
    build_persona_prompt,
    chunk_reply,
    classify_message,
    extract_file_markers,
    extract_media_markers,
    extract_private_message,
    format_image_info,
    is_duplicate,
    is_task,
    should_treat_as_task,
)


def test_extract_private_message():
    event = {
        "post_type": "message",
        "message_type": "private",
        "message_id": 1,
        "user_id": 10001,
        "message": [
            {"type": "text", "data": {"text": "看看 "}},
            {"type": "image", "data": {"url": "http://x/img.jpg"}},
        ],
    }
    info = extract_private_message(event)
    assert info["text"] == "看看"
    assert info["images"][0]["url"] == "http://x/img.jpg"
    assert info["user_id"] == "10001"


def test_extract_private_message_keeps_image_with_file_only():
    event = {
        "post_type": "message",
        "message_type": "private",
        "message_id": 11,
        "user_id": 10001,
        "message": [
            {"type": "image", "data": {"file": "abc.image"}},
        ],
    }
    info = extract_private_message(event)
    assert info["images"] == [{"url": "", "file": "abc.image"}]


def test_extract_private_message_with_file():
    event = {
        "post_type": "message",
        "message_type": "private",
        "message_id": 2,
        "user_id": 10001,
        "message": [
            {"type": "text", "data": {"text": "收下 "}},
            {
                "type": "file",
                "data": {"file": "abc123", "name": "test.zip", "url": "http://x/test.zip"},
            },
        ],
    }
    info = extract_private_message(event)
    assert info["text"] == "收下"
    assert info["files"][0] == {
        "file": "abc123",
        "file_id": "",
        "url": "http://x/test.zip",
        "name": "test.zip",
        "path": "",
    }


def test_extract_file_markers():
    cleaned, markers = extract_file_markers(
        "给你文件 [FILE:/tmp/a.txt|a.txt]，还有 [FILE:http://x/b.zip]"
    )
    assert cleaned == "给你文件 ，还有"
    assert markers == [
        {"target": "/tmp/a.txt", "name": "a.txt"},
        {"target": "http://x/b.zip", "name": "b.zip"},
    ]


def test_is_duplicate():
    seen = deque(maxlen=10)
    assert not is_duplicate("1", seen)
    assert is_duplicate("1", seen)


def test_is_task_by_prefix_and_keyword():
    cfg = {"task_prefixes": ["任务："], "task_keywords": ["帮我", "把"], "task_auto_length": 60}
    assert is_task("任务：写周报", cfg)
    assert is_task("帮我写周报", cfg)
    assert is_task("把这个文件改成大写", cfg)
    assert not is_task("今天天气怎么样", cfg)
    assert is_task("今天天气怎么样" * 12, cfg)


def _task_cfg(**overrides):
    cfg = {
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
    }
    cfg.update(overrides)
    return cfg


def test_task_phrases_and_followups_are_tasks():
    cfg = _task_cfg(task_phrases=["发给我", "做成pdf", "重命名"])
    assert is_task("整理好发给我", cfg)
    assert is_task("做成pdf发给我", cfg)
    assert is_task("把周报重命名一下", cfg)
    assert is_task("帮我写一个脚本\n做好发给我", cfg)
    assert not is_task("今天天气不错", cfg)


def test_casual_chat_is_still_not_task():
    cfg = _task_cfg()
    assert not is_task("早", cfg)
    assert not is_task("好累", cfg)
    assert not is_task("今天天气怎么样", cfg)
    assert not is_task("其实只是找你打招呼", cfg)


def test_custom_task_phrases_override_defaults():
    cfg = _task_cfg(task_phrases=["出卷子"])
    assert is_task("帮我出卷子", cfg)
    assert is_task("今晚出卷子", cfg)
    assert not is_task("做好发给我", cfg)


def test_chunk_reply():
    chunks = chunk_reply("一" * 5000 + "。" + "二" * 5000, 2000)
    assert all(len(c) <= 2000 for c in chunks)
    assert "".join(chunks) == "一" * 5000 + "。" + "二" * 5000


def test_extract_private_message_with_face_and_mface():
    event = {
        "post_type": "message",
        "message_type": "private",
        "message_id": 3,
        "user_id": 10001,
        "message": [
            {"type": "face", "data": {"id": "178"}},
            {
                "type": "mface",
                "data": {
                    "emoji_id": "abc",
                    "emoji_package_id": "pkg1",
                    "key": "k1",
                    "summary": "哈哈",
                },
            },
        ],
    }
    info = extract_private_message(event)
    assert info["faces"] == [{"id": "178"}]
    assert info["mfaces"] == [
        {
            "emoji_id": "abc",
            "emoji_package_id": "pkg1",
            "key": "k1",
            "summary": "哈哈",
        }
    ]


def test_extract_media_markers_all_kinds():
    cleaned, markers = extract_media_markers(
        "看 [FACE:178]，[MFACE:a|b|c|哈]，图 [IMAGE:/tmp/x.png|x.png]，文件 [FILE:/tmp/a.txt|a.txt]"
    )
    assert cleaned == "看 ，，图 ，文件"
    assert markers == [
        {"kind": "face", "id": "178"},
        {
            "kind": "mface",
            "emoji_id": "a",
            "emoji_package_id": "b",
            "key": "c",
            "summary": "哈",
        },
        {"kind": "image", "target": "/tmp/x.png", "name": "x.png"},
        {"kind": "file", "target": "/tmp/a.txt", "name": "a.txt"},
    ]


def test_extract_media_markers_mface_missing_fields():
    cleaned, markers = extract_media_markers("[MFACE:a|b]")
    assert cleaned == ""
    assert markers == [
        {"kind": "mface", "emoji_id": "a", "emoji_package_id": "b", "key": "", "summary": ""}
    ]


def test_build_persona_prompt_includes_stickers_and_guide():
    prompt = build_persona_prompt(
        "test-persona",
        "哈哈哈",
        sticker_infos=["QQ表情：178", "商城表情：a|b|c|哈"],
        casual_multipart=False,
    )
    assert "用户发来的表情" in prompt
    assert "QQ表情：178" in prompt
    assert "商城表情：a|b|c|哈" in prompt
    assert "[FACE:" in prompt
    assert "[MFACE:" in prompt
    assert "[IMAGE:" in prompt
    assert "[FILE:" in prompt


def test_format_image_info():
    assert format_image_info("/tmp/a.png", "蓝色短发少女") == "路径：/tmp/a.png\n蓝色短发少女"


def test_build_proactive_prompt():
    from message_utils import build_proactive_prompt

    prompt = build_proactive_prompt(
        "test-persona",
        "2026-08-06 10:00 星期四",
        notes_text="明天 9 点开会",
        class_hint="下一节课：高等数学，10:15，地点：教1-101",
    )
    assert "test-persona" in prompt
    assert "主动发起话题" in prompt
    assert "当前时间：2026-08-06 10:00 星期四" in prompt
    assert "明天 9 点开会" in prompt
    assert "高等数学" in prompt
    assert "不要解释" in prompt
    assert "只输出要发给对方的正文" in prompt
    assert "不要输出技能加载" in prompt


def test_build_proactive_prompt_without_notes():
    from message_utils import build_proactive_prompt

    prompt = build_proactive_prompt("test-persona", "2026-08-06 10:00 星期四")
    assert "可用日程/待办资讯" not in prompt
    assert "课表提醒" not in prompt


def test_build_persona_prompt_includes_memory():
    from message_utils import build_persona_prompt

    prompt = build_persona_prompt(
        "test-persona",
        "你好",
        memory_text="记得：主人喜欢看书。",
    )
    assert "长期记忆" in prompt
    assert "记得：主人喜欢看书。" in prompt


def test_roleplay_prompt_guides_web_search_for_images():
    from message_utils import build_persona_prompt

    prompt = build_persona_prompt(
        "test-persona",
        "看看这张图",
        image_descriptions=["路径：/tmp/a.png\n一个卡通小熊"],
    )
    assert "联网搜索" in prompt
    assert "必须先使用联网搜索" in prompt
    assert "禁止直接回复" in prompt
    assert "资讯不足" in prompt
    plain = build_persona_prompt("test-persona", "你好")
    assert "联网搜索" not in plain


def test_build_proactive_prompt_includes_memory():
    from message_utils import build_proactive_prompt

    prompt = build_proactive_prompt(
        "test-persona",
        "2026-08-06 10:00 星期四",
        memory_text="记得：下午有课。",
    )
    assert "长期记忆" in prompt
    assert "记得：下午有课。" in prompt


def test_casual_prompt_mentions_media_frequency():
    from message_utils import build_persona_prompt

    casual = build_persona_prompt("test-persona", "你好", casual_multipart=True)
    assert "活人感" in casual
    task = build_persona_prompt("test-persona", "帮我写文件")
    assert "活人感" not in task


def test_proactive_prompt_mentions_media_frequency():
    from message_utils import build_proactive_prompt

    prompt = build_proactive_prompt("test-persona", "2026-08-08 10:00 星期六")
    assert "活人感" in prompt


def test_prompt_has_no_image_hallucination_rule():
    from message_utils import build_persona_prompt, build_proactive_prompt

    rp = build_persona_prompt("test-persona", "发文件给我")
    assert "不要说自己收到" in rp
    pp = build_proactive_prompt("test-persona", "2026-08-10 09:00 星期一")
    assert "不要说自己收到" in pp


def test_extract_voice_marker():
    text, markers = extract_media_markers("……嗯。\n[VOICE:こんにちは。]\n要一起看书吗。")
    assert text == "……嗯。\n要一起看书吗。"
    assert markers == [{"kind": "voice", "text": "こんにちは。"}]


def test_media_marker_guide_mentions_voice():
    assert "[VOICE:" in MEDIA_MARKER_GUIDE


def test_roleplay_prompt_mentions_voice_rule():
    prompt = build_persona_prompt("test-persona", "你好")
    assert "[VOICE:" in prompt
    assert "语音规则" in prompt


def test_classify_casual_beats_follow_and_length():
    cfg = _task_cfg()
    follow = {"active": True, "last_task_ts": 1000.0}
    for text in ("早", "哎", "好累", "在？", "在吗"):
        decision = classify_message(text, cfg, follow=follow, now=1001.0)
        assert decision.is_task is False, text
        assert decision.reason == "casual"


def test_classify_video_and_rename_are_tasks():
    cfg = _task_cfg()
    assert classify_message("这个视频讲了什么", cfg).is_task is True
    assert classify_message("好了你再试着看看视频？", cfg).is_task is True
    assert classify_message("重命名一下那个文件", cfg).is_task is True
    assert classify_message("帮我下载这个视频", cfg).is_task is True
    assert classify_message("任务：写周报", cfg).is_task is True


def test_follow_on_short_feedback_stays_task():
    cfg = _task_cfg(task_follow_idle_sec=7200)
    follow = {"active": True, "last_task_ts": 1000.0}
    decision = classify_message("？一个多小时了", cfg, follow=follow, now=1000.0 + 60)
    assert decision.is_task is True
    assert decision.reason == "follow"
    decision = classify_message("你真的在干活吗", cfg, follow=follow, now=1000.0 + 60)
    assert decision.is_task is True
    assert decision.reason == "follow"
    decision = classify_message("就这个模式与难度", cfg, follow=follow, now=1000.0 + 60)
    assert decision.is_task is True


def test_follow_expires_after_idle():
    cfg = _task_cfg(task_follow_idle_sec=7200)
    follow = {"active": True, "last_task_ts": 1000.0}
    decision = classify_message("你真的在干活吗", cfg, follow=follow, now=1000.0 + 7201)
    assert decision.is_task is False
    assert decision.reason != "follow"


def test_image_only_still_not_task_even_with_follow():
    cfg = _task_cfg()
    follow = {"active": True, "last_task_ts": 1000.0}
    assert should_treat_as_task("", True, cfg, follow=follow, now=1001.0) is False
