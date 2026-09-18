"""配置加载：内置默认值 + config.json + 环境变量，三层合并。

设计目标（全平台可配置）：

1. **零硬编码**：代码里不出现个人路径、账号、密钥；默认值都是相对路径或空值。
2. **任意位置可跑**：所有相对路径都相对 ``data_dir`` / 项目目录解析，与当前工作目录无关。
3. **环境变量覆盖**：任意配置键都可用 ``QQBOT_<大写键名>`` 覆盖，例如::

       QQBOT_ONEBOT_WS_URL=ws://127.0.0.1:3001
       QQBOT_FULL_ACCESS_QQ='["123456"]'
       QQBOT_API_KEY=sk-xxx

   值先按 JSON 解析（列表 / 数字 / 布尔都能写），解析失败当普通字符串。
4. **跨平台**：Windows / macOS / Linux 都能找到配置目录，见 :func:`platform_config_dir`。
5. **向后兼容**：早期版本用过的键名（见 :data:`LEGACY_KEYS`）仍然可用，启动时会提示改名。

改配置前先看 CONFIG.md（全量配置手册）；只想快速跑起来，复制 config.example.json 改 3 行即可。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parent
ENV_PREFIX = "QQBOT_"
APP_NAME = "qq-agent-bridge"  # 用户级配置/数据目录名

DEFAULTS: dict[str, Any] = {
    # ---------- 连接 ----------
    "onebot_ws_url": "ws://127.0.0.1:3001",
    # 允许使用机器人全部权限的 QQ 号（必填）；留空会启动失败并给出提示
    "full_access_qq": [],
    # ---------- 数据目录 ----------
    # 状态数据目录（日志 / SQLite / 会话 / 记忆）。留空 = 项目下的 data/
    "data_dir": "data",
    # ---------- 助手工作区 / 调用策略 ----------
    "workdir": "",  # 助手的文件工具能读写的目录；留空 = 项目目录
    "request_timeout": 900,  # 单次模型请求的兜底超时（秒）
    "vision_native": False,
    "fallback_enabled": True,
    "fallback_model": "",
    "chat_effort": "low",  # 闲聊的推理强度：low / medium / high / max
    "task_effort": "max",  # 执行任务的推理强度
    "search_effort": "low",  # 联网补查的推理强度
    "chat_timeout": 240,  # 闲聊超时（秒）
    "task_timeout": 900,  # 任务超时（秒）
    "search_timeout": 240,  # 联网补查超时（秒）
    # ---------- 模型接口（任意 OpenAI 兼容服务）----------
    "model": "",  # 例如 gpt-4o-mini / deepseek-chat
    "api_base_url": "",  # 例如 https://api.openai.com/v1
    "api_key": "",  # 建议用环境变量 QQBOT_API_KEY 注入，不要写进文件
    "memory_db": "memory.db",  # 长期记忆 / 会话持久化用的 SQLite 文件
    "tools_enabled": True,  # 总开关：助手能不能调用工具
    "shell_enabled": True,  # 允许执行命令（限制在 workdir 内）
    "file_tools_enabled": True,  # 允许读写文件（限制在 workdir 内）
    "web_search_enabled": True,  # 允许联网搜索
    "memory_enabled": True,  # 长期记忆
    "memory_auto_update": True,  # 每次对话后自动沉淀记忆
    "memory_in_chat": True,  # 把记忆注入上下文
    "history_turns": 20,  # 每次带多少轮历史
    "knowledge_tool_enabled": True,  # 允许助手检索本地知识库
    "skills_tool_enabled": True,  # 允许助手调用 skills/ 下的外部技能
    "memory_effort": "low",
    "memory_timeout": 180,
    # 保留系统代理（默认 False：清掉 HTTP(S)_PROXY，避免失效代理导致连接失败）
    "keep_proxy": False,
    "user_agent": "",  # 请求头 UA，留空用内置的浏览器 UA
    "github_token": "",  # 可选：GitHub 技能用（提高 API 限额）
    # ---------- 人格设定（留空 = 普通中文助手）----------
    "persona_name": "",  # 助手自称，例如“小助手”
    "persona_prompt": "",  # 人设描述，例如“说话简短、先给结论”
    "persona_skill_home": "~/.agents/skills",  # 技能目录根，persona_skill 从这里找
    "persona_enabled": True,  # 是否启用"人格模式"
    "persona_skill": "",  # 填技能名则提示模型先读 <persona_skill_home>/<技能>/SKILL.md
    "persona_ack_lines": ["收到，我处理一下。", "好的，稍等。"],
    "persona_chat_max_chars": 40,
    "persona_chat_max_segments": 4,
    "persona_chat_delay_sec": 1.0,
    "persona_session_prefix": "persona",
    "persona_reset_turns": 150,
    "persona_reset_hours": 24,
    "persona_memory_file": "memory.md",
    "ack_delay_sec": 0.8,
    # ---------- 提示词覆盖（留空即用内置通用版）----------
    "chat_style_guide": "",
    "media_frequency_guide": "",
    "media_marker_guide": "",
    "proactive_topic_guide": "",
    "emoticon_examples": ["(・_・)", "(￣▽￣)", "(._.)", "(￣ω￣)", "(。-ω-)zzz"],
    # 想让模型用某个"找图"工具时填工具名（需自己在 agent_client 里注册）；留空则不提示
    "image_search_tool": "",
    # 自定义技能触发：命中关键词时在提示词里追加技能提示
    # 例：[{"keywords": ["记账", "买入"], "skill": "my-ledger", "hint": "先读 SKILL.md 再回答。"}]
    "extra_skill_triggers": [],
    # ---------- 任务分阶段 ----------
    "task_stage_enabled": True,
    "task_stage_timeout": 900,
    "task_stage_max": 10,
    "task_stage_summary_timeout": 120,
    "task_stage_continue_keywords": ["继续", "可以", "好", "嗯", "ok", "yes", "1"],
    "task_stage_stop_keywords": ["停止", "停", "不要", "算了", "取消", "no", "0"],
    # ---------- 媒体 / OCR ----------
    "pdf_ocr_enabled": True,
    "pdf_ocr_max_pages": 10,
    "pdf_ocr_timeout_sec": 120,
    "pdf_ocr_max_chars": 4000,
    # 留空 = 自动从 PATH 查找（pdftoppm / magick / tesseract）
    "pdf_render_cmd": "",
    "pdf_ocr_cmd": "",
    "video_analysis_enabled": True,
    "video_max_frames": 8,
    "video_max_width": 1280,
    "video_asr_enabled": True,
    "video_asr_backend": "auto",  # auto / whisper / faster-whisper / mlx-whisper / none
    "video_asr_model": "whisper-turbo",
    "video_asr_language": "",
    "video_asr_timeout": 600,
    "video_subtitle_enabled": True,
    "video_subtitle_max_chars": 4000,
    "video_asr_skip_if_subtitles": True,
    "video_link_parse_enabled": True,
    "video_bilibili_quality": "480",
    "video_ffmpeg_path": "",  # 留空 = imageio-ffmpeg 自带 / PATH
    "video_ffprobe_path": "",
    "video_shot_cols": 5,
    "video_shot_rows": 2,
    "video_shot_thumb_width": 160,
    "video_shot_thumb_height": 90,
    # ---------- 第三方插件（AstrBot 兼容层，可选，默认关闭）----------
    "restart_command": "",  # /restart 用；留空时 macOS 尝试 launchd，其它平台跳过
    "plugins_enabled": False,
    "plugins_dir": "astrbot_plugins",
    # ---------- 沙箱 / 视觉 ----------
    "vision_url": "",
    "vision_model": "",
    "vision_api_key": "",
    "vision_max_tokens": 2000,
    "vision_timeout_sec": 150,
    "vision_enrich_enabled": True,
    "vision_enrich_keywords": ["不确定", "无法确认", "资讯不足", "需要查证", "看不清"],
    # ---------- 消息分类 ----------
    "batch_window": 2.5,
    "image_wait_window": 8.0,
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
    "task_phrases": ["发给我", "发我", "做好发", "做成pdf", "做成 pdf", "重命名"],
    "casual_phrases": ["早", "早安", "早上好", "哎", "唉", "好累", "在"],
    "task_follow_idle_sec": 7200,
    "task_auto_length": 60,
    "task_ack_lines": ["收到，我先看下", "这个我处理一下"],
    # ---------- 主动消息（默认关闭）----------
    "proactive_enabled": False,
    "proactive_fixed_times": ["09:30", "21:30"],
    "proactive_idle_minutes": 180,
    "proactive_cooldown_minutes": 180,
    "proactive_windows": ["09:00-23:30"],
    "proactive_max_per_day": 6,
    "proactive_notes_file": "proactive-notes.md",
    "proactive_check_interval_sec": 60,
    "proactive_decision_enabled": True,
    "proactive_trending_enabled": False,
    "proactive_trending_ttl_hours": 6,
    "proactive_trending_timeout_sec": 60,
    "image_search_timeout_sec": 45,
    # 外部搜索脚本（可选）：默认找 ~/.agents/skills/grok-search/scripts/grok_search.py
    "web_search_script": "",
    "web_search_python": "",
    "proactive_trending_query": "最近有什么网络热梗/热搜，适合日常聊天的轻松话题",
    "proactive_trending_image_search_enabled": False,
    "proactive_news_enabled": False,
    "proactive_news_query": "今日 AI 与科技领域值得关注的新闻和进展",
    "proactive_art_enabled": False,
    "proactive_art_query": "",
    "proactive_art_image_query": "",
    "proactive_artists": [],
    "proactive_topic_directions": [
        "生活日常（天气、吃饭、作息）",
        "科技/数码/互联网趣事",
        "音乐/电影/书",
        "季节/节日",
    ],
    "proactive_class_lead_minutes": 15,
    "proactive_class_windows": ["07:00-23:30"],
    "timetable_file": "timetable.json",
    # ---------- 存储 / 通道 ----------
    "state_db_file": "state.db",
    "sessions_file": "sessions.json",
    "scheduler_interval_sec": 15,
    "task_worker_interval_sec": 0.5,
    "messages_dir": "channels",
    "to_qq_dir": "channels/to_qq",
    "to_qq_sent_dir": "channels/to_qq/sent",
    "from_qq_log_file": "channels/from_qq/feedback.jsonl",
    "main_agent_prefixes": ["/本机"],
    "main_agent_inbox_file": "channels/from_qq/main.jsonl",
    "agent_status_file": "channels/state/agent-status.md",
    "pending_file": "channels/state/pending.json",
    "outbox_dir": "outbox",
    "outbox_sent_dir": "sent",
    "outbox_check_interval_sec": 5,
    "inbox_dir": "inbox",
    "inbox_log_file": "feedback.log",
    "inbox_log_max_lines": 200,
    "inbox_log_max_bytes": 65536,
    "decisions_dir": "decisions",
    # ---------- 知识库 ----------
    "rag_dirs": [],
    "rag_extensions": [".md", ".txt", ".pdf"],
    # ---------- 内置技能 ----------
    "skills_enabled": ["weather", "rss", "github"],
    # ---------- TTS 语音（可选，默认关闭）----------
    "tts_backend": "off",  # off / local（GPT-SoVITS HTTP）
    "tts_local_url": "http://127.0.0.1:9880/tts",
    "tts_models_dir": "",
    "tts_character": "",
    "tts_ref": "",
    "tts_ref_dir": "",  # 参考音频子目录（可选，不同语音包目录结构不同）
    "tts_text_lang": "all_ja",
    "tts_prompt_lang": "all_ja",
    "tts_timeout_sec": 120,
    "tts_language": "ja",
    "voice_max_chars": 120,
    "voice_max_per_reply": 1,
    "voice_fallback_text": "（语音合成失败）",
    "voice_fallback_to_text": False,
    "voice_cache_dir": "voice_cache",
    # ---------- Web 工作台 ----------
    "web_enabled": False,
    "web_host": "127.0.0.1",
    "web_port": 8080,
    "web_token": "",
    # ---------- 发送 / 日志 ----------
    "chunk_limit": 3800,
    "chunk_delay_sec": 0.5,
    "forward_threshold": 5,
    # 合并转发的节点显示名/QQ 号（留空则用 persona_name 或 “AI 助手”）
    "forward_sender_name": "",
    "forward_sender_uin": "10000",
    "log_file": "bridge.log",
    "log_level": "INFO",
}

#: 需要按路径展开的键（相对路径 → 相对 data_dir / 项目目录）
#: 旧配置键 → 新键。老 config.json / 老 QQBOT_* 环境变量继续可用（启动时提示改名）。
LEGACY_KEYS: dict[str, str] = {
    # 模型接口
    "agno_base_url": "api_base_url",
    "agno_api_key": "api_key",
    "agno_model": "model",
    "codex_model": "model",
    "agno_db_file": "memory_db",
    "agno_tools_enabled": "tools_enabled",
    "agno_shell_enabled": "shell_enabled",
    "agno_file_tools_enabled": "file_tools_enabled",
    "agno_web_search_enabled": "web_search_enabled",
    "agno_agentic_memory_enabled": "memory_enabled",
    "agno_update_memory_on_run": "memory_auto_update",
    "agno_add_memories_to_context": "memory_in_chat",
    "agno_history_runs": "history_turns",
    "agno_memory_reasoning_effort": "memory_effort",
    "agno_memory_timeout": "memory_timeout",
    "agno_user_agent": "user_agent",
    # 调用策略
    "codex_workdir": "workdir",
    "codex_timeout": "request_timeout",
    "codex_native_vision": "vision_native",
    "codex_fallback_enabled": "fallback_enabled",
    "codex_fallback_model": "fallback_model",
    "codex_roleplay_reasoning_effort": "chat_effort",
    "codex_task_reasoning_effort": "task_effort",
    "codex_enrich_reasoning_effort": "search_effort",
    "codex_roleplay_timeout": "chat_timeout",
    "codex_task_timeout": "task_timeout",
    "codex_enrich_timeout": "search_timeout",
    # 人格
    "roleplay_enabled": "persona_enabled",
    "roleplay_skill": "persona_skill",
    "roleplay_ack_lines": "persona_ack_lines",
    "roleplay_casual_max_chars": "persona_chat_max_chars",
    "roleplay_casual_max_segments": "persona_chat_max_segments",
    "roleplay_casual_delay_sec": "persona_chat_delay_sec",
    "roleplay_session_prefix": "persona_session_prefix",
    "roleplay_reset_turns": "persona_reset_turns",
    "roleplay_reset_hours": "persona_reset_hours",
    "roleplay_memory_file": "persona_memory_file",
    "kaomoji_examples": "emoticon_examples",
    # 插件 / 外部搜索
    "astrbot_plugins_enabled": "plugins_enabled",
    "astrbot_plugins_dir": "plugins_dir",
    "grok_search_script": "web_search_script",
    "grok_search_python": "web_search_python",
    "grok_image_search_timeout_sec": "image_search_timeout_sec",
    # 其它历史键
    "agno_knowledge_enabled": "knowledge_tool_enabled",
    "agno_skills_enabled": "skills_tool_enabled",
}

#: 状态数据：相对路径 → 相对 data_dir（用 data_dir 就能把状态整体挪走）
_DATA_PATH_KEYS: tuple[str, ...] = (
    "memory_db",
    "state_db_file",
    "sessions_file",
    "log_file",
    "timetable_file",
    "persona_memory_file",
    "proactive_notes_file",
    "voice_cache_dir",
)
#: 项目内目录：相对路径 → 相对项目目录（channels / outbox 等需要固定位置）
_PROJECT_PATH_KEYS: tuple[str, ...] = (
    "workdir",
    "messages_dir",
    "to_qq_dir",
    "to_qq_sent_dir",
    "from_qq_log_file",
    "main_agent_inbox_file",
    "agent_status_file",
    "pending_file",
    "outbox_dir",
    "inbox_dir",
    "decisions_dir",
    "inbox_log_file",
    "plugins_dir",
)
#: 外部资源：相对路径 → 相对项目目录，支持 ~ 与环境变量
_EXTERNAL_PATH_KEYS: tuple[str, ...] = (
    "tts_models_dir",
    "video_ffmpeg_path",
    "video_ffprobe_path",
    "pdf_render_cmd",
    "pdf_ocr_cmd",
    "persona_skill_home",
)
_PATH_KEYS: tuple[str, ...] = (  # 兼容旧引用
    *_DATA_PATH_KEYS,
    *_PROJECT_PATH_KEYS,
    *_EXTERNAL_PATH_KEYS,
)
_PATH_LIST_KEYS: tuple[str, ...] = ("rag_dirs",)


def platform_config_dir() -> Path:
    """跨平台用户级配置目录。"""
    if os.name == "nt":
        base = os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / APP_NAME


def platform_data_dir() -> Path:
    """跨平台用户级数据目录（``data_dir`` 的兜底说明用）。"""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / APP_NAME


def find_config_path(path: str | os.PathLike[str] | None = None) -> Path | None:
    """定位配置文件：显式参数 → 环境变量 → 项目目录 → 用户配置目录。"""
    if path:
        return Path(path).expanduser()
    env_path = os.environ.get(f"{ENV_PREFIX}CONFIG", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    candidates = [PROJECT_DIR / "config.json", platform_config_dir() / "config.json"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _parse_env_value(raw: str, current: Any) -> Any:
    text = raw.strip()
    if isinstance(current, bool):
        return text.lower() in ("1", "true", "yes", "on", "y")
    if text == "":
        return ""
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return raw
    if isinstance(current, list) and not isinstance(value, list):
        return [value]
    return value


def _env_raw(key: str) -> str | None:
    """读环境变量：先读新键名，再回退到旧键名（LEGACY_KEYS）。"""
    raw = os.environ.get(f"{ENV_PREFIX}{key.upper()}")
    if raw is not None:
        return raw
    for old, new in LEGACY_KEYS.items():
        if new == key:
            raw = os.environ.get(f"{ENV_PREFIX}{old.upper()}")
            if raw is not None:
                return raw
    return None


def _apply_env_overrides(cfg: dict[str, Any]) -> dict[str, Any]:
    for key in list(cfg):
        raw = _env_raw(key)
        if raw is None:
            continue
        cfg[key] = _parse_env_value(raw, cfg.get(key))
    return cfg


def _expand_path(value: Any, base: Path) -> Any:
    if not isinstance(value, str) or not value.strip():
        return value
    expanded = os.path.expandvars(value).strip()
    path = Path(expanded).expanduser()
    if not path.is_absolute():
        path = base / path
    return str(path)


def _resolve_paths(cfg: dict[str, Any]) -> dict[str, Any]:
    explicit = str(cfg.get("data_dir") or "").strip()
    data_dir = Path(os.path.expandvars(explicit)).expanduser() if explicit else PROJECT_DIR
    if not data_dir.is_absolute():
        data_dir = PROJECT_DIR / data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    cfg["data_dir"] = str(data_dir)
    for key in _DATA_PATH_KEYS:
        if key in cfg:
            cfg[key] = _expand_path(cfg[key], data_dir)
    for key in _PROJECT_PATH_KEYS:
        if key in cfg:
            cfg[key] = _expand_path(cfg[key], PROJECT_DIR)
    for key in _EXTERNAL_PATH_KEYS:
        if key in cfg:
            cfg[key] = _expand_path(cfg[key], PROJECT_DIR)
    for key in _PATH_LIST_KEYS:
        value = cfg.get(key)
        if isinstance(value, list):
            cfg[key] = [_expand_path(item, PROJECT_DIR) for item in value]
    if not str(cfg.get("workdir") or "").strip():
        cfg["workdir"] = str(PROJECT_DIR)
    return cfg


def load_config(path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """加载配置；优先级：环境变量 > config.json > 内置默认值。"""
    cfg = json.loads(json.dumps(DEFAULTS))
    config_path = find_config_path(path)
    if config_path is not None and Path(config_path).exists():
        with Path(config_path).open(encoding="utf-8") as handle:
            loaded = json.load(handle)
        if not isinstance(loaded, dict):
            raise ValueError(f"配置文件必须是 JSON 对象：{config_path}")
        cfg.update(loaded)
    elif path:
        raise FileNotFoundError(f"配置文件不存在：{config_path}")
    legacy_used: list[str] = []
    for old, new in LEGACY_KEYS.items():
        if new in cfg and cfg[new] != DEFAULTS.get(new):
            continue  # 新键名已经显式配置过了，优先用新键
        if old in cfg:
            cfg[new] = cfg[old]
            legacy_used.append(old)
    cfg = _apply_env_overrides(cfg)
    if legacy_used:
        cfg["_legacy_keys"] = legacy_used
    cfg["_config_path"] = str(config_path) if config_path else ""
    cfg["_project_dir"] = str(PROJECT_DIR)
    cfg["full_access_qq"] = [str(item) for item in (cfg.get("full_access_qq") or [])]
    if not cfg["full_access_qq"]:
        raise ValueError(
            "未配置允许使用的 QQ 号：请将 config.example.json 复制为 config.json，"
            "填写 full_access_qq；也可直接使用环境变量 "
            "QQBOT_FULL_ACCESS_QQ='[\"123456789\"]'。"
        )
    if bool(cfg.get("web_enabled", False)):
        web_token = str(cfg.get("web_token") or "").strip()
        if not web_token or web_token == "dev-token-change-me":
            raise ValueError(
                "web_enabled=true 时必须配置一个非默认的 web_token"
                "（config.json 或环境变量 QQBOT_WEB_TOKEN）"
            )
    cfg = _resolve_paths(cfg)
    return cfg


def ensure_runtime_dirs(cfg: dict[str, Any]) -> None:
    """创建运行期需要的目录。"""
    for key in ("voice_cache_dir", "plugins_dir"):
        value = str(cfg.get(key) or "").strip()
        if value:
            Path(value).mkdir(parents=True, exist_ok=True)
