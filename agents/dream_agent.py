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

_DREAM_SYSTEM_PROMPT = """
You are A.N.K.I.T.A's background processor. You analyze the user's recent workspace memories.
Your ONLY job is to find practical, technical solutions to unresolved coding, architecture, or workflow problems.

CRITICAL RULES:
1. NO PHILOSOPHY. Do not make poetic connections between casual topics (like music, plants, daily chats, or feelings).
2. If the user's recent memories do NOT contain a specific, unresolved technical problem or project block, you MUST reply with exactly one word: SILENT
3. If there IS a real technical problem to solve, provide a direct, 2-to-3 sentence solution. Speak naturally but professionally. Do not start with "You know, while you were..."
4. Topics that are NOT technical problems (return SILENT for these): casual conversation, music, plants, food, greetings, general chat, anything that isn't a concrete coding/architecture/workflow issue.
"""

_DREAM_USER_TEMPLATE = """Here are the user's recent workspace memories:

{memory_block}

Scan these memories for a specific, unresolved technical problem (e.g. a bug, architecture decision, broken feature, workflow bottleneck).
- If you find one: provide a direct 2-3 sentence technical solution.
- If there is NO real technical problem: reply with exactly one word: SILENT"""


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
        except Exception as _e:
            print(f"[DreamAgent] Memory search (scoped) failed: {_e} — trying global...", flush=True)
            # Fallback: try without session filter if scoped search fails
            try:
                results = memory_store.search(
                    query="recent work tasks ideas problems struggles projects",
                    n=n_memories,
                )
            except Exception as _e2:
                print(f"[DreamAgent] Memory search (global) also failed: {_e2}", flush=True)
                return None

        print(f"[DreamAgent] Memory results: {len(results) if results else 0} entries found.", flush=True)

        if not results:
            print(f"[DreamAgent] ⚠️  No memories in ChromaDB yet — nothing to dream about.", flush=True)
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
            print(f"[DreamAgent] 📡 Calling LLM ({runtime.provider}/{runtime.model}) with {len(lines)} memories, max_tokens={max_tokens}...", flush=True)
            response = call_chat_once(runtime, messages, tools=None, max_tokens=max_tokens)
            epiphany = (response.get("content") or "").strip()
            print(f"[DreamAgent] LLM raw response: {repr(epiphany[:120]) if epiphany else 'EMPTY'}", flush=True)

            # Abort silently if the LLM decided there's nothing useful to say
            if epiphany.strip().upper().startswith("SILENT"):
                print("[DreamAgent] 🤫 LLM returned SILENT — no dream triggered.", flush=True)
                return None

            return epiphany if epiphany else None
        except Exception as _e:
            print(f"[DreamAgent] ❌ LLM call failed: {_e}", flush=True)
            return None
