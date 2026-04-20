from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

from jakata_agent.config import Settings
from jakata_agent.llm import NvidiaChatClient
from jakata_agent.memory.manager import MemoryManager
from jakata_agent.plan_validator import PlanValidator
from jakata_agent.router import IntentRouter, PlanStep
from jakata_agent.tools.registry import ToolRegistry


SYSTEM_PROMPT = """You are JAKATA, a personal AI assistant.

Be direct, natural, and concise.
Never say "I am an AI" or add disclaimers.
Never ask follow-up questions unless genuinely necessary.
If tool results are provided, answer from them directly.
If one tool fails, still answer from the others.
If memory or knowledge contains personal facts about the user, treat those facts as available context and answer from them directly.
Do not say you do not know something if it is present in memory or knowledge context.
Facts from memory or knowledge files belong to the user, not to JAKATA.
Never present the user's name, email, age, preferences, or profile details as if they are your own.
"""

CASUAL_SYSTEM_PROMPT = """You are JAKATA, a personal AI assistant.

Reply in one or two sentences maximum.
Be casual and natural — like texting a friend.
No bullet points. No follow-up questions. No "I'm here to help" phrases.
Just respond to what was said.
"""

SYNTHESIS_SYSTEM_PROMPT = """You are JAKATA.

You have tool and memory results. Answer the user directly from those results.

Rules:
- One natural response — not a bullet list unless the user asked for one.
- Cover every successful step.
- For failed steps: mention briefly what wasn't available.
- No follow-up questions.
- No AI disclaimers.
- No "based on the information provided" preamble.
- Concise unless the user asked for detail.
- If memory results contain structured personal facts or knowledge-file facts, use them directly.
- Prefer structured facts over archived chat snippets.
- Do not ask the user to provide details that already exist in memory or knowledge results.
- Facts in memory and knowledge are facts about the user, not about JAKATA.
- Never say the user's email, age, or name belongs to you.
"""

# Short messages that are clearly casual — skip the planner entirely
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


@dataclass
class JakataAgent:
    settings: Settings
    client: NvidiaChatClient
    tools: ToolRegistry
    memory: MemoryManager
    router: IntentRouter
    validator: PlanValidator
    messages: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        loaded = self.memory.load_session_messages()
        if loaded:
            self.messages = loaded
        else:
            self.messages = [
                {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{self.memory.bootstrap_system_note()}"}
            ]
            self.memory.persist_turn(self.messages)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def reply(self, user_message: str) -> tuple[str, str]:
        model, content = self._handle(user_message)
        self.messages.append({"role": "user", "content": user_message})
        self.messages.append({"role": "assistant", "content": content})
        self.memory.learn_from_user_message(user_message)
        self.memory.persist_turn(self.messages)
        return model, content

    def stream_reply(self, user_message: str) -> Iterator[tuple[str, str]]:
        model, content = self._handle(user_message)
        self.messages.append({"role": "user", "content": user_message})
        self.messages.append({"role": "assistant", "content": content})
        self.memory.learn_from_user_message(user_message)
        self.memory.persist_turn(self.messages)
        yield model, content

    def reset(self) -> None:
        self.messages = [
            {"role": "system", "content": f"{SYSTEM_PROMPT}\n\n{self.memory.bootstrap_system_note()}"}
        ]
        self.memory.persist_turn(self.messages)

    # ------------------------------------------------------------------
    # Core dispatch
    # ------------------------------------------------------------------

    def _handle(self, user_message: str) -> tuple[str, str]:
        # Short casual messages — fast LLM with minimal prompt, skip planner entirely
        if self._is_casual(user_message):
            return self._casual_reply(user_message)

        # Plan → execute → synthesise
        plan = self._plan(user_message)
        tool_results = self._execute(plan)

        # Pure general_chat — no tool results, just LLM chat with memory context
        if not tool_results:
            return self._general_chat_reply(user_message)

        # Tool results exist — always synthesise via LLM for natural responses
        return self._synthesise(user_message, plan, tool_results)

    # ------------------------------------------------------------------
    # Casual fast path
    # ------------------------------------------------------------------

    def _is_casual(self, user_message: str) -> bool:
        stripped = user_message.strip()
        lowered = stripped.lower()
        if lowered in _CASUAL_EXACT:
            return True
        # Short message starting with a casual opener
        if len(stripped) <= 40 and any(lowered.startswith(s) for s in _CASUAL_STARTERS):
            return True
        return False

    def _casual_reply(self, user_message: str) -> tuple[str, str]:
        messages = [
            {"role": "system", "content": CASUAL_SYSTEM_PROMPT},
            *self.messages[-6:],  # last 3 turns for context
            {"role": "user", "content": user_message},
        ]
        return self.client.complete(messages)

    # ------------------------------------------------------------------
    # Plan
    # ------------------------------------------------------------------

    def _plan(self, user_message: str) -> list[PlanStep]:
        manifest = self.tools.manifest() + [
            {
                "name": "general_chat",
                "description": "Use ONLY when the user is having a normal conversation and no tool is needed.",
                "args": {},
                "required": [],
                "safety": "read_only",
            }
        ]
        planned = self.router.plan(user_message, manifest)
        return self.validator.validate(planned, self.tools).steps[:MAX_TOOL_STEPS]

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def _execute(self, plan: list[PlanStep]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for step in plan:
            if step.tool == "general_chat":
                continue

            if step.tool == "memory":
                payload = self._build_memory_payload(step.args.get("query", ""))
                results.append({
                    "tool": "memory",
                    "ok": True,
                    "summary": payload["summary"],
                    "data": payload,
                    "rendered": json.dumps(payload, ensure_ascii=False),
                })
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

            results.append({
                "tool": step.tool,
                "ok": result.ok,
                "summary": result.summary,
                "data": result.data,
                "error": result.error,
                "rendered": rendered,
            })
        return results

    # ------------------------------------------------------------------
    # Synthesise
    # ------------------------------------------------------------------

    def _synthesise(self, user_message: str, plan: list[PlanStep], results: list[dict]) -> tuple[str, str]:
        step_summaries: list[str] = []
        for r in results:
            tool = r["tool"]
            if not r["ok"]:
                step_summaries.append(f"[{tool}] FAILED: {r.get('error', 'unknown error')}")
            else:
                rendered = r.get("rendered", "").strip()
                step_summaries.append(f"[{tool}] {rendered or r['summary']}")

        context = "\n".join(step_summaries)
        synthesis_messages = [
            {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
            {"role": "user", "content": f"User: {user_message}\n\nResults:\n{context}"},
        ]
        return self.client.complete(synthesis_messages)

    # ------------------------------------------------------------------
    # General chat (no tools invoked)
    # ------------------------------------------------------------------

    def _general_chat_reply(self, user_message: str) -> tuple[str, str]:
        retrieved = self.memory.retrieve(user_message)
        messages = list(self.messages)
        context_parts: list[str] = []
        if retrieved.permanent_memories:
            context_parts.append(
                "Permanent memories:\n"
                + "\n".join(f"- [{item.kind}] {item.content}" for item in retrieved.permanent_memories)
            )
        if retrieved.knowledge_chunks:
            context_parts.append("Knowledge files:\n" + "\n".join(f"- {item}" for item in retrieved.knowledge_chunks))
        ctx = "\n\n".join(context_parts).strip()
        if ctx:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Relevant context:\n"
                        f"{ctx}\n\n"
                        "Treat knowledge files and permanent memories as the trusted source of truth for user profile facts. "
                        "Use explicit user facts from them directly. Do not ignore them. "
                        "Do not ask the user for details that are already present. "
                        "These facts describe the user, never JAKATA."
                    ),
                }
            )
        messages.append({"role": "user", "content": user_message})
        return self.client.complete(messages)

    # ------------------------------------------------------------------
    # Memory helpers
    # ------------------------------------------------------------------

    def _build_memory_payload(self, query: str) -> dict[str, Any]:
        retrieved = self.memory.retrieve(query)
        source = retrieved.permanent_memories or self.memory.store.recent(limit=10)
        facts = [
            {
                "kind": r.kind,
                "content": r.content.strip().rstrip("."),
                "summary": r.summary,
                "source": "memory",
            }
            for r in source
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
        for f in facts:
            structured.setdefault(f["kind"], []).append(f["content"])
        summary = "; ".join(f["content"] for f in facts[:5]) if facts else "No personal memory found."
        return {
            "summary": summary,
            "facts": facts,
            "structured": structured,
            "archived_chat_chunks": retrieved.archived_chat_chunks,
        }
