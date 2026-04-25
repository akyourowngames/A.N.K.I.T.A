from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from jakata_agent.tasks.models import (
    ACTIVE_TASK_STATUSES,
    AgentMessageRecord,
    AgentRunRecord,
    TaskEventRecord,
    TaskRecord,
    utcnow_iso,
)


class TaskStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    status TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    execution_mode TEXT NOT NULL,
                    context TEXT NOT NULL,
                    background_reason TEXT NOT NULL,
                    budget_minutes INTEGER NOT NULL,
                    repair_limit INTEGER NOT NULL,
                    action_limit INTEGER NOT NULL,
                    repair_count INTEGER NOT NULL,
                    action_count INTEGER NOT NULL,
                    worker_id TEXT NOT NULL,
                    success_criteria TEXT NOT NULL,
                    allowed_surfaces TEXT NOT NULL,
                    pending_approval TEXT NOT NULL DEFAULT '',
                    cwd TEXT NOT NULL,
                    result_summary TEXT NOT NULL,
                    last_error TEXT NOT NULL,
                    final_report TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                )
                """
            )
            self._ensure_column(conn, "tasks", "pending_approval", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "tasks", "final_report", "TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    details TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def create_task(
        self,
        *,
        goal: str,
        session_id: str,
        execution_mode: str = "background",
        context: str = "",
        background_reason: str = "",
        budget_minutes: int = 20,
        repair_limit: int = 5,
        action_limit: int = 30,
        success_criteria: list[str] | None = None,
        allowed_surfaces: list[str] | None = None,
        cwd: str = "",
    ) -> TaskRecord:
        now = utcnow_iso()
        record = TaskRecord(
            id=str(uuid.uuid4()),
            goal=goal.strip(),
            status="queued",
            session_id=session_id,
            execution_mode=execution_mode,
            context=context,
            background_reason=background_reason,
            budget_minutes=budget_minutes,
            repair_limit=repair_limit,
            action_limit=action_limit,
            success_criteria=success_criteria or [],
            allowed_surfaces=allowed_surfaces or [],
            cwd=cwd,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tasks (
                    id, goal, status, session_id, execution_mode, context, background_reason,
                    budget_minutes, repair_limit, action_limit, repair_count, action_count,
                    worker_id, success_criteria, allowed_surfaces, pending_approval, cwd, result_summary,
                    last_error, final_report, created_at, updated_at, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.goal,
                    record.status,
                    record.session_id,
                    record.execution_mode,
                    record.context,
                    record.background_reason,
                    record.budget_minutes,
                    record.repair_limit,
                    record.action_limit,
                    record.repair_count,
                    record.action_count,
                    record.worker_id,
                    json.dumps(record.success_criteria),
                    json.dumps(record.allowed_surfaces),
                    json.dumps(record.pending_approval),
                    record.cwd,
                    record.result_summary,
                    record.last_error,
                    record.final_report,
                    record.created_at,
                    record.updated_at,
                    record.started_at,
                    record.completed_at,
                ),
            )
        return record

    def list_tasks(self, limit: int = 25, session_id: str | None = None) -> list[TaskRecord]:
        query = "SELECT * FROM tasks"
        params: list[object] = []
        if session_id:
            query += " WHERE session_id = ?"
            params.append(session_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def append_event(self, task_id: str, event_type: str, payload: dict) -> TaskEventRecord:
        record = TaskEventRecord(id=None, task_id=task_id, event_type=event_type, payload=payload)
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO task_events (task_id, event_type, payload, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (task_id, event_type, json.dumps(payload, ensure_ascii=False, default=str), record.created_at),
            )
            record.id = int(cur.lastrowid)
        return record

    def list_events(self, task_id: str, limit: int = 100) -> list[TaskEventRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM task_events
                WHERE task_id = ?
                ORDER BY id ASC
                LIMIT ?
                """,
                (task_id, limit),
            ).fetchall()
        return [
            TaskEventRecord(
                id=row["id"],
                task_id=row["task_id"],
                event_type=row["event_type"],
                payload=json.loads(row["payload"]) if row["payload"] else {},
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def update_task(self, task_id: str, **fields: object) -> TaskRecord | None:
        if not fields:
            return self.get_task(task_id)
        fields["updated_at"] = utcnow_iso()
        columns = ", ".join(f"{name} = ?" for name in fields)
        values = [self._encode_field(name, value) for name, value in fields.items()]
        with self._connect() as conn:
            conn.execute(
                f"UPDATE tasks SET {columns} WHERE id = ?",
                (*values, task_id),
            )
        return self.get_task(task_id)

    def cancel_task(self, task_id: str) -> TaskRecord | None:
        task = self.get_task(task_id)
        if not task:
            return None
        if task.status in {"completed", "failed", "timed_out", "canceled"}:
            return task
        task = self.update_task(task_id, status="canceled", completed_at=utcnow_iso())
        self.append_event(task_id, "task_failed", {"status": "canceled"})
        return task

    def set_pending_approval(self, task_id: str, approval: dict) -> TaskRecord | None:
        record = {
            **approval,
            "status": "waiting",
            "created_at": approval.get("created_at") or utcnow_iso(),
        }
        task = self.update_task(
            task_id,
            status="awaiting_approval",
            pending_approval=record,
            last_error="approval_required",
        )
        self.append_event(task_id, "approval_requested", record)
        return task

    def approve_pending(self, token: str, *, actor: str = "") -> TaskRecord | None:
        task = self.find_task_by_approval(token) or self.get_task(token)
        if task is None or not task.pending_approval:
            return None
        if str(task.pending_approval.get("status", "waiting")) != "waiting":
            return None
        approval = {**task.pending_approval, "status": "approved", "approved_by": actor, "decided_at": utcnow_iso()}
        task = self.update_task(
            task.id,
            status="queued",
            pending_approval=approval,
            last_error="",
        )
        self.append_event(task.id, "approval_approved", approval)
        return task

    def deny_pending(self, token: str, *, actor: str = "") -> TaskRecord | None:
        task = self.find_task_by_approval(token) or self.get_task(token)
        if task is None or not task.pending_approval:
            return None
        if str(task.pending_approval.get("status", "waiting")) != "waiting":
            return None
        approval = {**task.pending_approval, "status": "denied", "denied_by": actor, "decided_at": utcnow_iso()}
        summary = "Task denied by operator before the pending action ran."
        task = self.update_task(
            task.id,
            status="denied",
            pending_approval=approval,
            last_error="approval_denied",
            result_summary=summary,
            final_report=summary,
            completed_at=utcnow_iso(),
        )
        self.append_event(task.id, "approval_denied", approval)
        return task

    def clear_pending_approval(self, task_id: str) -> TaskRecord | None:
        self.append_event(task_id, "approval_consumed", {})
        return self.update_task(task_id, pending_approval={}, last_error="")

    def list_pending_approvals(self, limit: int = 25, session_id: str | None = None) -> list[TaskRecord]:
        query = "SELECT * FROM tasks WHERE status = 'awaiting_approval'"
        params: list[object] = []
        if session_id:
            query += " AND session_id = ?"
            params.append(session_id)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_task(row) for row in rows]

    def find_task_by_approval(self, approval_id: str) -> TaskRecord | None:
        approval_id = approval_id.strip()
        if not approval_id:
            return None
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM tasks
                WHERE pending_approval != ''
                ORDER BY updated_at DESC
                """
            ).fetchall()
        for row in rows:
            task = self._row_to_task(row)
            if str(task.pending_approval.get("id", "")).strip() == approval_id:
                return task
        return None

    def create_agent_run(self, task_id: str, role: str, status: str, details: dict | None = None) -> AgentRunRecord:
        record = AgentRunRecord(
            id=None,
            task_id=task_id,
            role=role,
            status=status,
            details=details or {},
        )
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO agent_runs (task_id, role, status, details, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    role,
                    status,
                    json.dumps(record.details, ensure_ascii=False, default=str),
                    record.created_at,
                    record.completed_at,
                ),
            )
            record.id = int(cur.lastrowid)
        return record

    def update_agent_run(self, run_id: int, status: str, details: dict | None = None) -> None:
        payload = json.dumps(details or {}, ensure_ascii=False, default=str)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_runs
                SET status = ?, details = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, payload, utcnow_iso(), run_id),
            )

    def list_agent_runs(self, task_id: str) -> list[AgentRunRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_runs WHERE task_id = ? ORDER BY id ASC",
                (task_id,),
            ).fetchall()
        return [
            AgentRunRecord(
                id=row["id"],
                task_id=row["task_id"],
                role=row["role"],
                status=row["status"],
                details=json.loads(row["details"]) if row["details"] else {},
                created_at=row["created_at"],
                completed_at=row["completed_at"],
            )
            for row in rows
        ]

    def add_agent_message(self, run_id: int, role: str, direction: str, content: str) -> AgentMessageRecord:
        record = AgentMessageRecord(
            id=None,
            run_id=run_id,
            role=role,
            direction=direction,
            content=content,
        )
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO agent_messages (run_id, role, direction, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, role, direction, content, record.created_at),
            )
            record.id = int(cur.lastrowid)
        return record

    def list_agent_messages_for_task(self, task_id: str) -> list[AgentMessageRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT agent_messages.*
                FROM agent_messages
                JOIN agent_runs ON agent_runs.id = agent_messages.run_id
                WHERE agent_runs.task_id = ?
                ORDER BY agent_messages.id ASC
                """,
                (task_id,),
            ).fetchall()
        return [
            AgentMessageRecord(
                id=row["id"],
                run_id=row["run_id"],
                role=row["role"],
                direction=row["direction"],
                content=row["content"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def claim_next_task(self, worker_id: str) -> TaskRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM tasks
                WHERE status IN ('queued', 'repairing')
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if not row:
                return None
            started_at = row["started_at"] or utcnow_iso()
            conn.execute(
                """
                UPDATE tasks
                SET status = ?, worker_id = ?, started_at = ?, updated_at = ?
                WHERE id = ? AND status IN ('queued', 'repairing')
                """,
                ("planning", worker_id, started_at, utcnow_iso(), row["id"]),
            )
        return self.get_task(str(row["id"]))

    def recover_incomplete_tasks(self) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                """
                UPDATE tasks
                SET status = 'queued', worker_id = '', updated_at = ?
                WHERE status IN ('planning', 'running', 'verifying', 'repairing')
                """,
                (utcnow_iso(),),
            )
        return int(cur.rowcount)

    def _encode_field(self, name: str, value: object) -> object:
        if name in {"success_criteria", "allowed_surfaces"}:
            return json.dumps(value or [], ensure_ascii=False)
        if name == "pending_approval":
            return json.dumps(value or {}, ensure_ascii=False)
        return value

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, name: str, definition: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> TaskRecord:
        return TaskRecord(
            id=row["id"],
            goal=row["goal"],
            status=row["status"],
            session_id=row["session_id"],
            execution_mode=row["execution_mode"],
            context=row["context"],
            background_reason=row["background_reason"],
            budget_minutes=row["budget_minutes"],
            repair_limit=row["repair_limit"],
            action_limit=row["action_limit"],
            repair_count=row["repair_count"],
            action_count=row["action_count"],
            worker_id=row["worker_id"],
            success_criteria=json.loads(row["success_criteria"]) if row["success_criteria"] else [],
            allowed_surfaces=json.loads(row["allowed_surfaces"]) if row["allowed_surfaces"] else [],
            pending_approval=TaskStore._decode_pending_approval(row["pending_approval"]),
            cwd=row["cwd"],
            result_summary=row["result_summary"],
            last_error=row["last_error"],
            final_report=row["final_report"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )

    @staticmethod
    def _decode_pending_approval(value: str) -> dict:
        if not value:
            return {}
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
