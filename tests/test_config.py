import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import PROJECT_DIR, load_config


def test_load_config_merges_user_file():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(
            json.dumps({"full_access_qq": ["123"], "batch_window": 5}), encoding="utf-8"
        )
        cfg = load_config(path)
        assert cfg["full_access_qq"] == ["123"]
        assert cfg["batch_window"] == 5
        assert cfg["onebot_ws_url"] == "ws://127.0.0.1:3001"


def test_load_config_requires_allowlist():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(json.dumps({}), encoding="utf-8")
        try:
            load_config(path)
            raise AssertionError("应当抛出 ValueError")
        except ValueError:
            pass


def test_web_enabled_requires_token():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(
            json.dumps({"full_access_qq": ["1"], "web_enabled": True}), encoding="utf-8"
        )
        try:
            load_config(path)
            raise AssertionError("应当抛出 ValueError")
        except ValueError:
            pass


def test_web_enabled_with_token_ok():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(
            json.dumps({"full_access_qq": ["1"], "web_enabled": True, "web_token": "secret-token"}),
            encoding="utf-8",
        )
        cfg = load_config(path)
        assert cfg["web_token"] == "secret-token"


def test_load_config_has_proactive_defaults():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(json.dumps({"full_access_qq": ["123"]}), encoding="utf-8")
        cfg = load_config(path)
    # 白板默认不主动打扰，需要的用户自己打开
    assert cfg["proactive_enabled"] is False
    assert cfg["proactive_fixed_times"] == ["09:30", "21:30"]
    assert cfg["proactive_idle_minutes"] == 180
    assert cfg["proactive_cooldown_minutes"] == 180
    assert cfg["proactive_windows"] == ["09:00-23:30"]
    assert cfg["proactive_max_per_day"] == 6
    assert Path(cfg["proactive_notes_file"]).name == "proactive-notes.md"
    assert cfg["proactive_check_interval_sec"] == 60
    assert cfg["proactive_class_lead_minutes"] == 15
    assert cfg["proactive_class_windows"] == ["07:00-23:30"]
    assert Path(cfg["timetable_file"]).name == "timetable.json"


def test_voice_defaults_present():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(json.dumps({"full_access_qq": ["1"]}), encoding="utf-8")
        cfg = load_config(path)
    # TTS 默认关闭：没配语音包时不应该报错
    assert cfg["tts_backend"] == "off"
    assert cfg["tts_local_url"] == "http://127.0.0.1:9880/tts"
    assert cfg["tts_character"] == ""
    assert cfg["tts_ref"] == ""
    assert cfg["voice_max_chars"] == 120
    assert cfg["voice_max_per_reply"] == 1
    assert cfg["voice_fallback_to_text"] is False


def test_context_and_outbox_defaults_present():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(json.dumps({"full_access_qq": ["1"]}), encoding="utf-8")
        cfg = load_config(path)
    assert cfg["search_timeout"] == 240
    assert cfg["chat_effort"] == "low"
    assert cfg["task_effort"] == "max"
    assert cfg["search_effort"] == "low"
    assert cfg["chat_timeout"] == 240
    assert cfg["task_timeout"] == 900
    assert cfg["task_stage_enabled"] is True
    assert cfg["task_stage_timeout"] == 900
    assert cfg["task_stage_max"] == 10
    assert cfg["task_stage_summary_timeout"] == 120
    assert cfg["pdf_ocr_enabled"] is True
    assert cfg["pdf_ocr_max_pages"] == 10
    assert cfg["pdf_ocr_timeout_sec"] == 120
    assert cfg["pdf_ocr_max_chars"] == 4000
    assert Path(cfg["outbox_dir"]).name == "outbox"
    assert cfg["outbox_sent_dir"] == "sent"
    assert cfg["outbox_check_interval_sec"] == 5
    assert Path(cfg["inbox_dir"]).name == "inbox"
    assert Path(cfg["inbox_log_file"]).name == "feedback.log"
    assert cfg["inbox_log_max_lines"] == 200
    assert cfg["inbox_log_max_bytes"] == 65536
    assert Path(cfg["decisions_dir"]).name == "decisions"
    assert Path(cfg["messages_dir"]).name == "channels"
    assert cfg["to_qq_dir"].endswith(str(Path("channels") / "to_qq"))
    assert cfg["to_qq_sent_dir"].endswith(str(Path("channels") / "to_qq" / "sent"))
    assert cfg["from_qq_log_file"].endswith(
        str(Path("channels") / "from_qq" / "feedback.jsonl")
    )
    assert cfg["main_agent_prefixes"] == ["/本机"]
    assert cfg["main_agent_inbox_file"].endswith(
        str(Path("channels") / "from_qq" / "main.jsonl")
    )
    assert cfg["pending_file"].endswith(str(Path("channels") / "state" / "pending.json"))
    assert cfg["agent_status_file"].endswith(
        str(Path("channels") / "state" / "agent-status.md")
    )
    assert cfg["vision_enrich_enabled"] is True
    assert "不确定" in cfg["vision_enrich_keywords"]
    assert "资讯不足" in cfg["vision_enrich_keywords"]
    assert cfg["vision_model"] == ""
    assert cfg["vision_url"] == ""
    assert cfg["vision_max_tokens"] == 2000
    # 旧的本地视觉模型键必须已经下架（vision_* 现在跟随主模型，不再单列识图模型）
    assert "vision_fallback_model" not in cfg
    assert "vision_num_ctx" not in cfg
    assert cfg["persona_reset_turns"] == 150
    assert cfg["persona_reset_hours"] == 24
    assert Path(cfg["persona_memory_file"]).name == "memory.md"
    assert "发给我" in cfg["task_phrases"]
    assert "早" in cfg["casual_phrases"]
    assert cfg["task_follow_idle_sec"] == 7200


def test_relative_paths_resolve_against_data_dir():
    """相对路径必须展开成绝对路径，且与当前工作目录无关。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(
            json.dumps({"full_access_qq": ["1"], "data_dir": str(Path(tmp) / "state")}),
            encoding="utf-8",
        )
        cfg = load_config(path)
    state = Path(tmp) / "state"
    # 状态数据挂到 data_dir 下面
    assert Path(cfg["log_file"]).is_absolute()
    assert Path(cfg["log_file"]).parent == state
    assert Path(cfg["state_db_file"]).parent == state
    assert Path(cfg["sessions_file"]).parent == state
    assert Path(cfg["voice_cache_dir"]).parent == state
    # channels / outbox 这类工作目录固定在项目里，不跟着 data_dir 走
    assert Path(cfg["messages_dir"]).name == "channels"
    assert Path(cfg["messages_dir"]).parent == PROJECT_DIR
    assert Path(cfg["outbox_dir"]).parent == PROJECT_DIR


def test_env_override_wins_over_file(monkeypatch):
    """环境变量 QQBOT_* 覆盖 config.json 里的值。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "config.json"
        path.write_text(
            json.dumps({"full_access_qq": ["1"], "web_port": 8080}), encoding="utf-8"
        )
        monkeypatch.setenv("QQBOT_WEB_PORT", "9090")
        monkeypatch.setenv("QQBOT_FULL_ACCESS_QQ", '["20002"]')
        cfg = load_config(path)
    assert cfg["web_port"] == 9090
    assert cfg["full_access_qq"] == ["20002"]
