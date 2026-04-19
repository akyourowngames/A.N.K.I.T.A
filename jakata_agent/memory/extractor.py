from __future__ import annotations

import re
from datetime import datetime

from jakata_agent.memory.models import MemoryRecord


class MemoryExtractor:
    def __init__(self) -> None:
        self._patterns: list[tuple[str, re.Pattern[str]]] = [
            ("preference", re.compile(r"\b(i (?:prefer|like|want|need) .+)", re.IGNORECASE)),
            ("identity", re.compile(r"\b(my name is .+|i am .+|i'm .+)", re.IGNORECASE)),
            ("location", re.compile(r"\b(i live in .+|i am from .+|i'm from .+)", re.IGNORECASE)),
            ("favorite", re.compile(r"\b(my favorite .+ is .+)", re.IGNORECASE)),
            ("profile", re.compile(r"\b(i am \d{1,3} years old|i'm \d{1,3} years old)", re.IGNORECASE)),
            ("project", re.compile(r"\b(we are (?:building|making) .+|i am (?:building|making) .+)", re.IGNORECASE)),
            ("instruction", re.compile(r"\b(always .+|remember .+|use .+ by default.*)", re.IGNORECASE)),
        ]

    def extract(self, user_message: str, session_id: str) -> list[MemoryRecord]:
        now = datetime.utcnow().isoformat()
        found: list[MemoryRecord] = []
        cleaned = " ".join(user_message.strip().split())
        for kind, pattern in self._patterns:
            match = pattern.search(cleaned)
            if match:
                content = match.group(1).strip().rstrip(".")
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
