from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    remind_at TEXT NOT NULL,
    repeat TEXT NOT NULL DEFAULT 'none',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    due_at TEXT NOT NULL DEFAULT '',
    done INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    schedule TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    next_run TEXT NOT NULL DEFAULT '',
    last_run TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'task',
    prompt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    result TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    thread_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    finished_at TEXT NOT NULL DEFAULT ''
);
CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
    path UNINDEXED,
    title,
    content
);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, remind_at);
CREATE INDEX IF NOT EXISTS idx_todos_user ON todos(user_id, done);
CREATE INDEX IF NOT EXISTS idx_jobs_next_run ON jobs(enabled, next_run);
CREATE INDEX IF NOT EXISTS idx_tasks_user_status ON tasks(user_id, status);
"""

_TASK_FIELDS = {
    "status",
    "result",
    "error",
    "thread_id",
    "finished_at",
}


def _now_iso() -> str:
    import datetime as _dt

    return _dt.datetime.now().isoformat(timespec="seconds")


def _dicts(cursor: sqlite3.Cursor) -> list[dict[str, Any]]:
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row, strict=False)) for row in cursor.fetchall()]


class StateDB:
    """统一 SQLite 状态库：提醒 / 待办 / 定时任务 / 后台任务 / 知识库索引。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._closed = False
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            rows = _dicts(cur)
            return rows

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return int(cur.lastrowid or 0)

    # ---- reminders ----

    def create_reminder(
        self,
        user_id: str,
        text: str,
        remind_at: str,
        repeat: str = "none",
    ) -> int:
        return self._execute(
            "INSERT INTO reminders (user_id, text, remind_at, repeat, status, created_at)"
            " VALUES (?, ?, ?, ?, 'active', ?)",
            (user_id, text, remind_at, repeat, _now_iso()),
        )

    def list_due_reminders(self, now: str) -> list[dict[str, Any]]:
        return self._query(
            "SELECT * FROM reminders WHERE status = 'active' AND remind_at <= ? ORDER BY remind_at",
            (now,),
        )

    def list_reminders(self, user_id: str) -> list[dict[str, Any]]:
        return self._query(
            "SELECT * FROM reminders WHERE user_id = ? ORDER BY status ASC, remind_at ASC",
            (user_id,),
        )

    def cancel_reminder(self, reminder_id: int) -> None:
        self._execute("UPDATE reminders SET status = 'done' WHERE id = ?", (reminder_id,))

    def mark_reminder_done(self, reminder_id: int) -> None:
        self._execute("UPDATE reminders SET status='done' WHERE id = ?", (reminder_id,))

    def set_reminder_next(self, reminder_id: int, next_at: str) -> None:
        self._execute(
            "UPDATE reminders SET remind_at = ?, status = 'active' WHERE id = ?",
            (next_at, reminder_id),
        )

    # ---- todos ----

    def add_todo(self, user_id: str, text: str, due_at: str = "") -> int:
        return self._execute(
            "INSERT INTO todos (user_id, text, due_at, done, created_at) VALUES (?, ?, ?, 0, ?)",
            (user_id, text, due_at, _now_iso()),
        )

    def list_todos(self, user_id: str) -> list[dict[str, Any]]:
        return self._query(
            "SELECT * FROM todos WHERE user_id = ? ORDER BY done ASC, due_at ASC, id DESC",
            (user_id,),
        )

    def complete_todo(self, todo_id: int) -> None:
        self._execute("UPDATE todos SET done = 1 WHERE id = ?", (todo_id,))

    def delete_todo(self, todo_id: int) -> None:
        self._execute("DELETE FROM todos WHERE id = ?", (todo_id,))

    # ---- scheduled jobs ----

    def add_job(
        self,
        name: str,
        schedule: str,
        payload: dict[str, Any] | None = None,
        next_run: str = "",
    ) -> int:
        payload_json = json.dumps(payload or {}, ensure_ascii=False)
        return self._execute(
            "INSERT INTO jobs (name, schedule, payload, enabled, next_run, created_at)"
            " VALUES (?, ?, ?, 1, ?, ?)",
            (name, schedule, payload_json, next_run, _now_iso()),
        )

    def list_due_jobs(self, now: str) -> list[dict[str, Any]]:
        rows = self._query(
            "SELECT * FROM jobs WHERE enabled = 1 AND next_run != '' AND next_run <= ?"
            " ORDER BY next_run",
            (now,),
        )
        for row in rows:
            try:
                row["payload"] = json.loads(row.get("payload") or "{}")
            except json.JSONDecodeError:
                row["payload"] = {}
        return rows

    def set_job_next_run(self, job_id: int, next_run: str) -> None:
        self._execute(
            "UPDATE jobs SET next_run = ?, last_run = ? WHERE id = ?",
            (next_run, _now_iso(), job_id),
        )

    # ---- background tasks ----

    def add_task(
        self,
        user_id: str,
        kind: str,
        prompt: str,
        status: str = "queued",
    ) -> int:
        return self._execute(
            "INSERT INTO tasks (user_id, kind, prompt, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, kind, prompt, status, _now_iso()),
        )

    def update_task(self, task_id: int, **fields: Any) -> None:
        allowed = {k: v for k, v in fields.items() if k in _TASK_FIELDS}
        if not allowed:
            return
        sets = ", ".join(f"{key} = ?" for key in allowed)
        self._execute(
            f"UPDATE tasks SET {sets} WHERE id = ?",
            (*allowed.values(), task_id),
        )

    def list_tasks(self, user_id: str | None = None) -> list[dict[str, Any]]:
        if user_id:
            return self._query(
                "SELECT * FROM tasks WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            )
        return self._query("SELECT * FROM tasks ORDER BY id DESC")

    # ---- knowledge base ----

    def add_document(
        self,
        path: str,
        chunk_index: int,
        title: str,
        content: str,
    ) -> None:
        self._execute(
            "INSERT INTO knowledge_fts (path, title, content) VALUES (?, ?, ?)",
            (f"{path}#{chunk_index}", title, content),
        )

    def search_documents(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        trimmed = query.strip()
        if not trimmed:
            return []
        try:
            fts_query = '"' + trimmed.replace('"', '""') + '"'
            rows = self._query(
                "SELECT path, title, snippet(knowledge_fts, 2, '…', '…', '…', 12) AS snippet"
                " FROM knowledge_fts WHERE knowledge_fts MATCH ? ORDER BY rank LIMIT ?",
                (fts_query, int(limit)),
            )
        except sqlite3.OperationalError:
            rows = []
        if rows:
            return rows
        # FTS5 对中文/复杂查询可能不命中时退化为 LIKE 子串搜索。
        like = f"%{trimmed}%"
        return self._query(
            "SELECT path, title, substr(content, 1, 200) AS snippet"
            " FROM knowledge_fts WHERE title LIKE ? OR content LIKE ?"
            " ORDER BY rowid DESC LIMIT ?",
            (like, like, int(limit)),
        )

    def clear_documents(self) -> None:
        self._execute("DELETE FROM knowledge_fts")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True

    def __enter__(self) -> StateDB:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
