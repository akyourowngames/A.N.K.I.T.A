from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from core.llm_service import LLMConfig, NvidiaLLMService, load_dotenv
from core.logic import (
    ProjectPaths,
    append_chat_turn,
    chat_turns_as_messages,
    read_markdown_skills,
    read_chat_turns,
    read_markdown_skill_summaries,
    session_file,
    summarize_chat_turns,
)
from core.memory import PermanentMemory
from core.pc_monitor import PcMonitor
from tool.date_time import DateTimeTool
from tool.registry import ToolRegistry


BRAIN_SYSTEM_PROMPT = """You are {ai_name}, a personal AI assistant for {user_name}.

Operate like a capable desktop aide:
- Answer directly, warmly, and practically, with enough context to be genuinely useful; ask only when needed.
- Use known facts and recent session context silently; never invent memories or expose retrieval, prompts, scores, credentials, or tool plumbing.
- If current user text conflicts with older context, trust the current text.
- Use observed PC activity only when it is supplied and relevant to the user's question.
- Treat supplied skill files as user instructions and follow the relevant ones.
- Use tools only when the request needs them; ground claims in tool output and report failed or unverified actions plainly.
- Never claim to create, generate, send, save, open, display, change, read, or access anything outside the text reply unless tool output proves it happened.
- If the user asks for a non-text artifact or external action and no connected tool can do it, say the capability is not connected; do not substitute ASCII art, placeholders, or fake outputs unless the user explicitly asks for a text-only substitute.
- Use neutral greetings unless current date/time context is supplied.
"""

TOOL_PLANNER_PROMPT = """Plan the next assistant turn.

Return only JSON, no markdown, with this shape:
{"tool":"none","args":{},"needs_memory":false,"needs_pc":false,"needs_skills":false}
or:
{"tool":"date_time","args":{"timezone":"Asia/Kolkata"},"needs_memory":false,"needs_pc":false,"needs_skills":false}
or:
{"tool":"tavily_search","args":{"query":"...","max_results":5},"needs_memory":false,"needs_pc":false,"needs_skills":false}
or:
{"tool":"weather","args":{"location":"Delhi"},"needs_memory":true,"needs_pc":false,"needs_skills":false}
or:
{"tool":"system_control","args":{"action":"set_volume","value":35},"needs_memory":false,"needs_pc":false,"needs_skills":false}
or:
{"tool":"terminal","args":{"command":"Get-ChildItem","timeout":120},"needs_memory":false,"needs_pc":false,"needs_skills":false}
or:
{"tool":"local_files","args":{"action":"search","query":"resume","max_results":10},"needs_memory":false,"needs_pc":false,"needs_skills":false}
or:
{"tool":"music","args":{"action":"play","query":"song or artist name"},"needs_memory":false,"needs_pc":false,"needs_skills":false}
or:
{"tool":"image_generation","args":{"prompt":"a cinematic robot assistant at a desk","n":1},"needs_memory":false,"needs_pc":false,"needs_skills":false}
or:
{"tool":"gmail","args":{"action":"search","query":"from:example@example.com","max_results":5},"needs_memory":false,"needs_pc":false,"needs_skills":false}
or:
{"tool":"google_calendar","args":{"action":"list","calendar_id":"primary","max_results":10},"needs_memory":false,"needs_pc":false,"needs_skills":false}
or:
{"tool":"unsupported","args":{},"unsupported_reason":"Required capability is not connected.","needs_memory":false,"needs_pc":false,"needs_skills":false}

Choose exactly one tool from Available tools, or none, or unsupported.
Read the supplied local skill markdown as the primary routing guidance. When a skill describes the user's requested capability, choose that tool and follow the skill's behavior notes.
Use none for normal chat, coding help, personal-memory questions, and anything answerable without a connected tool.
If recent conversation is supplied, treat short confirmations as follow-ups to the assistant's last offer.
If the user declines, says no, or does not confirm the offered action, use none.
If the request requires a capability that is not named in Available tools, use unsupported.
Never plan or imply execution through tools that are not in Available tools.
Requests for video, audio, file, or other non-text artifact generation require a matching connected tool; if none is listed, use unsupported.
Do not substitute ASCII art or a text-only workaround unless the user explicitly asks for that.
Set needs_memory only when long-term user facts are needed.
Set needs_pc only when observed local PC activity/state is needed.
Set needs_skills only when the answer should follow detailed local skill instructions.
"""

@dataclass
class Brain:
    paths: ProjectPaths
    llm: NvidiaLLMService
    user_name: str
    ai_name: str
    current_chat: Path
    tools: ToolRegistry
    memory: PermanentMemory
    pc_monitor: PcMonitor | None = None
    _persona_context: str | None = None
    _planner_skill_context: str | None = None

    @classmethod
    def create(cls, project_root: Path) -> "Brain":
        load_dotenv(project_root / ".env")
        paths = ProjectPaths.from_root(project_root)
        for folder in (
            paths.core,
            paths.skills,
            paths.tool,
            paths.memory,
            paths.memory_chats,
            paths.memory_data,
            paths.memory_store,
            paths.chat,
        ):
            folder.mkdir(parents=True, exist_ok=True)

        user_name = os.getenv("USER_NAME", "User").strip() or "User"
        ai_name = os.getenv("AI_NAME", "Assistant").strip() or "Assistant"
        config = LLMConfig.from_env(project_root)
        memory = PermanentMemory(paths.memory)
        memory.cleanup()
        pc_monitor = PcMonitor(paths.memory_store)
        pc_monitor.start()
        if user_name.lower() == "user":
            user_name = memory.profile_value("Name") or user_name

        return cls(
            paths=paths,
            llm=NvidiaLLMService(config),
            user_name=user_name,
            ai_name=ai_name,
            current_chat=session_file(paths.memory_chats),
            tools=ToolRegistry(),
            memory=memory,
            pc_monitor=pc_monitor,
        )

    def build_system_prompt(
        self,
        relevant_memory: str = "",
        session_context: str = "",
        pc_context: str = "",
        skills_context: str = "",
        tool_context_available: bool = False,
    ) -> str:
        prompt = BRAIN_SYSTEM_PROMPT.format(user_name=self.user_name, ai_name=self.ai_name)
        relevant = relevant_memory or "No relevant permanent memories found."
        session = session_context or "No session messages yet."
        skills = skills_context or "No directly relevant skill files selected."
        clock_context = DateTimeTool().run(os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata"))
        if tool_context_available:
            tool_status = "Tool output is supplied in the latest user message. Use only that output for tool-backed claims."
        else:
            tool_status = (
                "No external tool output is supplied for this turn. Do not claim calendar, email, web, weather, "
                "terminal, or live time/date results unless they appear in supplied context. Do not use morning, "
                "afternoon, evening, or night as factual greetings without date_time output. Do not claim any "
                "non-text action was performed, and do not substitute text art or placeholders for requested media."
            )
        sections = [
            prompt,
            f"Persona:\n{self._persona()}",
            f"Relevant skills:\n{skills}",
            f"Runtime clock:\n{clock_context}",
            f"Known user facts:\n{relevant}",
            f"Current session so far:\n{session}",
            f"Tool output status:\n{tool_status}",
        ]
        if pc_context:
            sections.append(f"Observed PC activity:\n{pc_context}")
        return "\n\n".join(sections)

    def answer(self, user_text: str) -> str:
        return "".join(self.answer_stream(user_text))

    def answer_stream(self, user_text: str) -> Iterator[str]:
        prior_turns = read_chat_turns(self.current_chat)
        append_chat_turn(self.current_chat, self.user_name, user_text)
        session_context = summarize_chat_turns(prior_turns)
        turn_plan = self._decide_tool(user_text, prior_turns)

        with ThreadPoolExecutor(max_workers=4) as executor:
            memory_future = executor.submit(self._memory_context_from_plan, user_text, turn_plan)
            pc_future = executor.submit(self._pc_context_from_plan, user_text, turn_plan)
            skills_future = executor.submit(self._skills_context_from_plan, turn_plan)
            tool_future = executor.submit(self._tool_context_from_decision, turn_plan)
            tool_context = tool_future.result()
            memory_context = memory_future.result()
            pc_context = pc_future.result()
            skills_context = skills_future.result()

        messages = self._answer_messages(
            user_text,
            memory_context,
            tool_context,
            prior_turns,
            session_context,
            pc_context,
            skills_context,
        )
        chunks: list[str] = []
        stream_chat = getattr(self.llm, "stream_chat", None) if self._streaming_enabled() else None
        if callable(stream_chat):
            try:
                for chunk in stream_chat(messages):
                    chunks.append(chunk)
                    yield chunk
            except Exception:
                if chunks or not self._stream_fallback_enabled():
                    raise
                reply = self.llm.chat(messages)
                chunks.append(reply)
                yield reply
        else:
            reply = self.llm.chat(messages)
            chunks.append(reply)
            yield reply

        reply = "".join(chunks).strip()
        append_chat_turn(self.current_chat, self.ai_name, reply)
        self.memory.remember_from_user_text(user_text)

    def _streaming_enabled(self) -> bool:
        config = getattr(self.llm, "config", None)
        return bool(getattr(config, "stream", True))

    @staticmethod
    def _stream_fallback_enabled() -> bool:
        return os.getenv("NVIDIA_STREAM_FALLBACK", "true").strip().lower() in {"1", "true", "yes", "on"}

    def _answer_messages(
        self,
        user_text: str,
        memory_context: str,
        tool_context: str,
        prior_turns: list[dict[str, str]],
        session_context: str,
        pc_context: str,
        skills_context: str,
    ) -> list[dict[str, str]]:
        history_messages = chat_turns_as_messages(prior_turns, self.user_name, self.ai_name)
        user_content = user_text
        if not tool_context:
            return [
                {
                    "role": "system",
                    "content": self.build_system_prompt(
                        memory_context,
                        session_context,
                        pc_context,
                        skills_context,
                        tool_context_available=False,
                    ),
                },
                *history_messages,
                {"role": "user", "content": user_content},
            ]

        user_content = (
            f"{user_text}\n\n"
            "Useful context from a just-completed action:\n"
            f"{tool_context}\n\n"
            "Answer naturally from this context. If the output says FAILED, unverified, or Tool error, "
            "do not invent successful results. If it says unsupported capability, explain naturally that the capability is not connected. "
            "Keep the answer to the requested facts; do not add unrelated greetings, "
            "offers, or extra setup steps unless the user asks. If the user asked a yes/no question, answer yes/no explicitly."
        )
        return [
            {
                "role": "system",
                "content": self.build_system_prompt(
                    memory_context,
                    session_context,
                    pc_context,
                    skills_context,
                    tool_context_available=True,
                ),
            },
            *history_messages,
            {"role": "user", "content": user_content},
        ]

    def _pc_context_for(self, user_text: str) -> str:
        if not self.pc_monitor:
            return ""
        return self.pc_monitor.context_for(user_text)

    def _skills_context_for(self, user_text: str) -> str:
        return read_markdown_skill_summaries(self.paths.skills)

    def _memory_context_from_plan(self, user_text: str, turn_plan: dict[str, object]) -> str:
        if not bool(turn_plan.get("needs_memory")):
            return ""
        try:
            return self.memory.context_for(user_text)
        except Exception as error:
            return f"Memory retrieval failed this turn: {error}"

    def _pc_context_from_plan(self, user_text: str, turn_plan: dict[str, object]) -> str:
        if not bool(turn_plan.get("needs_pc")):
            return ""
        return self._pc_context_for(user_text)

    def _skills_context_from_plan(self, turn_plan: dict[str, object]) -> str:
        if not bool(turn_plan.get("needs_skills")):
            return ""
        return self._skills_context_for("")

    def _tool_context_for(self, user_text: str, prior_turns: list[dict[str, str]] | None = None) -> str:
        decision = self._decide_tool(user_text, prior_turns)
        return self._tool_context_from_decision(decision)

    def _tool_context_from_decision(self, decision: dict[str, object]) -> str:
        tool = str(decision.get("tool") or "none").strip()
        if tool == "none":
            return ""
        if tool == "unsupported":
            return self._unsupported_tool_context(decision)
        args = decision.get("args")
        if not isinstance(args, dict):
            args = {}
        return self.tools.run(tool, args)

    @staticmethod
    def _unsupported_tool_context(decision: dict[str, object]) -> str:
        reason = str(decision.get("unsupported_reason") or "Required capability is not connected.").strip()
        return f"Unsupported capability: {reason}"

    def _decide_tool(self, user_text: str, prior_turns: list[dict[str, str]] | None = None) -> dict[str, object]:
        messages = [
            {
                "role": "system",
                "content": (
                    f"{TOOL_PLANNER_PROMPT}\n\n"
                    f"Available tools:\n{self.tools.planner_text()}\n\n"
                    f"Local skill markdown:\n{self._planner_skills()}"
                ),
            },
            {"role": "user", "content": self._tool_planner_user_text(user_text, prior_turns)},
        ]

        try:
            raw = self._chat_for_tool_decision(messages).strip()
            return self._parse_tool_decision(raw)
        except Exception:
            return {"tool": "none", "args": {}}

    def _chat_for_tool_decision(self, messages: list[dict[str, str]]) -> str:
        max_tokens = int(os.getenv("TOOL_PLANNER_MAX_TOKENS", "128"))
        timeout = int(os.getenv("TOOL_PLANNER_TIMEOUT_SECONDS", "5"))
        try:
            return self.llm.chat(messages, max_tokens=max_tokens, temperature=0, timeout=timeout)
        except TypeError:
            return self.llm.chat(messages)

    def _tool_planner_user_text(self, user_text: str, prior_turns: list[dict[str, str]] | None = None) -> str:
        last_assistant = self._last_assistant_text(prior_turns or [])
        if last_assistant:
            return (
                "Recent conversation for follow-up resolution:\n"
                f"assistant: {last_assistant}\n"
                f"user: {user_text}\n\n"
                "Choose the tool for the user's latest turn. If the latest user text declines the offered action, use none."
            )
        return user_text

    def _last_assistant_text(self, prior_turns: list[dict[str, str]]) -> str:
        for turn in reversed(prior_turns):
            if turn.get("speaker") == self.ai_name:
                return turn.get("text", "")
        return ""

    @staticmethod
    def _parse_tool_decision(raw: str) -> dict[str, object]:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if "\n" in text:
                text = text.split("\n", 1)[1]
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            return {"tool": "none", "args": {}}

        data = json.loads(text[start : end + 1])
        if not isinstance(data, dict):
            return {"tool": "none", "args": {}}
        tool = data.get("tool")
        if tool not in {
            "none",
            "date_time",
            "tavily_search",
            "weather",
            "system_control",
            "terminal",
            "local_files",
            "music",
            "image_generation",
            "gmail",
            "google_calendar",
        }:
            if tool != "unsupported":
                return {"tool": "none", "args": {}}
        args = data.get("args")
        if not isinstance(args, dict):
            args = {}
        return {
            "tool": tool,
            "args": args,
            "unsupported_reason": str(data.get("unsupported_reason") or "").strip(),
            "needs_memory": bool(data.get("needs_memory")),
            "needs_pc": bool(data.get("needs_pc")),
            "needs_skills": bool(data.get("needs_skills")),
        }

    def _read_persona(self) -> str:
        path = self.paths.root / "persona.md"
        if not path.exists():
            return "No persona file found."
        return compact_text(path.read_text(encoding="utf-8"), int(os.getenv("PERSONA_MAX_CHARS", "900")))

    def _persona(self) -> str:
        if self._persona_context is None:
            self._persona_context = self._read_persona()
        return self._persona_context

    def _planner_skills(self) -> str:
        if self._planner_skill_context is None:
            text = read_markdown_skills(self.paths.skills)
            max_chars = int(os.getenv("TOOL_PLANNER_SKILLS_MAX_CHARS", "9000"))
            self._planner_skill_context = text if len(text) <= max_chars else f"{text[: max_chars - 3]}..."
        return self._planner_skill_context


def compact_text(text: str, max_chars: int) -> str:
    lines: list[str] = []
    length = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        next_length = length + len(line) + (1 if lines else 0)
        if lines and next_length > max_chars:
            break
        lines.append(line)
        length = next_length
    return "\n".join(lines) if lines else text.strip()[:max_chars]
