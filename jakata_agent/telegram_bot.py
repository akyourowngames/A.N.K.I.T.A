from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

from jakata_agent.agent import JakataAgent
from jakata_agent.prompts import load_prompt
from jakata_agent.runtime import JakataRuntime, create_runtime
from jakata_agent.tasks.models import DEFAULT_TASK_ACTION_LIMIT, DEFAULT_TASK_BUDGET_MINUTES, DEFAULT_TASK_REPAIR_LIMIT, utcnow_iso
from jakata_agent.telegram_artifacts import ArtifactError, ArtifactRecord, TelegramArtifactService
from jakata_agent.tools.registry import ToolRegistry
from jakata_agent.tools.telegram_send import TelegramSendTool


GUEST_SYSTEM_PROMPT = load_prompt("telegram/guest.md")


GUEST_HELP_TEXT = """JAKATA Telegram help

Guest mode:
- Type normal chat messages.
- Try: "what can you do?", "explain this topic", "help me write a message".
- Private PC control, files, screenshots, reports, and tasks are locked.

Commands:
/help - show this help
/admin - how admin unlock works
/unlock <password> - unlock owner/admin mode
"""


ADMIN_HELP_TEXT = """JAKATA admin commands

Natural control:
- Send a normal message to use the same JAKATA agent path as CLI, including chat and tools.
- Ask naturally to send files/images back here; JAKATA will use Telegram delivery when the planner selects it.
- Use the file/screenshot/image commands only when you explicitly want Telegram to send an attachment.

Tasks:
/task <goal>
/tasks
/details <task_id>
/approve <id>
/deny <id>
/cancel <task_id>

PC and files:
/screen
/sendfile <path>
/senddir <path>
/ls <path>
/findfile <query>
/outputs
/download <artifact_id>

Reports:
/report <task_id>
/export <task_id> md|json|zip
/logs <task_id>

Uploads and images:
Send a document/photo to store it on the PC.
/put <artifact_or_upload_id> <pc_path>
/img <prompt>
/imgfile <prompt>

Session:
/lock
"""


ADMIN_UNLOCK_TEXT = """Admin mode is locked.

To unlock:
/unlock <password>

After unlock, send /help to see private task, file, report, screenshot, and image commands.
The admin session expires automatically after the configured timeout.
"""


def _utcnow() -> datetime:
    return datetime.utcnow()


@dataclass
class TelegramAuthManager:
    password: str = ""
    password_hash: str = ""
    session_ttl_minutes: int = 720
    guest_daily_limit: int = 50
    _sessions: dict[int, datetime] = field(default_factory=dict)
    _guest_counts: dict[tuple[int, str], int] = field(default_factory=dict)

    def unlock(self, user_id: int, password: str) -> bool:
        if not self._password_matches(password):
            return False
        self._sessions[user_id] = _utcnow() + timedelta(minutes=max(1, self.session_ttl_minutes))
        return True

    def lock(self, user_id: int) -> None:
        self._sessions.pop(user_id, None)

    def is_admin(self, user_id: int) -> bool:
        expires_at = self._sessions.get(user_id)
        if expires_at is None:
            return False
        if expires_at <= _utcnow():
            self._sessions.pop(user_id, None)
            return False
        return True

    def can_guest_chat(self, user_id: int) -> bool:
        today = _utcnow().strftime("%Y-%m-%d")
        key = (user_id, today)
        count = self._guest_counts.get(key, 0)
        if count >= max(0, self.guest_daily_limit):
            return False
        self._guest_counts[key] = count + 1
        return True

    def _password_matches(self, password: str) -> bool:
        provided = password.strip()
        if self.password:
            return hmac.compare_digest(provided, self.password)
        if self.password_hash:
            digest = hashlib.sha256(provided.encode("utf-8")).hexdigest()
            return hmac.compare_digest(digest, self.password_hash.lower())
        return False


def build_auth_manager(runtime: JakataRuntime) -> TelegramAuthManager:
    settings = runtime.settings
    return TelegramAuthManager(
        password=settings.telegram_admin_password,
        password_hash=settings.telegram_admin_password_hash,
        session_ttl_minutes=settings.telegram_session_ttl_minutes,
        guest_daily_limit=settings.telegram_guest_daily_limit,
    )


def split_message(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        chunks.append(remaining[:limit])
        remaining = remaining[limit:]
    return chunks


@dataclass(slots=True)
class TelegramWorkItem:
    update: Any
    description: str
    run: Callable[[], Awaitable[None]]


class TelegramBotController:
    def __init__(self, runtime: JakataRuntime, auth: TelegramAuthManager | None = None) -> None:
        self.runtime = runtime
        self.auth = auth or build_auth_manager(runtime)
        self.artifacts = TelegramArtifactService(runtime.settings, runtime.task_store)
        self._foreground_queue: asyncio.Queue[TelegramWorkItem] | None = None
        self._foreground_worker: asyncio.Task | None = None
        self._foreground_loop: asyncio.AbstractEventLoop | None = None
        self._active_description = ""
        self._active_started_at: datetime | None = None
        self.agent = getattr(runtime, "agent", None) or self._build_agent(runtime, self._telegram_tool_registry(runtime))

    @staticmethod
    def _build_agent(runtime: JakataRuntime, tools: ToolRegistry | None = None) -> JakataAgent | None:
        required = ("settings", "client", "tools", "memory", "router", "validator", "task_store")
        if not all(hasattr(runtime, name) for name in required):
            return None
        return JakataAgent(
            settings=runtime.settings,
            client=runtime.client,
            tools=tools or runtime.tools,
            memory=runtime.memory,
            router=runtime.router,
            validator=runtime.validator,
            task_store=runtime.task_store,
            task_engine=getattr(runtime, "task_engine", None),
        )

    def _telegram_tool_registry(self, runtime: JakataRuntime) -> ToolRegistry | None:
        base = getattr(runtime, "tools", None)
        if not isinstance(base, ToolRegistry):
            return None
        registry = ToolRegistry()
        for tool in base._tools.values():
            registry.register(tool)
        registry.register(TelegramSendTool(self.artifacts))
        return registry

    async def start(self, update, context) -> None:
        await self.help(update, context)

    async def help(self, update, context) -> None:
        del context
        if self.auth.is_admin(self._user_id(update)):
            await self._reply(update, ADMIN_HELP_TEXT)
            return
        await self._reply(update, GUEST_HELP_TEXT)

    async def admin(self, update, context) -> None:
        del context
        if self.auth.is_admin(self._user_id(update)):
            await self._reply(update, "Admin mode is active.\n\n" + ADMIN_HELP_TEXT)
            return
        if not self.auth.password and not self.auth.password_hash:
            await self._reply(
                update,
                "Admin mode is locked, but no admin password is configured on this bot. Set JAKATA_TELEGRAM_ADMIN_PASSWORD or JAKATA_TELEGRAM_ADMIN_PASSWORD_HASH in .env.",
            )
            return
        await self._reply(update, ADMIN_UNLOCK_TEXT)

    async def unlock(self, update, context) -> None:
        user_id = self._user_id(update)
        password = " ".join(context.args or []).strip()
        if not password:
            await self._reply(update, ADMIN_UNLOCK_TEXT)
            return
        if self.auth.unlock(user_id, password):
            await self._reply(update, "Admin mode unlocked for this Telegram session.\n\n" + ADMIN_HELP_TEXT)
            return
        await self._reply(update, "Password did not match.")

    async def lock(self, update, context) -> None:
        del context
        self.auth.lock(self._user_id(update))
        await self._reply(update, "Admin mode locked.")

    async def task(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        goal = " ".join(context.args or []).strip()
        if not goal:
            await self._reply(update, "Usage: /task <goal>")
            return
        await self._run_task(update, goal)

    async def tasks(self, update, context) -> None:
        del context
        if not await self._require_admin(update):
            return
        tasks = self.runtime.task_store.list_tasks(limit=10)
        if not tasks:
            await self._reply(update, "No tasks yet.")
            return
        lines = []
        for task in tasks:
            summary = task.result_summary or task.last_error or task.pending_approval.get("summary", "")
            lines.append(f"{task.id} [{task.status}] {summary[:160]}")
        await self._reply(update, "\n".join(lines))

    async def details(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        token = " ".join(context.args or []).strip()
        task = self.runtime.task_store.get_task(token)
        if task is None:
            await self._reply(update, f"Task not found: {token}")
            return
        events = self.runtime.task_store.list_events(task.id, limit=20)
        lines = [
            f"Task: {task.id}",
            f"Status: {task.status}",
            f"Goal: {task.goal}",
            f"Result: {task.result_summary or '-'}",
            f"Error: {task.last_error or '-'}",
        ]
        if task.pending_approval:
            lines.append(f"Approval: {task.pending_approval.get('id')} {task.pending_approval.get('summary')}")
        if task.final_report:
            lines.append(f"\nReport:\n{task.final_report}")
        if events:
            lines.append("\nRecent events:")
            for event in events[-8:]:
                lines.append(f"- {event.event_type}: {str(event.payload)[:240]}")
        await self._reply(update, "\n".join(lines))

    async def approve(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        token = " ".join(context.args or []).strip()
        if not token:
            await self._reply(update, "Usage: /approve <approval_id_or_task_id>")
            return
        if await self._approve_artifact_action(update, token):
            return
        result = await asyncio.to_thread(
            self.runtime.task_engine.approve_and_resume,
            token,
            actor=f"telegram:{self._user_id(update)}",
        )
        if result is None:
            await self._reply(update, f"Approval not found: {token}")
            return
        await self._reply(update, result.report)

    async def deny(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        token = " ".join(context.args or []).strip()
        if not token:
            await self._reply(update, "Usage: /deny <approval_id_or_task_id>")
            return
        result = self.runtime.task_engine.deny(token, actor=f"telegram:{self._user_id(update)}")
        if result is None:
            await self._reply(update, f"Approval not found: {token}")
            return
        await self._reply(update, result.report)

    async def cancel(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        token = " ".join(context.args or []).strip()
        task = self.runtime.task_store.cancel_task(token)
        if task is None:
            await self._reply(update, f"Task not found: {token}")
            return
        await self._reply(update, f"Task {task.id} is {task.status}.")

    async def screen(self, update, context) -> None:
        del context
        if not await self._require_admin(update):
            return
        await self._enqueue_foreground_work(
            update,
            "capture and send screenshot",
            lambda: self._capture_and_send_screen(update),
        )

    async def sendfile(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        raw_path = " ".join(context.args or []).strip()
        if not raw_path:
            await self._reply(update, "Usage: /sendfile <path>")
            return
        await self._enqueue_foreground_work(
            update,
            f"send file: {raw_path}",
            lambda: self._sendfile_now(update, raw_path),
        )

    async def _sendfile_now(self, update, raw_path: str) -> None:
        try:
            path = self.artifacts.resolve_path(raw_path)
            if not path.exists() or not path.is_file():
                await self._reply(update, f"File not found: {path}")
                return
            if not self.artifacts.is_safe_path(path):
                await self._request_artifact_approval(
                    update,
                    kind="telegram_sendfile",
                    summary=f"Upload file outside safe roots: {path}",
                    payload={"command": "sendfile", "path": str(path)},
                )
                return
            await self._send_path_file(update, path)
        except ArtifactError as exc:
            await self._reply(update, str(exc))

    async def senddir(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        raw_path = " ".join(context.args or []).strip()
        if not raw_path:
            await self._reply(update, "Usage: /senddir <path>")
            return
        await self._enqueue_foreground_work(
            update,
            f"send directory: {raw_path}",
            lambda: self._senddir_now(update, raw_path),
        )

    async def _senddir_now(self, update, raw_path: str) -> None:
        try:
            path = self.artifacts.resolve_path(raw_path)
            if not path.exists() or not path.is_dir():
                await self._reply(update, f"Directory not found: {path}")
                return
            if not self.artifacts.is_safe_path(path):
                await self._request_artifact_approval(
                    update,
                    kind="telegram_senddir",
                    summary=f"Zip and upload directory outside safe roots: {path}",
                    payload={"command": "senddir", "path": str(path)},
                )
                return
            await self._send_path_directory(update, path)
        except ArtifactError as exc:
            await self._reply(update, str(exc))

    async def ls(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        raw_path = " ".join(context.args or []).strip() or "."
        try:
            await self._reply(update, self.artifacts.list_directory(raw_path))
        except ArtifactError as exc:
            await self._reply(update, str(exc))

    async def findfile(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        query = " ".join(context.args or []).strip()
        await self._enqueue_foreground_work(
            update,
            f"find file: {query or '*'}",
            lambda: self._findfile_now(update, query),
        )

    async def _findfile_now(self, update, query: str) -> None:
        try:
            matches = self.artifacts.find_files(query)
        except ArtifactError as exc:
            await self._reply(update, str(exc))
            return
        if not matches:
            await self._reply(update, "No matching files found in safe roots.")
            return
        await self._reply(update, "\n".join(matches[:50]))

    async def outputs(self, update, context) -> None:
        del context
        if not await self._require_admin(update):
            return
        records = self.artifacts.list_artifacts(limit=20)
        if not records:
            await self._reply(update, "No Telegram artifacts yet.")
            return
        lines = ["Recent artifacts:"]
        for record in records:
            lines.append(f"{record.id} [{record.kind}] {record.title} ({record.size_bytes} bytes)")
        await self._reply(update, "\n".join(lines))

    async def download(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        artifact_id = " ".join(context.args or []).strip()
        if not artifact_id:
            await self._reply(update, "Usage: /download <artifact_id>")
            return
        await self._enqueue_foreground_work(
            update,
            f"download artifact: {artifact_id}",
            lambda: self._download_now(update, artifact_id),
        )

    async def _download_now(self, update, artifact_id: str) -> None:
        record = self.artifacts.get_artifact(artifact_id)
        if record is None:
            await self._reply(update, f"Artifact not found: {artifact_id}")
            return
        await self._send_artifact(update, self.artifacts.sendable_or_manifest(record))

    async def report(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        task_id = " ".join(context.args or []).strip()
        if not task_id:
            await self._reply(update, "Usage: /report <task_id>")
            return
        await self._enqueue_foreground_work(
            update,
            f"export report: {task_id}",
            lambda: self._report_now(update, task_id),
        )

    async def _report_now(self, update, task_id: str) -> None:
        task = self.runtime.task_store.get_task(task_id)
        if task is None:
            await self._reply(update, f"Task not found: {task_id}")
            return
        await self._reply(update, f"{task.id} [{task.status}] {task.result_summary or task.last_error or task.goal}")
        try:
            record = self.artifacts.export_task(task.id, "md")
            await self._send_artifact(update, record)
        except ArtifactError as exc:
            await self._reply(update, str(exc))

    async def export(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        args = list(context.args or [])
        if len(args) < 2:
            await self._reply(update, "Usage: /export <task_id> md|json|zip")
            return
        task_id, fmt = args[0], args[1]
        await self._enqueue_foreground_work(
            update,
            f"export task {task_id} as {fmt}",
            lambda: self._export_now(update, task_id, fmt),
        )

    async def _export_now(self, update, task_id: str, fmt: str) -> None:
        try:
            record = self.artifacts.export_task(task_id, fmt)
            await self._send_artifact(update, record)
        except ArtifactError as exc:
            await self._reply(update, str(exc))

    async def logs(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        task_id = " ".join(context.args or []).strip()
        if not task_id:
            await self._reply(update, "Usage: /logs <task_id>")
            return
        await self._enqueue_foreground_work(
            update,
            f"export task logs: {task_id}",
            lambda: self._logs_now(update, task_id),
        )

    async def _logs_now(self, update, task_id: str) -> None:
        try:
            record = self.artifacts.create_json_artifact(
                f"task-{task_id}-logs",
                self.artifacts.task_logs_payload(task_id),
                kind="task_logs",
            )
            await self._send_artifact(update, record)
        except ArtifactError as exc:
            await self._reply(update, str(exc))

    async def put(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        args = list(context.args or [])
        if len(args) < 2:
            await self._reply(update, "Usage: /put <artifact_or_upload_id> <pc_path>")
            return
        artifact_id = args[0]
        target_raw = " ".join(args[1:])
        await self._enqueue_foreground_work(
            update,
            f"put artifact {artifact_id}: {target_raw}",
            lambda: self._put_now(update, artifact_id, target_raw),
        )

    async def _put_now(self, update, artifact_id: str, target_raw: str) -> None:
        try:
            target = self.artifacts.resolve_path(target_raw)
            if not self.artifacts.is_safe_path(target):
                await self._request_artifact_approval(
                    update,
                    kind="telegram_put",
                    summary=f"Write Telegram artifact to path outside safe roots: {target}",
                    payload={"command": "put", "artifact_id": artifact_id, "target_path": str(target)},
                )
                return
            await self._put_artifact(update, artifact_id, str(target))
        except ArtifactError as exc:
            await self._reply(update, str(exc))

    async def img(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        prompt = " ".join(context.args or []).strip()
        if not prompt:
            await self._reply(update, "Usage: /img <prompt>")
            return
        await self._enqueue_foreground_work(
            update,
            f"generate image: {prompt}",
            lambda: self._generate_image(update, prompt, send_as_document=False),
        )

    async def imgfile(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        prompt = " ".join(context.args or []).strip()
        if not prompt:
            await self._reply(update, "Usage: /imgfile <prompt>")
            return
        await self._enqueue_foreground_work(
            update,
            f"generate image file: {prompt}",
            lambda: self._generate_image(update, prompt, send_as_document=True),
        )

    async def upload(self, update, context) -> None:
        if not await self._require_admin(update):
            return
        message = getattr(update, "message", None)
        if message is None:
            return
        document = getattr(message, "document", None)
        photos = list(getattr(message, "photo", []) or [])
        if document is None and not photos:
            return
        try:
            user_id = self._user_id(update)
            if document is not None:
                file_id = document.file_id
                filename = document.file_name or f"document-{getattr(document, 'file_unique_id', uuid.uuid4().hex)}"
                kind = "upload"
            else:
                photo = photos[-1]
                file_id = photo.file_id
                filename = f"photo-{getattr(photo, 'file_unique_id', uuid.uuid4().hex)}.jpg"
                kind = "photo_upload"
            target = self.artifacts.prepare_upload_path(telegram_user_id=user_id, filename=filename)
            telegram_file = await context.bot.get_file(file_id)
            await telegram_file.download_to_drive(custom_path=str(target))
            record = self.artifacts.record_upload(target, telegram_user_id=user_id, kind=kind)
            await self._reply(update, f"Saved upload as artifact {record.id}: {target}")
        except Exception as exc:  # noqa: BLE001
            await self._reply(update, f"Upload failed: {exc}")

    async def message(self, update, context) -> None:
        text = (update.message.text or "").strip()
        if not text:
            return
        if self.auth.is_admin(self._user_id(update)):
            await self._reply_as_agent(update, text)
            return
        if not self.auth.can_guest_chat(self._user_id(update)):
            await self._reply(update, "Guest chat limit reached for today. Unlock admin mode to continue.")
            return
        model, reply = await asyncio.to_thread(
            self.runtime.client.complete,
            [{"role": "system", "content": GUEST_SYSTEM_PROMPT}, {"role": "user", "content": text}],
        )
        del model
        await self._reply(update, reply)

    async def _run_task(self, update, goal: str) -> None:
        await self._enqueue_foreground_work(
            update,
            goal,
            lambda: self._run_task_now(update, goal),
        )

    async def _run_task_now(self, update, goal: str) -> None:
        session_id = f"telegram-{self._user_id(update)}"
        context = self.runtime.memory.retrieve(goal).to_system_context()
        result = await asyncio.to_thread(
            self.runtime.task_engine.run_foreground_task,
            goal=goal,
            session_id=session_id,
            context=context,
        )
        await self._reply(update, result.report)
        await self._send_task_outputs(update, result.task.id)

    async def _reply_as_agent(self, update, text: str) -> None:
        if self.agent is None:
            model, reply = await asyncio.to_thread(
                self.runtime.client.complete,
                [{"role": "system", "content": GUEST_SYSTEM_PROMPT}, {"role": "user", "content": text}],
            )
            del model
            await self._reply(update, reply)
            return
        if hasattr(self.agent, "respond"):
            response = await asyncio.to_thread(self.agent.respond, text)
            sent = await self._send_agent_telegram_attachments(update, getattr(response, "tool_results", []))
            if not sent:
                await self._reply(update, response.content)
            return
        model, reply = await asyncio.to_thread(self.agent.reply, text)
        del model
        await self._reply(update, reply)

    async def _send_agent_telegram_attachments(self, update, tool_results: list[dict[str, Any]]) -> bool:
        sent_any = False
        for result in tool_results:
            if result.get("tool") != "telegram_send" or not result.get("ok"):
                continue
            data = result.get("data", {})
            records = data.get("records", []) if isinstance(data, dict) else []
            if not isinstance(records, list):
                continue
            for item in records:
                if not isinstance(item, dict):
                    continue
                record = ArtifactRecord(
                    id=str(item.get("id", "")),
                    kind=str(item.get("kind", "")),
                    title=str(item.get("title", "")),
                    path=str(item.get("path", "")),
                    size_bytes=int(item.get("size_bytes", 0) or 0),
                    mime_type=str(item.get("mime_type", "application/octet-stream")),
                    source=str(item.get("source", "")),
                    created_at=str(item.get("created_at", "")),
                    extra=item.get("extra") if isinstance(item.get("extra"), dict) else {},
                )
                await self._send_artifact(update, self.artifacts.sendable_or_manifest(record), as_photo=bool(item.get("as_photo", False)))
                sent_any = True
        return sent_any

    async def _enqueue_foreground_work(
        self,
        update,
        description: str,
        run: Callable[[], Awaitable[None]],
    ) -> None:
        queue = self._ensure_foreground_worker()
        waiting_ahead = queue.qsize() + (1 if self._active_description else 0)
        await queue.put(TelegramWorkItem(update=update, description=description.strip()[:180] or "task", run=run))
        if waiting_ahead:
            await self._reply(update, f"Queued foreground task. Position: {waiting_ahead + 1}. I will send the result here.")
        else:
            await self._reply(update, "Queued foreground task. Running now.")

    def _ensure_foreground_worker(self) -> asyncio.Queue[TelegramWorkItem]:
        loop = asyncio.get_running_loop()
        if self._foreground_queue is None or self._foreground_loop is not loop:
            self._foreground_queue = asyncio.Queue()
            self._foreground_loop = loop
            self._foreground_worker = None
            self._active_description = ""
            self._active_started_at = None
        if self._foreground_worker is None or self._foreground_worker.done():
            self._foreground_worker = loop.create_task(self._foreground_worker_loop())
        return self._foreground_queue

    async def _foreground_worker_loop(self) -> None:
        assert self._foreground_queue is not None
        while True:
            item = await self._foreground_queue.get()
            self._active_description = item.description
            self._active_started_at = _utcnow()
            try:
                await self._reply(item.update, f"Task started: {item.description}")
                await item.run()
                await self._reply(item.update, f"Task finished: {item.description}")
            except Exception as exc:  # noqa: BLE001
                await self._reply(item.update, f"Task failed: {item.description}\n{exc}")
            finally:
                self._active_description = ""
                self._active_started_at = None
                self._foreground_queue.task_done()

    async def _capture_and_send_screen(self, update) -> None:
        result = await asyncio.to_thread(self.runtime.tools.execute, "screen", {"action": "capture"})
        if not result.ok:
            await self._reply(update, result.summary)
            return
        path = Path(str(result.data.get("path", "")))
        if not path.exists():
            await self._reply(update, f"Screenshot was captured but file is missing: {path}")
            return
        record = self.artifacts.register_file(path, kind="screenshot", title=path.name, source="screen")
        await self._send_artifact(update, self.artifacts.sendable_or_manifest(record), as_photo=True)

    async def _send_task_outputs(self, update, task_id: str) -> None:
        sent: set[str] = set()
        for event in self.runtime.task_store.list_events(task_id, limit=200):
            if event.event_type != "observation_recorded":
                continue
            payload = event.payload
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            if not isinstance(data, dict):
                continue
            path_text = str(data.get("path", "")).strip()
            if not path_text:
                continue
            path = Path(path_text)
            if not path.exists() or not path.is_file():
                continue
            resolved = str(path.resolve())
            if resolved in sent:
                continue
            sent.add(resolved)
            kind = "task_output"
            if str(payload.get("tool", "")) == "image_generation":
                kind = "generated_image"
            if str(payload.get("tool", "")) == "screen":
                kind = "screenshot"
            record = self.artifacts.register_file(path, kind=kind, title=path.name, source="task_engine")
            await self._send_artifact(update, self.artifacts.sendable_or_manifest(record), as_photo=kind in {"generated_image", "screenshot"})

    async def _send_path_file(self, update, path: Path) -> ArtifactRecord:
        record = self.artifacts.register_file(path, kind="pc_file", title=path.name, source="pc")
        send_record = self.artifacts.sendable_or_manifest(record)
        await self._send_artifact(update, send_record)
        return send_record

    async def _send_path_directory(self, update, path: Path) -> ArtifactRecord:
        record = await asyncio.to_thread(self.artifacts.zip_directory, str(path))
        await self._send_artifact(update, record)
        return record

    async def _put_artifact(self, update, artifact_id: str, target_path: str) -> Path:
        copied_to = self.artifacts.put_artifact(artifact_id, target_path)
        await self._reply(update, f"Wrote artifact {artifact_id} to {copied_to}")
        return copied_to

    async def _send_artifact(self, update, record: ArtifactRecord, *, as_photo: bool = False) -> None:
        message = getattr(update, "message", None)
        if message is None:
            return
        path = Path(record.path)
        if not path.exists() or not path.is_file():
            await self._reply(update, f"Artifact file is missing: {record.id}")
            return
        caption = f"{record.title}\nArtifact: {record.id}"[:900]
        try:
            with path.open("rb") as handle:
                if as_photo and record.mime_type.startswith("image/") and record.size_bytes <= self.artifacts.max_upload_bytes:
                    await message.reply_photo(photo=handle, caption=caption)
                else:
                    await message.reply_document(document=handle, filename=path.name, caption=caption)
        except TypeError:
            with path.open("rb") as handle:
                await message.reply_document(document=handle, caption=caption)

    async def _generate_image(self, update, prompt: str, *, send_as_document: bool) -> None:
        await self._reply(update, "Generating image.")
        result = await asyncio.to_thread(
            self.runtime.tools.execute,
            "image_generation",
            {"prompt": prompt, "size": self.runtime.settings.image_size},
        )
        if not result.ok:
            await self._reply(update, result.summary)
            return
        path = Path(str(result.data.get("path", "")))
        try:
            record = self.artifacts.register_file(
                path,
                kind="generated_image",
                title=path.name,
                source="nvidia_image",
                extra={
                    "prompt": prompt,
                    "model": result.data.get("model", ""),
                    "size": result.data.get("size", ""),
                },
            )
            await self._send_artifact(update, self.artifacts.sendable_or_manifest(record), as_photo=not send_as_document)
        except ArtifactError as exc:
            await self._reply(update, str(exc))

    async def _request_artifact_approval(self, update, *, kind: str, summary: str, payload: dict[str, Any]) -> None:
        session_id = f"telegram-{self._user_id(update)}"
        task = self.runtime.task_store.create_task(
            goal=summary,
            session_id=session_id,
            context="telegram_artifact_action",
            success_criteria=["Operator approves or denies the Telegram artifact action."],
            allowed_surfaces=["telegram"],
        )
        approval = {
            "id": str(uuid.uuid4()),
            "kind": kind,
            "summary": summary,
            "payload": TelegramArtifactService.redact_payload(payload),
            "tool": kind,
            "args": TelegramArtifactService.redact_payload(payload),
            "created_at": utcnow_iso(),
        }
        self.runtime.task_store.set_pending_approval(task.id, approval)
        await self._reply(
            update,
            f"Approval required.\nTask: {task.id}\nApproval: {approval['id']}\nAction: {summary}\nUse /approve {approval['id']} or /deny {approval['id']}.",
        )

    async def _approve_artifact_action(self, update, token: str) -> bool:
        task = self.runtime.task_store.find_task_by_approval(token) or self.runtime.task_store.get_task(token)
        if task is None or not task.pending_approval:
            return False
        kind = str(task.pending_approval.get("kind", ""))
        if not kind.startswith("telegram_"):
            return False

        approved = self.runtime.task_store.approve_pending(token, actor=f"telegram:{self._user_id(update)}")
        if approved is None:
            await self._reply(update, f"Approval not found or already decided: {token}")
            return True
        payload = approved.pending_approval.get("payload", {})
        if not isinstance(payload, dict):
            await self._complete_artifact_approval(approved.id, ok=False, summary="Approval payload was invalid.")
            await self._reply(update, "Approval payload was invalid.")
            return True

        try:
            command = str(payload.get("command", ""))
            if command == "sendfile":
                record = await self._send_path_file(update, Path(str(payload["path"])))
                summary = f"Sent file artifact {record.id}."
            elif command == "senddir":
                record = await self._send_path_directory(update, Path(str(payload["path"])))
                summary = f"Sent directory artifact {record.id}."
            elif command == "put":
                target = await self._put_artifact(update, str(payload["artifact_id"]), str(payload["target_path"]))
                summary = f"Wrote artifact to {target}."
            else:
                raise ArtifactError(f"Unknown Telegram approval command: {command}")
            await self._complete_artifact_approval(approved.id, ok=True, summary=summary)
        except Exception as exc:  # noqa: BLE001
            summary = f"Approved Telegram artifact action failed: {exc}"
            await self._complete_artifact_approval(approved.id, ok=False, summary=summary)
            await self._reply(update, summary)
        return True

    async def _complete_artifact_approval(self, task_id: str, *, ok: bool, summary: str) -> None:
        self.runtime.task_store.clear_pending_approval(task_id)
        self.runtime.task_store.update_task(
            task_id,
            status="completed" if ok else "failed",
            result_summary=summary,
            last_error="" if ok else "telegram_artifact_failed",
            final_report=summary,
            completed_at=utcnow_iso(),
        )
        self.runtime.task_store.append_event(
            task_id,
            "telegram_artifact_completed" if ok else "telegram_artifact_failed",
            {"summary": summary},
        )

    async def _require_admin(self, update) -> bool:
        if self.auth.is_admin(self._user_id(update)):
            return True
        await self._reply(update, "Admin mode is locked. Send /admin for unlock steps.")
        return False

    async def _reply(self, update, text: str) -> None:
        if getattr(update, "message", None) is None:
            return
        for chunk in split_message(text):
            await update.message.reply_text(chunk)

    @staticmethod
    def _user_id(update) -> int:
        user = getattr(update, "effective_user", None)
        return int(getattr(user, "id", 0) or 0)

def create_application(runtime: JakataRuntime):
    try:
        from telegram.ext import Application, CommandHandler, MessageHandler, filters
    except ImportError as exc:
        raise RuntimeError("python-telegram-bot is not installed. Run: pip install -r requirements.txt") from exc

    token = runtime.settings.telegram_bot_token
    if not token:
        raise RuntimeError("JAKATA_TELEGRAM_BOT_TOKEN is missing in .env.")
    controller = TelegramBotController(runtime)
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", controller.start))
    app.add_handler(CommandHandler("help", controller.help))
    app.add_handler(CommandHandler("commands", controller.help))
    app.add_handler(CommandHandler("admin", controller.admin))
    app.add_handler(CommandHandler("unlock", controller.unlock))
    app.add_handler(CommandHandler("lock", controller.lock))
    app.add_handler(CommandHandler("task", controller.task))
    app.add_handler(CommandHandler("tasks", controller.tasks))
    app.add_handler(CommandHandler("details", controller.details))
    app.add_handler(CommandHandler("approve", controller.approve))
    app.add_handler(CommandHandler("deny", controller.deny))
    app.add_handler(CommandHandler("cancel", controller.cancel))
    app.add_handler(CommandHandler("screen", controller.screen))
    app.add_handler(CommandHandler("sendfile", controller.sendfile))
    app.add_handler(CommandHandler("senddir", controller.senddir))
    app.add_handler(CommandHandler("ls", controller.ls))
    app.add_handler(CommandHandler("findfile", controller.findfile))
    app.add_handler(CommandHandler("outputs", controller.outputs))
    app.add_handler(CommandHandler("download", controller.download))
    app.add_handler(CommandHandler("report", controller.report))
    app.add_handler(CommandHandler("export", controller.export))
    app.add_handler(CommandHandler("logs", controller.logs))
    app.add_handler(CommandHandler("put", controller.put))
    app.add_handler(CommandHandler("img", controller.img))
    app.add_handler(CommandHandler("imgfile", controller.imgfile))
    app.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO, controller.upload))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, controller.message))
    return app


def main() -> None:
    runtime = create_runtime()
    app = create_application(runtime)
    print("JAKATA Telegram bot is running.")
    app.run_polling()


if __name__ == "__main__":
    main()
