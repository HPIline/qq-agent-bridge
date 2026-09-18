from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import shlex
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

import websockets

import astrbot_plugins
import bridge_io
import handlers
import media
import schema
import task_stage
from agent_client import AgentClient, AgentError
from call_policy import resolve_policy, run_with_policy
from config import load_config
from message_utils import extract_private_message, is_duplicate
from proactive import proactive_tick, run_proactive, run_proactive_impl
from scheduler import run_scheduler
from sessions import SessionStore
from state_db import StateDB
from task_manager import TaskManager
from tts_client import LocalGPTSoVITSClient
from vision_client import build_vision_prompt, describe_image, vision_settings
from voice_sender import VoiceSender


class MessageBuffer:
    def __init__(self, user_id: str, cfg: dict[str, Any]):
        self.user_id = user_id
        self.cfg = cfg
        self.texts: list[str] = []
        self.images: list[dict[str, str]] = []
        self.videos: list[dict[str, str]] = []
        self.files: list[dict[str, str]] = []
        self.faces: list[dict[str, str]] = []
        self.mfaces: list[dict[str, str]] = []
        self.has_image = False
        self.has_video = False
        self.deadline: float | None = None

    def add_text(self, text: str) -> None:
        if text.strip():
            self.texts.append(text.strip())

    def add_image(self, image: dict[str, str]) -> None:
        self.images.append(image)
        self.has_image = True

    def add_video(self, video: dict[str, str]) -> None:
        self.videos.append(video)
        self.has_video = True

    def add_file(self, file: dict[str, str]) -> None:
        self.files.append(file)

    def add_face(self, face: dict[str, str]) -> None:
        self.faces.append(face)

    def add_mface(self, mface: dict[str, str]) -> None:
        self.mfaces.append(mface)

    def delay(self) -> float:
        if self.has_image or self.has_video:
            return float(self.cfg["image_wait_window"])
        return float(self.cfg.get("batch_window", 2.5))

    def reset_deadline(self, loop: asyncio.AbstractEventLoop) -> None:
        self.deadline = loop.time() + self.delay()

    def compose(self) -> str:
        return "\n".join(self.texts).strip()


class Bridge:
    """桥接编排层：事件缓冲、媒体与文件通道、主动调度、任务阶段、会话轮换。

    职责已拆到 handlers / media / bridge_io / task_stage / proactive / schema，
    本类保留兼容接口与编排。
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        store: SessionStore,
        agent: AgentClient,
        tts_client: Any | None = None,
        silk_encoder: Any | None = None,
    ):
        self.cfg = cfg
        self.store = store
        self.agent = agent
        self.ws: Any = None
        self.seen_ids: deque[str] = deque(maxlen=2000)
        self.buffers: dict[str, MessageBuffer] = {}
        self.buffer_tasks: dict[str, asyncio.Task[Any]] = {}
        self.pending_actions: dict[str, asyncio.Future[Any]] = {}
        self.web_replies: dict[str, asyncio.Queue[str | None]] = {}
        self.tmp_dir = Path(__file__).resolve().parent / "tmp"
        self.tmp_dir.mkdir(exist_ok=True)
        self.incoming_dir = self.tmp_dir / "incoming"
        self.incoming_dir.mkdir(exist_ok=True)
        self.bridge_dir = Path(__file__).resolve().parent
        self.notes_path = self.bridge_dir / cfg.get("proactive_notes_file", "proactive-notes.md")
        self.timetable_path = self.bridge_dir / cfg.get("timetable_file", "timetable.json")
        self.memory_path = self.bridge_dir / cfg.get("persona_memory_file", "memory.md")

        state_db_path = Path(cfg.get("state_db_file", "state.db"))
        if not state_db_path.is_absolute():
            state_db_path = self.bridge_dir / state_db_path
        self.state_db = StateDB(state_db_path)
        self.task_manager = TaskManager(self, self.state_db)

        # 统一文件通道 channels/
        self.messages_dir = self.bridge_dir / cfg.get("messages_dir", "channels")
        self.to_qq_dir = self.bridge_dir / cfg.get("to_qq_dir", "channels/to_qq")
        self.to_qq_sent_dir = self.bridge_dir / cfg.get("to_qq_sent_dir", "channels/to_qq/sent")
        self.from_qq_log_path = self.bridge_dir / cfg.get(
            "from_qq_log_file", "channels/from_qq/feedback.jsonl"
        )
        self.main_agent_inbox_path = self.bridge_dir / cfg.get(
            "main_agent_inbox_file", "channels/from_qq/main.jsonl"
        )
        self.agent_status_path = self.bridge_dir / cfg.get(
            "agent_status_file", "channels/state/agent-status.md"
        )
        self.legacy_agent_status_path = self.bridge_dir / cfg.get(
            "legacy_agent_status_file", "agent-status.md"
        )
        self.pending_path = self.bridge_dir / cfg.get("pending_file", "channels/state/pending.json")
        for directory in (
            self.messages_dir,
            self.to_qq_dir,
            self.to_qq_sent_dir,
            self.from_qq_log_path.parent,
            self.main_agent_inbox_path.parent,
            self.pending_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)

        # 旧通道兼容路径（启动时一次性迁移到 channels/）
        self.outbox_dir = self.bridge_dir / cfg.get("outbox_dir", "outbox")
        self.outbox_sent_dir = self.outbox_dir / cfg.get("outbox_sent_dir", "sent")
        self.outbox_dir.mkdir(exist_ok=True)
        self.outbox_sent_dir.mkdir(exist_ok=True)
        self.outbox_lock = asyncio.Lock()
        self.inbox_dir = self.bridge_dir / cfg.get("inbox_dir", "inbox")
        self.inbox_dir.mkdir(exist_ok=True)
        self.feedback_log_path = self.inbox_dir / cfg.get("inbox_log_file", "feedback.log")
        self.decisions_dir = self.bridge_dir / cfg.get("decisions_dir", "decisions")
        self.decisions_dir.mkdir(exist_ok=True)

        self.busy_users: set[str] = set()
        self.user_locks: dict[str, asyncio.Lock] = {}
        self.timetable_mode_users: set[str] = set()
        self.timetable_pending: dict[str, list[dict[str, Any]]] = {}
        if tts_client is None and cfg.get("tts_backend") == "local":
            tts_client = LocalGPTSoVITSClient(cfg)
        self.voice_sender = (
            VoiceSender(cfg, tts_client, silk_encoder=silk_encoder) if tts_client else None
        )

        # AstrBot 插件兼容层
        if cfg.get("plugins_enabled", True):
            try:
                self.astrbot_plugins = astrbot_plugins.load_plugins(self)
            except Exception:
                logging.exception("加载 AstrBot 插件失败")
                self.astrbot_plugins = []
        else:
            self.astrbot_plugins = []

    async def connect_loop(self) -> None:
        url = self.cfg["onebot_ws_url"]
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=16 * 1024 * 1024,
                ) as ws:
                    self.ws = ws
                    backoff = 1.0
                    logging.info("已连接 NapCat: %s", url)
                    async for raw in ws:
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        echo = event.get("echo")
                        if echo and echo in self.pending_actions:
                            fut = self.pending_actions.pop(echo)
                            if not fut.done():
                                fut.set_result(event)
                            continue
                        if event.get("post_type"):
                            asyncio.create_task(self._on_event(event))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.ws = None
                logging.warning("NapCat 连接失败：%s，%.0f 秒后重连", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _on_event(self, event: dict[str, Any]) -> None:
        info = extract_private_message(event)
        if not info:
            return
        if info["user_id"] not in self.cfg["full_access_qq"]:
            logging.info("忽略非白名单 QQ：%s", info["user_id"])
            return
        if is_duplicate(info["message_id"], self.seen_ids):
            return
        user_id = info["user_id"]
        self.store.mark_activity(user_id)
        await asyncio.to_thread(bridge_io.log_feedback, self, user_id, info["text"])
        captured = await asyncio.to_thread(
            bridge_io.capture_pending_reply, self, user_id, info["text"]
        )
        if isinstance(captured, dict) and captured.get("kind") == "task_stage":
            await self._send_private(user_id, "……收到。")
            asyncio.create_task(self._resume_task_stage(user_id))
            return
        if await asyncio.to_thread(bridge_io.route_main_agent_message, self, user_id, info["text"]):
            await self._send_private(user_id, "……收到，已转给主控。")
            return
        buf = self.buffers.get(user_id)
        if buf is None:
            buf = MessageBuffer(user_id, self.cfg)
            self.buffers[user_id] = buf
        if info["text"]:
            buf.add_text(info["text"])
        for image in info["images"]:
            buf.add_image(image)
        for video in info["videos"]:
            buf.add_video(video)
        for file in info["files"]:
            buf.add_file(file)
        for face in info["faces"]:
            buf.add_face(face)
        for mface in info["mfaces"]:
            buf.add_mface(mface)
        buf.reset_deadline(asyncio.get_running_loop())
        task = self.buffer_tasks.get(user_id)
        if task is None or task.done():
            self.buffer_tasks[user_id] = asyncio.create_task(self._wait_and_process(user_id, buf))

    async def _wait_and_process(self, user_id: str, buf: MessageBuffer) -> None:
        loop = asyncio.get_running_loop()
        while buf.deadline is not None:
            remaining = buf.deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.sleep(remaining)
        self.buffers.pop(user_id, None)
        try:
            await self._process_buffer(user_id, buf)
        except Exception:
            logging.exception("处理 QQ 消息失败")
            await self._send_private(user_id, "处理消息时出错了，稍后再试。")

    def _user_lock(self, user_id: str) -> asyncio.Lock:
        return self.user_locks.setdefault(user_id, asyncio.Lock())

    async def _run_agent_with_retry(
        self,
        prompt: str,
        thread_id: str | None,
        reasoning_effort: str | None = None,
        timeout: float | None = None,
        image_paths: list[str] | None = None,
        model: str | None = None,
        model_provider: str | None = None,
        bypass_proxy: bool = False,
    ) -> tuple[str, str | None]:
        kwargs: dict[str, Any] = {
            "reasoning_effort": reasoning_effort,
            "timeout": timeout,
            "image_paths": image_paths,
        }
        if model is not None:
            kwargs["model"] = model
        if model_provider is not None:
            kwargs["model_provider"] = model_provider
        if bypass_proxy:
            kwargs["bypass_proxy"] = True
        try:
            return await self.agent.run(prompt, thread_id, **kwargs)
        except AgentError as exc:
            if getattr(exc, "timeout", False):
                raise
            logging.warning("Codex 调用失败，改用低推理重试一次：%s", exc)
            kwargs["reasoning_effort"] = "low"
            return await self.agent.run(prompt, thread_id, **kwargs)

    async def _process_buffer(self, user_id: str, buf: MessageBuffer) -> None:
        async with self._user_lock(user_id):
            await self._process_buffer_impl(user_id, buf)

    async def _process_buffer_impl(self, user_id: str, buf: MessageBuffer) -> None:
        await handlers.process_buffer_impl(self, user_id, buf)

    # ---- 媒体（委托 media.py） ----

    async def _call_action(
        self, action: str, params: dict[str, Any], timeout: float = 60.0
    ) -> dict[str, Any]:
        return await media.call_action(self, action, params, timeout)

    async def _send_private_file(self, user_id: str, target: str, name: str) -> None:
        await media.send_private_file(self, user_id, target, name)

    async def _send_private_segments(self, user_id: str, segments: list[dict[str, Any]]) -> None:
        await media.send_private_segments(self, user_id, segments)

    async def _send_private_face(self, user_id: str, face_id: str) -> None:
        await media.send_private_face(self, user_id, face_id)

    async def _send_private_mface(self, user_id: str, marker: dict[str, str]) -> None:
        await media.send_private_mface(self, user_id, marker)

    async def _send_private_image(self, user_id: str, target: str, name: str = "") -> None:
        await media.send_private_image(self, user_id, target, name)

    async def _send_private_video(self, user_id: str, target: str, name: str = "") -> None:
        await media.send_private_video(self, user_id, target, name)

    async def _send_private_record(self, user_id: str, path: str) -> None:
        await media.send_private_record(self, user_id, path)

    async def _send_media_marker(self, user_id: str, marker: dict[str, str]) -> None:
        await media.send_media_marker(self, user_id, marker)

    async def _download_incoming_file(self, file: dict[str, str]) -> str:
        return await media.download_incoming_file(self, file)

    # ---- 主动调度（委托 proactive.py） ----

    async def proactive_loop(self) -> None:
        interval = float(self.cfg.get("proactive_check_interval_sec", 60))
        while True:
            try:
                await self._proactive_tick()
            except Exception:
                logging.exception("主动调度检查失败")
            await asyncio.sleep(interval)

    async def _proactive_tick(self, now: dt.datetime | None = None) -> None:
        await proactive_tick(self, now=now)

    async def _run_proactive(
        self,
        user_id: str,
        source: str,
        slot: str | None = None,
        class_key: str | None = None,
        record: bool = True,
        now: dt.datetime | None = None,
    ) -> None:
        await run_proactive(
            self,
            user_id,
            source,
            slot=slot,
            class_key=class_key,
            record=record,
            now=now,
        )

    async def _run_proactive_impl(
        self,
        user_id: str,
        source: str,
        slot: str | None = None,
        class_key: str | None = None,
        record: bool = True,
        now: dt.datetime | None = None,
    ) -> None:
        await run_proactive_impl(
            self,
            user_id,
            source,
            slot=slot,
            class_key=class_key,
            record=record,
            now=now,
        )

    # ---- 文件通道（委托 bridge_io.py） ----

    async def outbox_loop(self) -> None:
        interval = float(self.cfg.get("outbox_check_interval_sec", 5))
        while True:
            try:
                await self._flush_outbox()
            except Exception:
                logging.exception("outbox 发送检查失败")
            await asyncio.sleep(interval)

    async def _flush_outbox(self) -> None:
        await bridge_io.flush_outbox(self)

    def _archive_outbox(self, path: Path) -> None:
        bridge_io._archive(path, self.outbox_sent_dir)

    def _log_feedback(self, user_id: str, text: str) -> None:
        bridge_io.log_feedback(self, user_id, text)

    def _maybe_capture_pending_reply(self, user_id: str, text: str) -> dict[str, Any] | None:
        return bridge_io.capture_pending_reply(self, user_id, text)

    def _pending_task_stage_waiting(self) -> bool:
        return bridge_io.pending_task_stage_waiting(self)

    def _write_pending_task_stage(
        self,
        user_id: str,
        original_prompt: str,
        thread_id: str,
        stage: int,
    ) -> None:
        bridge_io.write_pending_task_stage(self, user_id, original_prompt, thread_id, stage)

    def _clear_task_pending(self) -> None:
        bridge_io.clear_task_pending(self)

    # ---- 任务阶段（委托 task_stage.py） ----

    async def _start_task_stage(
        self,
        user_id: str,
        original_prompt: str,
        thread_id: str,
        stage: int,
    ) -> None:
        await task_stage.start_task_stage(self, user_id, original_prompt, thread_id, stage)

    async def _resume_task_stage(self, user_id: str) -> None:
        await task_stage.resume_task_stage(self, user_id)

    # ---- 记忆与轮换 ----

    def _read_notes(self) -> str:
        try:
            if not self.notes_path.exists():
                return ""
            return self.notes_path.read_text(encoding="utf-8", errors="replace")[:2000].strip()
        except Exception:
            logging.exception("读取 notes 文件失败")
            return ""

    def _read_memory(self) -> str:
        try:
            if not self.memory_path.exists():
                return ""
            return self.memory_path.read_text(encoding="utf-8", errors="replace")[:8000].strip()
        except Exception:
            logging.exception("读取记忆文件失败")
            return ""

    async def _write_memory(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        await asyncio.to_thread(self.memory_path.write_text, text + "\n", encoding="utf-8")

    async def _maybe_rotate_persona(self, user_id: str) -> None:
        if not self.cfg.get("persona_enabled", True):
            return
        if self._pending_task_stage_waiting():
            return
        if user_id in self.busy_users:
            return
        thread_id = self.store.get_persona_thread(user_id)
        if not thread_id:
            return
        turns = self.store.get_persona_turns(user_id)
        started_ts = self.store.get_persona_started_ts(user_id)
        limit_turns = int(self.cfg.get("persona_reset_turns", 150))
        limit_hours = float(self.cfg.get("persona_reset_hours", 24))
        due_turns = turns >= limit_turns
        due_time = started_ts is None or (time.time() - started_ts) >= limit_hours * 3600
        if not (due_turns or due_time):
            return
        logging.info(
            "角色扮演会话达到轮换条件（轮次 %s/%s，创建于 %s），开始整理记忆",
            turns,
            limit_turns,
            dt.datetime.fromtimestamp(started_ts).strftime("%Y-%m-%d %H:%M")
            if started_ts
            else "未知",
        )
        try:
            summary_prompt = (
                "请阅读这段会话的历史，把需要长期记住的内容整理成简洁清单，"
                "包括：用户身份与关系、偏好、当前进行中的事情或项目、承诺、重要日期。"
                "不要角色扮演，不要寒暄，不要使用任何媒体标记，直接输出清单文本。"
            )
            reply, _ = await run_with_policy(
                self,
                summary_prompt,
                thread_id,
                resolve_policy(self.cfg, "summary"),
            )
            await self._write_memory(reply)
        except Exception:
            logging.exception("整理角色扮演记忆失败，仍继续轮换（保留旧记忆文件）")
        self.store.reset_persona(user_id)
        logging.info("角色扮演会话已轮换：%s", user_id)

    async def _describe_image(self, path: str, user_text: str = "") -> str:
        settings = vision_settings(self.cfg)
        description = await describe_image(
            path,
            settings.url,
            settings.model,
            api_key=settings.api_key,
            timeout=settings.timeout,
            max_tokens=settings.max_tokens,
            prompt=build_vision_prompt(user_text),
        )
        return await self._enrich_vision(description)

    async def _enrich_vision(self, description: str) -> str:
        if not self.cfg.get("vision_enrich_enabled", True):
            return description
        has_section = "【不确定项】" in description
        empty_section = "【不确定项】无" in description or "【不确定项】：无" in description
        if has_section:
            if empty_section:
                return description
        else:
            keywords = self.cfg.get(
                "vision_enrich_keywords",
                ["不确定", "无法确认", "资讯不足", "需要查证", "看不清"],
            )
            if not any(keyword in description for keyword in keywords):
                return description
        prompt = (
            "以下是图片识图描述：\n"
            + description
            + "\n\n请判断图片里的主体是什么（角色、物品、场景等）。"
            "如果仅凭描述无法确定，必须使用联网搜索查证。"
            "只输出：结论 + 依据 + 置信度，不要寒暄，不要放弃。"
        )
        try:
            reply, _ = await run_with_policy(
                self,
                prompt,
                None,
                resolve_policy(self.cfg, "enrich"),
            )
            reply = reply.strip()
            if reply:
                logging.info("图片补充查证完成：%s", reply[:120])
                return description.rstrip() + "\n\n补充查证（联网）：\n" + reply
        except Exception as exc:
            logging.warning("图片补充查证失败：%s", exc)
        return description

    async def _ingest_timetable(self, user_id: str, buf: MessageBuffer) -> None:
        await handlers.ingest_timetable(self, user_id, buf)

    async def _restart_bridge(self) -> None:
        await asyncio.sleep(0.5)
        command = str(self.cfg.get("restart_command") or "").strip()
        if not command and sys.platform == "darwin":
            command = f"launchctl kickstart -k gui/{os.getuid()}/com.qq-agent-bridge"
        if not command:
            logging.info("未配置 restart_command，跳过自动重启（各平台启动方式见 README）")
            return
        try:
            args = shlex.split(command, posix=os.name != "nt")
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception:
            logging.exception("自动重启失败")

    async def process_web_message(
        self,
        user_id: str,
        text: str,
        timeout: float = 900.0,
    ) -> list[str]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.web_replies[user_id] = queue
        self.store.mark_activity(user_id)
        buf = MessageBuffer(user_id, self.cfg)
        buf.add_text(text)
        task = asyncio.create_task(self._process_web_buffer(user_id, buf, queue))
        replies: list[str] = []
        try:
            while True:
                item = await asyncio.wait_for(queue.get(), timeout=timeout)
                if item is None:
                    break
                replies.append(item)
        except TimeoutError:
            task.cancel()
            replies.append("（处理超时）")
        finally:
            self.web_replies.pop(user_id, None)
            if not task.done():
                task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return replies

    async def _process_web_buffer(
        self,
        user_id: str,
        buf: MessageBuffer,
        queue: asyncio.Queue[str | None],
    ) -> None:
        try:
            await self._process_buffer(user_id, buf)
        finally:
            await queue.put(None)

    async def _send_private(self, user_id: str, text: str) -> None:
        if not text.strip():
            return
        if user_id in self.web_replies:
            await self.web_replies[user_id].put(text)
            return
        if self.ws is None:
            logging.warning("WS 未连接，无法发送：%s", text[:80])
            return
        try:
            user_id_num = int(user_id)
        except ValueError:
            user_id_num = user_id
        payload = {
            "action": "send_private_msg",
            "params": {"user_id": user_id_num, "message": text},
        }
        await self.ws.send(json.dumps(payload, ensure_ascii=False))
        logging.info("已发送给 %s：%s", user_id, text[:80])
        self.store.mark_activity(user_id)


async def main() -> None:
    cfg = load_config()
    log_file = Path(cfg["log_file"])
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, str(cfg.get("log_level", "INFO")).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    logging.info("配置：%s", cfg.get("_config_path") or "（内置默认值）")
    legacy_keys = cfg.get("_legacy_keys") or []
    if legacy_keys:
        logging.warning(
            "配置里用了旧键名 %s，当前仍然生效；建议按 CONFIG.md 改成新键名",
            "、".join(legacy_keys),
        )
    store = SessionStore(Path(cfg["sessions_file"]))
    agent = AgentClient(cfg)
    bridge = Bridge(cfg, store, agent)
    migrated = bridge_io.migrate_legacy_channels(bridge)
    if any(migrated.values()):
        logging.info("旧文件通道迁移完成：%s", migrated)
    if schema.self_check_sessions(store):
        logging.info("sessions.json schema 自检完成并已修复")
    if schema.self_check_pending(bridge.pending_path):
        logging.info("pending.json schema 自检完成并已修复")
    scheduler_task = asyncio.create_task(
        run_scheduler(bridge, interval=float(cfg.get("scheduler_interval_sec", 15)))
    )
    task_worker_task = asyncio.create_task(
        bridge.task_manager.worker_loop(interval=float(cfg.get("task_worker_interval_sec", 0.5)))
    )
    tasks = [
        bridge.connect_loop(),
        bridge.proactive_loop(),
        bridge.outbox_loop(),
        scheduler_task,
        task_worker_task,
    ]
    if bool(cfg.get("web_enabled", False)):
        # 延迟导入：没开 Web 工作台就不需要 fastapi/uvicorn
        try:
            from web_panel import start_web_panel
        except ImportError as exc:
            raise RuntimeError(
                "web_enabled=true 需要额外依赖，请先执行："
                "pip install -r requirements-web.txt"
            ) from exc
        web_task = asyncio.create_task(start_web_panel(bridge))
        tasks.append(web_task)
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        bridge.state_db.close()
        await agent.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
