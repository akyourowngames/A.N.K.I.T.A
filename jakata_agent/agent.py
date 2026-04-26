from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterator

from jakata_agent.config import Settings
from jakata_agent.llm import NvidiaChatClient
from jakata_agent.memory.manager import MemoryManager
from jakata_agent.plan_validator import PlanValidator
from jakata_agent.prompts import load_prompt
from jakata_agent.router import IntentRouter, PlanDecision, PlanStep
from jakata_agent.tasks.approval import GUARDED_TOOLS, ApprovalDenied, ApprovalGate, ApprovalRequired
from jakata_agent.tasks.engine import TaskCompletionEngine
from jakata_agent.tasks.store import TaskStore
from jakata_agent.tools.base import ToolResult
from jakata_agent.tools.coding_agent import CodingAgentTool
from jakata_agent.tools.os_agent import OsAgentTool
from jakata_agent.tools.registry import ToolRegistry
from jakata_agent.tools.semantic_manifest import SemanticToolManifest


SYSTEM_PROMPT = load_prompt("agent/system.md")
SYNTHESIS_SYSTEM_PROMPT = load_prompt("agent/synthesis.md")

MAX_TOOL_STEPS = 4
DIRECT_TOOL_ENGINE_ENV = "JAKATA_FOREGROUND_TASK_ENGINE"
PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


@dataclass(slots=True)
class AgentResponse:
    model: str
    content: str
    tool_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class JakataAgent:
    settings: Settings
    client: NvidiaChatClient
    tools: ToolRegistry
    memory: MemoryManager
    router: IntentRouter
    validator: PlanValidator
    task_store: TaskStore
    task_engine: TaskCompletionEngine | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{self.memory.bootstrap_system_note()}"}]
        self.memory.persist_turn(self.messages)

    def reply(self, user_message: str) -> tuple[str, str]:
        response = self.respond(user_message)
        return response.model, response.content

    def respond(self, user_message: str) -> AgentResponse:
        response = self._handle(user_message)
        self._record_conversation(user_message, response.content)
        return response

    def stream_reply(self, user_message: str) -> Iterator[tuple[str, str]]:
        decision = self._plan(user_message)
        if decision.direct_answer:
            self._record_conversation(user_message, decision.direct_answer)
            yield "router:answer", decision.direct_answer
            return
        if self._should_use_task_engine(decision):
            result = self._run_task_engine(user_message, decision)
            self._record_conversation(user_message, result.report)
            yield result.model, result.report
            return
        tool_results = self._execute(decision.steps)
        if not tool_results:
            messages = self._build_general_chat_messages(user_message, decision.memory_context)
            yield from self._stream_messages(user_message, messages)
            return

        direct = self._direct_tool_reply(tool_results)
        if direct is not None:
            self._record_conversation(user_message, direct)
            yield "local:tool", direct
            return

        messages = self._build_synthesis_messages(user_message, tool_results, decision.memory_context)
        yield from self._stream_messages(user_message, messages)

    def plan(self, user_message: str) -> PlanDecision:
        return self._plan(user_message)

    def execute_steps(self, steps: list[PlanStep]) -> list[dict[str, Any]]:
        return self._execute(steps)

    def stream_general_chat(self, user_message: str) -> Iterator[tuple[str, str]]:
        memory_context = self._retrieve_memory_context(user_message)
        yield from self._stream_messages(user_message, self._build_general_chat_messages(user_message, memory_context))

    def stream_general_chat_with_context(self, user_message: str, memory_context: str = "") -> Iterator[tuple[str, str]]:
        yield from self._stream_messages(user_message, self._build_general_chat_messages(user_message, memory_context))

    def stream_direct_answer(self, user_message: str, content: str) -> Iterator[tuple[str, str]]:
        self._record_conversation(user_message, content)
        yield "router:answer", content

    def stream_tool_results_reply(
        self,
        user_message: str,
        tool_results: list[dict[str, Any]],
    ) -> Iterator[tuple[str, str]]:
        direct = self._direct_tool_reply(tool_results)
        if direct is not None:
            self._record_conversation(user_message, direct)
            yield "local:tool", direct
            return
        yield from self._stream_messages(user_message, self._build_synthesis_messages(user_message, tool_results))

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{self.memory.bootstrap_system_note()}"}]
        self.memory.persist_turn(self.messages)

    def _record_conversation(self, user_message: str, content: str) -> None:
        self.messages.append({"role": "user", "content": user_message})
        self.messages.append({"role": "assistant", "content": content})
        self.memory.learn_from_user_message(user_message)
        self.memory.persist_turn(self.messages)

    def _handle(self, user_message: str) -> AgentResponse:
        decision = self._plan(user_message)
        if decision.direct_answer:
            return AgentResponse(model="router:answer", content=decision.direct_answer)
        if self._is_general_chat_decision(decision):
            model, content = self._general_chat_reply(user_message, decision.memory_context)
            return AgentResponse(model=model, content=content)
        if self._should_use_task_engine(decision):
            result = self._run_task_engine(user_message, decision)
            return AgentResponse(model=result.model, content=result.report)
        tool_results = self._execute(decision.steps)
        if not tool_results:
            model, content = self._general_chat_reply(user_message, decision.memory_context)
            return AgentResponse(model=model, content=content)

        model, content = self._synthesise(user_message, decision.steps, tool_results, decision.memory_context)
        return AgentResponse(model=model, content=content, tool_results=tool_results)

    def _plan(self, user_message: str) -> PlanDecision:
        manifest_result = self._planner_manifest(user_message)
        if manifest_result.used_semantic_ranking and manifest_result.tools:
            first_tool = self.tools.get(str(manifest_result.tools[0].get("name", "")))
            direct_min_score = float(getattr(first_tool, "semantic_direct_min_score", 0.0) or 0.0) if first_tool else 0.0
            direct_min_margin = float(getattr(first_tool, "semantic_direct_min_margin", 0.0) or 0.0) if first_tool else 0.0
            direct_margin = float(manifest_result.best_score) - float(getattr(manifest_result, "second_score", 0.0) or 0.0)
            direct_ready = manifest_result.best_score >= direct_min_score and direct_margin >= direct_min_margin
            direct_args_builder = getattr(first_tool, "semantic_direct_args", None)
            if callable(direct_args_builder) and direct_ready:
                direct_args = direct_args_builder(user_message)
                if isinstance(direct_args, dict):
                    return PlanDecision(
                        steps=[PlanStep(tool=first_tool.name, args=direct_args, reason="semantic_direct_tool")],
                        memory_context="",
                    )
            if getattr(first_tool, "semantic_direct", False) and direct_ready:
                return PlanDecision(
                    steps=[PlanStep(tool=first_tool.name, args={}, reason="semantic_direct_tool")],
                    memory_context="",
                )
        if manifest_result.used_semantic_ranking and not manifest_result.tools:
            return PlanDecision(
                steps=[PlanStep(tool="general_chat", args={}, reason="semantic_no_tool_match")],
                memory_context="",
            )

        first_manifest_tool = self.tools.get(str(manifest_result.tools[0].get("name", ""))) if manifest_result.tools else None
        if getattr(first_manifest_tool, "skip_planning_memory", False):
            memory_context = ""
        else:
            memory_context = self._retrieve_memory_context(user_message)
        manifest = manifest_result.tools + [
            {
                "name": "general_chat",
                "description": "Use ONLY when the user is having a normal conversation and no tool is needed.",
                "args": {},
                "required": [],
                "safety": "read_only",
            }
        ]
        conversation_context = self._conversation_context()
        decision = self.router.plan(user_message, manifest, memory_context=memory_context, conversation_context=conversation_context)
        decision.memory_context = memory_context
        decision.steps = self.validator.validate(decision.steps, self.tools).steps[:MAX_TOOL_STEPS]
        return decision

    def _planner_manifest(self, user_message: str):
        manifest = self.tools.manifest(public_only=True)
        embedder = getattr(self.memory, "embedder", None)
        limit = int(getattr(self.settings, "router_tool_limit", 0) or 0)
        min_score = float(getattr(self.settings, "router_min_tool_score", 0.0) or 0.0)
        if embedder is None or limit <= 0:
            return SemanticToolManifest(None, limit=0, min_score=0.0).shortlist(user_message, manifest)
        return SemanticToolManifest(embedder, limit=limit, min_score=min_score).shortlist(user_message, manifest)

    def _should_use_task_engine(self, decision: PlanDecision) -> bool:
        if self.task_engine is None:
            return False
        return os.getenv(DIRECT_TOOL_ENGINE_ENV, "0").strip().lower() in {"1", "true", "on", "yes"} and any(
            step.tool != "general_chat" for step in decision.steps
        )

    def _run_task_engine(self, user_message: str, decision: PlanDecision):
        assert self.task_engine is not None
        context = decision.memory_context or self.memory.retrieve(user_message).to_system_context()
        return self.task_engine.run_foreground_task(
            goal=user_message,
            session_id=self.settings.session_id,
            context=context,
            decision=decision,
        )

    def _execute(self, plan: list[PlanStep]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        tool_context: dict[str, Any] = {}
        for step in plan:
            if step.tool == "general_chat":
                continue
            if step.tool == "memory":
                payload = self._build_memory_payload(step.args.get("query", ""))
                results.append(
                    {
                        "tool": "memory",
                        "ok": True,
                        "summary": payload["summary"],
                        "data": payload,
                        "rendered": json.dumps(payload, ensure_ascii=False),
                    }
                )
                continue

            resolved_step = PlanStep(
                tool=step.tool,
                args=self._resolve_tool_placeholders(step.args, tool_context),
                reason=step.reason,
                fallbacks=step.fallbacks,
            )
            if self._has_unresolved_placeholder(resolved_step.args):
                result = ToolResult(
                    ok=False,
                    summary=f"Skipped {step.tool}: required previous tool output was not available.",
                    data={"args": resolved_step.args},
                    error="missing_dependency",
                )
            else:
                result = self._execute_one_direct_tool(resolved_step)
            result_tool_name = step.tool
            if not result.ok:
                for fallback in step.fallbacks:
                    fallback_step = PlanStep(
                        tool=fallback.tool,
                        args=self._resolve_tool_placeholders(fallback.args, tool_context),
                        reason=fallback.reason,
                    )
                    if self._has_unresolved_placeholder(fallback_step.args):
                        continue
                    fallback_result = self._execute_one_direct_tool(fallback_step)
                    if fallback_result.ok:
                        result = fallback_result
                        result_tool_name = fallback.tool
                        break

            tool = self.tools.get(result_tool_name)
            rendered = ""
            if result.ok and tool is not None:
                try:
                    rendered = tool.render(result.data).strip()
                except Exception:
                    rendered = result.summary

            results.append(
                {
                    "tool": result_tool_name,
                    "ok": result.ok,
                    "summary": result.summary,
                    "data": result.data,
                    "error": result.error,
                    "rendered": rendered,
                }
            )
            if result.ok:
                tool_context["previous"] = result.data
                tool_context[result_tool_name] = result.data
        return results

    def _execute_one_direct_tool(self, step: PlanStep):
        tool = self.tools.get(step.tool)
        approval_gate = self._approval_gate_for_direct_step(step)
        if approval_gate is not None and step.tool not in {"os_agent", "coding_agent", "memory"}:
            try:
                approval_gate.require(step.tool, step.args, step.reason)
            except ApprovalRequired as exc:
                return self._approval_result(exc.request.as_dict())
            except ApprovalDenied as exc:
                return self._denied_result(exc.approval)
        if isinstance(tool, OsAgentTool):
            normalized = tool.normalize_args(dict(step.args))
            return tool.controller.run_goal(
                str(normalized["goal"]),
                context=str(normalized.get("context", "")),
                success_criteria=list(normalized.get("success_criteria", [])),
                budget_minutes=int(normalized.get("budget_minutes", 20)),
                allowed_surfaces=list(normalized.get("allowed_surfaces", [])),
                cwd=str(normalized.get("cwd", self._workspace_dir())),
                approval_gate=approval_gate,
            )
        if isinstance(tool, CodingAgentTool):
            normalized = tool.normalize_args(dict(step.args))
            cwd = str(normalized.get("cwd", "")).strip() or str(self._generated_projects_dir())
            return tool.controller.run_goal(
                str(normalized["goal"]),
                context=str(normalized.get("context", "")),
                success_criteria=list(normalized.get("success_criteria", [])),
                cwd=cwd,
                budget_minutes=int(normalized.get("budget_minutes", 20)),
                allowed_tools=list(normalized.get("allowed_tools", [])),
                approval_gate=approval_gate,
            )
        return self.tools.execute(step.tool, step.args)

    def _approval_gate_for_direct_step(self, step: PlanStep) -> ApprovalGate | None:
        if step.tool in {"os_agent", "coding_agent", "memory"}:
            return None
        if step.tool not in GUARDED_TOOLS:
            return None
        task = self.task_store.create_task(
            goal=f"Approve direct foreground action: {step.tool}",
            session_id=self.settings.session_id,
            context="direct_approval_gate",
            cwd=str(self._workspace_dir()),
        )
        return ApprovalGate(
            task_store=self.task_store,
            task=task,
            approval_policy=self._approval_policy(),
            workspace_dir=self._workspace_dir(),
            data_dir=self._data_dir(),
        )

    def _workspace_dir(self):
        from pathlib import Path

        return Path(getattr(self.settings, "workspace_dir", Path.cwd())).resolve()

    def _data_dir(self):
        from pathlib import Path

        return Path(getattr(self.settings, "data_dir", Path("data"))).resolve()

    def _generated_projects_dir(self):
        return self._data_dir() / "generated" / "projects"

    def _approval_policy(self) -> str:
        return str(getattr(self.settings, "approval_policy", "auto_safe"))

    @staticmethod
    def _approval_result(approval: dict[str, Any]):
        from jakata_agent.tools.base import ToolResult

        return ToolResult(
            ok=False,
            summary=f"Approval required. Use /approve {approval.get('id')} or /deny {approval.get('id')}.",
            data={"approval": approval},
            error="approval_required",
        )

    @staticmethod
    def _denied_result(approval: dict[str, Any]):
        from jakata_agent.tools.base import ToolResult

        return ToolResult(ok=False, summary="Action denied by operator.", data={"approval": approval}, error="approval_denied")

    def _synthesise(
        self,
        user_message: str,
        plan: list[PlanStep],
        results: list[dict[str, Any]],
        memory_context: str = "",
    ) -> tuple[str, str]:
        del plan
        direct = self._direct_tool_reply(results)
        if direct is not None:
            return "local:tool", direct
        return self.client.complete(self._build_synthesis_messages(user_message, results, memory_context))

    def _general_chat_reply(self, user_message: str, memory_context: str = "") -> tuple[str, str]:
        return self.client.complete(self._build_general_chat_messages(user_message, memory_context))

    def _build_general_chat_messages(self, user_message: str, memory_context: str = "") -> list[dict[str, Any]]:
        messages = [self.messages[0], *self._short_prompt_context()]
        context = memory_context.strip()
        if context:
            messages.append({"role": "system", "content": "Relevant memory and knowledge context:\n" + context})
        messages.append({"role": "user", "content": user_message})
        return messages

    def _build_synthesis_messages(
        self,
        user_message: str,
        results: list[dict[str, Any]],
        memory_context: str = "",
    ) -> list[dict[str, Any]]:
        step_summaries: list[str] = []
        for result in results:
            tool_name = result["tool"]
            if not result["ok"]:
                step_summaries.append(f"[{tool_name}] FAILED: {result.get('error', 'unknown error')}")
            else:
                rendered = str(result.get("rendered", "")).strip()
                step_summaries.append(f"[{tool_name}] {rendered or result['summary']}")
        context = memory_context.strip()
        context_block = f"\n\nRelevant memory and knowledge context:\n{context}" if context else ""
        return [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": f"User: {user_message}{context_block}\n\nResults:\n" + "\n".join(step_summaries)},
        ]

    def _stream_messages(self, user_message: str, messages: list[dict[str, Any]]) -> Iterator[tuple[str, str]]:
        chunks: list[str] = []
        current_model = ""
        try:
            for model, chunk in self.client.stream_complete(messages):
                current_model = model
                chunks.append(chunk)
                yield model, chunk
        except Exception:
            if chunks:
                self._record_conversation(user_message, "".join(chunks))
                return
            current_model, content = self.client.complete(messages)
            chunks = [content]
            yield current_model, content
        self._record_conversation(user_message, "".join(chunks))

    @staticmethod
    def _direct_tool_reply(results: list[dict[str, Any]]) -> str | None:
        if not results:
            return None
        if len(results) > 1:
            if any(result.get("tool") == "read_file" for result in results):
                return None
            lines: list[str] = []
            for result in results:
                if not result.get("ok"):
                    return None
                rendered = str(result.get("rendered") or result.get("summary") or "").strip()
                lines.append(f"{result.get('tool')}: {rendered[:500]}")
            return "\n".join(lines)
        result = results[0]
        if result.get("tool") == "read_file":
            return None
        summary = str(result.get("summary", "")).strip()
        error = str(result.get("error", "")).strip()
        if result.get("ok"):
            rendered = str(result.get("rendered", "")).strip()
            if rendered and ("\n" in rendered or rendered.startswith("#")):
                return rendered
            return summary or rendered or "Tool action complete."
        return summary or error or "System action failed."

    @staticmethod
    def _is_general_chat_decision(decision: PlanDecision) -> bool:
        return all(step.tool == "general_chat" for step in decision.steps)

    def _build_memory_payload(self, query: str) -> dict[str, Any]:
        retrieved = self.memory.retrieve(query)
        source = retrieved.permanent_memories or self.memory.store.recent(limit=10)
        facts = [
            {
                "kind": record.kind,
                "content": record.content.strip().rstrip("."),
                "summary": record.summary,
                "source": "memory",
            }
            for record in source
        ]
        knowledge_chunks = retrieved.knowledge_chunks or self.memory.knowledge_chunks
        if not facts and knowledge_chunks:
            for chunk in knowledge_chunks:
                for raw_line in chunk.splitlines():
                    line = raw_line.strip().strip("-").strip()
                    if not line:
                        continue
                    facts.append(
                        {
                            "kind": "knowledge_fact",
                            "content": line.rstrip("."),
                            "summary": line[:160],
                            "source": "knowledge",
                        }
                    )
        structured: dict[str, list[str]] = {}
        for fact in facts:
            structured.setdefault(fact["kind"], []).append(fact["content"])
        graph = self.memory.graph_search(query)
        summary = "; ".join(fact["content"] for fact in facts[:5]) if facts else "No personal memory found."
        return {
            "summary": summary,
            "facts": facts,
            "structured": structured,
            "archived_chat_chunks": retrieved.archived_chat_chunks,
            "graph": graph,
        }

    def _retrieve_memory_context(self, user_message: str, max_chars: int = 6000) -> str:
        try:
            context = self.memory.retrieve(user_message).to_system_context()
        except Exception:
            return ""
        context = context.strip()
        if len(context) <= max_chars:
            return context
        return context[:max_chars].rstrip() + "\n..."

    def _short_prompt_context(self, *, max_messages: int = 2) -> list[dict[str, Any]]:
        return [dict(item) for item in self.messages if item.get("role") != "system"][-max_messages:]

    def _conversation_context(self, *, max_messages: int = 2, max_chars: int = 1600) -> str:
        recent = [item for item in self.messages if item.get("role") != "system"][-max_messages:]
        lines: list[str] = []
        for item in recent:
            role = str(item.get("role", "")).strip() or "message"
            content = str(item.get("content", "")).strip()
            if content:
                lines.append(f"{role}: {content[:700]}")
        context = "\n".join(lines).strip()
        if len(context) <= max_chars:
            return context
        return context[-max_chars:].lstrip()

    @classmethod
    def _resolve_tool_placeholders(cls, value: Any, tool_context: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            return {key: cls._resolve_tool_placeholders(item, tool_context) for key, item in value.items()}
        if isinstance(value, list):
            return [cls._resolve_tool_placeholders(item, tool_context) for item in value]
        if not isinstance(value, str):
            return value

        def replace(match: re.Match[str]) -> str:
            path = match.group(1)
            current: Any = tool_context
            for part in path.split("."):
                if isinstance(current, dict) and part in current:
                    current = current[part]
                else:
                    return match.group(0)
            return str(current)

        return PLACEHOLDER_RE.sub(replace, value)

    @classmethod
    def _has_unresolved_placeholder(cls, value: Any) -> bool:
        if isinstance(value, dict):
            return any(cls._has_unresolved_placeholder(item) for item in value.values())
        if isinstance(value, list):
            return any(cls._has_unresolved_placeholder(item) for item in value)
        return isinstance(value, str) and bool(PLACEHOLDER_RE.search(value))
