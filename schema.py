"""状态文件 schema：pending.json / sessions.json 的规范化与启动自检。"""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Any

PENDING_VERSION = 1
PENDING_KINDS = ("decision", "task_stage")
PENDING_STATUSES = ("waiting", "answered")


def _now_iso() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def normalize_pending(data: Any) -> dict[str, Any] | None:
    """把 pending.json 内容规范化为 v1，字段不对就修复；无法修复返回 None。"""
    if not isinstance(data, dict):
        return None
    out = dict(data)
    out["version"] = PENDING_VERSION
    kind = out.get("kind")
    if kind not in PENDING_KINDS:
        kind = "decision"
        out["kind"] = kind
    status = out.get("status")
    if status not in PENDING_STATUSES:
        status = "waiting"
        out["status"] = status
    if not str(out.get("id") or "").strip():
        out["id"] = f"pending-{int(time.time())}"
    if not out.get("created_at"):
        out["created_at"] = _now_iso()
    if status == "answered":
        out["reply"] = str(out.get("reply") or "")
        if not out.get("replied_at"):
            out["replied_at"] = _now_iso()
    else:
        out.pop("reply", None)
        out.pop("replied_at", None)
    if kind == "task_stage":
        out["thread_id"] = str(out.get("thread_id") or "")
        out["original_prompt"] = str(out.get("original_prompt") or "")
        try:
            out["stage"] = int(out.get("stage", 1))
        except (TypeError, ValueError):
            out["stage"] = 1
    else:
        for key in ("thread_id", "original_prompt", "stage"):
            out.pop(key, None)
    return out


def normalize_sessions(data: Any) -> dict[str, Any]:
    """把 sessions.json 规范化：每个用户保留已知字段的正确类型，未知字段保留。"""
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for user_id, raw in data.items():
        if not isinstance(raw, dict):
            continue
        user = dict(raw)
        turns = user.get("persona_turns")
        if turns is not None and not isinstance(turns, bool):
            try:
                user["persona_turns"] = int(turns)
            except (TypeError, ValueError):
                user["persona_turns"] = 0
        if "persona_started_ts" in user:
            try:
                user["persona_started_ts"] = float(user["persona_started_ts"])
            except (TypeError, ValueError):
                user.pop("persona_started_ts", None)
        follow = user.get("task_follow")
        if follow is not None:
            if not isinstance(follow, dict):
                user.pop("task_follow", None)
            else:
                try:
                    last_ts = float(follow.get("last_task_ts") or 0.0)
                except (TypeError, ValueError):
                    last_ts = 0.0
                user["task_follow"] = {
                    "active": bool(follow.get("active")),
                    "last_task_ts": last_ts,
                }
        proactive = user.get("proactive")
        if proactive is not None:
            if not isinstance(proactive, dict):
                proactive = {}
            else:
                proactive = dict(proactive)
            try:
                proactive["count"] = int(proactive.get("count") or 0)
            except (TypeError, ValueError):
                proactive["count"] = 0
            for key in ("fixed_done", "reminded_classes"):
                if not isinstance(proactive.get(key), list):
                    proactive[key] = []
            for key in ("last_ts", "last_active_ts"):
                if key in proactive:
                    try:
                        proactive[key] = float(proactive[key])
                    except (TypeError, ValueError):
                        proactive.pop(key, None)
            if "paused" in proactive:
                proactive["paused"] = bool(proactive["paused"])
            user["proactive"] = proactive
        out[str(user_id)] = user
    return out


def self_check_sessions(store: Any) -> bool:
    """启动时校验并修复 sessions.json，返回是否有改动。"""
    normalized = normalize_sessions(store._data)
    if normalized != store._data:
        store._data = normalized
        store.save()
        return True
    return False


def self_check_pending(pending_path: Path) -> bool:
    """启动时校验并修复 pending.json；损坏文件移到 .corrupt-<ts>，返回是否有改动。"""
    if not pending_path.is_file():
        return False
    try:
        data = json.loads(pending_path.read_text(encoding="utf-8"))
    except Exception:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        pending_path.rename(pending_path.with_name(f"{pending_path.name}.corrupt-{stamp}"))
        return True
    normalized = normalize_pending(data)
    if normalized is None:
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        pending_path.rename(pending_path.with_name(f"{pending_path.name}.corrupt-{stamp}"))
        return True
    if normalized != data:
        pending_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return True
    return False
