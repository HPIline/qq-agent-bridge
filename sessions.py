from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


class SessionStore:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path)
        self._data: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._data = {}
            return
        try:
            with self.path.open(encoding="utf-8") as f:
                self._data = json.load(f)
        except Exception:
            self._data = {}

    def get_thread(self, user_id: str) -> str | None:
        return self._data.get(str(user_id), {}).get("thread_id")

    def set_thread(self, user_id: str, thread_id: str) -> None:
        self._data.setdefault(str(user_id), {})["thread_id"] = thread_id
        self.save()

    def get_persona_thread(self, user_id: str) -> str | None:
        return self._data.get(str(user_id), {}).get("persona_thread_id")

    def set_persona_thread(self, user_id: str, thread_id: str) -> None:
        data = self._data.setdefault(str(user_id), {})
        old = data.get("persona_thread_id")
        data["persona_thread_id"] = thread_id
        if old != thread_id:
            data["persona_turns"] = 0
            data["persona_started_ts"] = time.time()
        self.save()

    def get_persona_turns(self, user_id: str) -> int:
        return int(self._data.get(str(user_id), {}).get("persona_turns", 0))

    def set_persona_turns(self, user_id: str, count: int) -> None:
        self._data.setdefault(str(user_id), {})["persona_turns"] = int(count)
        self.save()

    def increment_persona_turns(self, user_id: str) -> int:
        count = self.get_persona_turns(user_id) + 1
        self.set_persona_turns(user_id, count)
        return count

    def get_persona_started_ts(self, user_id: str) -> float | None:
        value = self._data.get(str(user_id), {}).get("persona_started_ts")
        return float(value) if value else None

    def is_persona(self, user_id: str) -> bool:
        return bool(self._data.get(str(user_id), {}).get("persona", True))

    def set_persona(self, user_id: str, enabled: bool) -> None:
        self._data.setdefault(str(user_id), {})["persona"] = enabled
        self.save()

    def reset(self, user_id: str) -> bool:
        existed = str(user_id) in self._data
        self._data.pop(str(user_id), None)
        if existed:
            self.save()
        return existed

    def get_task_follow(self, user_id: str) -> dict[str, Any]:
        raw = self._data.get(str(user_id), {}).get("task_follow")
        if not isinstance(raw, dict):
            return {"active": False, "last_task_ts": 0.0}
        try:
            last_ts = float(raw.get("last_task_ts") or 0.0)
        except (TypeError, ValueError):
            last_ts = 0.0
        return {"active": bool(raw.get("active")), "last_task_ts": last_ts}

    def mark_task_follow(self, user_id: str, now: float | None = None) -> None:
        data = self._data.setdefault(str(user_id), {})
        data["task_follow"] = {
            "active": True,
            "last_task_ts": float(time.time() if now is None else now),
        }
        self.save()

    def clear_task_follow(self, user_id: str) -> None:
        data = self._data.get(str(user_id))
        if not data or "task_follow" not in data:
            return
        data.pop("task_follow", None)
        self.save()

    def reset_persona(self, user_id: str) -> bool:
        data = self._data.get(str(user_id))
        if not data:
            return False
        existed = "persona_thread_id" in data
        data.pop("persona_thread_id", None)
        data.pop("persona_turns", None)
        data.pop("persona_started_ts", None)
        data.pop("task_follow", None)
        self.save()
        return existed

    def get_proactive_state(self, user_id: str) -> dict[str, Any]:
        return dict(self._data.setdefault(str(user_id), {}).setdefault("proactive", {}))

    def save_proactive_state(self, user_id: str, state: dict[str, Any]) -> None:
        target = self._data.setdefault(str(user_id), {}).setdefault("proactive", {})
        target.clear()
        target.update(state)
        self.save()

    def touch_activity(self, user_id: str) -> None:
        self.mark_activity(user_id)
        self.save()

    def mark_activity(self, user_id: str) -> None:
        """只更新内存活动时间，不立即写盘；配合 batch() 由批量上下文统一落盘。"""
        target = self._data.setdefault(str(user_id), {}).setdefault("proactive", {})
        target["last_active_ts"] = time.time()

    class _SessionBatch:
        def __init__(self, store: SessionStore):
            self.store = store

        def __enter__(self) -> SessionStore:
            self.store._batch_depth = getattr(self.store, "_batch_depth", 0) + 1
            return self.store

        def __exit__(self, *exc: object) -> bool:
            self.store._batch_depth -= 1
            if self.store._batch_depth <= 0:
                self.store._batch_depth = 0
                self.store.save()
            return False

    def batch(self) -> _SessionBatch:
        """批量写盘上下文：期间多次修改只落盘一次。可嵌套。"""
        return self._SessionBatch(self)

    def save(self) -> None:
        if getattr(self, "_batch_depth", 0) > 0:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".sessions-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
