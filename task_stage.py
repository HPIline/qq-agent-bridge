"""大任务分阶段：超时汇报、继续/停止确认、跨阶段续跑。"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from agent_client import AgentError
from call_policy import resolve_policy, run_with_policy
from message_utils import chunk_reply


async def start_task_stage(
    bridge: Any,
    user_id: str,
    original_prompt: str,
    thread_id: str,
    stage: int,
) -> None:
    summary = ""
    if thread_id:
        try:
            summary, _ = await bridge.agent.run(
                "请总结这个任务线程目前已经完成的部分和下一步计划，200 字以内，直接输出。",
                thread_id,
                reasoning_effort="low",
                timeout=int(bridge.cfg.get("task_stage_summary_timeout", 120)),
            )
        except Exception as exc:
            logging.warning("任务阶段进度总结失败：%s", exc)
    report = (
        f"……大任务第 {stage} 阶段到时间了，我先汇报：\n"
        + (summary.strip() or "目前进度暂时总结不出来，但任务线程已保留。")
        + "\n回复“继续”我就接着干，回复“停止”就到这里。"
    )
    await bridge._send_private(user_id, report)
    bridge._write_pending_task_stage(user_id, original_prompt, thread_id, stage)
    logging.info("任务阶段 %s 已进入等待确认（thread=%s）", stage, thread_id)


async def resume_task_stage(bridge: Any, user_id: str) -> None:
    async with bridge._user_lock(user_id):
        with bridge.store.batch():
            try:
                data = json.loads(bridge.pending_path.read_text(encoding="utf-8"))
            except Exception:
                return
            if not isinstance(data, dict) or data.get("kind") != "task_stage":
                return
            if data.get("status") != "answered":
                return
            reply_text = str(data.get("reply") or "").strip()
            thread_id = str(data.get("thread_id") or "")
            original = str(data.get("original_prompt") or "")
            stage = int(data.get("stage", 1))
            stop_words = bridge.cfg.get(
                "task_stage_stop_keywords",
                ["停止", "停", "不要", "算了", "取消", "no", "0"],
            )
            if any(word in reply_text for word in stop_words):
                await bridge._send_private(user_id, "……好，任务先到这里。")
                bridge._clear_task_pending()
                return
            continue_words = bridge.cfg.get(
                "task_stage_continue_keywords",
                ["继续", "可以", "好", "嗯", "ok", "yes", "1"],
            )
            if not any(word in reply_text.lower() for word in continue_words):
                await bridge._send_private(user_id, "……没看懂，回复“继续”我就接着干。")
                data["status"] = "waiting"
                data.pop("reply", None)
                data.pop("replied_at", None)
                bridge.pending_path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                return
            next_stage = stage + 1
            max_stages = int(bridge.cfg.get("task_stage_max", 10))
            if next_stage > max_stages:
                await bridge._send_private(
                    user_id,
                    f"……任务已经超过 {max_stages} 个阶段，建议开新任务。",
                )
                bridge._clear_task_pending()
                return
            bridge._clear_task_pending()
            continue_prompt = (
                "用户已确认继续。请接着完成之前未完成的任务，不要重复已完成的部分，直接继续干活。\n"
                f"原任务：{original}\n"
                "如果本阶段又接近超时，把当前进度整理好，任务线程会自动保留，下个阶段继续。"
            )
            try:
                reply, new_thread_id = await run_with_policy(
                    bridge,
                    continue_prompt,
                    thread_id,
                    resolve_policy(bridge.cfg, "task"),
                )
            except AgentError as exc:
                if getattr(exc, "timeout", False):
                    resumed_thread = getattr(exc, "thread_id", None) or thread_id
                    if resumed_thread:
                        if bridge.store.is_persona(user_id):
                            bridge.store.set_persona_thread(user_id, resumed_thread)
                        else:
                            bridge.store.set_thread(user_id, resumed_thread)
                    await start_task_stage(bridge, user_id, original, resumed_thread, next_stage)
                else:
                    await bridge._send_private(user_id, "……这个阶段处理出错了，请再试一次。")
                return
            if new_thread_id:
                if bridge.store.is_persona(user_id):
                    bridge.store.set_persona_thread(user_id, new_thread_id)
                else:
                    bridge.store.set_thread(user_id, new_thread_id)
            for segment in chunk_reply(reply, int(bridge.cfg.get("chunk_limit", 3800))):
                await bridge._send_private(user_id, segment)
                await asyncio.sleep(float(bridge.cfg.get("chunk_delay_sec", 0.5)))
