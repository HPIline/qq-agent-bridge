from __future__ import annotations

import asyncio
import logging
from typing import Any

from call_policy import resolve_policy, run_with_policy
from state_db import StateDB


class TaskManager:
    """后台任务队列：持久化任务、顺序执行、状态回写、完成推送。"""

    def __init__(self, bridge: Any, db: StateDB):
        self.bridge = bridge
        self.db = db

    def submit(self, user_id: str, prompt: str, kind: str = "task") -> int:
        return self.db.add_task(user_id, kind, prompt, status="queued")

    def list_tasks(self, user_id: str | None = None) -> list[dict[str, Any]]:
        return self.db.list_tasks(user_id)

    def cancel(self, task_id: int) -> bool:
        tasks = self.db.list_tasks()
        target = next((t for t in tasks if t["id"] == task_id), None)
        if target is None:
            return False
        if target["status"] in ("done", "failed", "cancelled"):
            return True
        self.db.update_task(task_id, status="cancelled", finished_at=_now_iso())
        return True

    async def process_next(self) -> bool:
        queued = [t for t in self.db.list_tasks() if t["status"] == "queued"]
        if not queued:
            return False
        task = queued[0]
        task_id = int(task["id"])
        self.db.update_task(task_id, status="running")
        prompt = str(task["prompt"])
        user_id = str(task["user_id"])
        try:
            reply, thread_id = await run_with_policy(
                self.bridge,
                prompt,
                None,
                resolve_policy(self.bridge.cfg, "task"),
            )
            self.db.update_task(
                task_id,
                status="done",
                result=reply,
                thread_id=str(thread_id or ""),
                finished_at=_now_iso(),
            )
            await self.bridge._send_private(user_id, f"✅ 任务完成：{reply}")
        except Exception as exc:
            logging.exception("后台任务 %s 执行失败", task_id)
            self.db.update_task(
                task_id,
                status="failed",
                error=str(exc),
                finished_at=_now_iso(),
            )
            await self.bridge._send_private(user_id, f"❌ 任务失败：{exc}")
        return True

    async def worker_loop(self, interval: float = 0.5) -> None:
        while True:
            try:
                if not await self.process_next():
                    await asyncio.sleep(interval)
            except Exception:
                logging.exception("任务 worker 循环出错")
                await asyncio.sleep(interval)


def _now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now().isoformat(timespec="seconds")
