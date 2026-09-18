from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from call_policy import resolve_policy, run_with_policy
from message_utils import (
    build_proactive_prompt,
    extract_topic_markers,
    filter_memory_for_proactive,
    sanitize_persona_reply,
)
from reply_sender import send_reply
from timetable import load_timetable, next_class
from trending import get_cached_trending_context, prefetch_trending


def parse_time(value: str) -> dt.time:
    hour, minute = value.strip().split(":", 1)
    return dt.time(int(hour), int(minute))


def in_windows(now: dt.datetime, windows: list[str]) -> bool:
    if not windows:
        return True
    minutes = now.hour * 60 + now.minute
    for window in windows:
        start_s, end_s = window.split("-", 1)
        start_h, start_m = start_s.strip().split(":", 1)
        end_h, end_m = end_s.strip().split(":", 1)
        start = int(start_h) * 60 + int(start_m)
        end = int(end_h) * 60 + int(end_m)
        if start <= minutes < end:
            return True
    return False


def format_now(now: dt.datetime) -> str:
    weekday = "一二三四五六日"[now.weekday()]
    return f"{now:%Y-%m-%d %H:%M} 星期{weekday}"


def prepare_state(state: dict[str, Any], now: dt.datetime) -> dict[str, Any]:
    day = f"{now:%Y-%m-%d}"
    if state.get("day") != day:
        state["day"] = day
        state["count"] = 0
        state["fixed_done"] = []
        state["reminded_classes"] = []
    return state


def _cooled(state: dict[str, Any], now: dt.datetime, cfg: dict[str, Any]) -> bool:
    last_ts = state.get("last_ts")
    if last_ts is None:
        return True
    cooldown_min = float(cfg.get("proactive_cooldown_minutes", 240))
    return (now.timestamp() - float(last_ts)) / 60.0 >= cooldown_min


def _due_fixed_slot(state: dict[str, Any], now: dt.datetime, cfg: dict[str, Any]) -> str | None:
    current = f"{now:%H:%M}"
    done = set(state.get("fixed_done", []))
    for slot in cfg.get("proactive_fixed_times", []):
        if current >= slot and f"{now:%Y-%m-%d}|{slot}" not in done:
            return slot
    return None


def _idle_due(state: dict[str, Any], now: dt.datetime, cfg: dict[str, Any]) -> bool:
    last_active = state.get("last_active_ts")
    if last_active is None:
        return False
    idle_min = float(cfg.get("proactive_idle_minutes", 180))
    return (now.timestamp() - float(last_active)) / 60.0 >= idle_min


def should_initiate(
    state: dict[str, Any],
    cfg: dict[str, Any],
    now: dt.datetime,
    busy: bool = False,
) -> tuple[bool, str | None, str | None]:
    if not cfg.get("proactive_enabled", True):
        return False, None, None
    if state.get("paused") or busy:
        return False, None, None
    if int(state.get("count", 0)) >= int(cfg.get("proactive_max_per_day", 4)):
        return False, None, None
    if not in_windows(now, cfg.get("proactive_windows", ["09:00-23:30"])):
        return False, None, None
    if not _cooled(state, now, cfg):
        return False, None, None
    slot = _due_fixed_slot(state, now, cfg)
    if slot:
        return True, "fixed", slot
    if _idle_due(state, now, cfg):
        return True, "idle", None
    return False, None, None


def class_reminder_due(
    next_class: dict[str, Any] | None,
    now: dt.datetime,
    cfg: dict[str, Any],
    state: dict[str, Any],
    busy: bool = False,
) -> tuple[bool, str | None]:
    if not cfg.get("proactive_enabled", True):
        return False, None
    if state.get("paused") or busy:
        return False, None
    if int(state.get("count", 0)) >= int(cfg.get("proactive_max_per_day", 4)):
        return False, None
    if not next_class:
        return False, None
    if not in_windows(now, cfg.get("proactive_class_windows", ["07:00-23:30"])):
        return False, None
    start = dt.datetime.combine(now.date(), parse_time(next_class["start"]))
    lead_min = float(cfg.get("proactive_class_lead_minutes", 15))
    delta_min = (start - now).total_seconds() / 60.0
    if not (0 <= delta_min <= lead_min):
        return False, None
    key = f"{now:%Y-%m-%d}|{next_class['start']}|{next_class['name']}"
    if key in state.get("reminded_classes", []):
        return False, None
    return True, key


def mark_triggered(
    state: dict[str, Any],
    cfg: dict[str, Any],
    now: dt.datetime,
    source: str,
    slot: str | None = None,
    class_key: str | None = None,
    count: bool = True,
) -> dict[str, Any]:
    state["last_ts"] = now.timestamp()
    state["last_active_ts"] = now.timestamp()
    if count:
        state["count"] = int(state.get("count", 0)) + 1
    if source == "fixed" and slot:
        state.setdefault("fixed_done", []).append(f"{now:%Y-%m-%d}|{slot}")
    if source == "class" and class_key:
        state.setdefault("reminded_classes", []).append(class_key)
    return state


def mark_proactive_skipped(
    state: dict[str, Any],
    now: dt.datetime,
    source: str,
    slot: str | None = None,
) -> dict[str, Any]:
    """模型判断“现在不适合开口”时，只刷新冷却、不占用当天次数。"""
    state["last_ts"] = now.timestamp()
    if source == "fixed" and slot:
        state.setdefault("fixed_done", []).append(f"{now:%Y-%m-%d}|{slot}")
    return state


def _reject_proactive_reply(reply: str) -> bool:
    first_line = (reply or "").strip().splitlines()[0].strip().rstrip("。！!；;")
    token = first_line.upper()
    return token in {"NO", "不", "不发", "算了", "跳过", "SKIP", "N"} or token.startswith("NO")


async def proactive_tick(bridge: Any, now: dt.datetime | None = None) -> None:
    if not bridge.cfg.get("proactive_enabled", True):
        return
    if bridge.ws is None:
        return
    now = now or dt.datetime.now()
    prefetch_trending(bridge.cfg)
    classes = load_timetable(bridge.timetable_path)
    for user_id in bridge.cfg["full_access_qq"]:
        if user_id in bridge.busy_users:
            logging.info("主动调度检查：%s 忙碌，跳过", user_id)
            continue
        if user_id in bridge.buffers:
            logging.info("主动调度检查：%s 有待处理缓冲，跳过", user_id)
            continue
        buffer_task = bridge.buffer_tasks.get(user_id)
        if buffer_task is not None and not buffer_task.done():
            logging.info("主动调度检查：%s 消息任务处理中，跳过", user_id)
            continue
        if not bridge.store.is_persona(user_id):
            continue
        state = prepare_state(bridge.store.get_proactive_state(user_id), now)
        busy = user_id in bridge.busy_users
        next_c = next_class(classes, now)
        due, class_key = class_reminder_due(next_c, now, bridge.cfg, state, busy=busy)
        if due:
            await run_proactive(bridge, user_id, "class", class_key=class_key, now=now)
            continue
        due, source, slot = should_initiate(state, bridge.cfg, now, busy=busy)
        if due:
            await run_proactive(bridge, user_id, source, slot=slot, now=now)


async def run_proactive(
    bridge: Any,
    user_id: str,
    source: str,
    slot: str | None = None,
    class_key: str | None = None,
    record: bool = True,
    now: dt.datetime | None = None,
) -> None:
    if user_id in bridge.busy_users:
        logging.info("主动调度跳过：%s 忙碌", user_id)
        return
    lock = bridge._user_lock(user_id)
    if lock.locked():
        logging.info("主动调度跳过：%s 处理中（用户锁被占用）", user_id)
        return
    async with lock:
        await run_proactive_impl(
            bridge,
            user_id,
            source,
            slot=slot,
            class_key=class_key,
            record=record,
            now=now,
        )


async def run_proactive_impl(
    bridge: Any,
    user_id: str,
    source: str,
    slot: str | None = None,
    class_key: str | None = None,
    record: bool = True,
    now: dt.datetime | None = None,
) -> None:
    if user_id in bridge.busy_users:
        return
    if bridge._pending_task_stage_waiting():
        return
    await bridge._maybe_rotate_persona(user_id)
    bridge.busy_users.add(user_id)
    try:
        with bridge.store.batch():
            now = now or dt.datetime.now()
            state = prepare_state(bridge.store.get_proactive_state(user_id), now)
            notes_text = bridge._read_notes()
            trending_text = ""
            if source != "class":
                trending_text = get_cached_trending_context(bridge.cfg)
            class_hint = ""
            if source == "class":
                next_c = next_class(load_timetable(bridge.timetable_path), now)
                if next_c:
                    class_hint = (
                        f"下一节课：{next_c['name']}，{next_c['start']}，"
                        f"地点：{next_c.get('location') or '未知'}"
                    )
            memory_text = filter_memory_for_proactive(bridge._read_memory())
            topic_history = {
                "avoid_events": state.get("avoid_events", []),
                "categories": state.get("category_counts", {}),
            }
            decision_enabled = bool(
                bridge.cfg.get("proactive_decision_enabled", True)
            ) and source in ("fixed", "idle")
            prompt = build_proactive_prompt(
                bridge.cfg.get("persona_skill", ""),
                format_now(now),
                notes_text,
                class_hint,
                memory_text=memory_text,
                trending_text=trending_text,
                topic_directions=bridge.cfg.get("proactive_topic_directions"),
                topic_history=topic_history,
                cfg=bridge.cfg,
                decision_mode=decision_enabled,
            )
            thread_id = bridge.store.get_persona_thread(user_id)
            reply, new_thread_id = await run_with_policy(
                bridge,
                prompt,
                thread_id,
                resolve_policy(bridge.cfg, "casual"),
            )
            if decision_enabled and _reject_proactive_reply(reply):
                mark_proactive_skipped(state, now, source, slot=slot)
                bridge.store.save_proactive_state(user_id, state)
                logging.info("模型判断当前不适合主动开口，跳过（触发源：%s）", source)
                return
            if new_thread_id:
                bridge.store.set_persona_thread(user_id, new_thread_id)
            bridge.store.increment_persona_turns(user_id)
            clean_reply, topic_markers = extract_topic_markers(reply)
            for marker in topic_markers:
                if marker["kind"] == "event" and marker["specific"]:
                    key = f"{marker['category']}|{marker['specific']}"
                    avoid_events = state.setdefault("avoid_events", [])
                    if key not in avoid_events:
                        avoid_events.append(key)
                elif marker["kind"] == "category" and marker["category"]:
                    counts = state.setdefault("category_counts", {})
                    counts[marker["category"]] = (
                        int(counts.get(marker["category"], 0)) + 1
                    )
            await send_reply(
                bridge,
                user_id,
                sanitize_persona_reply(clean_reply),
                persona_mode=True,
                task_mode=False,
            )
            mark_triggered(
                state,
                bridge.cfg,
                now,
                source,
                slot=slot,
                class_key=class_key,
                count=record,
            )
            bridge.store.save_proactive_state(user_id, state)
            logging.info("主动消息已发送给 %s（触发源：%s）", user_id, source)
    except Exception:
        logging.exception("主动消息发送给 %s 失败（触发源：%s）", user_id, source)
        bridge.store.reset_persona(user_id)
    finally:
        bridge.busy_users.discard(user_id)
