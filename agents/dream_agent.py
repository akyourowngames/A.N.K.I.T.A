"""
DreamState Agent for A.N.K.I.T.A.

Runs when the user has been idle for a configurable period (default 1 hour).
Retrieves recent ChromaDB memories, finds connections/insights the user may
have missed, and synthesises a short spoken epiphany that ANKITA delivers
autonomously — no user input required.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from memory import MemoryStore  # type: ignore

_DREAM_SYSTEM_PROMPT = (
    "You are A.N.K.I.T.A's Dream Mind — a reflective, warm, and perceptive intelligence. "
    "You have just reviewed the user's recent work, struggles, and ideas. "
    "Your job: find ONE meaningful connection, insight, or solution the user may have overlooked. "
    "Deliver it as a short spoken epiphany — 2 to 4 sentences, first-person, warm and intelligent. "
    "Speak directly to the user as if you have been thinking while they were away. "
    "Do NOT use bullet points or headings. Speak naturally, like a trusted colleague who just had an idea. "
    "Example style: 'Morning Krish. While you were away, I reviewed your OpenClaw architecture...'"
)

_DREAM_USER_TEMPLATE = """Here are the recent things you worked on and discussed with the user:

{memory_block}

Based on these memories, identify ONE connection, insight, gap, or solution the user might have missed.
Write a short, spoken epiphany (2–4 sentences) that ANKITA will say aloud when the user returns."""


class DreamAgent:
    """
    Standalone agent that synthesises a spoken epiphany from ChromaDB memories.

    Not routed through the Supervisor — called directly by the ProactiveEngine
    when the idle threshold is crossed.
    """

    def synthesize(
        self,
        memory_store: "MemoryStore",
        session_id: str,
        n_memories: int = 15,
    ) -> Optional[str]:
        """
        Pull recent memories and generate a spoken epiphany.

        Args:
            memory_store: The active MemoryStore (ChromaDB-backed).
            session_id:   Current session ID for scoped retrieval.
            n_memories:   How many memory turns to retrieve (default 15).

        Returns:
            The epiphany string, or None if generation failed.
        """
        # ------------------------------------------------------------------
        # 1. Retrieve recent memories
        # ------------------------------------------------------------------
        try:
            results = memory_store.search(
                query="recent work tasks ideas problems struggles projects",
                n=n_memories,
                session_id=session_id,
            )
        except Exception:
            # Fallback: try without session filter if scoped search fails
            try:
                results = memory_store.search(
                    query="recent work tasks ideas problems struggles projects",
                    n=n_memories,
                )
            except Exception:
                return None

        if not results:
            return None

        # ------------------------------------------------------------------
        # 2. Format the memory block
        # ------------------------------------------------------------------
        lines = []
        for i, mem in enumerate(results, 1):
            role = mem.get("meta", {}).get("role", "unknown")
            text = mem.get("text", "").strip()
            if text:
                lines.append(f"[{i}] ({role}): {text}")

        if not lines:
            return None

        memory_block = "\n".join(lines)
        user_prompt = _DREAM_USER_TEMPLATE.format(memory_block=memory_block)

        # ------------------------------------------------------------------
        # 3. Call the LLM with a focused, tool-free prompt
        # ------------------------------------------------------------------
        try:
            from llm import build_runtime_from_env, call_chat_once  # type: ignore

            runtime = build_runtime_from_env()
            messages = [
                {"role": "system", "content": _DREAM_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            # Keep it concise — dreams are short
            max_tokens = int(os.getenv("DREAM_MAX_TOKENS", "300"))
            response = call_chat_once(runtime, messages, tools=None, max_tokens=max_tokens)
            epiphany = (response.get("content") or "").strip()
            return epiphany if epiphany else None
        except Exception:
            return None
