from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jakata_agent.memory.manager import MemoryManager
from jakata_agent.router import IntentRouter, PlanDecision
from jakata_agent.tasks.models import (
    DEFAULT_TASK_ACTION_LIMIT,
    DEFAULT_TASK_BUDGET_MINUTES,
    DEFAULT_TASK_REPAIR_LIMIT,
    MAX_TASK_BUDGET_MINUTES,
    TaskRecord,
)
from jakata_agent.tasks.orchestrator import TaskOrchestrator
from jakata_agent.tasks.store import TaskStore
from jakata_agent.tools.registry import ToolRegistry


@dataclass(slots=True)
class EngineResult:
    task: TaskRecord
    report: str
    model: str = "local:task_engine"


class TaskCompletionEngine:
    def __init__(
        self,
        *,
        client,
        router: IntentRouter,
        tools: ToolRegistry,
        validator,
        memory: MemoryManager,
        task_store: TaskStore,
        approval_policy: str = "manual",
        workspace_dir: str | Path | None = None,
        data_dir: str | Path | None = None,
    ) -> None:
        self.task_store = task_store
        self.memory = memory
        self.orchestrator = TaskOrchestrator(
            client=client,
            router=router,
            tools=tools,
            validator=validator,
            memory=memory,
            task_store=task_store,
            approval_policy=approval_policy,
            workspace_dir=workspace_dir,
            data_dir=data_dir,
        )

    def run_foreground_task(
        self,
        *,
        goal: str,
        session_id: str,
        context: str = "",
        decision: PlanDecision | None = None,
        success_criteria: list[str] | None = None,
        allowed_surfaces: list[str] | None = None,
        cwd: str = "",
        budget_minutes: int = DEFAULT_TASK_BUDGET_MINUTES,
    ) -> EngineResult:
        budget = min(max(int(budget_minutes), 1), MAX_TASK_BUDGET_MINUTES)
        task = self.task_store.create_task(
            goal=goal,
            session_id=session_id,
            execution_mode="foreground",
            context=context,
            background_reason=decision.background_reason if decision else "",
            budget_minutes=budget,
            repair_limit=DEFAULT_TASK_REPAIR_LIMIT,
            action_limit=DEFAULT_TASK_ACTION_LIMIT,
            success_criteria=success_criteria or [],
            allowed_surfaces=allowed_surfaces or [],
            cwd=cwd,
        )
        self.task_store.append_event(
            task.id,
            "planned",
            {
                "source": "task_engine",
                "execution_mode": "foreground",
                "steps": self._decision_steps(decision),
            },
        )
        processed = self.orchestrator.process_task(task)
        return EngineResult(task=processed, report=self.format_report(processed))

    def resume_task(self, token: str) -> EngineResult | None:
        task = self.task_store.find_task_by_approval(token) or self.task_store.get_task(token)
        if task is None:
            return None
        processed = self.orchestrator.process_task(task)
        return EngineResult(task=processed, report=self.format_report(processed))

    def approve_and_resume(self, token: str, *, actor: str = "") -> EngineResult | None:
        task = self.task_store.approve_pending(token, actor=actor)
        if task is None:
            return None
        return self.resume_task(task.id)

    def deny(self, token: str, *, actor: str = "") -> EngineResult | None:
        task = self.task_store.deny_pending(token, actor=actor)
        if task is None:
            return None
        return EngineResult(task=task, report=self.format_report(task))

    @staticmethod
    def format_report(task: TaskRecord) -> str:
        if task.status == "awaiting_approval" and task.pending_approval:
            approval = task.pending_approval
            return (
                f"Approval required.\n"
                f"Task: {task.id}\n"
                f"Approval: {approval.get('id')}\n"
                f"Action: {approval.get('summary')}\n"
                f"Use /approve {approval.get('id')} or /deny {approval.get('id')}."
            )
        if task.final_report:
            return task.final_report
        summary = task.result_summary or task.last_error or task.status
        return f"Task {task.id} [{task.status}]: {summary}"

    @staticmethod
    def _decision_steps(decision: PlanDecision | None) -> list[dict[str, Any]]:
        if decision is None:
            return []
        return [{"tool": step.tool, "args": step.args, "reason": step.reason} for step in decision.steps]
