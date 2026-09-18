"""主控⇄桥接统一文件通道：出站队列、入站日志、决断文件、旧通道迁移。"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any

import message_utils
import schema


def _unique_dest(dest_dir: Path, name: str) -> Path:
    dest = dest_dir / name
    counter = 1
    while dest.exists():
        dest = dest_dir / f"{counter}-{name}"
        counter += 1
    return dest


def _archive(path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = _unique_dest(dest_dir, f"{stamp}-{path.name}")
    shutil.move(str(path), str(dest))


async def flush_outbox(bridge: Any) -> None:
    """发送统一出站队列，并兜底发送旧 outbox 文本文件。"""
    if bridge.ws is None:
        return
    sent_any = False
    if bridge.to_qq_dir.is_dir():
        for path in sorted(bridge.to_qq_dir.iterdir()):
            if not path.is_file() or path.name.startswith(".") or path.suffix != ".json":
                continue
            try:
                try:
                    envelope = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    path.rename(
                        path.with_name(f"{path.name}.invalid-{int(dt.datetime.now().timestamp())}")
                    )
                    logging.warning("channels/to_qq 存在无效信封，已标记：%s", path.name)
                    continue
                text = str(envelope.get("text") or "").strip()
                if not isinstance(envelope, dict) or not text:
                    path.rename(
                        path.with_name(f"{path.name}.invalid-{int(dt.datetime.now().timestamp())}")
                    )
                    logging.warning("channels/to_qq 存在无效信封，已标记：%s", path.name)
                    continue
                recipients = envelope.get("to") or bridge.cfg["full_access_qq"]
                for user_id in recipients:
                    await _send_envelope_text(bridge, user_id, text)
                await asyncio.to_thread(_archive, path, bridge.to_qq_sent_dir)
                logging.info("channels/to_qq 已发送并归档：%s", path.name)
                sent_any = True
            except Exception:
                logging.exception("channels/to_qq 发送失败，保留文件：%s", path.name)
    if bridge.outbox_dir.is_dir() and bridge.outbox_dir.resolve() != bridge.to_qq_dir.resolve():
        async with bridge.outbox_lock:
            for path in sorted(bridge.outbox_dir.iterdir()):
                if not path.is_file() or path.name.startswith(".") or path.suffix == ".json":
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="replace").strip()
                    if not text:
                        await asyncio.to_thread(_archive, path, bridge.outbox_sent_dir)
                        continue
                    for user_id in bridge.cfg["full_access_qq"]:
                        await _send_envelope_text(bridge, user_id, text)
                    await asyncio.to_thread(_archive, path, bridge.outbox_sent_dir)
                    logging.info("outbox 已发送并归档：%s", path.name)
                    sent_any = True
                except Exception:
                    logging.exception("outbox 发送失败，保留文件：%s", path.name)
    if sent_any:
        bridge.store.save()


async def _send_envelope_text(bridge: Any, user_id: str, text: str) -> None:
    """发送信封文本；解析 [FACE]/[MFACE]/[IMAGE]/[FILE]/[VOICE] 媒体标记。"""
    text, markers = message_utils.extract_media_markers(text)
    if text:
        await bridge._send_private(str(user_id), text)
    voice_sent = 0
    for marker in markers:
        if marker["kind"] == "voice":
            if voice_sent >= int(bridge.cfg.get("voice_max_per_reply", 1)):
                logging.warning("忽略超出数量限制的语音标记")
                continue
            if bridge.voice_sender is not None:
                ok = await bridge.voice_sender.send_voice(
                    str(user_id), marker["text"], bridge._send_private_record
                )
                if ok:
                    voice_sent += 1
            continue
        await bridge._send_media_marker(str(user_id), marker)


def log_feedback(bridge: Any, user_id: str, text: str) -> None:
    """把用户 QQ 消息追加到 JSONL 入站日志；超过阈值才裁剪，避免每条都重写。"""
    text = text.strip()
    if not text:
        return
    path = bridge.from_qq_log_path
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "user_id": str(user_id),
            "text": text,
        },
        ensure_ascii=False,
    )
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    max_bytes = int(bridge.cfg.get("inbox_log_max_bytes", 65536))
    max_lines = int(bridge.cfg.get("inbox_log_max_lines", 200))
    try:
        if path.stat().st_size < max_bytes:
            return
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return
    if len(lines) > max_lines:
        path.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")


def route_main_agent_message(bridge: Any, user_id: str, text: str) -> bool:
    """把带“/本机”前缀的消息转交主控，写入主控专用 JSONL 收件箱。"""
    text = text.strip()
    if not text:
        return False
    for prefix in bridge.cfg.get("main_agent_prefixes", ["/本机"]):
        if text.startswith(prefix):
            body = text[len(prefix) :].strip()
            path = bridge.main_agent_inbox_path
            path.parent.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": dt.datetime.now().isoformat(timespec="seconds"),
                "user_id": str(user_id),
                "text": body,
            }
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            logging.info("已转交主控（%s）：%s", user_id, body[:80])
            return True
    return False


def capture_pending_reply(bridge: Any, user_id: str, text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        if not bridge.pending_path.exists():
            return None
        data = json.loads(bridge.pending_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    normalized = schema.normalize_pending(data)
    if normalized is None or normalized.get("status") != "waiting":
        return None
    normalized["status"] = "answered"
    normalized["reply"] = text
    normalized["replied_at"] = dt.datetime.now().isoformat(timespec="seconds")
    bridge.pending_path.parent.mkdir(parents=True, exist_ok=True)
    bridge.pending_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logging.info("已捕获决断回复（%s）：%s", user_id, text)
    return normalized


def pending_task_stage_waiting(bridge: Any) -> bool:
    try:
        if not bridge.pending_path.exists():
            return False
        data = json.loads(bridge.pending_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    normalized = schema.normalize_pending(data)
    return bool(
        normalized
        and normalized.get("kind") == "task_stage"
        and normalized.get("status") == "waiting"
    )


def write_pending_task_stage(
    bridge: Any,
    user_id: str,
    original_prompt: str,
    thread_id: str,
    stage: int,
) -> None:
    data = schema.normalize_pending(
        {
            "id": f"task-stage-{int(dt.datetime.now().timestamp())}",
            "kind": "task_stage",
            "question": "继续执行任务？",
            "original_prompt": original_prompt,
            "thread_id": thread_id,
            "stage": stage,
            "status": "waiting",
            "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    )
    bridge.pending_path.parent.mkdir(parents=True, exist_ok=True)
    bridge.pending_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_task_pending(bridge: Any) -> None:
    try:
        if not bridge.pending_path.exists():
            return
        data = json.loads(bridge.pending_path.read_text(encoding="utf-8"))
        normalized = schema.normalize_pending(data)
        if normalized and normalized.get("kind") == "task_stage":
            bridge.pending_path.unlink()
    except Exception:
        pass


def write_report_envelope(
    to_qq_dir: Path,
    text: str,
    recipients: list[str] | None = None,
    envelope_type: str = "report",
) -> Path:
    """主控侧写入统一出站信封；桥接启动后会自动发送并归档。"""
    to_qq_dir = Path(to_qq_dir)
    to_qq_dir.mkdir(parents=True, exist_ok=True)
    envelope = {
        "schema_version": 1,
        "id": f"{envelope_type}-{uuid.uuid4().hex[:12]}",
        "type": envelope_type,
        "text": text,
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "to": [str(x) for x in recipients] if recipients else [],
    }
    path = to_qq_dir / f"{envelope['id']}.json"
    path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def migrate_legacy_channels(bridge: Any) -> dict[str, int]:
    """把旧 outbox / feedback.log / pending.json / agent-status.md 一次性迁到 channels/。"""
    counts = {"outbox": 0, "feedback": 0, "pending": 0, "status": 0}
    if bridge.outbox_dir.is_dir():
        sent = bridge.outbox_sent_dir
        sent.mkdir(parents=True, exist_ok=True)
        for path in sorted(bridge.outbox_dir.iterdir()):
            if not path.is_file() or path.name.startswith("."):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace").strip()
                if text:
                    write_report_envelope(bridge.to_qq_dir, text)
                _archive(path, sent)
                counts["outbox"] += 1
            except Exception:
                logging.exception("迁移 outbox 文件失败：%s", path.name)
    if bridge.feedback_log_path.is_file() and not bridge.from_qq_log_path.exists():
        try:
            lines = bridge.feedback_log_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()
            bridge.from_qq_log_path.parent.mkdir(parents=True, exist_ok=True)
            with bridge.from_qq_log_path.open("a", encoding="utf-8") as f:
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    entry = {
                        "ts": dt.datetime.now().isoformat(timespec="seconds"),
                        "user_id": "",
                        "text": line,
                    }
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            bridge.feedback_log_path.rename(
                bridge.feedback_log_path.with_name(
                    f"{bridge.feedback_log_path.name}.migrated-{int(dt.datetime.now().timestamp())}"
                )
            )
            counts["feedback"] = len(lines)
        except Exception:
            logging.exception("迁移 feedback.log 失败")
    if bridge.decisions_dir.joinpath("pending.json").is_file() and not bridge.pending_path.exists():
        try:
            old = bridge.decisions_dir / "pending.json"
            data = json.loads(old.read_text(encoding="utf-8"))
            normalized = schema.normalize_pending(data)
            if normalized is not None:
                bridge.pending_path.parent.mkdir(parents=True, exist_ok=True)
                bridge.pending_path.write_text(
                    json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            old.rename(old.with_name(f"{old.name}.migrated-{int(dt.datetime.now().timestamp())}"))
            counts["pending"] = 1
        except Exception:
            logging.exception("迁移 pending.json 失败")
    if bridge.agent_status_path is not None:
        old_status = bridge.legacy_agent_status_path
        if old_status.is_file() and not bridge.agent_status_path.exists():
            try:
                bridge.agent_status_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(old_status), str(bridge.agent_status_path))
                old_status.rename(
                    old_status.with_name(
                        f"{old_status.name}.migrated-{int(dt.datetime.now().timestamp())}"
                    )
                )
                counts["status"] = 1
            except Exception:
                logging.exception("迁移 agent-status.md 失败")
    return counts
