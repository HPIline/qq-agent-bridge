"""QQ 消息处理主流程：命令、任务判定、媒体描述、Codex 调用、回复发送。"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any

import commands_impl  # noqa: F401  确保命令装饰器注册到全局 registry
from agent_client import AgentError
from astrbot_plugins import dispatch_plugins
from call_policy import resolve_policy, run_with_policy
from command_registry import registry
from image_utils import download_images
from media import download_incoming_image, download_incoming_video
from message_utils import (
    IMAGE_ANALYSIS_GUIDE,
    MEDIA_MARKER_GUIDE,
    VIDEO_REPLY_GUIDE,
    build_persona_prompt,
    classify_message,
    format_image_info,
    is_persona_command,
    sanitize_persona_reply,
)
from pdf_utils import extract_pdf_text
from reply_sender import send_reply
from timetable import format_preview, load_timetable, parse_csv, parse_xlsx, save_timetable
from video_utils import (
    build_videoshot_from_frames,
    build_videoshot_index,
    cleanup_video_cache,
    download_video_from_link_with_subtitles,
    extract_audio,
    extract_frames,
    extract_subtitles,
    extract_video_links,
    probe_video,
    transcribe_audio,
)
from vision_client import (
    build_vision_prompt,
    describe_image,
    extract_timetable_text,
    vision_settings,
)


def _build_work_prompt(
    text: str,
    image_paths: list[str],
    descriptions: list[str],
    file_infos: list[str],
    sticker_infos: list[str],
    video_infos: list[str] | None = None,
) -> str:
    prompt = "[普通工作模式] 你是对方的工作助理。直接回答问题，不要角色扮演。\n"
    if image_paths:
        prompt += (
            "\n用户发来的图片（已作为附件直接传给你，请直接查看图片回答）：\n"
            + "\n".join(f"- {Path(p).name}" for p in image_paths)
            + "\n"
        )
        prompt += "\n" + IMAGE_ANALYSIS_GUIDE + "\n"
    elif descriptions:
        prompt += "\n用户发来的图片内容：\n" + "\n---\n".join(descriptions) + "\n"
        prompt += "\n" + IMAGE_ANALYSIS_GUIDE + "\n"
    if video_infos:
        prompt += "\n用户发来的视频分析：\n" + "\n---\n".join(video_infos) + "\n"
        prompt += "\n" + VIDEO_REPLY_GUIDE + "\n"
    if file_infos:
        prompt += "\n用户发来的文件：\n" + "\n".join(f"- {x}" for x in file_infos) + "\n"
    if sticker_infos:
        prompt += "\n用户发来的表情：\n" + "\n".join(f"- {x}" for x in sticker_infos) + "\n"
    prompt += "\n" + MEDIA_MARKER_GUIDE + "\n"
    prompt += "\n用户消息：\n" + (text or "（用户只发了图片、视频或表情，请根据内容直接回答）")
    return prompt


def _format_video_timestamp(duration: float, index: int, count: int) -> str:
    if duration <= 0:
        return f"第{index + 1}/{count}帧"
    seconds = duration * (index + 0.5) / count
    return f"{int(seconds // 60):02d}:{int(seconds % 60):02d}"


def _build_video_frame_prompt(video_name: str, index: int, count: int) -> str:
    return (
        f"这是用户发来的视频《{video_name}》中按时间均匀抽取的第 {index + 1}/{count} 帧。"
        "你是视频画面扫描器，只描述这一帧里的事实：主体与数量、人物/生物、动作与表情、"
        "文字内容（逐字）、颜色布局、可辨认标识。"
        "无法确认身份/名称/含义的内容写进【不确定项】，不要瞎猜，控制在 500 字以内。"
    )


async def _analyze_video(bridge: Any, video: dict[str, str], index: int = 0) -> str:
    """下载并分析一个视频，返回给 Codex 看的文本块。"""
    try:
        vpath = await download_incoming_video(bridge, video)
    except Exception as exc:
        logging.warning("视频下载失败：%s", exc)
        return f"（视频下载失败：{exc}）"
    name = str(video.get("name") or Path(vpath).name)
    return await _analyze_video_path(bridge, vpath, name, index)


async def _analyze_video_path(
    bridge: Any,
    vpath: str,
    name: str,
    index: int = 0,
    external_subtitles: str = "",
) -> str:
    """分析一个本地视频文件，返回给 Codex 看的文本块。

    视频文件和抽帧目录在分析完成后立即清理；视频文件在每次处理结束后删除，
    只保留拼好的文本结果，避免 tmp/incoming 无限膨胀。
    """
    frame_dir = bridge.tmp_dir / "video_frames" / f"video_{index}_{time.time_ns()}"
    frame_dir.mkdir(parents=True, exist_ok=True)
    try:
        return await _analyze_video_path_inner(
            bridge, vpath, name, index, frame_dir, external_subtitles
        )
    finally:
        # 每次处理完就删：先删抽帧/音频/雪碧图目录，再删下载的视频本体。
        shutil.rmtree(frame_dir, ignore_errors=True)
        try:
            Path(vpath).unlink(missing_ok=True)
            logging.info("已清理视频文件：%s", vpath)
        except Exception as exc:
            logging.warning("清理视频文件失败：%s %s", vpath, exc)
        try:
            await asyncio.to_thread(cleanup_video_cache, bridge.tmp_dir)
        except Exception:
            pass


async def _collect_video_transcripts(
    bridge: Any,
    vpath: str,
    frame_dir: Path,
    external_subtitles: str = "",
) -> tuple[str, str, str]:
    subtitle_text = ""
    if external_subtitles.strip():
        subtitle_text = external_subtitles.strip()
    elif bridge.cfg.get("video_subtitle_enabled", True):
        try:
            subtitle_text = await extract_subtitles(
                vpath,
                frame_dir,
                cfg=bridge.cfg,
                max_chars=int(bridge.cfg.get("video_subtitle_max_chars", 4000)),
            )
        except Exception as exc:
            logging.warning("视频字幕导出失败：%s", exc)

    asr_text = ""
    asr_note = ""
    if bridge.cfg.get("video_asr_enabled", True):
        if subtitle_text and bridge.cfg.get("video_asr_skip_if_subtitles", True):
            asr_note = "已有字幕，跳过音频转写"
        else:
            try:
                audio_path = await extract_audio(vpath, frame_dir, bridge.cfg)
                if audio_path:
                    asr_text = await transcribe_audio(
                        audio_path,
                        model=str(bridge.cfg.get("video_asr_model", "whisper-turbo")),
                        language=str(bridge.cfg.get("video_asr_language") or "") or None,
                        timeout=int(bridge.cfg.get("video_asr_timeout", 600)),
                        backend=str(bridge.cfg.get("video_asr_backend", "auto")),
                    )
            except Exception as exc:
                logging.warning("视频音频转写失败：%s", exc)
    return subtitle_text, asr_text, asr_note


async def _describe_video_frames(
    bridge: Any,
    name: str,
    frame_dir: Path,
    frames: list[str],
    duration: float,
) -> tuple[str, str] | None:
    if not frames:
        return None
    try:
        await build_videoshot_from_frames(
            frames,
            frame_dir,
            cols=int(bridge.cfg.get("video_shot_cols", 5)),
            rows=int(bridge.cfg.get("video_shot_rows", 2)),
            thumb_width=int(bridge.cfg.get("video_shot_thumb_width", 160)),
            thumb_height=int(bridge.cfg.get("video_shot_thumb_height", 90)),
            cfg=bridge.cfg,
        )
    except Exception as exc:
        logging.warning("生成视频雪碧图失败：%s", exc)
    frame_index = build_videoshot_index(duration, len(frames))
    descriptions: list[str] = []
    frame_settings = vision_settings(bridge.cfg)
    for i, frame_path in enumerate(frames):
        desc = await describe_image(
            frame_path,
            frame_settings.url,
            frame_settings.model,
            api_key=frame_settings.api_key,
            timeout=frame_settings.timeout,
            max_tokens=frame_settings.max_tokens,
            prompt=_build_video_frame_prompt(name, i, len(frames)),
        )
        stamp = _format_video_timestamp(duration, i, len(frames))
        sec = frame_index[i] if i < len(frame_index) else stamp
        descriptions.append(f"[{stamp} / {sec}s] {desc}")
    return "\n".join(descriptions), str(frame_index)


async def _analyze_video_path_inner(
    bridge: Any,
    vpath: str,
    name: str,
    index: int,
    frame_dir: Path,
    external_subtitles: str = "",
) -> str:
    duration = 0.0
    frames: list[str] = []
    try:
        info = await probe_video(vpath, bridge.cfg)
        duration = float(info.get("duration") or 0.0)
        frames = await extract_frames(
            vpath,
            frame_dir,
            count=int(bridge.cfg.get("video_max_frames", 8)),
            max_width=int(bridge.cfg.get("video_max_width", 1280)),
            cfg=bridge.cfg,
        )
    except Exception as exc:
        logging.warning("视频抽帧失败：%s", exc)
        frames = []

    subtitle_text, asr_text, asr_note = await _collect_video_transcripts(
        bridge, vpath, frame_dir, external_subtitles
    )

    parts = [f"视频文件：{name}"]
    if duration > 0:
        parts.append(f"时长：约 {duration:.0f} 秒")
    if subtitle_text:
        parts.append(f"字幕：\n{subtitle_text}")
    else:
        parts.append("字幕：（无字幕轨或导出失败）")
    if asr_text:
        parts.append(f"音频转写：\n{asr_text}")
    else:
        parts.append(f"音频转写：（{asr_note or '无音轨或转写失败'}）")
    frame_summary = await _describe_video_frames(bridge, name, frame_dir, frames, duration)
    if frame_summary:
        descriptions, frame_index = frame_summary
        parts.append("抽帧画面描述：\n" + descriptions)
        parts.append(f"帧时间表（秒，videoshot.index）：{frame_index}")
    else:
        parts.append("抽帧画面描述：（抽帧失败，无法提供画面）")
    return "\n".join(parts)


async def _collect_link_videos(bridge: Any, text: str) -> tuple[list[dict[str, str]], list[str]]:
    link_videos: list[dict[str, str]] = []
    link_video_errors: list[str] = []
    if bridge.cfg.get("video_link_parse_enabled", True) and text:
        for link in extract_video_links(text):
            logging.info("识别到视频链接：%s", link)
            try:
                vpath, subs = await download_video_from_link_with_subtitles(
                    link, bridge.incoming_dir, bridge.cfg
                )
                name = Path(link.split("?")[0]).name or "视频链接"
                link_videos.append(
                    {
                        "path": vpath,
                        "name": name,
                        "url": link,
                        "file": "",
                        "subtitles": subs,
                    }
                )
            except Exception as exc:
                logging.warning("视频链接下载失败：%s %s", link, exc)
                link_video_errors.append(f"链接 {link} 下载失败：{exc}")
    return link_videos, link_video_errors


async def _collect_images(
    bridge: Any,
    buf: Any,
    native_vision: bool,
    text: str,
) -> tuple[list[str], list[str]]:
    image_paths: list[str] = []
    descriptions: list[str] = []
    for image in buf.images:
        logging.info("收到图片：%s", image["url"])
        try:
            path = await download_incoming_image(bridge, image)
        except Exception as exc:
            logging.warning("图片下载失败：%s", exc)
            descriptions.append(f"（图片下载失败：{exc}）")
            continue
        logging.info("图片下载完成：%s", path)
        if native_vision:
            image_paths.append(path)
            logging.info("原生多模态：图片直接附加给 Codex：%s", path)
        else:
            started = time.monotonic()
            description = await bridge._describe_image(path, text)
            logging.info(
                "图片识别完成，耗时 %.1fs：%s",
                time.monotonic() - started,
                description[:200],
            )
            descriptions.append(format_image_info(path, description))
    return image_paths, descriptions


async def _collect_video_infos(bridge: Any, all_videos: list[dict[str, str]]) -> list[str]:
    video_infos: list[str] = []
    if not bridge.cfg.get("video_analysis_enabled", True):
        return video_infos
    for index, video in enumerate(all_videos):
        if video.get("error"):
            video_infos.append(f"（视频链接处理失败：{video['error']}）")
            continue
        logging.info("分析视频：%s", video.get("url") or video.get("path") or video.get("file"))
        try:
            if video.get("path"):
                info = await _analyze_video_path(
                    bridge,
                    video["path"],
                    str(video.get("name") or "视频"),
                    index,
                    external_subtitles=str(video.get("subtitles") or ""),
                )
            else:
                info = await _analyze_video(bridge, video, index)
            video_infos.append(info)
            logging.info("视频分析完成：%s", info[:200])
        except Exception as exc:
            logging.warning("视频分析失败：%s", exc)
            video_infos.append(f"（视频分析失败：{exc}）")
    return video_infos


async def _collect_file_infos(bridge: Any, buf: Any) -> list[str]:
    file_infos: list[str] = []
    for file in buf.files:
        logging.info("收到文件：%s", file)
        try:
            path = await bridge._download_incoming_file(file)
            size = Path(path).stat().st_size
            info = f"{path}（{file.get('name') or Path(path).name}，{size} 字节）"
            if bridge.cfg.get("pdf_ocr_enabled", True) and Path(path).suffix.lower() == ".pdf":
                try:
                    text = await extract_pdf_text(
                        path,
                        max_pages=int(bridge.cfg.get("pdf_ocr_max_pages", 10)),
                        timeout=int(bridge.cfg.get("pdf_ocr_timeout_sec", 120)),
                    )
                    if text:
                        max_chars = int(bridge.cfg.get("pdf_ocr_max_chars", 4000))
                        info += f"\nPDF文字提取：\n{text[:max_chars]}"
                        logging.info("PDF OCR 提取 %d 字", min(len(text), max_chars))
                except Exception as exc:
                    logging.warning("PDF OCR 失败：%s", exc)
            file_infos.append(info)
        except Exception as exc:
            logging.warning("文件下载失败：%s", exc)
            file_infos.append(f"（文件下载失败：{exc}）")
    return file_infos


def _collect_sticker_infos(buf: Any) -> list[str]:
    sticker_infos: list[str] = []
    for face in buf.faces:
        sticker_infos.append(f"QQ表情：{face['id']}")
    for mface in buf.mfaces:
        sticker_infos.append(
            "商城表情：{}|{}|{}|{}".format(
                mface["emoji_id"],
                mface["emoji_package_id"],
                mface["key"],
                mface["summary"],
            )
        )
    return sticker_infos


async def process_buffer_impl(bridge: Any, user_id: str, buf: Any) -> None:
    with bridge.store.batch():
        text = buf.compose()
        if bridge._pending_task_stage_waiting():
            await bridge._send_private(user_id, "……任务阶段等待确认中，先回‘继续’或‘停止’。")
            return
        persona_mode = bool(bridge.cfg.get("persona_enabled", True))
        persona_command = is_persona_command(text)
        if persona_command == "enter":
            bridge.store.set_persona(user_id, True)
            await bridge._send_private(user_id, "……了解。")
            return
        cmd_match = registry.match(text)
        if cmd_match is not None:
            await cmd_match.handler(bridge, user_id, cmd_match.args_str)
            return
        if user_id in bridge.timetable_mode_users:
            if buf.images or buf.files:
                await ingest_timetable(bridge, user_id, buf)
                return
            if text:
                pending = bridge.timetable_pending.get(user_id)
                if pending is not None:
                    if text.startswith("确认") or text in ("好的", "好", "可以"):
                        try:
                            save_timetable(bridge.timetable_path, pending)
                        except Exception as exc:
                            await bridge._send_private(user_id, f"保存失败：{exc}")
                            return
                        state = bridge.store.get_proactive_state(user_id)
                        state["reminded_classes"] = []
                        bridge.store.save_proactive_state(user_id, state)
                        bridge.timetable_pending.pop(user_id, None)
                        bridge.timetable_mode_users.discard(user_id)
                        await bridge._send_private(user_id, "已保存。")
                        return
                    if text.startswith("取消") or text in ("不要", "算了"):
                        bridge.timetable_pending.pop(user_id, None)
                        bridge.timetable_mode_users.discard(user_id)
                        await bridge._send_private(user_id, "……好。")
                        return
                bridge.timetable_pending.pop(user_id, None)
                bridge.timetable_mode_users.discard(user_id)

        if bridge.cfg.get("plugins_enabled", True) and bridge.astrbot_plugins:
            outcome = await dispatch_plugins(bridge, user_id, buf, text)
            if outcome == "stop":
                return

        raw_has_media = (
            bool(buf.images)
            or bool(buf.videos)
            or bool(buf.files)
            or bool(buf.faces)
            or bool(buf.mfaces)
        )
        follow = bridge.store.get_task_follow(user_id)
        if raw_has_media and not text.strip():
            task_mode = False
            reason = "image_only"
        else:
            decision = classify_message(text, bridge.cfg, follow=follow)
            task_mode = decision.is_task
            reason = decision.reason
        logging.info("任务判定：%s task=%s reason=%s", user_id, task_mode, reason)
        if task_mode:
            bridge.store.mark_task_follow(user_id)
        ack_lines = (
            bridge.cfg.get("persona_ack_lines", ["了解。", "我会处理。"])
            if persona_mode
            else bridge.cfg.get("task_ack_lines", ["收到，我先看下"])
        )
        if task_mode:
            for line in ack_lines:
                await bridge._send_private(user_id, line)
                await asyncio.sleep(float(bridge.cfg.get("ack_delay_sec", 0.8)))

        link_videos, link_video_errors = await _collect_link_videos(bridge, text)
        all_videos = list(buf.videos) + link_videos

        image_paths, descriptions = await _collect_images(
            bridge, buf, bool(bridge.cfg.get("vision_native", True)), text
        )

        video_infos = await _collect_video_infos(bridge, all_videos)
        for error in link_video_errors:
            video_infos.append(f"（{error}）")

        file_infos = await _collect_file_infos(bridge, buf)
        sticker_infos = _collect_sticker_infos(buf)

        if (
            buf.images
            and not buf.videos
            and not text.strip()
            and not image_paths
            and descriptions
            and all(str(desc).startswith("（图片下载失败") for desc in descriptions)
        ):
            await bridge._send_private(user_id, "图片下载失败了，再发一次试试？")
            return
        if (
            all_videos
            and not buf.images
            and not text.strip()
            and video_infos
            and all(str(info).startswith("（视频") for info in video_infos)
        ):
            await bridge._send_private(user_id, "视频下载失败了，再发一次试试？")
            return

        if persona_mode:
            await bridge._maybe_rotate_persona(user_id)
            image_suggestions = ""
            if text and any(k in text for k in ("图", "画", "梗图", "图片", "新作", "表情包")):
                try:
                    from trending import format_trending_context, run_search_from_cfg

                    timeout = float(bridge.cfg.get("image_search_timeout_sec", 45))
                    data = await asyncio.to_thread(
                        run_search_from_cfg, bridge.cfg, text, True, timeout
                    )
                    image_urls = data.get("image_urls") or []
                    local_images = await asyncio.to_thread(
                        download_images,
                        image_urls,
                        bridge.tmp_dir / "grok_images",
                        3,
                        20,
                    )
                    if not local_images:
                        # grok 外链图不可下载时，退回国内可直连的 cn.bing 图源
                        from cn_search import search_cn_images

                        domestic_urls = await asyncio.to_thread(search_cn_images, text, 15)
                        local_images = await asyncio.to_thread(
                            download_images,
                            domestic_urls,
                            bridge.tmp_dir / "grok_images",
                            3,
                            20,
                        )
                    if local_images:
                        described: list[tuple[str, str]] = []
                        picker_settings = vision_settings(bridge.cfg)
                        for path in local_images:
                            desc = await describe_image(
                                path,
                                picker_settings.url,
                                picker_settings.model,
                                api_key=picker_settings.api_key,
                                timeout=picker_settings.timeout,
                                max_tokens=min(picker_settings.max_tokens, 800),
                                prompt=(
                                    f"用一句话描述这张图片内容，并判断它是否与用户请求"
                                    f"「{text}」相关。只输出：描述；相关/不相关"
                                ),
                            )
                            described.append((path, desc))
                        relevant = [
                            (p, d) for p, d in described
                            if "不相关" not in d and "无关" not in d
                        ]
                        if not relevant:
                            relevant = described
                        lines = [
                            "已下载可发送的图片（已做图像识别，选相关的用 [IMAGE:本地路径] 发送）："
                        ]
                        for path, desc in relevant:
                            lines.append(f"- {path}\n  识别：{desc[:150]}")
                        image_suggestions = "\n".join(lines)
                    else:
                        image_suggestions = format_trending_context(data, include_images=True)
                except Exception:
                    image_suggestions = ""
            prompt = build_persona_prompt(
                bridge.cfg.get("persona_skill", ""),
                text,
                descriptions,
                image_count=len(image_paths),
                file_infos=file_infos,
                sticker_infos=sticker_infos,
                video_infos=video_infos or None,
                casual_multipart=not task_mode,
                memory_text=bridge._read_memory(),
                image_suggestions=image_suggestions,
                cfg=bridge.cfg,
            )
            thread_id = bridge.store.get_persona_thread(user_id)
        else:
            prompt = _build_work_prompt(
                text,
                image_paths,
                descriptions,
                file_infos,
                sticker_infos,
                video_infos=video_infos or None,
            )
            thread_id = bridge.store.get_thread(user_id)
        try:
            reply, new_thread_id = await run_with_policy(
                bridge,
                prompt,
                thread_id,
                resolve_policy(bridge.cfg, "task" if task_mode else "casual"),
                image_paths=image_paths or None,
            )
        except AgentError as exc:
            fallback_model = str(bridge.cfg.get("fallback_model") or "").strip()
            fallback_enabled = bool(bridge.cfg.get("fallback_enabled", True))
            task_stage_timeout = (
                task_mode
                and bridge.cfg.get("task_stage_enabled", True)
                and getattr(exc, "timeout", False)
            )
            if fallback_enabled and fallback_model and (image_paths or not task_stage_timeout):
                fallback_descriptions = list(descriptions)
                fallback_settings = vision_settings(bridge.cfg)
                for path in image_paths:
                    description = await describe_image(
                        path,
                        fallback_settings.url,
                        fallback_settings.model,
                        api_key=fallback_settings.api_key,
                        timeout=fallback_settings.timeout,
                        max_tokens=fallback_settings.max_tokens,
                        prompt=build_vision_prompt(text),
                    )
                    fallback_descriptions.append(format_image_info(path, description))
                if persona_mode:
                    fallback_prompt = build_persona_prompt(
                        bridge.cfg.get("persona_skill", ""),
                        text,
                        fallback_descriptions,
                        image_count=0,
                        file_infos=file_infos,
                        sticker_infos=sticker_infos,
                        video_infos=video_infos or None,
                        casual_multipart=not task_mode,
                        memory_text=bridge._read_memory(),
                        cfg=bridge.cfg,
                    )
                else:
                    fallback_prompt = _build_work_prompt(
                        text,
                        [],
                        fallback_descriptions,
                        file_infos,
                        sticker_infos,
                        video_infos=video_infos or None,
                    )
                if image_paths or fallback_descriptions:
                    fallback_prompt += (
                        "\n本次不要调用任何工具或联网搜索；"
                        "如果图片信息不足，直接告诉用户需要重新发送图片。\n"
                    )
                logging.warning(
                    "Codex 主模型无响应，回退本地视觉 + %s：%s",
                    fallback_model,
                    exc,
                )
                try:
                    reply, new_thread_id = await run_with_policy(
                        bridge,
                        fallback_prompt,
                        None,
                        resolve_policy(bridge.cfg, "task" if task_mode else "casual"),
                        model=fallback_model,
                        bypass_proxy=True,
                    )
                except AgentError as fallback_exc:
                    logging.error("兜底模型也失败：%s", fallback_exc)
                    if persona_mode:
                        bridge.store.reset_persona(user_id)
                    await bridge._send_private(user_id, "……刚才处理中断了，请再发一次。")
                    return
            elif task_stage_timeout:
                task_thread_id = getattr(exc, "thread_id", None) or thread_id
                if task_thread_id:
                    if persona_mode:
                        bridge.store.set_persona_thread(user_id, task_thread_id)
                    else:
                        bridge.store.set_thread(user_id, task_thread_id)
                await bridge._start_task_stage(
                    user_id,
                    text or "（任务）",
                    task_thread_id or "",
                    1,
                )
                return
            else:
                logging.error("Codex 处理失败：%s", exc)
                if persona_mode:
                    bridge.store.reset_persona(user_id)
                await bridge._send_private(user_id, "……刚才处理中断了，请再发一次。")
                return
        if new_thread_id:
            if persona_mode:
                bridge.store.set_persona_thread(user_id, new_thread_id)
            else:
                bridge.store.set_thread(user_id, new_thread_id)
        if persona_mode:
            bridge.store.increment_persona_turns(user_id)
        if persona_mode:
            reply = sanitize_persona_reply(reply)
        await send_reply(
            bridge,
            user_id,
            reply,
            persona_mode=persona_mode,
            task_mode=task_mode,
        )


async def ingest_timetable(bridge: Any, user_id: str, buf: Any) -> None:
    try:
        if buf.files:
            path = await bridge._download_incoming_file(buf.files[0])
            suffix = Path(path).suffix.lower()
            if suffix == ".csv":
                classes = parse_csv(Path(path).read_text(encoding="utf-8-sig", errors="replace"))
            elif suffix == ".json":
                classes = load_timetable(path)
            elif suffix in (".xlsx", ".xls"):
                try:
                    classes = parse_xlsx(path)
                except ImportError:
                    await bridge._send_private(user_id, "暂不支持 Excel，请用 CSV 或图片。")
                    return
            else:
                await bridge._send_private(user_id, "只支持图片、CSV、JSON 或 Excel。")
                return
        elif buf.images:
            path = await download_incoming_image(bridge, buf.images[0])
            if bridge.cfg.get("vision_native", True):
                prompt = (
                    "请直接查看这张课表图片，输出 CSV 文本，第一行是表头："
                    "day,start,end,name,location,weeks。"
                    "day 用 1-7 表示周一到周日；start/end 用 HH:MM；"
                    "weeks 留空表示每周，“单周”或“双周”表示单双周；"
                    "每行一门课，字段用英文逗号分隔，不加引号；无法确定的字段留空。"
                    "只输出 CSV，不要解释。"
                )
                try:
                    rows_text, _ = await run_with_policy(
                        bridge,
                        prompt,
                        None,
                        resolve_policy(bridge.cfg, "casual"),
                        image_paths=[path],
                    )
                except AgentError as exc:
                    logging.warning("课表识别主模型失败，回退视觉模型：%s", exc)
                    timetable_settings = vision_settings(bridge.cfg)
                    rows_text = await extract_timetable_text(
                        path,
                        timetable_settings.url,
                        timetable_settings.model,
                        api_key=timetable_settings.api_key,
                        timeout=timetable_settings.timeout,
                        max_tokens=timetable_settings.max_tokens,
                    )
            else:
                timetable_settings = vision_settings(bridge.cfg)
                rows_text = await extract_timetable_text(
                    path,
                    timetable_settings.url,
                    timetable_settings.model,
                    api_key=timetable_settings.api_key,
                    timeout=timetable_settings.timeout,
                    max_tokens=timetable_settings.max_tokens,
                )
            rows_text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", rows_text.strip())
            classes = parse_csv(rows_text)
        else:
            return
    except Exception as exc:
        await bridge._send_private(user_id, f"课表解析失败：{exc}")
        return
    bridge.timetable_pending[user_id] = classes
    preview = format_preview(classes)
    await bridge._send_private(
        user_id,
        f"识别结果：\n{preview}\n\n确认后回复“确认”，取消回复“取消”。",
    )
