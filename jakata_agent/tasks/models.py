from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def utcnow_iso() -> str:
    return datetime.utcnow().isoformat()


ACTIVE_TASK_STATUSES = {"queued", "planning", "running", "verifying", "repairing", "awaiting_approval"}
FINAL_TASK_STATUSES = {"completed", "failed", "timed_out", "canceled", "denied"}
DEFAULT_TASK_BUDGET_MINUTES = 20
MAX_TASK_BUDGET_MINUTES = 30
DEFAULT_TASK_REPAIR_LIMIT = 5
DEFAULT_TASK_ACTION_LIMIT = 30


@dataclass(slots=True)
class TaskRecord:
    id: str
    goal: str
    status: str
    session_id: str
    execution_mode: str = "foreground"
    context: str = ""
    budget_minutes: int = DEFAULT_TASK_BUDGET_MINUTES
    repair_limit: int = DEFAULT_TASK_REPAIR_LIMIT
    action_limit: int = DEFAULT_TASK_ACTION_LIMIT
    repair_count: int = 0
    action_count: int = 0
    worker_id: str = ""
    success_criteria: list[str] = field(default_factory=list)
    allowed_surfaces: list[str] = field(default_factory=list)
    pending_approval: dict[str, Any] = field(default_factory=dict)
    cwd: str = ""
    result_summary: str = ""
    last_error: str = ""
    final_report: str = ""
    created_at: str = field(default_factory=utcnow_iso)
    updated_at: str = field(default_factory=utcnow_iso)
    started_at: str | None = None
    completed_at: str | None = None


@dataclass(slots=True)
class TaskEventRecord:
    id: int | None
    task_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: str = field(default_factory=utcnow_iso)


@dataclass(slots=True)
class AgentRunRecord:
    id: int | None
    task_id: str
    role: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utcnow_iso)
    completed_at: str | None = None


@dataclass(slots=True)
class AgentMessageRecord:
    id: int | None
    run_id: int
    role: str
    direction: str
    content: str
    created_at: str = field(default_factory=utcnow_iso)


@dataclass(slots=True)
class ExecutionStep:
    tool: str
    args: dict[str, Any]
    reason: str = ""
    fallback_to: str | None = None


@dataclass(slots=True)
class VerificationResult:
    ok: bool
    summary: str
    reason: str = "verified"
    evidence: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RoleSelection:
    roles: list[str]
    summary: str = ""
