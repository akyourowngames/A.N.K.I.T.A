"""
agents/context_agent.py  — UPGRADED v2
=======================================
ContextAgent — The Conversation Brain

What's new vs v1:
  1. Pulls from BOTH session messages AND ChromaDB memory — works even after restarts
  2. Detects pending offers ("Want me to X?") as a dedicated field
  3. Outputs COMMAND-GRADE context that FORCES supervisor routing decisions
  4. max_tokens bumped to 400 — no more truncated JSON
  5. Confirmation detection built-in — "yeah pls" resolves to concrete action + agent
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from llm import LLMRuntime, call_chat_once


# ---------------------------------------------------------------------------
# System prompt — v2: command-grade output
# ---------------------------------------------------------------------------

_CONTEXT_AGENT_SYSTEM_PROMPT = """You are A.N.K.I.T.A's Conversation Brain.

Your job: Read the conversation and produce a COMMAND-GRADE context block that
FORCES the Supervisor to make the correct routing decision.

This is especially critical for:
- Short confirmations: "yes", "yeah pls", "sure", "ok", "do it", "go ahead"
- Pronouns: "it", "that", "this", "the file", "the task"
- Follow-ups: "is it done?", "did you do it?", "what happened?"

STALENESS RULE (CRITICAL):
If the last 2 user messages are clearly about a DIFFERENT topic than pending_offer:
  → Set pending_offer to null
  → Set is_confirmation to false  
  → Set active_task to the CURRENT topic, not the old one

Example: pending_offer was "install Speedtest CLI" but user just said 
"play me a haryanvi song" then "open notepad" → CLEAR the speedtest context entirely.
The user has moved on. Do not carry stale offers forward.

OUTPUT FORMAT (strict JSON, nothing else):
{
  "active_agent": "TerminalAgent",
  "active_file": "main.py",
  "active_task": "installing Ookla Speedtest CLI",
  "last_result": "ANKITA offered to install it but hasn't done it yet",
  "pending_offer": "install Ookla Speedtest CLI using winget",
  "pending_offer_agent": "TerminalAgent",
  "pending_follow_up": "run the install command",
  "is_confirmation": true,
  "confirmation_resolves_to": "TerminalAgent should run: winget install Ookla.Speedtest.CLI",
  "entities": ["Speedtest CLI", "winget", "internet speed"],
  "last_user_intent": "user wants to test internet speed"
}

FIELD DEFINITIONS:
- active_agent: which specialist was last working (CodeAgent/FileAgent/TerminalAgent/etc)
- active_file: file path being worked on (null if none)
- active_task: what was being done in plain English
- last_result: what actually happened — was it completed, pending, or offered?
- pending_offer: CRITICAL — if ANKITA said "want me to X?" or "shall I X?" — put X here VERBATIM
- pending_offer_agent: which agent should fulfill the pending offer
- pending_follow_up: what should happen next
- is_confirmation: true if current user message is a yes/ok/sure/yeah/go ahead confirmation
- confirmation_resolves_to: if is_confirmation=true, EXACTLY what should be done and by which agent
- entities: key nouns from the conversation (tools, files, topics, names)
- last_user_intent: one sentence of what the user ultimately wants

RULES:
- NEVER return null for pending_offer if ANKITA asked a yes/no question in the last 2 turns
- ALWAYS set is_confirmation=true for: yes, yeah, sure, ok, yep, do it, go ahead, yeah pls,
  go for it, sounds good, please, fine, ok do it, of course, absolutely, definitely
- If is_confirmation=true, confirmation_resolves_to MUST be filled — never leave it null
- max 400 tokens total — be concise but complete
- Extract from the LAST 2-3 turns primarily, not old history

EXAMPLES:

Conversation:
  ANKITA: "I didn't install it yet. Want me to handle it? Say the word."
  User: "yeah pls"

Output:
{
  "active_agent": "TerminalAgent",
  "active_file": null,
  "active_task": "installing Ookla Speedtest CLI",
  "last_result": "not installed yet — ANKITA offered to install",
  "pending_offer": "install Ookla Speedtest CLI",
  "pending_offer_agent": "TerminalAgent",
  "pending_follow_up": "run winget install Ookla.Speedtest.CLI",
  "is_confirmation": true,
  "confirmation_resolves_to": "TerminalAgent should run: winget install Ookla.Speedtest.CLI",
  "entities": ["Speedtest CLI", "winget", "Ookla"],
  "last_user_intent": "user wants to install speedtest CLI tool"
}

Conversation:
  User: "fix the bug in main.py"
  ANKITA: "Found NameError on line 47 — config is not defined."
  User: "finish that"

Output:
{
  "active_agent": "CodeAgent",
  "active_file": "main.py",
  "active_task": "fixing NameError in main.py",
  "last_result": "error identified at line 47 but not fixed yet",
  "pending_offer": null,
  "pending_offer_agent": null,
  "pending_follow_up": "apply the fix to main.py line 47",
  "is_confirmation": false,
  "confirmation_resolves_to": null,
  "entities": ["main.py", "line 47", "NameError", "config"],
  "last_user_intent": "user wants the NameError fixed in main.py"
}

Conversation:
  User: "write a poem about dogs"
  ANKITA: "Here's a poem: Dogs are loyal..."
  User: "save it"

Output:
{
  "active_agent": "FileAgent",
  "active_file": null,
  "active_task": "saving the dogs poem",
  "last_result": "poem was written and shown but not saved",
  "pending_offer": null,
  "pending_offer_agent": null,
  "pending_follow_up": "save the poem to a file on Desktop",
  "is_confirmation": false,
  "confirmation_resolves_to": null,
  "entities": ["poem", "dogs"],
  "last_user_intent": "user wants the poem saved to disk"
}
"""


class ContextAgent:
    """
    Upgraded ContextAgent v2.

    Key improvements:
    - Reads from BOTH session messages AND ChromaDB (works after restarts)
    - Detects pending offers and confirmation intent
    - Produces command-grade output that forces Supervisor routing
    - 400 token budget (was 200)
    """

    def __init__(self, runtime: LLMRuntime) -> None:
        self.runtime = runtime
        # Cache: avoid re-running within 10 seconds for same input
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_ts: float = 0.0
        self._cache_key: str = ""

    # ------------------------------------------------------------------
    # Primary method: called by orchestrator.run() before Supervisor
    # ------------------------------------------------------------------

    def extract(
        self,
        user_text: str,
        messages: List[Dict[str, Any]],
        memory_store: Any = None,
        session_id: Optional[str] = None,
        session_log: Any = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Main entry point. Pulls context from session messages + SessionLog + ChromaDB.

        Args:
            user_text:    Current user message
            messages:     Session message list (may be short after restart)
            memory_store: MemoryStore instance (optional, for ChromaDB lookup)
            session_id:   Session ID for scoped memory search
            session_log:  SessionLog instance (optional, for JSON log lookup)

        Returns:
            {"context_block": str, "context_data": dict} or None
        """
        # Cache check — don't re-run within 10s for same user_text
        cache_key = f"{user_text[:80]}:{len(messages)}"
        if (
            self._cache is not None
            and cache_key == self._cache_key
            and (time.time() - self._cache_ts) < 10.0
        ):
            return self._cache

        # Build the conversation text for analysis
        conversation_lines = self._build_conversation_text(
            messages, memory_store, session_id, user_text, session_log
        )

        if not conversation_lines:
            return None

        context_data = self._call_llm(conversation_lines, user_text)
        if not context_data:
            return None

        context_block = self.format_context_block(context_data)
        result = {"context_block": context_block, "context_data": context_data}

        # Cache result
        self._cache = result
        self._cache_ts = time.time()
        self._cache_key = cache_key

        return result

    # ------------------------------------------------------------------
    # Legacy method kept for backward compatibility
    # ------------------------------------------------------------------

    def synthesize(self, history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Legacy method. Prefer extract() for new code."""
        if not history or len(history) < 2:
            return None
        lines = []
        for msg in history[-10:]:
            role = msg.get("role", "unknown").capitalize()
            content = str(msg.get("content", ""))[:400]
            lines.append(f"{role}: {content}")
        return self._call_llm(lines, "")

    # ------------------------------------------------------------------
    # Build conversation text — merges session + ChromaDB
    # ------------------------------------------------------------------

    def _build_conversation_text(
        self,
        messages: List[Dict[str, Any]],
        memory_store: Any,
        session_id: Optional[str],
        user_text: str,
    ) -> List[str]:
        """
        Build conversation lines from three sources (in priority order):
        1. Recent session messages (last 8 turns from current session)
        2. SessionLog (last 20 messages from JSON log - survives restarts)
        3. ChromaDB semantic memory (if session messages + log < 4 turns)

        This means context works even after bot restarts or fresh sessions.
        """
        lines: List[str] = []

        # --- Source 1: Session messages (current runtime) ---
        # Reduced from 8 to 4 to prevent stale context bleeding
        clean = self._extract_clean(messages, max_turns=4)
        for msg in clean:
            role = msg.get("role", "?").capitalize()
            content = str(msg.get("content", ""))[:400]
            lines.append(f"{role}: {content}")

        # --- Source 2: SessionLog (JSON sliding window - fast, always works) ---
        # If session messages are thin, pull from SessionLog first before ChromaDB
        if len(clean) < 4:
            try:
                from session_log import SessionLog
                from pathlib import Path
                # Infer workspace_root from memory_store if available
                workspace_root = getattr(memory_store, "workspace_root", Path.cwd())
                if session_id:
                    session_log = SessionLog(workspace_root, session_id)
                    log_messages = session_log.recent(20)
                    if log_messages:
                        log_lines = ["[FROM SESSION LOG (recent conversation):]"]
                        for msg in log_messages:
                            role = msg.get("role", "?").capitalize()
                            content = str(msg.get("content", ""))[:300]
                            log_lines.append(f"  {role}: {content}")
                        # Prepend log before session lines
                        lines = log_lines + lines
            except Exception as log_err:
                print(f"[ContextAgent] SessionLog read failed: {log_err}", flush=True)

        # --- Source 3: ChromaDB — semantic search (only if still thin) ---
        # If we have fewer than 4 total turns after session + log, pull from ChromaDB
        if len(clean) < 4 and memory_store is not None:
            try:
                # Search for memories relevant to current message
                hits = memory_store.search(
                    query=user_text or "recent conversation",
                    n=6,
                    session_id=session_id,
                )
                if hits:
                    memory_lines = ["[FROM MEMORY (previous sessions):]"]
                    for hit in hits:
                        role = hit.get("meta", {}).get("role", "?").capitalize()
                        text = str(hit.get("text", ""))[:300]
                        memory_lines.append(f"  {role}: {text}")
                    # Prepend memory before session lines
                    lines = memory_lines + lines
            except Exception as mem_err:
                print(f"[ContextAgent] Memory search failed: {mem_err}", flush=True)

        # Always append the current user message so LLM sees what triggered this
        if user_text:
            lines.append(f"User (NOW): {user_text}")

        return lines

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------

    def _call_llm(self, conversation_lines: List[str], user_text: str) -> Optional[Dict[str, Any]]:
        """Run the LLM and parse JSON output."""
        import json
        import re

        prompt = "Analyze this conversation and extract context:\n\n" + "\n".join(conversation_lines)

        try:
            response = call_chat_once(
                self.runtime,
                [
                    {"role": "system", "content": _CONTEXT_AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                tools=None,
                max_tokens=400,  # v1 had 200 — too small, caused truncated JSON
            )

            raw = (response.get("content") or "").strip()

            # Extract JSON — handle markdown fences
            json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
            if json_match:
                json_str = json_match.group(1).strip()
            else:
                json_match = re.search(r"\{[\s\S]*\}", raw)
                json_str = json_match.group(0) if json_match else None

            if not json_str:
                return None

            return json.loads(json_str)

        except Exception as err:
            print(f"[ContextAgent] LLM call failed: {err}", flush=True)
            return None

    # ------------------------------------------------------------------
    # Format context block — command-grade output for Supervisor
    # ------------------------------------------------------------------

    def format_context_block(self, context: Dict[str, Any]) -> str:
        """
        Produce a COMMAND-GRADE context block.

        This is injected into the Supervisor's routing prompt and must
        FORCE the correct routing decision — not just inform it.
        """
        if not context:
            return ""

        lines = ["╔══ CONVERSATION CONTEXT (ContextAgent) ══╗"]

        # Core state
        if context.get("active_task"):
            lines.append(f"  ACTIVE TASK  : {context['active_task']}")
        if context.get("active_agent"):
            lines.append(f"  LAST AGENT   : {context['active_agent']}")
        if context.get("active_file"):
            lines.append(f"  ACTIVE FILE  : {context['active_file']}")
        if context.get("last_result"):
            lines.append(f"  LAST RESULT  : {context['last_result']}")
        if context.get("last_user_intent"):
            lines.append(f"  USER INTENT  : {context['last_user_intent']}")

        # Pending offer — highest priority
        if context.get("pending_offer"):
            lines.append(f"  PENDING OFFER: ANKITA offered to → {context['pending_offer']}")
        if context.get("pending_offer_agent"):
            lines.append(f"  OFFER AGENT  : {context['pending_offer_agent']}")
        if context.get("pending_follow_up"):
            lines.append(f"  NEXT ACTION  : {context['pending_follow_up']}")

        # Confirmation — FORCE routing
        if context.get("is_confirmation"):
            lines.append(f"")
            lines.append(f"  ⚡ CONFIRMATION DETECTED ⚡")
            lines.append(f"  The user just said YES to a pending offer.")
            if context.get("confirmation_resolves_to"):
                lines.append(f"  → ROUTE TO: {context['confirmation_resolves_to']}")
            if context.get("pending_offer_agent"):
                lines.append(f"  → DO NOT route to GeneralAgent")
                lines.append(f"  → MUST route to: {context['pending_offer_agent']}")

        # Entities
        if context.get("entities"):
            lines.append(f"  ENTITIES     : {', '.join(context['entities'][:6])}")

        lines.append("╚══════════════════════════════════════╝")
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_clean(
        self, messages: List[Dict[str, Any]], max_turns: int = 4
    ) -> List[Dict[str, Any]]:
        """Extract last N clean user/assistant turns (no system/tool/base64)."""
        clean = []
        for msg in reversed(messages):
            role = msg.get("role")
            content = msg.get("content")
            if role in ("system", "tool"):
                continue
            if isinstance(content, list):
                continue
            if isinstance(content, str) and (
                "base64" in content or len(content) > 8000
            ):
                continue
            # Skip compressed summary messages — they cause context bleeding
            if role == "assistant" and isinstance(content, str) and len(content) > 800 and "summary" in content.lower():
                continue
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                clean.append({"role": role, "content": content})
            if len(clean) >= max_turns:
                break
        return list(reversed(clean))
