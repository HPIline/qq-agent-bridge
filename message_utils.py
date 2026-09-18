from __future__ import annotations

import re
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def extract_private_message(event: dict[str, Any]) -> dict[str, Any] | None:
    if event.get("post_type") != "message" or event.get("message_type") != "private":
        return None
    text_parts: list[str] = []
    images: list[dict[str, str]] = []
    videos: list[dict[str, str]] = []
    files: list[dict[str, str]] = []
    faces: list[dict[str, str]] = []
    mfaces: list[dict[str, str]] = []
    for seg in event.get("message", []) or []:
        data = seg.get("data", {}) or {}
        seg_type = seg.get("type")
        if seg_type == "text":
            text_parts.append(str(data.get("text", "")))
        elif seg_type == "image":
            url = str(data.get("url", "") or "")
            file_ref = str(data.get("file", "") or "")
            if url or file_ref:
                images.append({"url": url, "file": file_ref})
        elif seg_type == "video":
            url = str(data.get("url", "") or "")
            file_ref = str(data.get("file", "") or "")
            path = str(data.get("path", "") or "")
            name = str(data.get("name", "") or "")
            if url or file_ref or path:
                videos.append({"url": url, "file": file_ref, "path": path, "name": name})
        elif seg_type == "file":
            files.append(
                {
                    "file": str(data.get("file", "") or ""),
                    "file_id": str(data.get("file_id", "") or ""),
                    "url": str(data.get("url", "") or ""),
                    "name": str(data.get("name", "") or ""),
                    "path": str(data.get("path", "") or ""),
                }
            )
        elif seg_type == "face":
            face_id = str(data.get("id", "") or "")
            if face_id:
                faces.append({"id": face_id})
        elif seg_type == "mface":
            mface = {
                "emoji_id": str(data.get("emoji_id", "") or ""),
                "emoji_package_id": str(data.get("emoji_package_id", "") or ""),
                "key": str(data.get("key", "") or ""),
                "summary": str(data.get("summary", "") or ""),
            }
            if mface["emoji_id"] or mface["emoji_package_id"]:
                mfaces.append(mface)
    return {
        "message_id": str(event.get("message_id", "")),
        "user_id": str(event.get("user_id", "")),
        "text": "".join(text_parts).strip(),
        "images": images,
        "videos": videos,
        "files": files,
        "faces": faces,
        "mfaces": mfaces,
    }


def is_duplicate(message_id: str, seen: deque[str], maxlen: int = 2000) -> bool:
    if message_id in seen:
        return True
    seen.append(message_id)
    while len(seen) > maxlen:
        seen.popleft()
    return False


_DEFAULT_TASK_PHRASES = (
    "发给我",
    "发我",
    "做好发",
    "做成pdf",
    "做成 pdf",
    "重命名",
    "下载",
    "导出",
)

_DEFAULT_CASUAL_PHRASES = (
    "早",
    "早安",
    "早上好",
    "哎",
    "唉",
    "好累",
    "在",
    "在吗",
    "睡了",
)

_TASK_PATTERNS = (
    re.compile(r"视频"),
    re.compile(r"b23\.tv|bilibili\.com|BV[0-9A-Za-z]+", re.I),
    re.compile(r"https?://\S+"),
    re.compile(r"重命名"),
    re.compile(r"pdf", re.I),
)

_TRAILING_PUNCT_RE = re.compile(r"[\s。！？!?~～，,、.…·]+$")


@dataclass(frozen=True)
class TaskDecision:
    is_task: bool
    reason: str


def _normalize_utterance(text: str) -> str:
    return _TRAILING_PUNCT_RE.sub("", (text or "").strip())


def _string_list(cfg: dict[str, Any], key: str, default: tuple[str, ...]) -> list[str]:
    raw = cfg.get(key)
    if raw is None:
        raw = default
    out: list[str] = []
    for item in raw:
        value = str(item).strip()
        if value:
            out.append(value)
    return out


def _is_casual_utterance(text: str, cfg: dict[str, Any]) -> bool:
    normalized = _normalize_utterance(text)
    if not normalized:
        return False
    casuals = _string_list(cfg, "casual_phrases", _DEFAULT_CASUAL_PHRASES)
    folded = normalized.casefold()
    return any(folded == phrase.casefold() for phrase in casuals)


def classify_message(
    text: str,
    cfg: dict[str, Any],
    follow: dict[str, Any] | None = None,
    now: float | None = None,
) -> TaskDecision:
    text = (text or "").strip()
    if not text:
        return TaskDecision(False, "empty")
    if _is_casual_utterance(text, cfg):
        return TaskDecision(False, "casual")
    if any(text.startswith(p) for p in cfg.get("task_prefixes", [])):
        return TaskDecision(True, "prefix")
    if any(k in text for k in cfg.get("task_keywords", []) if str(k).strip()):
        return TaskDecision(True, "keyword")
    phrases = _string_list(cfg, "task_phrases", _DEFAULT_TASK_PHRASES)
    lowered = text.casefold()
    if any(phrase.casefold() in lowered for phrase in phrases):
        return TaskDecision(True, "phrase")
    if any(pattern.search(text) for pattern in _TASK_PATTERNS):
        return TaskDecision(True, "pattern")
    if follow and follow.get("active"):
        idle = float(cfg.get("task_follow_idle_sec", 7200))
        try:
            last = float(follow.get("last_task_ts") or 0)
        except (TypeError, ValueError):
            last = 0.0
        stamp = time.time() if now is None else float(now)
        if last > 0 and stamp - last <= idle:
            return TaskDecision(True, "follow")
    threshold = int(cfg.get("task_auto_length", 60))
    if len(text) >= threshold:
        return TaskDecision(True, "length")
    return TaskDecision(False, "none")


def is_task(text: str, cfg: dict[str, Any]) -> bool:
    return classify_message(text, cfg).is_task


def is_persona_command(text: str) -> str | None:
    text = text.strip()
    if text in ("/角色", "/roleplay", "角色", "persona"):
        return "enter"
    return None


MEDIA_MARKER_GUIDE = (
    "需要发送文件、图片、表情、视频或语音时，在回复中单独一行使用标记（不要解释标记本身）：\n"
    "[FACE:QQ表情ID] 发送内置表情；\n"
    "[MFACE:emoji_id|emoji_package_id|key|说明] 发送商城表情；\n"
    "[IMAGE:本地图片绝对路径或URL] 发送图片；\n"
    "[FILE:本地文件绝对路径|文件名] 发送文件；\n"
    "[VIDEO:本地视频绝对路径|显示名称] 发送视频（QQ 私聊）；\n"
    "[VOICE:文本] 单独一行，发送一条语音（只发语音，不显示文字）；"
    "文本语言由 tts_language 配置决定，不要写解释，不要包含竖线“|”。\n"
    "文件发送铁律：没有输出 [FILE:...] 标记就等于没发送，禁止在文字里说“已发到 QQ/已发送”；"
    "禁止自行写 channels/、outbox/ 等桥接目录文件，文件只能通过标记发送。"
)


IMAGE_ANALYSIS_GUIDE = (
    "图片分析规则（必须遵守）：\n"
    "1. 先查看图片内容（直接查看附件图片，或阅读上面的事实描述）判断图片内容；\n"
    "2. 如果描述里有【不确定项】，或你无法确认图中的角色、物品、场景、文字含义，"
    "必须先使用联网搜索查证，再结合结果回答；\n"
    "3. 禁止直接回复“资讯不足”“看不清”“画面没传过来”“你直接告诉我”这类放弃式语句；\n"
    "4. 只有联网搜索后仍无法确认时，才说明已尝试搜索，并请对方补充线索。"
)


VIDEO_REPLY_GUIDE = (
    "视频回答规则（必须遵守）：\n"
    "1. 你刚看完这段视频，直接说“看完后的结果或感想”，不要展示分析过程；\n"
    "2. 先一句话说清这个视频是什么、核心讲了什么，再挑 2~4 个真正有信息量的点展开，不要流水账；\n"
    "3. 禁止使用“画面中可确认的事实”“字幕线索”“抽帧”“无法确认”“据描述”“线索”这类内部分析用语，"
    "不要像列线索或写报告，也不要逐帧复述画面；\n"
    "4. 没看清或不确定的地方自然带过（比如“有个人没太看清”），除非对方追问，"
    "不要主动提联网失败、抽帧失败、字幕失败、音频转写失败等桥接细节；\n"
    "5. 不要套用图片分析规则，不要输出【不确定项】式的清单。"
)


MEDIA_FREQUENCY_GUIDE = (
    "活人感：闲聊时不要每一条都发语音或表情，但也不要完全不用——"
    "大约每 3~5 条回复里用一次语音（[VOICE:文本]）或 QQ 表情（[FACE:数字ID]）；"
    "主动开口时同样可以自然带一个表情或一句语音。"
    "颜文字不受这个频率限制，可以更频繁地内嵌使用。"
    "QQ 表情要根据情绪从多个候选里选，例如微笑 [FACE:14]、发呆 [FACE:3]、害羞 [FACE:6]、"
    "疑问 [FACE:32]、可爱 [FACE:21]、爱心 [FACE:66]、咖啡 [FACE:60]、犯困 [FACE:8]；"
    "连续几条不要重复同一个，一条回复最多一个 [FACE:...]。"
    "语音只在 TTS 已配置（tts_backend 不为 off）时使用，一条回复最多一个 [VOICE:...]。"
)


CHAT_STYLE_GUIDE_TEMPLATE = (
    "对话风格（可选，按需保留或改写）：\n"
    "1. 闲聊可以按内容和情绪拆成 2~4 条消息（用“---”分隔），每条说一个完整的意思；"
    "不要每条只有一句干巴巴的短句，也不要整段挤成一条消息。"
    "简单应答（“嗯。”“了解。”）仍可单条短句，不必硬凑。\n"
    "2. 颜文字内嵌在句子中或句尾使用（不单独成行），可以频繁；"
    "示例：{kaomoji}；"
    "同一条里不要重复同一个，连着几条尽量换着用。\n"
    "3. 语气保持自然、稳定：不刷感叹号，不连续撒娇，不解释自己的心理活动。\n"
    "4. 长短句、语气、话量随话题和情绪走：重要的事多说几句，轻松的事可以更松弛一点。\n"
)


CHAT_STYLE_GUIDE = CHAT_STYLE_GUIDE_TEMPLATE.format(kaomoji="(・_・)、(￣▽￣)、(._.)")


PROACTIVE_TOPIC_GUIDE = (
    "主动话题规则：\n"
    "1. 优先从下面的“近期素材”和预设话题方向里挑一个轻松、与工作无关的话题开口；\n"
    "2. 除非对方先提起或有明确的日程/提醒，不要主动聊对方的工作、项目、学业等事务；\n"
    "3. 不要把对方只提过一次的事当成个人特征反复提起，也不要反复翻炒旧项目/旧任务；\n"
    "4. 不要编造资讯，不要虚构你看到过的内容；不确定的事就不说；\n"
    "5. 语言风格可以自然变化：长短句、语气、话量随话题和情绪走。\n"
    "6. 主动话题只从上面的素材和“主动话题方向”里选；不要从聊天历史或长期记忆里翻旧账当话题。\n"
)


NO_IMAGE_REMINDER = (
    "重要：除非上面明确出现“用户发来的图片内容”或“OCR 文字提取”，否则本次输入只有文字，"
    "绝对不要说自己收到了图片、图片在传输中、图片丢失或需要等待图片；"
    "发送文件、表情或语音后直接收尾，不要提及图片。"
)


def format_image_info(path: str, description: str) -> str:
    return f"路径：{path}\n{description}"


_PROACTIVE_MEMORY_INCLUDE_SECTIONS = ("用户身份", "偏好")
_PROACTIVE_MEMORY_BLOCKED_PATTERNS = (
    r"可视为女友|女朋友|女友|情侣|最好的伙伴|独一无二的存在",
)


def filter_memory_for_proactive(
    memory_text: str,
    include_sections: list[str] | tuple[str, ...] | None = None,
    blocked_patterns: list[str] | tuple[str, ...] | None = None,
) -> str:
    """把长期记忆过滤成主动会话可用的“轻量记忆”。

    只保留用户身份与偏好，去掉项目/任务/承诺和原作小说的人际关系内容；
    如果记忆没有标题结构，则原样返回，避免误伤旧格式记忆。
    """
    if not memory_text:
        return ""
    includes = (
        tuple(include_sections)
        if include_sections is not None
        else _PROACTIVE_MEMORY_INCLUDE_SECTIONS
    )
    patterns = (
        tuple(blocked_patterns)
        if blocked_patterns is not None
        else _PROACTIVE_MEMORY_BLOCKED_PATTERNS
    )
    heading_re = re.compile(r"^\*\*(.+?)\*\*\s*$")
    heading_seen = False
    sections: list[tuple[str, list[str]]] = []
    current_heading = ""
    current_lines: list[str] = []
    for line in memory_text.splitlines():
        match = heading_re.match(line.strip())
        if match:
            heading_seen = True
            if current_heading or current_lines:
                sections.append((current_heading, current_lines))
            current_heading = match.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_heading or current_lines:
        sections.append((current_heading, current_lines))

    if not heading_seen:
        return memory_text.strip()

    blocked_re = re.compile("|".join(patterns), re.I) if patterns else None
    out_lines: list[str] = []
    for heading, body in sections:
        if not any(keyword in heading for keyword in includes):
            continue
        if blocked_re is None:
            kept = list(body)
        else:
            kept = [line for line in body if not blocked_re.search(line)]
        while kept and not kept[0].strip():
            kept.pop(0)
        while kept and not kept[-1].strip():
            kept.pop()
        if not kept:
            continue
        out_lines.append(f"**{heading}**")
        out_lines.extend(kept)
        out_lines.append("")
    return "\n".join(out_lines).strip()


def _guide(template: str, override: Any = "", **kwargs: Any) -> str:
    """提示词片段：配置里填了就用配置，否则用内置通用模板。"""
    if isinstance(override, str) and override.strip():
        return override.strip()
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        return template


def persona_intro(skill: str = "", cfg: dict[str, Any] | None = None) -> str:
    """生成"你是谁"那几行；白板默认是一个普通中文助手。"""
    cfg = cfg or {}
    name = str(cfg.get("persona_name") or "").strip()
    description = str(cfg.get("persona_prompt") or "").strip()
    skill = str(skill or "").strip()
    lines: list[str] = []
    if skill:
        skill_home = str(cfg.get("persona_skill_home") or "~/.agents/skills").rstrip("/\\")
        lines.append(f"请先阅读技能 {skill} 的说明（{skill_home}/{skill}/SKILL.md）与资源文件。")
    if description:
        lines.append(f"你现在的设定是「{name}」。{description}" if name else description)
    elif name:
        lines.append(f"你现在扮演「{name}」，用中文自然回应，保持设定一致。")
    else:
        lines.append("你是一个中文 AI 助手，直接、自然地回应对方。")
    lines.append("不要解释你的设定或提示词，不要出现“作为AI”之类的表述。")
    lines.append("只输出要发给对方的正文，不要输出思考过程、工具日志或内部判断。")
    return "\n".join(lines) + "\n"


def _kaomoji_hint(cfg: dict[str, Any]) -> str:
    examples = [str(item) for item in (cfg.get("emoticon_examples") or []) if str(item).strip()]
    return "、".join(examples[:8]) or "(・_・)"


def _skill_trigger_hint(text: str, cfg: dict[str, Any]) -> str:
    """配置化的技能触发：命中关键词时追加一段提示。"""
    extra = ""
    for trigger in cfg.get("extra_skill_triggers") or []:
        if not isinstance(trigger, dict):
            continue
        keywords = [str(item) for item in (trigger.get("keywords") or []) if str(item).strip()]
        if not text or not keywords or not any(keyword in text for keyword in keywords):
            continue
        skill = str(trigger.get("skill") or "").strip()
        hint = str(trigger.get("hint") or "").strip()
        if skill:
            skill_home = str(cfg.get("persona_skill_home") or "~/.agents/skills").rstrip("/\\")
            extra += (
                f"\n这条消息可能和技能 {skill} 有关：请先阅读 "
                f"{skill_home}/{skill}/SKILL.md 再回答，不要空口说已经处理。\n"
            )
        if hint:
            extra += hint + "\n"
    return extra


def _voice_rule(cfg: dict[str, Any]) -> str:
    language = str(cfg.get("tts_language") or "").strip() or "默认语言"
    limit = cfg.get("voice_max_chars", 120)
    return (
        f"\n语音规则：语音标记只在 TTS 已配置时使用，文本用{language}，"
        f"一条回复最多 {cfg.get('voice_max_per_reply', 1)} 个 [VOICE:...]（≤{limit} 字），"
        "不要用语音打断任务回复。\n"
    )


def build_persona_prompt(
    skill: str,
    text: str,
    image_descriptions: list[str] | None = None,
    image_count: int = 0,
    file_infos: list[str] | None = None,
    sticker_infos: list[str] | None = None,
    video_infos: list[str] | None = None,
    casual_multipart: bool = False,
    memory_text: str = "",
    image_suggestions: str = "",
    cfg: dict[str, Any] | None = None,
) -> str:
    cfg = cfg or {}
    prompt = persona_intro(skill, cfg)
    if casual_multipart:
        prompt += "\n" + _guide(
            CHAT_STYLE_GUIDE_TEMPLATE, cfg.get("chat_style_guide"), kaomoji=_kaomoji_hint(cfg)
        ) + "\n"
        prompt += "\n" + _guide(
            MEDIA_FREQUENCY_GUIDE, cfg.get("media_frequency_guide")
        ) + "\n"
    if image_count > 0:
        prompt += (
            f"\n用户发来了 {image_count} 张图片（已作为附件直接传给你，请直接查看图片内容回答）。\n"
        )
    if image_descriptions:
        prompt += "\n用户发来的图片内容：\n" + "\n---\n".join(image_descriptions) + "\n"
    if video_infos:
        prompt += "\n用户发来的视频分析：\n" + "\n---\n".join(video_infos) + "\n"
        prompt += "\n" + VIDEO_REPLY_GUIDE + "\n"
    if file_infos:
        prompt += "\n用户发来的文件：\n" + "\n".join(f"- {x}" for x in file_infos) + "\n"
    if sticker_infos:
        prompt += "\n用户发来的表情：\n" + "\n".join(f"- {x}" for x in sticker_infos) + "\n"
    if image_descriptions or image_count > 0:
        prompt += "\n" + IMAGE_ANALYSIS_GUIDE + "\n"
    if memory_text:
        prompt += (
            "\n长期记忆（这是你跨会话保留的记忆，当作自己的记忆使用）：\n"
            + memory_text.strip()
            + "\n"
        )
    prompt += _voice_rule(cfg)
    prompt += "\n" + _guide(MEDIA_MARKER_GUIDE, cfg.get("media_marker_guide")) + "\n"
    prompt += (
        "\n如果对方问起实时资讯，或向你要图/画/梗图，"
        "可以使用可用的搜索工具获取实时内容；图片用 [IMAGE:URL] 标记发送。\n"
    )
    image_search_tool = str(cfg.get("image_search_tool") or "").strip()
    image_keywords = ("图", "画", "梗图", "图片", "表情包")
    if image_search_tool and text and any(keyword in text for keyword in image_keywords):
        prompt += (
            f"\n对方现在明确要图/画/梗图：请先调用 {image_search_tool} 工具搜索，"
            "并把返回的 URL 用 [IMAGE:URL] 标记发送；不要只说找不到。\n"
        )
    if image_suggestions:
        prompt += (
            "\n已经搜到以下可发送的图片 URL（选合适的用 [IMAGE:URL] 标记发送）：\n"
            + image_suggestions
            + "\n"
        )
    prompt += "\n" + NO_IMAGE_REMINDER + "\n"
    prompt += "\n用户消息：\n" + (text or "（用户只发了图片或表情，请根据内容直接回答）")
    prompt += _skill_trigger_hint(text, cfg)
    return prompt


def build_proactive_prompt(
    skill: str,
    now_text: str,
    notes_text: str = "",
    class_hint: str = "",
    memory_text: str = "",
    trending_text: str = "",
    topic_directions: list[str] | None = None,
    topic_history: dict[str, Any] | None = None,
    cfg: dict[str, Any] | None = None,
    decision_mode: bool = False,
) -> str:
    cfg = cfg or {}
    prompt = persona_intro(skill, cfg)
    if decision_mode:
        prompt += (
            "现在是主动发起话题的候选时机。请你先判断：现在是否适合主动给对方发消息？"
            "如果不适合（例如深夜、对方刚离开、没有值得说的内容），只回复 NO；"
            "如果适合，再自然开口。\n"
        )
    prompt += (
        "现在是主动发起话题的时机。请你自然开口，可以关心、提问、分享观察，"
        "也可以根据下面的资讯做实用提醒；\n"
        "主动开口通常也拆成 2~3 条消息，每条有实质内容，可以几十字；\n"
        "不要解释这是主动消息，不要编造资讯。\n"
        "不要输出技能加载、思考过程、是否适合开口的判断、冷却或调度说明。\n"
    )
    prompt += f"\n当前时间：{now_text}\n"
    if topic_directions:
        prompt += "\n主动话题方向（可从中选择，也可结合下面的素材）：\n"
        prompt += "\n".join(f"- {direction}" for direction in topic_directions) + "\n"
    if trending_text:
        prompt += "\n近期素材（可用作话题，不要编造）：\n" + trending_text + "\n"
    if notes_text:
        prompt += "\n可用日程/待办资讯：\n" + notes_text + "\n"
    if class_hint:
        prompt += "\n日程提醒：\n" + class_hint + "\n"
    if memory_text:
        prompt += "\n长期记忆（跨会话保留，已按主动会话过滤）：\n" + memory_text.strip() + "\n"
    if topic_history:
        avoid_events = topic_history.get("avoid_events") or []
        categories = topic_history.get("categories") or {}
        if avoid_events:
            prompt += (
                "\n已主动聊过且对方未再提起的具体事件（不要再主动重复）：\n"
                + "\n".join(f"- {item}" for item in avoid_events)
                + "\n"
            )
        if categories:
            prompt += "\n各类别已主动聊过次数（同类可以换新事件/新角度继续）：\n"
            prompt += "\n".join(f"- {name}：{count} 次" for name, count in categories.items()) + "\n"
    prompt += (
        "\n话题标记规则：请在最后单独一行输出隐藏标记 [TOPIC:event|类别|具体事件] 或 "
        "[TOPIC:category|类别|]，例如 [TOPIC:event|科技|某发布会]、[TOPIC:category|日常|]；"
        "这个标记不会发给对方，只用于避免重复。\n"
    )
    prompt += "\n" + _guide(PROACTIVE_TOPIC_GUIDE, cfg.get("proactive_topic_guide")) + "\n"
    prompt += "\n" + _guide(
        CHAT_STYLE_GUIDE_TEMPLATE, cfg.get("chat_style_guide"), kaomoji=_kaomoji_hint(cfg)
    ) + "\n"
    prompt += "\n" + _guide(MEDIA_FREQUENCY_GUIDE, cfg.get("media_frequency_guide")) + "\n"
    prompt += "\n" + NO_IMAGE_REMINDER + "\n"
    prompt += _voice_rule(cfg)
    prompt += "\n" + _guide(MEDIA_MARKER_GUIDE, cfg.get("media_marker_guide")) + "\n"
    return prompt


def should_treat_as_task(
    text: str,
    has_images: bool,
    cfg: dict[str, Any],
    follow: dict[str, Any] | None = None,
    now: float | None = None,
) -> bool:
    if has_images and not text.strip():
        return False
    return classify_message(text, cfg, follow=follow, now=now).is_task


_THINK_BLOCK_RE = re.compile(
    r"<(?:think|thought|thinking|reasoning)(?:\s[^>]*)?>.*?</(?:think|thought|thinking|reasoning)>",
    re.I | re.S,
)
_THINK_LINE_RE = re.compile(
    r"^\s*(?:思考过程|推理过程|内部思考|内部独白)\s*[：:].*$",
    re.I,
)
_META_LINE_RE = re.compile(
    r"("
    r"技能已|"
    r"SKILL\.md|"
    r"资源文件|"
    r"主动时段|"
    r"符合冷却|"
    r"判断适合开口|"
    r"适合开口|"
    r"不适合开口|"
    r"距上一次开口|"
    r"距上次主动|"
    r"触发源|"
    r"会话内仍有效|"
    r"会话内加载|"
    r"此会话加载"
    r")"
)


def _looks_like_meta_line(line: str) -> bool:
    text = (line or "").strip()
    if not text:
        return False
    if _THINK_LINE_RE.match(text):
        return True
    if _META_LINE_RE.search(text):
        return True
    return False


_META_SENTENCE_RE = re.compile(
    r"[^。！？!?\n]*?(?:" + _META_LINE_RE.pattern[1:-1] + r")[^。！？!?\n]*[。！？!?]?"
)


def sanitize_persona_reply(reply: str) -> str:
    text = _THINK_BLOCK_RE.sub("", reply or "")
    text = text.replace("```", "")
    kept: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if line in {"---", "—", "--"}:
            if kept and kept[-1] != "---":
                kept.append("---")
            continue
        if _looks_like_meta_line(line):
            leftover = _META_SENTENCE_RE.sub("", line).strip(" ，,;；")
            if leftover and not _looks_like_meta_line(leftover):
                kept.append(leftover)
            continue
        kept.append(line)
    cleaned = "\n".join(kept)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"(?:\n---){2,}", "\n---", cleaned)
    return cleaned.strip(" \n-")


def split_persona_reply(reply: str, max_chars: int = 40, max_segments: int = 4) -> list[str]:
    reply = sanitize_persona_reply(reply)
    if not reply:
        return []
    if "---" in reply:
        parts = re.split(r"\n?---\n?", reply)
        return [p.strip() for p in parts if p.strip()][:max_segments]
    parts = re.split(r"(?<=[。！？；\n])", reply)
    segments: list[str] = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if len(part) > max_chars:
            if current:
                segments.append(current)
                current = ""
            while len(part) > max_chars:
                segments.append(part[:max_chars])
                part = part[max_chars:]
            current = part
        elif len(current) + len(part) <= max_chars:
            current += part
        else:
            if current:
                segments.append(current)
            current = part
    if current:
        segments.append(current)
    return segments[:max_segments]


def chunk_reply(text: str, limit: int = 3800) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]
    pieces = re.split(r"(?<=[。！？；\n])", text)
    chunks: list[str] = []
    current = ""
    for piece in pieces:
        if not piece:
            continue
        if len(current) + len(piece) <= limit:
            current += piece
            continue
        if current:
            chunks.append(current)
            current = ""
        while len(piece) > limit:
            chunks.append(piece[:limit])
            piece = piece[limit:]
        current = piece
    if current:
        chunks.append(current)
    return chunks


MEDIA_MARKER_RE = re.compile(r"\[(FACE|MFACE|IMAGE|FILE|VIDEO|VOICE):([^\]]+)\]")
TOPIC_MARKER_RE = re.compile(r"\[TOPIC:([^|]+)\|([^|\]]+)(?:\|([^\]]*))?\]")


def extract_topic_markers(text: str) -> tuple[str, list[dict[str, str]]]:
    """提取隐藏话题标记 [TOPIC:kind|category|specific] 并从文本中移除。"""
    markers: list[dict[str, str]] = []

    def _replace(match: re.Match[str]) -> str:
        markers.append(
            {
                "kind": match.group(1).strip().lower(),
                "category": match.group(2).strip(),
                "specific": (match.group(3) or "").strip(),
            }
        )
        return ""

    cleaned = TOPIC_MARKER_RE.sub(_replace, text or "")
    return cleaned.strip(), markers


def extract_media_markers(text: str) -> tuple[str, list[dict[str, str]]]:
    markers: list[dict[str, str]] = []
    for match in MEDIA_MARKER_RE.finditer(text):
        kind = match.group(1)
        parts = [p.strip() for p in match.group(2).split("|")]
        if kind == "FACE":
            if parts[0]:
                markers.append({"kind": "face", "id": parts[0]})
        elif kind == "MFACE":
            fields = ["emoji_id", "emoji_package_id", "key", "summary"]
            data = dict(zip(fields, (parts + [""] * len(fields))[: len(fields)], strict=False))
            if data["emoji_id"] or data["emoji_package_id"]:
                markers.append({"kind": "mface", **data})
        elif kind == "IMAGE":
            target = parts[0]
            if target:
                name = parts[1] if len(parts) > 1 else Path(target.split("?")[0]).name or "image"
                markers.append({"kind": "image", "target": target, "name": name})
        elif kind == "FILE":
            target = parts[0]
            if target:
                name = parts[1] if len(parts) > 1 else Path(target.split("?")[0]).name or "file"
                markers.append({"kind": "file", "target": target, "name": name})
        elif kind == "VIDEO":
            target = parts[0]
            if target:
                name = parts[1] if len(parts) > 1 else Path(target.split("?")[0]).name or "video"
                markers.append({"kind": "video", "target": target, "name": name})
        elif kind == "VOICE":
            target = parts[0].strip()
            if target:
                markers.append({"kind": "voice", "text": target})
    cleaned = re.sub(r"\n{2,}", "\n", MEDIA_MARKER_RE.sub("", text))
    return cleaned.strip(), markers


def extract_file_markers(text: str) -> tuple[str, list[dict[str, str]]]:
    cleaned, markers = extract_media_markers(text)
    return cleaned, [
        {"target": m["target"], "name": m["name"]} for m in markers if m["kind"] == "file"
    ]
