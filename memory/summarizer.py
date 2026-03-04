"""
Summarizer — JSONL session logger + DreamAgent compression for A.N.K.I.T.A.

Responsibilities:
  1. Append every turn (user + assistant) to a daily JSONL file
  2. generate_summary(): compress recent N turns into a human-readable paragraph via LLM
  3. save_summary(): persist that paragraph to summaries.jsonl
  4. load_recent_summary(): return the latest summary for context injection
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class Summarizer:
    """
    JSONL session logger with LLM-powered compression.

    File layout (inside memory_dir):
      sessions/YYYY-MM-DD.jsonl   — daily turn log (all interfaces)
      summaries.jsonl             — compressed summaries (newest last)
    """

    def __init__(self, memory_dir: Path) -> None:
        self.sessions_dir = memory_dir / "sessions"
        self.summaries_path = memory_dir / "summaries.jsonl"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    # ── Session log ───────────────────────────────────────────────────────────

    def _today_path(self) -> Path:
        return self.sessions_dir / f"{datetime.now().strftime('%Y-%m-%d')}.jsonl"

    def log_turn(self, role: str, content: str, interface: str = "unknown") -> None:
        """Append a single turn to today's JSONL session log."""
        if not content or not content.strip():
            return
        entry = {
            "ts": time.time(),
            "role": role,
            "content": content.strip(),
            "interface": interface,
        }
        try:
            with open(self._today_path(), "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("[Summarizer] Failed to log turn: %s", exc)

    def load_recent_turns(self, n: int = 30) -> List[Dict[str, Any]]:
        """Load the last N turns across the most recent session files (no duplicates)."""
        turns: List[Dict] = []
        # Read files newest-first, stop as soon as we have enough
        for path in sorted(self.sessions_dir.glob("*.jsonl"), reverse=True):
            if len(turns) >= n:
                break
            try:
                lines = path.read_text(encoding="utf-8").strip().splitlines()
                for line in reversed(lines):
                    try:
                        turns.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                    if len(turns) >= n:
                        break
            except Exception:
                continue
        # Return in chronological order
        return list(reversed(turns[:n]))

    # ── Summarization ─────────────────────────────────────────────────────────

    def generate_summary(
        self,
        llm_runtime: Any,
        n_turns: int = 30,
    ) -> Optional[str]:
        """
        Build a compressed paragraph summary of the last N turns.
        Returns None if not enough content or LLM fails.
        """
        turns = self.load_recent_turns(n_turns)
        if len(turns) < 4:
            return None  # Not enough to summarize

        # Format turns for the LLM
        lines = []
        for t in turns:
            prefix = "User" if t["role"] == "user" else "Ankita"
            lines.append(f"{prefix}: {t['content'][:400]}")
        conversation_text = "\n".join(lines)

        prompt = (
            "You are a memory compression assistant. Read the following conversation and "
            "write a concise factual summary (3-6 sentences) capturing:\n"
            "- Key facts stated by the user (preferences, names, decisions, plans)\n"
            "- Important tasks completed or discussed\n"
            "- Any user context that Ankita should remember long-term\n\n"
            "Do NOT include greetings or filler. Only extract meaningful, lasting facts.\n\n"
            f"Conversation:\n{conversation_text}\n\n"
            "Summary:"
        )

        try:
            from llm import call_chat_once
            messages = [
                {"role": "system", "content": "You are a precise memory compression assistant."},
                {"role": "user", "content": prompt},
            ]
            response = call_chat_once(llm_runtime, messages, tools=None, max_tokens=400)
            summary = (response.get("content") or "").strip()
            return summary if summary else None
        except Exception as exc:
            logger.warning("[Summarizer] LLM summary generation failed: %s", exc)
            return None

    def save_summary(self, summary: str, interface: str = "dream") -> None:
        """Persist a compressed summary to summaries.jsonl."""
        if not summary:
            return
        entry = {
            "ts": time.time(),
            "summary": summary.strip(),
            "interface": interface,
            "date": datetime.now().strftime("%Y-%m-%d"),
        }
        try:
            with open(self.summaries_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.warning("[Summarizer] Failed to save summary: %s", exc)

    def load_recent_summaries(self, n: int = 3) -> List[str]:
        """Return the last N summaries. Auto-prunes file to 100 entries max."""
        if not self.summaries_path.exists():
            return []
        try:
            lines = self.summaries_path.read_text(encoding="utf-8").strip().splitlines()
            # Prune to latest 100 to prevent unbounded growth
            if len(lines) > 100:
                keep = lines[-100:]
                try:
                    self.summaries_path.write_text("\n".join(keep) + "\n", encoding="utf-8")
                    lines = keep
                except Exception:
                    pass
            summaries = []
            for line in reversed(lines):
                try:
                    entry = json.loads(line)
                    text = entry.get("summary", "").strip()
                    if text:
                        summaries.append(text)
                except json.JSONDecodeError:
                    continue
                if len(summaries) >= n:
                    break
            return list(reversed(summaries))
        except Exception as exc:
            logger.warning("[Summarizer] Failed to load summaries: %s", exc)
            return []
