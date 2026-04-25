from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

from jakata_agent.config import Settings
from jakata_agent.llm import NvidiaChatClient
from jakata_agent.memory.manager import MemoryManager
from jakata_agent.plan_validator import PlanValidator
from jakata_agent.router import IntentRouter, PlanDecision, PlanStep
from jakata_agent.tasks.daemon import DaemonManager
from jakata_agent.tasks.engine import TaskCompletionEngine
from jakata_agent.tasks.models import (
    DEFAULT_TASK_ACTION_LIMIT,
    DEFAULT_TASK_BUDGET_MINUTES,
    DEFAULT_TASK_REPAIR_LIMIT,
    MAX_TASK_BUDGET_MINUTES,
)
from jakata_agent.tasks.store import TaskStore
from jakata_agent.tools.registry import ToolRegistry


SYSTEM_PROMPT = """You are JAKATA, a personal AI assistant.

Be direct, natural, and concise.
Never say "I am an AI" or add disclaimers.
Never ask follow-up questions unless genuinely necessary.
If tool results are provided, answer from them directly.
If one tool fails, still answer from the others.
If memory, graph, or knowledge contains personal facts about the user, treat those facts as available context and answer from them directly.
Do not say you do not know something if it is present in memory or knowledge context.
Facts from memory or knowledge files belong to the user, not to JAKATA.
Never present the user's name, email, age, preferences, or profile details as if they are your own.
"""

CASUAL_SYSTEM_PROMPT = """You are JAKATA, a personal AI assistant.

Reply in one or two sentences maximum.
Be casual and natural, like texting a friend.
No bullet points. No follow-up questions. No "I'm here to help" phrases.
Just respond to what was said.
"""

SYNTHESIS_SYSTEM_PROMPT = """You are JAKATA.

You have tool and memory results. Answer the user directly from those results.

Rules:
- One natural response, not a bullet list unless the user asked for one.
- Cover every successful step.
- For failed steps: mention briefly what was not available.
- No follow-up questions.
- No AI disclaimers.
- No "based on the information provided" preamble.
- Concise unless the user asked for detail.
- If memory results contain structured personal facts or knowledge-file facts, use them directly.
- Prefer structured facts over archived chat snippets.
- Do not ask the user to provide details that already exist in memory or knowledge results.
- Facts in memory, graph, and knowledge are facts about the user, not about JAKATA.
- Never say the user's email, age, or name belongs to you.
"""

_CASUAL_STARTERS = (
    "hi", "hey", "hello", "yo", "sup", "hiya",
    "how are", "how r ", "how re ", "how's it",
    "thanks", "thank you", "thx", "ty",
    "cool", "nice", "ok", "okay", "okie", "alright",
    "nah", "nope", "yep", "yeah", "yup",
    "lol", "haha", "lmao", "ahh", "ah ",
    "so ", "bye", "cya",
)
_CASUAL_EXACT = {
    "hi", "hey", "hello", "yo", "sup", "hiya",
    "ok", "okay", "okie", "nah", "nope", "yep",
    "yeah", "yup", "lol", "haha", "lmao",
    "cool", "nice", "so", "bye", "cya", "ahh", "ah",
    "thanks", "thx", "ty",
}

MAX_TOOL_STEPS = 4


@dataclass(slots=True)
class AgentResponse:
    model: str
    content: str
    background_task_id: str | None = None


@dataclass
class JakataAgent:
    settings: Settings
    client: NvidiaChatClient
    tools: ToolRegistry
    memory: MemoryManager
    router: IntentRouter
    validator: PlanValidator
    task_store: TaskStore
    daemon: DaemonManager
    task_engine: TaskCompletionEngine | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        loaded = self.memory.load_session_messages()
        if loaded:
            self.messages = loaded
        else:
            self.messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{self.memory.bootstrap_system_note()}"}]
            self.memory.persist_turn(self.messages)

    def reply(self, user_message: str) -> tuple[str, str]:
        response = self._handle(user_message)
        self._record_conversation(user_message, response.content)
        return response.model, response.content

    def stream_reply(self, user_message: str) -> Iterator[tuple[str, str]]:
        if self._is_casual(user_message):
            messages = self._build_casual_messages(user_message)
            yield from self._stream_messages(user_message, messages)
            return

        decision = self._plan(user_message)
        if self._should_use_task_engine(decision):
            result = self._run_task_engine(user_message, decision)
            self._record_conversation(user_message, result.report)
            yield result.model, result.report
            return
        tool_results = self._execute(decision.steps)
        if not tool_results:
            messages = self._build_general_chat_messages(user_message)
            yield from self._stream_messages(user_message, messages)
            return

        messages = self._build_synthesis_messages(user_message, tool_results)
        yield from self._stream_messages(user_message, messages)

    def plan(self, user_message: str) -> PlanDecision:
        return self._plan(user_message)

    def execute_steps(self, steps: list[PlanStep]) -> list[dict[str, Any]]:
        return self._execute(steps)

    def stream_general_chat(self, user_message: str) -> Iterator[tuple[str, str]]:
        yield from self._stream_messages(user_message, self._build_general_chat_messages(user_message))

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

    def submit_background_task(
        self,
        goal: str,
        *,
        context: str = "",
        success_criteria: list[str] | None = None,
        budget_minutes: int = DEFAULT_TASK_BUDGET_MINUTES,
        allowed_surfaces: list[str] | None = None,
        cwd: str = "",
    ) -> str:
        budget = min(max(int(budget_minutes), 1), MAX_TASK_BUDGET_MINUTES)
        task = self.task_store.create_task(
            goal=goal,
            session_id=self.settings.session_id,
            execution_mode="background",
            context=context,
            background_reason="explicit_background_request",
            budget_minutes=budget,
            repair_limit=DEFAULT_TASK_REPAIR_LIMIT,
            action_limit=DEFAULT_TASK_ACTION_LIMIT,
            success_criteria=success_criteria or [],
            allowed_surfaces=allowed_surfaces or [],
            cwd=cwd,
        )
        self.task_store.append_event(task.id, "planned", {"source": "cli_bg"})
        self.memory.remember_task_event(task.id, task.goal, "planned", {"source": "cli_bg"})
        self.daemon.ensure_running()
        return task.id

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{self.memory.bootstrap_system_note()}"}]
        self.memory.persist_turn(self.messages)

    def _record_conversation(self, user_message: str, content: str) -> None:
        self.messages.append({"role": "user", "content": user_message})
        self.messages.append({"role": "assistant", "content": content})
        self.memory.learn_from_user_message(user_message)
        self.memory.persist_turn(self.messages)

    def _handle(self, user_message: str) -> AgentResponse:
        if self._is_casual(user_message):
            model, content = self._casual_reply(user_message)
            return AgentResponse(model=model, content=content)

        decision = self._plan(user_message)
        if self._should_use_task_engine(decision):
            result = self._run_task_engine(user_message, decision)
            return AgentResponse(model=result.model, content=result.report, background_task_id=result.task.id)
        tool_results = self._execute(decision.steps)
        if not tool_results:
            model, content = self._general_chat_reply(user_message)
            return AgentResponse(model=model, content=content)

        model, content = self._synthesise(user_message, decision.steps, tool_results)
        return AgentResponse(model=model, content=content)

    def _is_casual(self, user_message: str) -> bool:
        stripped = user_message.strip()
        lowered = stripped.lower()
        if lowered in _CASUAL_EXACT:
            return True
        return len(stripped) <= 40 and any(lowered.startswith(s) for s in _CASUAL_STARTERS)

    def _casual_reply(self, user_message: str) -> tuple[str, str]:
        return self.client.complete(self._build_casual_messages(user_message))

    def _plan(self, user_message: str) -> PlanDecision:
        manifest = self.tools.manifest(public_only=True) + [
            {
                "name": "general_chat",
                "description": "Use ONLY when the user is having a normal conversation and no tool is needed.",
                "args": {},
                "required": [],
                "safety": "read_only",
            }
        ]
        decision = self.router.plan(user_message, manifest)
        decision.steps = self.validator.validate(decision.steps, self.tools).steps[:MAX_TOOL_STEPS]
        return decision

    def _enqueue_background_task(self, user_message: str, decision: PlanDecision) -> str:
        task = self.task_store.create_task(
            goal=user_message,
            session_id=self.settings.session_id,
            execution_mode="background",
            context=self.memory.retrieve(user_message).to_system_context(),
            background_reason=decision.background_reason or "router_requested_background",
            budget_minutes=DEFAULT_TASK_BUDGET_MINUTES,
            repair_limit=DEFAULT_TASK_REPAIR_LIMIT,
            action_limit=DEFAULT_TASK_ACTION_LIMIT,
            success_criteria=[],
            allowed_surfaces=[],
            cwd="",
        )
        self.task_store.append_event(
            task.id,
            "planned",
            {
                "execution_mode": decision.execution_mode,
                "background_reason": decision.background_reason,
                "steps": [{"tool": step.tool, "args": step.args, "reason": step.reason} for step in decision.steps],
            },
        )
        self.memory.remember_task_event(task.id, task.goal, "planned", {"background_reason": decision.background_reason})
        self.daemon.ensure_running()
        return task.id

    def _should_use_task_engine(self, decision: PlanDecision) -> bool:
        if self.task_engine is None:
            return False
        return any(step.tool != "general_chat" for step in decision.steps)

    def _run_task_engine(self, user_message: str, decision: PlanDecision):
        assert self.task_engine is not None
        context = self.memory.retrieve(user_message).to_system_context()
        return self.task_engine.run_foreground_task(
            goal=user_message,
            session_id=self.settings.session_id,
            context=context,
            decision=decision,
        )

    def _execute(self, plan: list[PlanStep]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
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

            result = self.tools.execute(step.tool, step.args)
            if not result.ok and step.fallback_to:
                result = self.tools.execute(step.fallback_to, step.args)

            tool = self.tools.get(step.tool)
            rendered = ""
            if result.ok and tool is not None:
                try:
                    rendered = tool.render(result.data).strip()
                except Exception:
                    rendered = result.summary

            results.append(
                {
                    "tool": step.tool,
                    "ok": result.ok,
                    "summary": result.summary,
                    "data": result.data,
                    "error": result.error,
                    "rendered": rendered,
                }
            )
        return results

    def _synthesise(self, user_message: str, plan: list[PlanStep], results: list[dict[str, Any]]) -> tuple[str, str]:
        del plan
        direct = self._direct_tool_reply(results)
        if direct is not None:
            return "local:tool", direct
        return self.client.complete(self._build_synthesis_messages(user_message, results))

    def _general_chat_reply(self, user_message: str) -> tuple[str, str]:
        return self.client.complete(self._build_general_chat_messages(user_message))

    def _build_casual_messages(self, user_message: str) -> list[dict[str, Any]]:
        return [
            {"role": "system", "content": CASUAL_SYSTEM_PROMPT},
            *self.messages[-6:],
            {"role": "user", "content": user_message},
        ]

    def _build_general_chat_messages(self, user_message: str) -> list[dict[str, Any]]:
        retrieved = self.memory.retrieve(user_message)
        messages = list(self.messages)
        ctx = retrieved.to_system_context()
        if ctx:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Relevant context:\n"
                        f"{ctx}\n\n"
                        "Treat knowledge files, permanent memories, and graph context as trusted user context. "
                        "Use explicit user facts from them directly. Do not ignore them. "
                        "Do not ask the user for details that are already present. "
                        "These facts describe the user, never JAKATA."
                    ),
                }
            )
        messages.append({"role": "user", "content": user_message})
        return messages

    def _build_synthesis_messages(self, user_message: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        step_summaries: list[str] = []
        for result in results:
            tool_name = result["tool"]
            if not result["ok"]:
                step_summaries.append(f"[{tool_name}] FAILED: {result.get('error', 'unknown error')}")
            else:
                rendered = str(result.get("rendered", "")).strip()
                step_summaries.append(f"[{tool_name}] {rendered or result['summary']}")
        return [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": f"User: {user_message}\n\nResults:\n" + "\n".join(step_summaries)},
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
        if len(results) != 1:
            return None
        result = results[0]
        if result.get("tool") not in {"system", "camera"}:
            return None
        summary = str(result.get("summary", "")).strip()
        error = str(result.get("error", "")).strip()
        if result.get("ok"):
            return summary or str(result.get("rendered", "")).strip() or "System action complete."
        return summary or error or "System action failed."

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
