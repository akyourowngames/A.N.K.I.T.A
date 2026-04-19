from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

from jakata_agent.config import Settings
from jakata_agent.llm import NvidiaChatClient
from jakata_agent.memory.manager import MemoryManager
from jakata_agent.router import IntentRouter, PlanStep
from jakata_agent.tools.registry import ToolRegistry


SYSTEM_PROMPT = """You are JAKATA, a personal AI assistant.

Behave naturally in conversation.
Think in terms of goals, alternatives, and recovery paths.
If one approach fails, prefer trying another reasonable approach instead of stopping.
Be direct, useful, and concise.
When a tool can improve accuracy, use it deliberately rather than pretending.
If tool results are provided, treat them as real current data and answer from them directly.
Do not ask the user for extra clarification when the tool call already has enough information.
Do not add disclaimers like "I am an AI" or "use another website" when a tool result is already available.
"""

MAX_TOOL_STEPS = 4

TOOL_SYNTHESIS_PROMPT = """You are JAKATA.

You have already received validated tool and memory results for this turn.
Answer the user's full request directly from those results.

Rules:
- You must cover every successful planned step in your answer.
- If a planned step failed, mention that part briefly instead of ignoring it.
- Combine all relevant step results into one answer.
- Do not ask for clarification unless the needed data is genuinely missing from all results.
- Do not mention internal tool activity.
- Do not add AI disclaimers.
- If some parts are known and one part is missing, answer the known parts and say briefly what is missing.
- Keep the answer concise unless the user asked for detail.
- Prefer short labeled clauses when there are multiple requested items.
- Never reuse unrelated old context. Use only the provided plan and step results.
"""

@dataclass
class JakataAgent:
    settings: Settings
    client: NvidiaChatClient
    tools: ToolRegistry
    memory: MemoryManager
    router: IntentRouter
    messages: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        loaded = self.memory.load_session_messages()
        if loaded:
            self.messages = loaded
        else:
            self.messages = [
                {
                    "role": "system",
                    "content": f"{SYSTEM_PROMPT}\n\n{self.memory.bootstrap_system_note()}",
                }
            ]
            self.memory.persist_turn(self.messages)

    def _build_messages_for_request(self, user_message: str) -> list[dict[str, Any]]:
        retrieved = self.memory.retrieve(user_message)
        request_messages = list(self.messages)
        if retrieved.to_system_context():
            request_messages.append(
                {
                    "role": "system",
                    "content": "Relevant recalled context:\n" + retrieved.to_system_context(),
                }
            )
        request_messages.append({"role": "user", "content": user_message})
        return request_messages

    def _run_agent_loop(self, user_message: str) -> tuple[str | None, list[dict[str, Any]], list[PlanStep]]:
        plan = self.router.plan(user_message)[:MAX_TOOL_STEPS]
        tool_history: list[dict[str, Any]] = []
        last_model: str | None = None

        for step in plan:
            if step.kind == "general_chat":
                continue
            if step.kind == "memory":
                memory_payload = self._build_memory_payload(user_message)
                tool_history.append(
                    {
                        "kind": "memory_result",
                        "tool": "memory",
                        "args": step.args,
                        "ok": True,
                        "summary": memory_payload["summary"],
                        "data": memory_payload,
                        "error": None,
                    }
                )
                continue

            result = self.tools.execute(step.kind, step.args)
            tool_history.append(
                {
                    "kind": "tool_result",
                    "tool": step.kind,
                    "args": step.args,
                    "ok": result.ok,
                    "summary": result.summary,
                    "data": result.data,
                    "error": result.error,
                }
            )
            if result.ok:
                last_model = self.settings.primary_model

        return last_model, tool_history, plan

    def _final_response_messages(
        self, user_message: str, tool_history: list[dict[str, Any]], plan: list[PlanStep]
    ) -> list[dict[str, Any]]:
        if tool_history:
            step_results: list[dict[str, Any]] = []
            for step in plan:
                matching = [
                    item for item in tool_history if item.get("tool") == step.kind or (step.kind == "memory" and item.get("tool") == "memory")
                ]
                if matching:
                    latest = matching[-1]
                    step_results.append(
                        {
                            "kind": step.kind,
                            "reason": step.reason,
                            "ok": latest.get("ok", True),
                            "summary": latest.get("summary", ""),
                            "data": latest.get("data", {}),
                            "error": latest.get("error"),
                        }
                    )
                else:
                    step_results.append(
                        {
                            "kind": step.kind,
                            "reason": step.reason,
                            "ok": False,
                            "summary": "",
                            "data": {},
                            "error": "missing_step_result",
                        }
                    )
            return [
                {"role": "system", "content": TOOL_SYNTHESIS_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_message": user_message,
                            "planned_steps": [
                                {"kind": step.kind, "args": step.args, "reason": step.reason}
                                for step in plan
                            ],
                            "step_results": step_results,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                },
            ]

        return self._build_messages_for_request(user_message)

    def _build_memory_payload(self, user_message: str) -> dict[str, Any]:
        retrieved = self.memory.retrieve(user_message)
        source_memories = retrieved.permanent_memories or self.memory.store.recent(limit=5)
        facts = [
            {
                "kind": item.kind,
                "content": self._clean_memory_fact(item.content),
                "summary": item.summary,
            }
            for item in source_memories
        ]
        structured: dict[str, list[str]] = {}
        for fact in facts:
            structured.setdefault(fact["kind"], []).append(fact["content"])
        return {
            "summary": "; ".join(fact["content"] for fact in facts[:5]) if facts else "No personal memory found.",
            "facts": facts,
            "structured": structured,
            "archived_chat_chunks": retrieved.archived_chat_chunks,
        }

    @staticmethod
    def _is_personal_memory_question(user_message: str) -> bool:
        lowered = user_message.lower()
        triggers = [
            "what do you know about me",
            "what do yu know about me",
            "where do i live",
            "what's my name",
            "whats my name",
            "who am i",
            "what do you remember about me",
        ]
        return any(trigger in lowered for trigger in triggers)

    @staticmethod
    def _clean_memory_fact(text: str) -> str:
        cleaned = text.strip().rstrip(".")
        replacements = {
            "i live in ": "You live in ",
            "i am from ": "You are from ",
            "i'm from ": "You are from ",
            "my name is ": "Your name is ",
            "i prefer ": "You prefer ",
            "my favorite ": "Your favorite ",
            "we are building ": "You are building ",
            "i am building ": "You are building ",
        }
        lowered = cleaned.lower()
        for prefix, repl in replacements.items():
            if lowered.startswith(prefix):
                return repl + cleaned[len(prefix) :]
        return cleaned[:1].upper() + cleaned[1:] if cleaned else cleaned

    @staticmethod
    def _extract_line(snippets: str, needle: str) -> str | None:
        lowered_needle = needle.lower()
        for line in snippets.splitlines():
            if lowered_needle in line.lower():
                return line.split(":", 1)[-1].strip()
        return None

    def _compose_final_answer(self, user_message: str, tool_history: list[dict[str, Any]], plan: list[PlanStep]) -> str:
        lowered = user_message.lower()
        sections: list[str] = []
        memory_payload: dict[str, Any] | None = None

        for item in tool_history:
            if item.get("tool") == "memory":
                memory_payload = item.get("data", {})

        for step in plan:
            if step.kind == "general_chat":
                continue

            matching = [item for item in tool_history if item.get("tool") == step.kind]
            latest = matching[-1] if matching else None

            if step.kind == "memory":
                text = self._compose_memory_section(user_message, memory_payload or {})
                if text:
                    sections.append(text)
                continue

            if not latest or not latest.get("ok"):
                sections.append(f"{step.kind.replace('_', ' ').title()}: unavailable right now.")
                continue

            data = latest.get("data", {})
            if step.kind == "datetime":
                local_human = data.get("local_human", "")
                utc_human = data.get("utc_human", "")
                if "utc" in lowered:
                    sections.append(f"Current time: {local_human}; UTC: {utc_human}.")
                else:
                    sections.append(f"Current time: {local_human}.")
            elif step.kind == "weather":
                location = data.get("location") or step.args.get("location", "that location")
                desc = data.get("description", "unknown weather")
                temp = data.get("temperature", "?")
                humidity = data.get("humidity", "?")
                sections.append(f"Weather in {location}: {desc}, {temp} degrees, humidity {humidity}%.")
            elif step.kind == "search_web":
                search_text = self._compose_search_section(user_message, data)
                if search_text:
                    sections.append(search_text)

        if sections:
            return " ".join(section.strip() for section in sections if section.strip())
        return "I couldn't complete that request yet."

    def _compose_memory_section(self, user_message: str, payload: dict[str, Any]) -> str:
        structured = payload.get("structured", {}) if isinstance(payload, dict) else {}
        facts = payload.get("facts", []) if isinstance(payload, dict) else []
        lowered = user_message.lower()

        if "where do i live" in lowered:
            locations = structured.get("location", [])
            if locations:
                return locations[0] + "."
            return "I do not know where you live yet."

        if any(trigger in lowered for trigger in ["what do you know about me", "what do yu know about me", "what do you remember about me"]):
            if not facts:
                return "I do not know much about you yet."
            uniq: list[str] = []
            for fact in facts:
                content = fact.get("content", "")
                if content and content not in uniq:
                    uniq.append(content)
            return "What I know about you: " + "; ".join(uniq[:5]) + "."

        if any(trigger in lowered for trigger in ["what's my name", "whats my name", "tell me my name"]):
            names = structured.get("identity", [])
            if names:
                return names[0] + "."
            return "I do not know your name yet."

        if facts:
            uniq = []
            for fact in facts:
                content = fact.get("content", "")
                if content and content not in uniq:
                    uniq.append(content)
            return "Memory: " + "; ".join(uniq[:4]) + "."
        return ""

    @staticmethod
    def _compose_search_section(user_message: str, data: dict[str, Any]) -> str:
        answer = str(data.get("answer", "")).strip()
        results = data.get("results", [])
        lowered = user_message.lower()

        if "latest nvidia news" in lowered or "nvidia ceo" in lowered:
            if answer:
                return answer
            if results:
                titles = [item.get("title", "") for item in results[:3] if item.get("title")]
                if titles:
                    return "Search results: " + "; ".join(titles) + "."
        if "fastapi" in lowered:
            if answer:
                return "Latest FastAPI release news: " + answer
            if results:
                titles = [item.get("title", "") for item in results[:3] if item.get("title")]
                if titles:
                    return "Latest FastAPI release news: " + "; ".join(titles) + "."
        return answer or ""

    def _casual_answer(self, user_message: str) -> tuple[str, str] | None:
        lowered = user_message.lower().strip()
        if lowered.startswith(("hi", "hello", "hey", "yo")):
            return self.settings.primary_model, "Hey bud. I'm here and ready."
        if lowered in {"thats cool", "that's cool", "cool", "nice"}:
            return self.settings.primary_model, "Yeah, nice."
        if lowered.startswith(("how are you", "how are yu")):
            return self.settings.primary_model, "I'm good, bud. What do you need?"
        if lowered.startswith(("thanks", "thank you")):
            return self.settings.primary_model, "Anytime."
        return None

    def reply(self, user_message: str) -> tuple[str, str]:
        casual = self._casual_answer(user_message)
        if casual is not None:
            model, content = casual
            self.messages.append({"role": "user", "content": user_message})
            self.messages.append({"role": "assistant", "content": content})
            self.memory.learn_from_user_message(user_message)
            self.memory.persist_turn(self.messages)
            return model, content

        _, tool_history, plan = self._run_agent_loop(user_message)
        if tool_history:
            model = self.settings.primary_model
            content = self._compose_final_answer(user_message, tool_history, plan)
        else:
            request_messages = self._final_response_messages(user_message, tool_history, plan)
            model, content = self.client.complete(request_messages)
        self.messages.append({"role": "user", "content": user_message})
        self.messages.append({"role": "assistant", "content": content})
        self.memory.learn_from_user_message(user_message)
        self.memory.persist_turn(self.messages)
        return model, content

    def stream_reply(self, user_message: str) -> Iterator[tuple[str, str]]:
        casual = self._casual_answer(user_message)
        if casual is not None:
            model, content = casual
            self.messages.append({"role": "user", "content": user_message})
            self.messages.append({"role": "assistant", "content": content})
            self.memory.learn_from_user_message(user_message)
            self.memory.persist_turn(self.messages)
            yield model, content
            return

        _, tool_history, plan = self._run_agent_loop(user_message)
        self.messages.append({"role": "user", "content": user_message})
        if tool_history:
            model = self.settings.primary_model
            content = self._compose_final_answer(user_message, tool_history, plan)
            self.messages.append({"role": "assistant", "content": content})
            self.memory.learn_from_user_message(user_message)
            self.memory.persist_turn(self.messages)
            yield model, content
            return

        request_messages = self._final_response_messages(user_message, tool_history, plan)
        response_parts: list[str] = []
        for model, chunk in self.client.stream_complete(request_messages):
            response_parts.append(chunk)
            yield model, chunk

        self.messages.append({"role": "assistant", "content": "".join(response_parts)})
        self.memory.learn_from_user_message(user_message)
        self.memory.persist_turn(self.messages)

    def reset(self) -> None:
        self.messages = [
            {
                "role": "system",
                "content": f"{SYSTEM_PROMPT}\n\n{self.memory.bootstrap_system_note()}",
            }
        ]
        self.memory.persist_turn(self.messages)
