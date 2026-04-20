from __future__ import annotations

import re
from datetime import datetime

from jakata_agent.memory.models import MemoryRecord


# Words that indicate the statement is directed at the agent, not about the user
_AGENT_DIRECTED = re.compile(
    r"\b(you|your|the agent|the assistant|jakata|answer|respond|handle|format|output|result)\b",
    re.IGNORECASE,
)

# Maximum length of a fact worth storing — long sentences are usually instructions, not facts
_MAX_FACT_LEN = 80

# Minimum length — single words are noise
_MIN_FACT_LEN = 5


class MemoryExtractor:
    """
    Extracts personal facts from user messages.

    Patterns are intentionally narrow:
    - Only first-person assertions about the user themselves
    - Never instructions directed at the agent
    - Never sentences that contain "you/your/answer/respond/handle"
    """

    def __init__(self) -> None:
        self._patterns: list[tuple[str, re.Pattern[str]]] = [
            # "my name is X" — identity
            ("identity",    re.compile(r"\bmy name is ([A-Za-z][A-Za-z\s]{1,30})", re.IGNORECASE)),
            # "i live in X" / "i am from X" / "i'm from X" — location
            ("location",    re.compile(r"\bi (?:live in|am from|'m from) ([A-Za-z][\w\s,]{2,40})", re.IGNORECASE)),
            # "i am X years old" — age
            ("profile",     re.compile(r"\bi(?:'m| am) (\d{1,3}) years old", re.IGNORECASE)),
            # "my favorite X is Y" — preference
            ("favorite",    re.compile(r"\bmy favorite ([\w\s]{1,20}) is ([A-Za-z][\w\s]{1,30})", re.IGNORECASE)),
            # "i prefer X" / "i like X" — short personal preference (not "i want you to...")
            ("preference",  re.compile(r"\bi (?:prefer|like) ([A-Za-z][\w\s]{1,40})", re.IGNORECASE)),
            # "i am building X" / "we are building X" — project
            ("project",     re.compile(r"\b(?:i am|i'm|we are|we're) (?:building|making|working on) ([A-Za-z][\w\s]{2,40})", re.IGNORECASE)),
        ]

    def extract(self, user_message: str, session_id: str) -> list[MemoryRecord]:
        now = datetime.utcnow().isoformat()
        found: list[MemoryRecord] = []
        cleaned = " ".join(user_message.strip().split())

        # Skip messages directed at the agent or that are instructions
        if self._is_agent_instruction(cleaned):
            return []

        for kind, pattern in self._patterns:
            match = pattern.search(cleaned)
            if not match:
                continue

            # Build the content from the full match group
            content = match.group(0).strip().rstrip(".,;")

            # Skip if too short or too long
            if not (_MIN_FACT_LEN <= len(content) <= _MAX_FACT_LEN):
                continue

            # Skip if the extracted content is itself agent-directed
            if self._is_agent_instruction(content):
                continue

            found.append(
                MemoryRecord(
                    id=None,
                    kind=kind,
                    content=content,
                    summary=content[:160],
                    tags=[kind],
                    confidence=0.75,
                    source_session=session_id,
                    created_at=now,
                    updated_at=now,
                    last_used_at=now,
                )
            )

        return found

    @staticmethod
    def _is_agent_instruction(text: str) -> bool:
        """Return True if this text looks like an instruction TO the agent, not a fact ABOUT the user."""
        lowered = text.lower().strip()

        # Contains agent-directed words
        if _AGENT_DIRECTED.search(text):
            return True

        # Imperative patterns — "do not", "always", "never", "make sure", "answer", "tell me"
        imperative = re.compile(
            r"^(do not|don't|always|never|make sure|please|answer|tell me|show me|give me|help me|use|remember|keep|stop|start)",
            re.IGNORECASE,
        )
        if imperative.match(lowered):
            return True

        return False