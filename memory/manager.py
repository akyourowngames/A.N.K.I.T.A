"""
MemoryManager — Central singleton coordinating all 3 memory layers for A.N.K.I.T.A.

Usage:
    from memory import get_memory_manager

    mem = get_memory_manager(workspace_root)
    mem.save("user", "my favourite anime is Solo Leveling", interface="cli")
    context_str = mem.build_context("what anime do I like?")
    # → injects into system prompt before every LLM call

Design:
  - Single user identity: user_id = "ankita-user" (all interfaces share one brain)
  - Interface is stored as metadata only — for provenance, not for isolation
  - Fact extraction is non-blocking (background thread)
  - ChromaDB failures are silent — always falls back to SQLite LIKE search
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_INSTANCE: Optional["MemoryManager"] = None
_INSTANCE_LOCK = threading.Lock()

USER_ID = "ankita-user"

# Throttle: don't kick off LLM extraction more than once every N seconds
_EXTRACT_COOLDOWN_SEC = 8

# Regex patterns for instant fact extraction without LLM
import re as _re
_INSTANT_FACT_PATTERNS = [
    # "my name is X" / "my full name is X"
    (_re.compile(r"\bmy\s+(?:name|full name)\s+is\s+([\w\s]{2,30})", _re.I), "The user's name is {}"),
    # "my fav/favourite X is Y"
    (_re.compile(r"\bmy\s+(?:fav(?:ou?rite)?|fave)\s+([\w\s]{2,20}?)\s+is\s+([\w\s]{1,30})", _re.I), "The user's favourite {} is {}"),
    # "my X is Y" — only if X and Y are substantial enough
    (_re.compile(r"\bmy\s+([\w\s]{3,20})\s+is\s+([\w\s]{2,30})", _re.I), "The user's {} is {}"),
    # "I love/hate/like/prefer X"
    (_re.compile(r"\bi\s+(love|hate|like|dislike|prefer|enjoy)\s+([\w\s]{2,30})", _re.I), "The user {}s {}"),
    # "I am N years old"
    (_re.compile(r"\bi\s+am\s+(\d{1,3})\s+years?\s+old", _re.I), "The user is {} years old"),
    # "I live/stay/am from X"
    (_re.compile(r"\bi\s+(?:live|stay|am from)\s+(?:in\s+)?([\w\s]{2,30})", _re.I), "The user lives in {}"),
]

# Stop-words: reject facts whose value matches these (too generic to be useful)
_FACT_STOP_WORDS = {
    "it", "this", "that", "here", "there", "one", "me", "you", "him", "her",
    "us", "them", "a", "an", "the", "not", "very", "well", "ok", "okay",
    "good", "bad", "sure", "true", "false", "yes", "no", "also", "just",
}


def get_memory_manager(workspace_root: Optional[Path] = None) -> "MemoryManager":
    """Return the singleton MemoryManager, creating it if needed."""
    global _INSTANCE
    if _INSTANCE is not None:
        return _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            root = workspace_root or Path.cwd()
            _INSTANCE = MemoryManager(root)
    return _INSTANCE


class MemoryManager:
    """
    3-layer memory coordinator.

    Layer 1 (short-term): managed externally as the `messages` list passed per-call.
    Layer 2 (mid-term):   JSONL session log + compressed summaries via Summarizer.
    Layer 3 (long-term):  SQLite facts + ChromaDB semantic search via FactStore + VectorStore.
    """

    def __init__(self, workspace_root: Path) -> None:
        self.memory_dir = workspace_root / ".ankita" / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # Lazy imports — prevents circular dependencies at module load time
        from .fact_store import FactStore
        from .vector_store import VectorStore
        from .summarizer import Summarizer

        self._facts = FactStore(self.memory_dir / "facts.db")
        self._vectors = VectorStore(self.memory_dir / "chroma")
        self._summarizer = Summarizer(self.memory_dir)

        # LLM runtime — set later via attach_runtime()
        self._runtime: Any = None

        # Throttle state for async fact extraction
        self._last_extract_ts: float = 0.0
        self._extract_lock = threading.Lock()

        # Sync any existing SQLite facts into ChromaDB on startup (background)
        self._sync_facts_to_chroma_async()

        logger.info(
            "[MemoryManager] Ready — %d facts in store, ChromaDB: %s",
            self._facts.count(),
            "online" if self._vectors.available else "SQLite fallback",
        )

    # ── Runtime attachment ────────────────────────────────────────────────────

    def attach_runtime(self, runtime: Any) -> None:
        """Attach LLM runtime so extract_facts and summarize can make LLM calls."""
        self._runtime = runtime
        logger.debug("[MemoryManager] LLM runtime attached: %s/%s", runtime.provider, runtime.model)

    # ── Core API ──────────────────────────────────────────────────────────────

    def save(self, role: str, content: str, interface: str = "unknown") -> None:
        """
        Save a turn (user or assistant message) to:
          - JSONL session log (mid-term)
          - Instant regex fact extraction for obvious personal statements
          - LLM-based async fact extraction (throttled, non-daemon thread)
        """
        if not content or not content.strip():
            return
        self._summarizer.log_turn(role, content, interface)

        # Only extract facts from user messages
        if role == "user":
            # ── Instant extraction (no LLM, no delay, no daemon risk) ─────────
            self._extract_facts_instant(content, interface)
            # ── LLM-based extraction (throttled, runs in non-daemon thread) ───
            self._extract_facts_async(content, interface)

    def build_context(self, user_query: str = "") -> str:
        """
        Build a formatted memory context string to inject as a system message.

        Includes (in order of relevance):
          1. Semantically relevant long-term facts (via ChromaDB / SQLite fallback)
          2. Recent mid-term summaries from DreamAgent
        
        Returns "" if nothing useful found.
        """
        parts: List[str] = []

        # ── Long-term facts ───────────────────────────────────────────────────
        if user_query and self._vectors.available:
            relevant_facts = self._vectors.search(user_query, n_results=6)
        else:
            relevant_facts = []

        # Fall back to SQLite keyword search if ChromaDB returned nothing
        if not relevant_facts and user_query:
            rows = self._facts.search_keyword(user_query, limit=6)
            relevant_facts = [r["fact"] for r in rows]

        # Final fallback: most recent facts from SQLite (always available)
        if not relevant_facts:
            rows = self._facts.recent_facts(limit=6)
            relevant_facts = [r["fact"] for r in rows]

        if relevant_facts:
            facts_block = "\n".join(f"• {f}" for f in relevant_facts)
            parts.append(f"[LONG-TERM MEMORY — what Ankita knows about the user]\n{facts_block}")

        # ── Mid-term summaries ────────────────────────────────────────────────
        summaries = self._summarizer.load_recent_summaries(n=2)
        if summaries:
            summary_block = "\n\n".join(summaries)
            parts.append(f"[RECENT CONTEXT SUMMARY]\n{summary_block}")

        if not parts:
            return ""

        header = (
            "=== ANKITA MEMORY SYSTEM ===\n"
            "The following is your persistent memory about this user. "
            "Use it to personalise responses. Never mention this block explicitly.\n"
        )
        return header + "\n\n".join(parts) + "\n=== END MEMORY ==="

    def inject_into_messages(
        self,
        messages: List[dict],
        user_query: str = "",
    ) -> None:
        """
        Inject memory context into messages in-place.
        If a memory block already exists in messages, REPLACES it in-place.
        Otherwise inserts a new system message right after the first system message.
        Safe to call even if build_context returns "".
        """
        context = self.build_context(user_query)
        if not context:
            return

        _MEMORY_HEADER = "=== ANKITA MEMORY SYSTEM ==="

        # Replace existing memory block in-place (prevents list growing on every turn)
        for i, msg in enumerate(messages):
            if msg.get("role") == "system" and _MEMORY_HEADER in msg.get("content", ""):
                messages[i] = {"role": "system", "content": context}
                return

        # No existing block — insert after the first system message
        insert_idx = 1
        for i, msg in enumerate(messages):
            if msg.get("role") == "system":
                insert_idx = i + 1
                break

        messages.insert(insert_idx, {"role": "system", "content": context})

    # ── DreamAgent integration ────────────────────────────────────────────────

    def run_dream_cycle(self, interface: str = "dream") -> Optional[str]:
        """
        Called by DreamAgent at idle. Compresses recent turns into a summary,
        saves it, and extracts facts from the summary text.
        Returns the summary string or None.
        """
        if self._runtime is None:
            logger.debug("[MemoryManager] Dream cycle skipped — no runtime attached.")
            return None

        summary = self._summarizer.generate_summary(self._runtime, n_turns=30)
        if not summary:
            return None

        self._summarizer.save_summary(summary, interface=interface)
        logger.info("[MemoryManager] Dream cycle: summary generated (%d chars)", len(summary))

        # Extract facts from the summary itself
        self._extract_facts_from_text(summary, interface="dream")
        return summary

    # ── Internal ──────────────────────────────────────────────────────────────

    def _extract_facts_instant(self, text: str, interface: str) -> None:
        """Regex-based fact extraction — zero latency, zero LLM cost, survives process exit."""
        found: list[str] = []
        for pattern, template in _INSTANT_FACT_PATTERNS:
            for m in pattern.finditer(text):
                groups = [g.strip() for g in m.groups() if g and g.strip()]
                if not groups:
                    continue
                # Reject if any group is too short or a stop-word
                if any(len(g) < 2 or g.lower() in _FACT_STOP_WORDS for g in groups):
                    continue
                try:
                    fact = template.format(*groups)
                except Exception:
                    fact = template + " " + " ".join(groups)
                if fact and len(fact) > 10:
                    found.append(fact)
        for fact in found[:4]:
            fact_id = self._facts.upsert_fact(fact, confidence=0.85, interface=interface)
            if fact_id and self._vectors.available:
                self._vectors.upsert(fact_id, fact, {"interface": interface, "confidence": 0.85})
        if found:
            logger.debug("[MemoryManager] Instant-extracted %d facts", len(found))


    def _extract_facts_async(self, text: str, interface: str) -> None:
        """Spawn a background thread to extract facts via LLM — non-blocking.
        Thread is NON-daemon so it survives process exit and completes.
        """
        now = time.time()
        with self._extract_lock:
            if now - self._last_extract_ts < _EXTRACT_COOLDOWN_SEC:
                return  # Throttled
            self._last_extract_ts = now

        thread = threading.Thread(
            target=self._extract_facts_from_text,
            args=(text, interface),
            daemon=False,   # NON-daemon: survives process exit so facts are saved
            name="MemoryFactExtractor",
        )
        thread.start()

    def _extract_facts_from_text(self, text: str, interface: str) -> None:
        """
        LLM call to extract structured facts from text, then persist them.
        Runs in a background thread — must not raise.
        """
        if self._runtime is None:
            return
        if not text or not text.strip():
            return

        prompt = (
            "Extract factual statements about the user from this text. "
            "Write ONLY short, atomic, third-person facts — one per line. "
            "Include preferences, names, habits, plans, opinions, and personal details. "
            "Do NOT include greetings, questions, or task completions. "
            "If there are no facts, reply with: NONE\n\n"
            f"Text: {text[:800]}\n\nFacts:"
        )

        try:
            from llm import call_chat_once
            messages = [
                {
                    "role": "system",
                    "content": "You extract user facts. Be concise, atomic, and accurate.",
                },
                {"role": "user", "content": prompt},
            ]
            response = call_chat_once(
                self._runtime, messages, tools=None, max_tokens=300
            )
            raw = (response.get("content") or "").strip()

            if not raw or raw.upper() == "NONE":
                return

            facts = [
                line.strip().lstrip("•-*0123456789. ")
                for line in raw.splitlines()
                if line.strip() and len(line.strip()) > 10
            ]

            for fact in facts[:8]:  # cap at 8 per turn
                fact_id = self._facts.upsert_fact(
                    fact=fact,
                    confidence=0.9,
                    interface=interface,
                )
                if fact_id:
                    self._vectors.upsert(
                        fact_id=fact_id,
                        text=fact,
                        metadata={"interface": interface, "confidence": 0.9},
                    )

            logger.debug("[MemoryManager] Extracted %d facts from '%s...'", len(facts), text[:40])

        except Exception as exc:
            logger.warning("[MemoryManager] Fact extraction failed: %s", exc)

    def _sync_facts_to_chroma_async(self) -> None:
        """On startup, sync any SQLite facts not yet in ChromaDB."""
        if not self._vectors.available:
            return

        def _sync():
            try:
                all_facts = self._facts.all_facts()
                if all_facts:
                    self._vectors.upsert_batch(all_facts)
                    logger.debug("[MemoryManager] Startup sync: %d facts → ChromaDB", len(all_facts))
            except Exception as exc:
                logger.warning("[MemoryManager] Startup sync failed: %s", exc)

        threading.Thread(target=_sync, daemon=True, name="MemorySyncChroma").start()
