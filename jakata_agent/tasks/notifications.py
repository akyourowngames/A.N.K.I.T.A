from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class TaskStoreLike(Protocol):
    def list_tasks(self, limit: int = 25, session_id: str | None = None) -> list: ...


@dataclass
class BackgroundTaskNotifier:
    session_id: str
    seen_terminal: set[str] = field(default_factory=set)

    def collect(self, task_store: TaskStoreLike) -> list[str]:
        messages: list[str] = []
        tasks = task_store.list_tasks(limit=25, session_id=self.session_id)
        for task in reversed(tasks):
            if task.status not in {"completed", "failed", "timed_out", "canceled"}:
                continue
            key = f"{task.id}:{task.status}:{task.updated_at}"
            if key in self.seen_terminal:
                continue
            self.seen_terminal.add(key)
            summary = task.result_summary or task.last_error or task.status
            messages.append(f"Background task {task.id} [{task.status}]: {summary}")
        return messages
