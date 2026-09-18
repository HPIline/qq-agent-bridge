"""统一 Web 工作台：聊天 + 提醒/待办/任务/日志/配置管理。

Web 和 QQ 共用同一套命令与处理管线：POST /api/chat 会走 bridge.process_web_message，
因此 QQ 能用的命令在 Web 里也能用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import uvicorn
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from calendar_todos import normalize_todo_text
from scheduler import add_reminder_from_text

_BEARER = HTTPBearer(auto_error=False)


class ChatIn(BaseModel):
    text: str
    session_id: str = "main"


class ReminderIn(BaseModel):
    text: str
    user_id: str = ""


class TodoIn(BaseModel):
    text: str
    user_id: str = ""


class TaskIn(BaseModel):
    text: str
    user_id: str = ""


class SearchIn(BaseModel):
    query: str
    limit: int = 5


class WebPanel:
    def __init__(self, bridge: Any):
        self.bridge = bridge
        self.token = str(bridge.cfg.get("web_token") or "dev-token-change-me")
        self.app = FastAPI(title="QQ Bridge Workbench")
        self._register_routes()

    def _require_auth(
        self,
        credentials: HTTPAuthorizationCredentials | None = Depends(_BEARER),  # noqa: B008
    ) -> None:
        if credentials is None or credentials.credentials != self.token:
            raise HTTPException(status_code=401, detail="Unauthorized")

    def _owner(self, user_id: str = "") -> str:
        if user_id:
            return user_id
        owners = self.bridge.cfg.get("full_access_qq") or []
        return str(owners[0]) if owners else "web-main"

    def _register_routes(self) -> None:
        app = self.app
        bridge = self.bridge

        @app.get("/")
        async def index() -> FileResponse:
            static = Path(__file__).resolve().parent / "web_panel" / "static" / "index.html"
            return FileResponse(str(static))

        @app.get("/api/status", dependencies=[Depends(self._require_auth)])
        async def api_status() -> dict[str, Any]:
            return {
                "status": "ok",
                "bot": "qq-agent-bridge",
                "ws_connected": bridge.ws is not None,
                "owner": self._owner(),
            }

        @app.get("/api/reminders", dependencies=[Depends(self._require_auth)])
        async def api_reminders(user_id: str = "") -> dict[str, Any]:
            return {"reminders": bridge.state_db.list_reminders(self._owner(user_id))}

        @app.post("/api/reminders", dependencies=[Depends(self._require_auth)])
        async def api_reminder_create(body: ReminderIn) -> dict[str, Any]:
            owner = self._owner(body.user_id)
            message = add_reminder_from_text(bridge.state_db, owner, body.text)
            return {"message": message}

        @app.get("/api/todos", dependencies=[Depends(self._require_auth)])
        async def api_todos(user_id: str = "") -> dict[str, Any]:
            return {"todos": bridge.state_db.list_todos(self._owner(user_id))}

        @app.post("/api/todos", dependencies=[Depends(self._require_auth)])
        async def api_todo_create(body: TodoIn) -> dict[str, Any]:
            owner = self._owner(body.user_id)
            cleaned, due_at = normalize_todo_text(body.text)
            if not cleaned:
                raise HTTPException(status_code=400, detail="待办内容不能为空")
            todo_id = bridge.state_db.add_todo(owner, cleaned, due_at)
            return {"id": todo_id, "message": f"已添加待办：{cleaned}"}

        @app.get("/api/tasks", dependencies=[Depends(self._require_auth)])
        async def api_tasks(user_id: str = "") -> dict[str, Any]:
            return {"tasks": bridge.task_manager.list_tasks(self._owner(user_id) or None)}

        @app.post("/api/tasks", dependencies=[Depends(self._require_auth)])
        async def api_task_create(body: TaskIn) -> dict[str, Any]:
            owner = self._owner(body.user_id)
            task_id = bridge.task_manager.submit(owner, body.text, kind="task")
            return {"id": task_id, "message": f"任务已加入后台队列 #{task_id}"}

        @app.post("/api/knowledge/search", dependencies=[Depends(self._require_auth)])
        async def api_knowledge_search(body: SearchIn) -> dict[str, Any]:
            try:
                from rag import search_knowledge

                return {"results": search_knowledge(bridge.state_db, body.query, body.limit)}
            except Exception:
                return {"results": [], "notice": "知识库尚未构建，请在 QQ 发送 /知识库 重建"}

        @app.get("/api/logs", dependencies=[Depends(self._require_auth)])
        async def api_logs(limit: int = 200) -> dict[str, Any]:
            log_path = Path(bridge.bridge_dir) / bridge.cfg.get("log_file", "bridge.log")
            lines: list[str] = []
            if log_path.exists():
                try:
                    with log_path.open(encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()[-max(1, min(limit, 2000)) :]
                except Exception:
                    lines = []
            return {"lines": [x.rstrip("\n") for x in lines]}

        @app.get("/api/config", dependencies=[Depends(self._require_auth)])
        async def api_config() -> dict[str, Any]:
            sensitive_keys = ("api_key", "token", "password", "secret")
            safe = {
                k: v
                for k, v in bridge.cfg.items()
                if not any(s in k.lower() for s in sensitive_keys)
            }
            return safe

        @app.post("/api/chat", dependencies=[Depends(self._require_auth)])
        async def api_chat(body: ChatIn) -> dict[str, Any]:
            web_user_id = f"web-{body.session_id}"
            replies = await bridge.process_web_message(web_user_id, body.text)
            return {"replies": replies}

        # 命令与聊天走同一个入口，让 Web 和 QQ 行为完全一致。
        @app.post("/api/command", dependencies=[Depends(self._require_auth)])
        async def api_command(body: ChatIn) -> dict[str, Any]:
            web_user_id = f"web-{body.session_id}"
            replies = await bridge.process_web_message(web_user_id, body.text)
            return {"replies": replies}


async def start_web_panel(bridge: Any) -> None:
    panel = WebPanel(bridge)
    config = uvicorn.Config(
        panel.app,
        host=str(bridge.cfg.get("web_host", "0.0.0.0")),
        port=int(bridge.cfg.get("web_port", 8080)),
        log_level="warning",
    )
    server = uvicorn.Server(config)
    await server.serve()
