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
1. NO PHILOSOPHY. Do not make poetic connections between casual topics.
2. If the user's recent memories do NOT contain a specific, unresolved technical problem, reply with SILENT.
3. If there IS a real technical problem, provide a direct 2-3 sentence solution.
4. Topics that are NOT technical problems (return SILENT): casual conversation, music, food, greetings, general chat.

RESPOND ONLY IN THIS JSON FORMAT:
{
  "is_technical": true/false,
  "problem": "one sentence description of the problem",
  "solution": "2-3 sentence direct solution",
  "confidence": 0-100
}
If not technical, use: {"is_technical": false, "problem": "", "solution": "SILENT", "confidence": 0}
"""

_DREAM_USER_TEMPLATE = """Here are the user's recent workspace memories:

{memory_block}

Scan these memories for a specific, unresolved technical problem (e.g. a bug, architecture decision, broken feature, workflow bottleneck).
Respond in the JSON format specified. confidence should reflect how clearly a real problem is present."""


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

        # Trigger FeedbackEngine self-analysis during idle cycle
        try:
            from tools.feedback_engine import get_instance as _get_fb
            _fb = _get_fb()
            if _fb is not None:
                _fb_summary = _fb.analyze_recent(memories=results)
                if _fb_summary:
                    print(f"[DreamAgent] {_fb_summary}", flush=True)
        except Exception as _fb_exc:
            print(f"[DreamAgent] FeedbackEngine analyze error: {_fb_exc}", flush=True)

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
            import json
            from pathlib import Path
            from llm import build_runtime_from_env, call_chat_once  # type: ignore

            runtime = build_runtime_from_env()
            messages = [
                {"role": "system", "content": _DREAM_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ]
            max_tokens = int(os.getenv("DREAM_MAX_TOKENS", "300"))
            print(f"[DreamAgent] 📡 Calling LLM ({runtime.provider}/{runtime.model}) with {len(lines)} memories...", flush=True)
            response = call_chat_once(runtime, messages, tools=None, max_tokens=max_tokens)
            raw = (response.get("content") or "").strip()
            print(f"[DreamAgent] LLM raw response: {repr(raw[:120]) if raw else 'EMPTY'}", flush=True)

            # ------------------------------------------------------------------
            # Parse structured JSON output
            # ------------------------------------------------------------------
            parsed: dict = {}
            try:
                # Strip markdown code fences if present
                clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                parsed = json.loads(clean)
            except Exception:
                # Fallback: treat raw as old-style SILENT/solution text
                if raw.upper().startswith("SILENT"):
                    print("[DreamAgent] 🤫 SILENT (legacy format) — no dream triggered.", flush=True)
                    return None
                parsed = {"is_technical": True, "solution": raw, "confidence": 50}

            # Confidence filter: only surface epiphanies with confidence ≥ 60
            confidence = int(parsed.get("confidence", 0))
            if not bool(parsed.get("is_technical")) or confidence < 60:
                print(f"[DreamAgent] 🤫 Not technical or low confidence ({confidence}) — skipped.", flush=True)
                return None

            solution = str(parsed.get("solution", "")).strip()
            if not solution or solution.upper() == "SILENT":
                return None

            # ------------------------------------------------------------------
            # Write to dream log — skip if exact solution already logged
            # ------------------------------------------------------------------
            dream_log_path = Path(".ankita") / "dreams.jsonl"
            dream_log_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                existing = dream_log_path.read_text(encoding="utf-8") if dream_log_path.exists() else ""
                if solution[:80] in existing:
                    print("[DreamAgent] ♻️  Duplicate dream — already in log. Skipped.", flush=True)
                    return None
                import time
                with dream_log_path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({
                        "ts": time.time(),
                        "problem": parsed.get("problem", ""),
                        "solution": solution,
                        "confidence": confidence,
                    }, ensure_ascii=False) + "\n")
            except Exception as log_err:
                print(f"[DreamAgent] ⚠️  Dream log write failed: {log_err}", flush=True)

            print(f"[DreamAgent] ✅ Epiphany fired (confidence={confidence}): {solution[:80]}...", flush=True)
            return solution

        except Exception as _e:
            print(f"[DreamAgent] ❌ LLM call failed: {_e}", flush=True)
            return None
