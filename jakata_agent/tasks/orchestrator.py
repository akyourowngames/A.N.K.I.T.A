from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jakata_agent.memory.manager import MemoryManager
from jakata_agent.prompts import load_prompt
from jakata_agent.router import IntentRouter, PlanDecision, PlanFallback, PlanStep
from jakata_agent.tasks.approval import ApprovalDenied, ApprovalGate, ApprovalRequired
from jakata_agent.tasks.models import RoleSelection, TaskRecord, utcnow_iso
from jakata_agent.tasks.store import TaskStore
from jakata_agent.tools.coding_agent import CodingAgentTool
from jakata_agent.tools.os_agent import OsAgentTool
from jakata_agent.tools.registry import ToolRegistry


ROLE_PROMPT = load_prompt("tasks/role_selector.md")
VERIFY_TASK_PROMPT = load_prompt("tasks/verifier.md")


@dataclass(slots=True)
class TaskRuntimeContext:
    task: TaskRecord
    research_summary: str = ""
    decision: PlanDecision | None = None
    results: list[dict[str, Any]] = field(default_factory=list)


class TaskOrchestrator:
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
        self.client = client
        self.router = router
        self.tools = tools
        self.validator = validator
        self.memory = memory
        self.task_store = task_store
        self.approval_policy = approval_policy.strip().lower() or "manual"
        self.workspace_dir = Path(workspace_dir).expanduser().resolve() if workspace_dir else None
        self.data_dir = Path(data_dir).expanduser().resolve() if data_dir else None

    def process_task(self, task: TaskRecord) -> TaskRecord:
        context = TaskRuntimeContext(task=task)
        roles = self._select_roles(task)
        self.task_store.append_event(task.id, "planned", {"roles": roles.roles, "summary": roles.summary})
        self.memory.remember_task_event(task.id, task.goal, "planned", {"roles": roles.roles})

        if "researcher" in roles.roles:
            context.research_summary = self._run_researcher(task)

        while task.repair_count <= task.repair_limit and task.action_count <= task.action_limit:
            task = self.task_store.update_task(task.id, status="planning") or task
            context.decision = self._plan(task, context.research_summary)
            self.task_store.append_event(
                task.id,
                "planned",
                {
                    "execution_mode": context.decision.execution_mode,
                    "background_reason": context.decision.background_reason,
                    "steps": [
                        {
                            "tool": step.tool,
                            "args": step.args,
                            "reason": step.reason,
                            "fallbacks": [{"tool": item.tool, "args": item.args, "reason": item.reason} for item in step.fallbacks],
                        }
                        for step in context.decision.steps
                    ],
                },
            )
            task = self.task_store.update_task(task.id, status="running") or task
            try:
                context.results = self._execute(task, context.decision.steps)
            except ApprovalRequired as exc:
                task = self.task_store.get_task(task.id) or task
                self.memory.remember_task_event(task.id, task.goal, "approval_requested", exc.request.as_dict())
                return task
            except ApprovalDenied as exc:
                summary = "Task denied by operator before the pending action ran."
                report = self._build_final_report(
                    task,
                    context,
                    {"ok": False, "summary": summary, "reason": "approval_denied", "evidence": []},
                )
                task = self.task_store.update_task(
                    task.id,
                    status="denied",
                    result_summary=summary,
                    last_error="approval_denied",
                    final_report=report,
                    completed_at=utcnow_iso(),
                ) or task
                self.task_store.append_event(task.id, "approval_denied", exc.approval)
                self.memory.remember_task_event(task.id, task.goal, "approval_denied", exc.approval)
                return task
            task = self.task_store.update_task(
                task.id,
                status="verifying",
                action_count=task.action_count + len(context.results),
            ) or task
            verdict = self._verify(task, context)
            if verdict["ok"]:
                report = self._build_final_report(task, context, verdict)
                task = self.task_store.update_task(
                    task.id,
                    status="completed",
                    result_summary=verdict["summary"],
                    final_report=report,
                    completed_at=utcnow_iso(),
                ) or task
                self.task_store.append_event(task.id, "task_completed", verdict)
                self.memory.remember_task_event(task.id, task.goal, "task_completed", verdict)
                return task

            next_repair = task.repair_count + 1
            if next_repair > task.repair_limit:
                report = self._build_final_report(task, context, verdict)
                task = self.task_store.update_task(
                    task.id,
                    status="failed",
                    result_summary=verdict["summary"],
                    last_error=verdict["reason"],
                    final_report=report,
                    completed_at=utcnow_iso(),
                ) or task
                self.task_store.append_event(task.id, "task_failed", verdict)
                self.memory.remember_task_event(task.id, task.goal, "task_failed", verdict)
                return task

            task = self.task_store.update_task(
                task.id,
                status="repairing",
                repair_count=next_repair,
                last_error=verdict["reason"],
            ) or task
            self.task_store.append_event(task.id, "repair_planned", verdict)
            self.memory.remember_task_event(task.id, task.goal, "repair_planned", verdict)

        task = self.task_store.update_task(
            task.id,
            status="timed_out",
            last_error="timeout",
            result_summary="Task budget exhausted.",
            final_report=self._build_final_report(
                task,
                context,
                {"ok": False, "summary": "Task budget exhausted.", "reason": "timeout", "evidence": []},
            ),
            completed_at=utcnow_iso(),
        ) or task
        self.task_store.append_event(task.id, "task_failed", {"reason": "timeout", "summary": "Task budget exhausted."})
        return task

    def _select_roles(self, task: TaskRecord) -> RoleSelection:
        payload = {
            "goal": task.goal,
            "context": task.context,
            "success_criteria": task.success_criteria,
        }
        run = self.task_store.create_agent_run(task.id, "orchestrator", "running", payload)
        self.task_store.add_agent_message(run.id or 0, "orchestrator", "input", json.dumps(payload, ensure_ascii=False))
        try:
            _, raw = self.client.complete_text(ROLE_PROMPT, json.dumps(payload, ensure_ascii=False), temperature=0.0)
            cleaned = self._clean_json(raw)
            roles = [str(role).strip() for role in cleaned.get("roles", []) if str(role).strip()]
            roles = [role for role in roles if role in {"planner", "researcher", "executor", "verifier"}]
            if not roles:
                roles = ["planner", "executor", "verifier"]
            if len(roles) > 3:
                roles = roles[:3]
            summary = str(cleaned.get("summary", "")).strip()
        except Exception:
            roles = ["planner", "executor", "verifier"]
            summary = "fallback role selection"
        self.task_store.add_agent_message(run.id or 0, "orchestrator", "output", json.dumps({"roles": roles, "summary": summary}))
        self.task_store.update_agent_run(run.id or 0, "completed", {"roles": roles, "summary": summary})
        return RoleSelection(roles=roles, summary=summary)

    def _run_researcher(self, task: TaskRecord) -> str:
        run = self.task_store.create_agent_run(task.id, "researcher", "running", {"goal": task.goal})
        retrieved = self.memory.retrieve(task.goal)
        summary = retrieved.to_system_context()
        self.task_store.add_agent_message(run.id or 0, "researcher", "output", summary[:4000])
        self.task_store.update_agent_run(run.id or 0, "completed", {"summary": summary[:200]})
        return summary

    def _plan(self, task: TaskRecord, research_summary: str) -> PlanDecision:
        prompt = task.goal
        if research_summary:
            prompt += f"\n\nContext:\n{research_summary}"
        if task.last_error:
            prompt += f"\n\nRepair context: previous failure reason = {task.last_error}"
        decision = self.router.plan(prompt, self.tools.manifest(public_only=True))
        decision.steps = self.validator.validate(decision.steps, self.tools).steps
        return decision

    def _execute(self, task: TaskRecord, steps: list[PlanStep]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        run = self.task_store.create_agent_run(task.id, "executor", "running", {"steps": len(steps)})
        approval_gate = ApprovalGate(
            task_store=self.task_store,
            task=task,
            approval_policy=self.approval_policy,
            workspace_dir=self.workspace_dir,
            data_dir=self.data_dir,
        )
        for step in steps:
            if step.tool == "general_chat":
                continue
            if step.tool == "memory":
                retrieved = self.memory.retrieve(step.args.get("query", task.goal))
                payload = {"summary": retrieved.to_system_context(), "facts": [item.content for item in retrieved.permanent_memories]}
                result = {"tool": "memory", "ok": True, "summary": payload["summary"], "data": payload, "rendered": payload["summary"]}
                self._record_executor_result(task, run.id or 0, result, results)
                continue

            attempts = [step, *self._fallback_steps(step)]
            for attempt_index, attempt in enumerate(attempts):
                result = self._execute_tool_step(task, attempt, approval_gate)
                if attempt_index > 0:
                    result["fallback_for"] = step.tool
                self._record_executor_result(task, run.id or 0, result, results)
                if result.get("ok"):
                    break
        self.task_store.update_agent_run(run.id or 0, "completed", {"results": len(results)})
        return results

    def _execute_tool_step(self, task: TaskRecord, step: PlanStep, approval_gate: ApprovalGate) -> dict[str, Any]:
        tool = self.tools.get(step.tool)
        if step.tool not in {"os_agent", "coding_agent"}:
            approval_gate.require(step.tool, step.args, step.reason)
        if isinstance(tool, OsAgentTool):
            normalized = tool.normalize_args(dict(step.args))
            remaining_repairs = max(1, task.repair_limit - task.repair_count)
            remaining_actions = max(1, task.action_limit - task.action_count)
            result_obj = tool.controller.run_goal(
                str(normalized["goal"]),
                context=str(normalized.get("context", task.context)),
                success_criteria=list(normalized.get("success_criteria", task.success_criteria)),
                budget_minutes=int(normalized.get("budget_minutes", task.budget_minutes)),
                allowed_surfaces=list(normalized.get("allowed_surfaces", task.allowed_surfaces)),
                cwd=str(normalized.get("cwd", task.cwd)),
                repair_limit=remaining_repairs,
                action_limit=remaining_actions,
                event_logger=lambda event_type, payload: self._record_nested_event(task, event_type, payload),
                approval_gate=approval_gate,
            )
        elif isinstance(tool, CodingAgentTool):
            normalized = tool.normalize_args(dict(step.args))
            remaining_repairs = max(1, task.repair_limit - task.repair_count)
            remaining_actions = max(1, task.action_limit - task.action_count)
            result_obj = tool.controller.run_goal(
                str(normalized["goal"]),
                context=str(normalized.get("context", task.context)),
                success_criteria=list(normalized.get("success_criteria", task.success_criteria)),
                cwd=str(normalized.get("cwd", task.cwd or self.workspace_dir or "")),
                budget_minutes=int(normalized.get("budget_minutes", task.budget_minutes)),
                allowed_tools=list(normalized.get("allowed_tools", [])),
                repair_limit=remaining_repairs,
                action_limit=remaining_actions,
                event_logger=lambda event_type, payload: self._record_nested_event(task, event_type, payload),
                approval_gate=approval_gate,
            )
        else:
            result_obj = self.tools.execute(step.tool, step.args)

        rendered = result_obj.summary
        tool = self.tools.get(step.tool)
        if tool is not None:
            try:
                rendered = tool.render(result_obj.data).strip() or rendered
            except Exception:
                rendered = result_obj.summary
        return {
            "tool": step.tool,
            "ok": result_obj.ok,
            "summary": result_obj.summary,
            "data": result_obj.data,
            "error": result_obj.error,
            "rendered": rendered,
        }

    def _record_executor_result(self, task: TaskRecord, run_id: int, result: dict[str, Any], results: list[dict[str, Any]]) -> None:
        self.task_store.append_event(task.id, "observation_recorded", result)
        self.memory.remember_task_event(task.id, task.goal, "observation_recorded", result)
        self.task_store.add_agent_message(run_id, "executor", "output", json.dumps(result, ensure_ascii=False, default=str)[:4000])
        results.append(result)

    def _fallback_steps(self, step: PlanStep) -> list[PlanStep]:
        fallbacks = [
            PlanStep(tool=item.tool, args=item.args, reason=item.reason or f"fallback for {step.tool}")
            for item in step.fallbacks
            if item.tool != step.tool
        ]
        fallbacks.extend(self._derived_fallback_steps(step))
        seen: set[tuple[str, str]] = set()
        unique: list[PlanStep] = []
        for fallback in fallbacks:
            key = (fallback.tool, json.dumps(fallback.args, sort_keys=True, default=str))
            if key in seen:
                continue
            seen.add(key)
            if self.tools.get(fallback.tool) is not None:
                unique.append(fallback)
        return unique[:3]

    @staticmethod
    def _derived_fallback_steps(step: PlanStep) -> list[PlanStep]:
        action = str(step.args.get("action", "")).strip()
        if step.tool == "system" and action == "open_url":
            target = str(step.args.get("target", "")).strip()
            if target:
                return [PlanStep(tool="browser", args={"action": "open_url", "url": target}, reason="fallback: open URL through browser tool")]
        if step.tool == "browser" and action == "open_url":
            url = str(step.args.get("url", "")).strip()
            if url:
                return [PlanStep(tool="system", args={"action": "open_url", "target": url}, reason="fallback: open URL through system shell")]
        if step.tool == "system" and action in {"launch_app", "open_path"}:
            target = str(step.args.get("target", "")).strip()
            if target:
                escaped = target.replace("'", "''")
                return [PlanStep(tool="shell", args={"command": f"Start-Process '{escaped}'"}, reason="fallback: launch through terminal")]
        return []

    def _build_final_report(self, task: TaskRecord, context: TaskRuntimeContext, verdict: dict[str, Any]) -> str:
        done: list[str] = []
        failed: list[str] = []
        evidence: list[str] = []
        for result in context.results:
            tool_name = str(result.get("tool", "tool"))
            rendered = str(result.get("rendered", "")).strip() or str(result.get("summary", "")).strip()
            if result.get("ok"):
                done.append(f"{tool_name}: {rendered[:220]}")
            else:
                failed.append(f"{tool_name}: {str(result.get('error') or result.get('summary') or 'failed')[:220]}")
            data = result.get("data", {})
            if isinstance(data, dict):
                observations = data.get("observations", [])
                if isinstance(observations, list):
                    evidence.extend(str(item) for item in observations[-3:])
        verdict_evidence = verdict.get("evidence", [])
        if isinstance(verdict_evidence, list):
            evidence.extend(str(item) for item in verdict_evidence[-3:])

        lines = [
            f"Goal: {task.goal}",
            f"Status: {'completed' if verdict.get('ok') else 'not completed'}",
            f"Verifier: {verdict.get('summary') or 'No verifier summary.'}",
        ]
        if done:
            lines.append("Done:")
            lines.extend(f"- {item}" for item in done[:6])
        if evidence:
            lines.append("Verified evidence:")
            lines.extend(f"- {item[:260]}" for item in evidence[-6:])
        if failed:
            lines.append("Failed or blocked:")
            lines.extend(f"- {item}" for item in failed[:4])
        if not verdict.get("ok"):
            reason = str(verdict.get("reason", "unknown"))
            lines.append(f"What else can be done: repair the task from reason={reason}, adjust the goal, or approve the next requested action.")
        else:
            lines.append("What else can be done: ask for follow-up work if you want another step.")
        return "\n".join(lines)

    def _verify(self, task: TaskRecord, context: TaskRuntimeContext) -> dict[str, Any]:
        delegated = self._verified_delegate_result(context.results)
        if delegated is not None:
            return delegated
        run = self.task_store.create_agent_run(task.id, "verifier", "running", {"results": len(context.results)})
        payload = {
            "goal": task.goal,
            "context": task.context,
            "success_criteria": task.success_criteria,
            "research_summary": context.research_summary,
            "results": context.results,
            "repair_count": task.repair_count,
        }
        self.task_store.add_agent_message(run.id or 0, "verifier", "input", json.dumps(payload, ensure_ascii=False, default=str)[:4000])
        try:
            _, raw = self.client.complete_text(VERIFY_TASK_PROMPT, json.dumps(payload, ensure_ascii=False, default=str), temperature=0.0)
            cleaned = self._clean_json(raw)
            verdict = {
                "ok": bool(cleaned.get("ok")),
                "summary": str(cleaned.get("summary", "")).strip() or "Verification completed.",
                "reason": str(cleaned.get("reason", "verified" if cleaned.get("ok") else "verifier_rejected")).strip(),
            }
        except Exception:
            evidence = self._verification_evidence(context.results)
            all_ok = bool(evidence)
            verdict = {
                "ok": all_ok,
                "summary": "Task completion was directly verified." if all_ok else "Task execution finished but completion is not proven.",
                "reason": "verified" if all_ok else "verifier_rejected",
                "evidence": evidence,
            }
        self.task_store.add_agent_message(run.id or 0, "verifier", "output", json.dumps(verdict, ensure_ascii=False))
        self.task_store.update_agent_run(run.id or 0, "completed", verdict)
        return verdict

    def _record_nested_event(self, task: TaskRecord, event_type: str, payload: dict[str, Any]) -> None:
        self.task_store.append_event(task.id, event_type, payload)
        self.memory.remember_task_event(task.id, task.goal, event_type, payload)

    @staticmethod
    def _verified_delegate_result(results: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not results or any(not result.get("ok") for result in results):
            return None
        for result in results:
            data = result.get("data", {})
            if result.get("tool") not in {"os_agent", "coding_agent"} or not isinstance(data, dict):
                continue
            if str(data.get("reason", "")).strip() != "verified":
                continue
            observations = data.get("observations", [])
            summary = str(result.get("summary", "")).strip() or "OS task verified."
            return {
                "ok": True,
                "summary": summary,
                "reason": "verified",
                "source": str(result.get("tool")),
                "evidence": observations[-4:] if isinstance(observations, list) else [],
            }
        return None

    @staticmethod
    def _verification_evidence(results: list[dict[str, Any]]) -> list[str]:
        evidence: list[str] = []
        for result in results:
            if not result.get("ok"):
                continue
            data = result.get("data", {})
            if isinstance(data, dict) and str(data.get("reason", "")).strip() == "verified":
                rendered = str(result.get("rendered", "")).strip() or str(result.get("summary", "")).strip()
                if rendered:
                    evidence.append(rendered)
        return evidence[:4]

    @staticmethod
    def _clean_json(raw: str) -> dict[str, Any]:
        cleaned = raw.strip().replace("```json", "").replace("```", "").strip()
        brace = cleaned.find("{")
        if brace > 0:
            cleaned = cleaned[brace:]
        end_brace = cleaned.rfind("}")
        if end_brace >= 0:
            cleaned = cleaned[: end_brace + 1]
        return json.loads(cleaned)
