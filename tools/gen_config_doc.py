#!/usr/bin/env python3
"""生成 CONFIG.md（全量配置手册）。

用法：
    python tools/gen_config_doc.py

每个配置键都必须在这里写一句说明，否则脚本会报错退出——
这样 CONFIG.md 永远不会和 config.py 的 DEFAULTS 脱节。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from config import DEFAULTS  # noqa: E402

#: (组标题, 组说明, [键...])
GROUPS: list[tuple[str, str, list[str]]] = [
    (
        "连接",
        "怎么连上 QQ。",
        ["onebot_ws_url", "full_access_qq"],
    ),
    (
        "目录与状态文件",
        "日志、数据库、会话、记忆放哪。相对路径相对 `data_dir` 解析。",
        [
            "data_dir", "workdir", "log_file", "log_level", "state_db_file",
            "sessions_file", "memory_db", "persona_memory_file", "timetable_file",
            "proactive_notes_file", "voice_cache_dir",
        ],
    ),
    (
        "模型接口",
        "任何 OpenAI 兼容服务都能用：官方 OpenAI、DeepSeek、中转站、自建网关。",
        ["api_base_url", "api_key", "model", "request_timeout", "keep_proxy", "user_agent"],
    ),
    (
        "工具与记忆",
        "助手能用哪些能力，以及它记不记得住事。",
        [
            "tools_enabled", "shell_enabled", "file_tools_enabled", "web_search_enabled",
            "knowledge_tool_enabled", "skills_tool_enabled", "github_token",
            "memory_enabled", "memory_auto_update", "memory_in_chat", "history_turns",
            "memory_effort", "memory_timeout",
        ],
    ),
    (
        "推理强度与超时",
        "不同场景用多少算力：闲聊要快，干活要稳。",
        [
            "chat_effort", "task_effort", "search_effort",
            "chat_timeout", "task_timeout", "search_timeout",
            "fallback_enabled", "fallback_model",
        ],
    ),
    (
        "图片与视觉",
        "看图、识图、找不到就联网补查。",
        [
            "vision_native", "vision_url", "vision_model", "vision_api_key",
            "vision_max_tokens", "vision_timeout_sec", "vision_enrich_enabled",
            "vision_enrich_keywords", "image_search_tool", "image_search_timeout_sec",
        ],
    ),
    (
        "PDF 与视频",
        "PDF 转文字、视频抽帧 + 字幕 + 语音转写。",
        [
            "pdf_ocr_enabled", "pdf_ocr_max_pages", "pdf_ocr_timeout_sec", "pdf_ocr_max_chars",
            "pdf_render_cmd", "pdf_ocr_cmd",
            "video_analysis_enabled", "video_max_frames", "video_max_width",
            "video_subtitle_enabled", "video_subtitle_max_chars",
            "video_asr_enabled", "video_asr_backend", "video_asr_model", "video_asr_language",
            "video_asr_timeout", "video_asr_skip_if_subtitles",
            "video_link_parse_enabled", "video_bilibili_quality",
            "video_ffmpeg_path", "video_ffprobe_path",
            "video_shot_cols", "video_shot_rows", "video_shot_thumb_width",
            "video_shot_thumb_height",
        ],
    ),
    (
        "消息识别",
        "怎么判断一句话是「闲聊」还是「任务」。",
        [
            "batch_window", "image_wait_window", "task_prefixes", "task_keywords",
            "task_phrases", "casual_phrases", "task_follow_idle_sec", "task_auto_length",
            "task_ack_lines", "ack_delay_sec",
        ],
    ),
    (
        "任务分阶段",
        "大任务跑一段就汇报一次，等你回复「继续」或「停止」。",
        [
            "task_stage_enabled", "task_stage_timeout", "task_stage_max",
            "task_stage_summary_timeout", "task_stage_continue_keywords",
            "task_stage_stop_keywords",
        ],
    ),
    (
        "人格设定",
        "留空就是普通助手；填了就是你自己的助手人设。",
        [
            "persona_enabled", "persona_name", "persona_prompt", "persona_skill",
            "persona_skill_home", "persona_ack_lines", "persona_chat_max_chars",
            "persona_chat_max_segments", "persona_chat_delay_sec",
            "persona_session_prefix", "persona_reset_turns", "persona_reset_hours",
        ],
    ),
    (
        "提示词覆盖",
        "内置提示词不满意就直接覆盖掉。",
        [
            "chat_style_guide", "media_frequency_guide", "media_marker_guide",
            "proactive_topic_guide", "emoticon_examples", "extra_skill_triggers",
        ],
    ),
    (
        "主动消息",
        "定时 / 长时间没消息 / 日程前主动找你（默认关闭）。",
        [
            "proactive_enabled", "proactive_fixed_times", "proactive_idle_minutes",
            "proactive_cooldown_minutes", "proactive_windows", "proactive_max_per_day",
            "proactive_check_interval_sec", "proactive_decision_enabled",
            "proactive_topic_directions", "proactive_class_lead_minutes",
            "proactive_class_windows", "proactive_notes_file",
            "proactive_trending_enabled", "proactive_trending_query",
            "proactive_trending_image_search_enabled", "proactive_trending_ttl_hours",
            "proactive_trending_timeout_sec", "proactive_news_enabled",
            "proactive_news_query", "proactive_art_enabled", "proactive_art_query",
            "proactive_art_image_query", "proactive_artists",
            "web_search_script", "web_search_python",
        ],
    ),
    (
        "提醒 / 待办 / 任务 / 知识库",
        "内置的轻量工作台。",
        [
            "scheduler_interval_sec", "task_worker_interval_sec",
            "rag_dirs", "rag_extensions", "skills_enabled",
        ],
    ),
    (
        "语音",
        "把回复变成语音条（默认关闭）。",
        [
            "tts_backend", "tts_local_url", "tts_models_dir", "tts_character", "tts_ref",
            "tts_ref_dir", "tts_text_lang", "tts_prompt_lang", "tts_language",
            "tts_timeout_sec", "voice_max_chars", "voice_max_per_reply",
            "voice_fallback_text", "voice_fallback_to_text",
        ],
    ),
    (
        "Web 工作台",
        "浏览器里聊天、看提醒/待办/任务、查日志（默认关闭）。",
        ["web_enabled", "web_host", "web_port", "web_token"],
    ),
    (
        "文件通道",
        "和另一个程序互通：写 JSON 就发 QQ，QQ 消息也能写文件（见 channels/README.md）。",
        [
            "messages_dir", "to_qq_dir", "to_qq_sent_dir", "from_qq_log_file",
            "main_agent_prefixes", "main_agent_inbox_file", "agent_status_file",
            "pending_file", "outbox_dir", "outbox_sent_dir", "outbox_check_interval_sec",
            "inbox_dir", "inbox_log_file", "inbox_log_max_lines", "inbox_log_max_bytes",
            "decisions_dir",
        ],
    ),
    (
        "回复发送",
        "长回复怎么拆、怎么合并转发。",
        [
            "chunk_limit", "chunk_delay_sec", "forward_threshold",
            "forward_sender_name", "forward_sender_uin",
        ],
    ),
    (
        "第三方插件",
        "可选：跑 AstrBot 生态里的简单插件。",
        ["plugins_enabled", "plugins_dir"],
    ),
    (
        "运行",
        "进程自身的行为。",
        ["restart_command"],
    ),
]

#: 每个键一句说明。缺一个都会生成失败。
DESCRIPTIONS: dict[str, str] = {
    # 连接
    "onebot_ws_url": "NapCat 的 OneBot WebSocket 地址，默认本机 3001 端口",
    "full_access_qq": "**必填**。允许使用机器人的 QQ 号列表；不在列表里的私聊会被忽略",
    # 目录与状态文件
    "data_dir": "日志 / 数据库 / 会话 / 记忆的存放目录，默认项目下的 `data/`",
    "workdir": "助手的文件读写和命令执行范围；留空 = 项目目录。建议指向一个可以随便折腾的目录",
    "log_file": "日志文件名（相对 `data_dir`）",
    "log_level": "日志级别：DEBUG / INFO / WARNING / ERROR",
    "state_db_file": "提醒 / 待办 / 任务 / 知识库索引的 SQLite 文件",
    "sessions_file": "QQ 会话 ID 与轮次的 JSON 文件",
    "memory_db": "助手的会话历史与长期记忆 SQLite 文件",
    "persona_memory_file": "人格模式下自动整理的长期记忆 Markdown 文件",
    "timetable_file": "课表数据文件（`/课表` 导入后生成）",
    "proactive_notes_file": "主动消息参考的日程/待办 Markdown 文件，可以直接手写",
    "voice_cache_dir": "TTS 合成结果的缓存目录",
    # 模型接口
    "api_base_url": "OpenAI 兼容接口地址，例如 `https://api.openai.com/v1`、`https://api.deepseek.com/v1`",
    "api_key": "接口密钥。建议用环境变量 `QQBOT_API_KEY` 注入，不要写进文件",
    "model": "模型名，例如 `gpt-4o-mini`、`deepseek-chat`；留空用 `OPENAI_MODEL` 环境变量",
    "request_timeout": "单次模型请求的兜底超时（秒）",
    "keep_proxy": "默认 False：清掉系统代理变量，避免失效代理导致连不上；必须走代理时设为 True",
    "user_agent": "请求头 UA；留空使用内置浏览器 UA（部分上游会拦默认的 python UA）",
    # 工具与记忆
    "tools_enabled": "助手工具总开关；关掉后它只能聊天",
    "shell_enabled": "允许执行命令（限制在 `workdir` 内）",
    "file_tools_enabled": "允许读写文件（限制在 `workdir` 内）",
    "web_search_enabled": "允许联网搜索",
    "knowledge_tool_enabled": "允许助手检索本地知识库（`/知识库 重建` 建立的索引）",
    "skills_tool_enabled": "允许助手调用 `skills/` 下的外部技能",
    "github_token": "可选：GitHub 技能用的 token，填了能提高 API 限额",
    "memory_enabled": "长期记忆总开关",
    "memory_auto_update": "每次对话后自动把值得记的内容沉淀进记忆",
    "memory_in_chat": "把长期记忆注入对话上下文",
    "history_turns": "每次请求带多少轮历史对话",
    "memory_effort": "记忆整理用的推理强度",
    "memory_timeout": "记忆整理超时（秒）",
    # 推理强度与超时
    "chat_effort": "闲聊的推理强度：low / medium / high / max",
    "task_effort": "执行任务的推理强度",
    "search_effort": "联网补查的推理强度",
    "chat_timeout": "闲聊单次超时（秒）",
    "task_timeout": "任务单次超时（秒）",
    "search_timeout": "联网补查超时（秒）",
    "fallback_enabled": "主模型失败时是否自动换兜底模型重试一次",
    "fallback_model": "兜底模型名；留空则不启用",
    # 图片与视觉
    "vision_native": "把图片直接作为附件交给多模态主模型（推荐开启）",
    "vision_url": "视觉接口地址；留空跟随 `api_base_url`",
    "vision_model": "视觉模型名；留空跟随 `model`",
    "vision_api_key": "视觉接口密钥；留空跟随 `api_key`",
    "vision_max_tokens": "视觉请求最大输出 token",
    "vision_timeout_sec": "视觉请求超时（秒）",
    "vision_enrich_enabled": "描述里出现不确定项时，自动联网补查一次",
    "vision_enrich_keywords": "触发自动补查的关键词",
    "image_search_tool": "想让助手用某个「找图」工具时填工具名；留空则不提示",
    "image_search_timeout_sec": "找图搜索超时（秒）",
    # PDF 与视频
    "pdf_ocr_enabled": "PDF 兜底 OCR（需要本机有 poppler + tesseract）",
    "pdf_ocr_max_pages": "OCR 最多处理多少页",
    "pdf_ocr_timeout_sec": "PDF 处理超时（秒）",
    "pdf_ocr_max_chars": "OCR 结果最多保留多少字符",
    "pdf_render_cmd": "自定义 PDF 渲染命令；留空自动查找 `pdftoppm`",
    "pdf_ocr_cmd": "自定义 OCR 命令；留空自动查找 `tesseract`",
    "video_analysis_enabled": "视频分析总开关（抽帧 + 字幕 + 语音转写）",
    "video_max_frames": "最多抽多少帧给视觉模型",
    "video_max_width": "抽帧最大宽度（越小越省 token）",
    "video_subtitle_enabled": "导出视频内嵌字幕作为参考",
    "video_subtitle_max_chars": "字幕最多保留多少字符",
    "video_asr_enabled": "没有字幕时用语音转写兜底",
    "video_asr_backend": "转写后端：auto / whisper / faster-whisper / mlx-whisper / none",
    "video_asr_model": "转写模型名，例如 `whisper-turbo`、`base`、`small`",
    "video_asr_language": "转写语言；留空自动识别",
    "video_asr_timeout": "语音转写超时（秒）",
    "video_asr_skip_if_subtitles": "已有字幕时跳过语音转写",
    "video_link_parse_enabled": "识别消息里的视频链接（B 站 / 直链）并下载分析",
    "video_bilibili_quality": "B 站下载清晰度，例如 480 / 720 / 1080",
    "video_ffmpeg_path": "ffmpeg 可执行文件路径；留空自动查找（含 imageio-ffmpeg 自带）",
    "video_ffprobe_path": "ffprobe 路径；留空自动查找",
    "video_shot_cols": "进度条雪碧图列数",
    "video_shot_rows": "进度条雪碧图行数",
    "video_shot_thumb_width": "雪碧图缩略图宽（像素）",
    "video_shot_thumb_height": "雪碧图缩略图高（像素）",
    # 消息识别
    "batch_window": "连续消息合并窗口（秒）",
    "image_wait_window": "只发了图片时，等多久看有没有配文字（秒）",
    "task_prefixes": "任务前缀，例如 `任务：`、`/task`",
    "task_keywords": "任务关键词，例如 `帮我`、`总结`",
    "task_phrases": "更像下命令的口语句式，例如 `发给我`、`做成pdf`",
    "casual_phrases": "明显是闲聊的短句，例如 `早`、`好累`",
    "task_follow_idle_sec": "上一轮是任务时，多久内的短回复继续当任务（秒）",
    "task_auto_length": "超过多少字自动当任务处理",
    "task_ack_lines": "收到任务先回的短句（可随机选一条）",
    "ack_delay_sec": "先回「收到」的延迟（秒）",
    # 任务分阶段
    "task_stage_enabled": "大任务分阶段执行：跑一段就汇报并等你确认",
    "task_stage_timeout": "每个阶段最长执行时间（秒）",
    "task_stage_max": "最多几个阶段",
    "task_stage_summary_timeout": "阶段总结超时（秒）",
    "task_stage_continue_keywords": "表示「继续」的回复",
    "task_stage_stop_keywords": "表示「停止」的回复",
    # 人格设定
    "persona_enabled": "是否启用「人格模式」（助手按人设说话）",
    "persona_name": "助手自称，例如「小助手」；留空 = 普通助手",
    "persona_prompt": "人设描述，例如「说话简短、先给结论，不确定就直说不知道」",
    "persona_skill": "技能名：填了会提示模型先读 `<persona_skill_home>/<技能>/SKILL.md`",
    "persona_skill_home": "技能目录根，默认 `~/.agents/skills`",
    "persona_ack_lines": "人格模式下收到任务的短回应",
    "persona_chat_max_chars": "闲聊时单条消息的软上限字数（超出会拆成多条）",
    "persona_chat_max_segments": "闲聊最多拆成几条消息",
    "persona_chat_delay_sec": "拆开发送时每条之间的间隔（秒）",
    "persona_session_prefix": "人格会话的 thread 前缀（一般不用改）",
    "persona_reset_turns": "聊满多少轮后自动整理记忆并开启新会话",
    "persona_reset_hours": "同一会话最长使用多少小时",
    # 提示词覆盖
    "chat_style_guide": "覆盖内置的「对话风格」提示词；留空用内置版本",
    "media_frequency_guide": "覆盖内置的「表情/语音使用频率」提示词",
    "media_marker_guide": "覆盖内置的「媒体标记」说明（高级用法）",
    "proactive_topic_guide": "覆盖内置的「主动话题规则」提示词",
    "emoticon_examples": "颜文字示例，会写进提示词",
    "extra_skill_triggers": "自定义技能触发：命中关键词时提示模型先读某个技能，例如 `[{\「keywords\」: [\「报销\」], \「skill\」: \「my-finance\」}]`",
    # 主动消息
    "proactive_enabled": "主动消息总开关（默认关闭）",
    "proactive_fixed_times": "每天固定主动开口的时间点，例如 `[\「09:30\」, \「21:30\」]`",
    "proactive_idle_minutes": "多久没消息后主动开口（分钟）",
    "proactive_cooldown_minutes": "两次主动之间的最小间隔（分钟）",
    "proactive_windows": "允许主动开口的时间段，例如 `[\「09:00-23:30\」]`",
    "proactive_max_per_day": "每天最多主动几次",
    "proactive_check_interval_sec": "调度检查间隔（秒）",
    "proactive_decision_enabled": "开口前先让模型判断「现在适不适合打扰」",
    "proactive_topic_directions": "主动聊天的方向列表",
    "proactive_class_lead_minutes": "日程开始前提前多久提醒（分钟）",
    "proactive_class_windows": "日程提醒允许的时间段",
    "web_search_script": "可选：外部搜索脚本路径（用于主动话题素材）。留空用 `~/.agents/skills/grok-search/scripts/grok_search.py`",
    "web_search_python": "运行搜索脚本用的 Python 解释器；留空用当前解释器",
    "proactive_trending_enabled": "主动开口前抓「近期素材」（需要上面的外部搜索脚本）",
    "proactive_trending_query": "素材搜索关键词",
    "proactive_trending_image_search_enabled": "素材搜索时也找图",
    "proactive_trending_ttl_hours": "素材缓存有效期（小时）",
    "proactive_trending_timeout_sec": "素材搜索超时（秒）",
    "proactive_news_enabled": "素材里包含新闻",
    "proactive_news_query": "新闻搜索关键词",
    "proactive_art_enabled": "素材里包含画师/新作（二次元场景用）",
    "proactive_art_query": "画师推荐搜索关键词",
    "proactive_art_image_query": "新作图片搜索关键词",
    "proactive_artists": "你关注的画师名单，会附加到搜索里",
    # 提醒 / 待办 / 任务 / 知识库
    "scheduler_interval_sec": "提醒调度循环间隔（秒）",
    "task_worker_interval_sec": "后台任务队列轮询间隔（秒）",
    "rag_dirs": "知识库要索引的目录列表",
    "rag_extensions": "知识库索引哪些后缀的文件",
    "skills_enabled": "启用哪些内置技能：weather / rss / github",
    # 语音
    "tts_backend": "语音合成后端：`off` 关闭 / `local` 本地 GPT-SoVITS",
    "tts_local_url": "本地 GPT-SoVITS 服务地址",
    "tts_models_dir": "GPT-SoVITS 模型目录（含 `GPT_weights_v2/characters.json`）",
    "tts_character": "角色名（对应 characters.json 里的 name）",
    "tts_ref": "参考语气名（对应角色 refs 里的 name）",
    "tts_ref_dir": "参考音频所在子目录；留空 = 参考音频路径直接相对 `tts_models_dir`",
    "tts_text_lang": "合成文本语言标记，例如 `all_ja`、`zh`",
    "tts_prompt_lang": "参考音频的语言标记",
    "tts_language": "提示词里告诉模型「用哪种语言发语音」",
    "tts_timeout_sec": "合成超时（秒）",
    "voice_max_chars": "一条语音最多多少字",
    "voice_max_per_reply": "一条回复最多几条语音",
    "voice_fallback_text": "合成失败时发的提示文本",
    "voice_fallback_to_text": "合成失败时是否直接把文本发出去",
    # Web 工作台
    "web_enabled": "是否开启 Web 工作台（需要 `pip install -r requirements-web.txt`）",
    "web_host": "监听地址，建议保持 `127.0.0.1`",
    "web_port": "监听端口",
    "web_token": "访问口令；`web_enabled=true` 时必须设置一个非默认值",
    # 文件通道
    "messages_dir": "文件通道根目录",
    "to_qq_dir": "投递目录：往这里写 JSON 信封就会发到 QQ",
    "to_qq_sent_dir": "已发送信封的归档目录",
    "from_qq_log_file": "QQ 消息落盘文件（JSONL）",
    "main_agent_prefixes": "以这些前缀开头的消息不经过模型，直接转给外部程序，例如 `[\「/本机\」]`",
    "main_agent_inbox_file": "转给外部程序的消息落盘文件",
    "agent_status_file": "外部程序维护的状态 Markdown，助手可以读",
    "pending_file": "等待用户回复的决断/阶段等待文件",
    "outbox_dir": "旧版投递目录（启动时自动迁移到 `to_qq_dir`）",
    "outbox_sent_dir": "旧版归档目录名",
    "outbox_check_interval_sec": "投递目录扫描间隔（秒）",
    "inbox_dir": "旧版接收目录",
    "inbox_log_file": "旧版消息日志文件名",
    "inbox_log_max_lines": "消息日志最多保留多少行",
    "inbox_log_max_bytes": "消息日志最多多少字节",
    "decisions_dir": "旧版决断目录",
    # 回复发送
    "chunk_limit": "单条消息最大长度（超出拆分）",
    "chunk_delay_sec": "拆开发送时每条之间的间隔（秒）",
    "forward_threshold": "回复超过几段时尝试「合并转发」",
    "forward_sender_name": "合并转发节点显示名；留空用 `persona_name` 或「AI 助手」",
    "forward_sender_uin": "合并转发节点显示的 QQ 号",
    # 第三方插件
    "plugins_enabled": "是否加载 AstrBot 兼容插件（默认关闭）",
    "plugins_dir": "插件目录（每个插件一个子目录，含 `main.py`）",
    # 运行
    "restart_command": "`/restart` 命令执行的命令，例如 `systemctl restart qq-agent-bridge`；留空时 macOS 尝试 launchd，其它平台跳过",
}


def _fmt(value: object) -> str:
    if isinstance(value, str):
        return f"`{value}`" if value else "`\"\"`"
    return "`" + json.dumps(value, ensure_ascii=False) + "`"


def main() -> int:
    missing = [k for k in DEFAULTS if k not in DESCRIPTIONS]
    if missing:
        print("以下配置键缺少说明，请在 tools/gen_config_doc.py 里补上：", file=sys.stderr)
        for key in missing:
            print("  -", key, file=sys.stderr)
        return 1

    grouped = {key for _, _, keys in GROUPS for key in keys}
    ungrouped = [k for k in DEFAULTS if k not in grouped]
    if ungrouped:
        print("以下配置键没有归组：", ungrouped, file=sys.stderr)
        return 1

    lines: list[str] = [
        "# 配置手册",
        "",
        "所有可配置项都在这里。**你只需要改 [config.example.json](config.example.json) 里那几行就能跑起来**，",
        "其余按键都有合理默认值，需要时再动。",
        "",
        "三种改法（优先级从高到低）：",
        "",
        "1. 环境变量：任意键都能写成 `QQBOT_<键名大写>`，值按 JSON 解析。",
        "",
        "   ```bash",
        "   export QQBOT_API_KEY=sk-xxx",
        "   export QQBOT_FULL_ACCESS_QQ='[\"123456789\"]'",
        "   export QQBOT_PERSONA_NAME=小助手",
        "   ```",
        "",
        "2. `config.json`（复制 `config.example.json` 得到）。",
        "3. 内置默认值（本手册「默认值」列）。",
        "",
        "路径类的键：相对路径按「数据类挂 `data_dir`、工作类挂项目目录」解析，",
        "所以从任何目录启动都不会串。",
        "",
        "> 配置键改名后旧名字仍然生效（升级时不会失效），启动日志会提示你改成新名字。",
        "",
        "---",
        "",
    ]
    for title, blurb, keys in GROUPS:
        lines.append(f"## {title}")
        lines.append("")
        lines.append(blurb)
        lines.append("")
        lines.append("| 键 | 默认值 | 说明 |")
        lines.append("| --- | --- | --- |")
        for key in keys:
            lines.append(f"| `{key}` | {_fmt(DEFAULTS[key])} | {DESCRIPTIONS[key]} |")
        lines.append("")

    (ROOT / "CONFIG.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"CONFIG.md 已生成：{len(DEFAULTS)} 个配置键")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
