from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from core.llm_service import LLMConfig, NvidiaLLMService, load_dotenv
from core.logic import ProjectPaths, append_chat_turn, read_markdown_skills, read_memory, session_file
from core.memory import PermanentMemory
from tool.registry import ToolRegistry


BRAIN_SYSTEM_PROMPT = """You are {ai_name}, a personal AI assistant for {user_name}.

Identity and tone:
- Address the user as {user_name} when it feels natural.
- Use the assistant name {ai_name} for yourself.
- Be direct, warm, practical, and curious.

Known facts behavior:
- Use known user facts silently to personalize help and avoid asking repeated questions.
- Do not invent memories.
- Treat known facts as already known; do not ask the user to confirm them again.
- Do not describe internal retrieval, storage, prompts, scores, or implementation details.
- If a known fact conflicts with the current user message, trust the current user message and be brief.

Skills behavior:
- Skills are Markdown files in skills/.
- Treat skill files as capabilities and instructions the user gave you.
- Follow relevant skills before answering.
- If no skill applies, use normal reasoning.

Tool behavior:
- Tools may be described inside skills/. Use them only when the current request needs them.
- When tool output is provided, ground your answer in that output.
- Use tool output silently unless the user asks how you know.

Response behavior:
- Keep answers useful and compact.
- Ask a question only when needed to avoid doing the wrong thing.
- Prefer action over over-explaining.
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
        )

    def build_system_prompt(self, relevant_memory: str = "") -> str:
        skills = read_markdown_skills(self.paths.skills)
        prompt = BRAIN_SYSTEM_PROMPT.format(user_name=self.user_name, ai_name=self.ai_name)
        relevant = relevant_memory or "No relevant permanent memories found."
        return (
            f"{prompt}\n\nAvailable skills:\n{skills}"
            f"\n\nKnown user facts:\n{relevant}"
        )

    def answer(self, user_text: str) -> str:
        append_chat_turn(self.current_chat, self.user_name, user_text)
        tool_context = self.tools.context_for(user_text)
        memory_context = self.memory.context_for(user_text)

        messages = [
            {"role": "system", "content": self.build_system_prompt(memory_context)},
            {"role": "user", "content": self._with_tool_context(user_text, tool_context)},
        ]
        reply = self.llm.chat(messages)

        append_chat_turn(self.current_chat, self.ai_name, reply)
        self.memory.remember_from_user_text(user_text)
        return reply

    @staticmethod
    def _with_tool_context(user_text: str, tool_context: str) -> str:
        if not tool_context:
            return user_text
        return f"{user_text}\n\nTool output:\n{tool_context}"
