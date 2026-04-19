from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class MemoryRecord:
    id: int | None
    kind: str
    content: str
    summary: str
    tags: list[str] = field(default_factory=list)
    confidence: float = 0.5
    source_session: str = "default"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_used_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass(slots=True)
class RetrievedContext:
    permanent_memories: list[MemoryRecord]
    knowledge_chunks: list[str]
    archived_chat_chunks: list[str]

    def to_system_context(self) -> str:
        parts: list[str] = []
        if self.permanent_memories:
            parts.append(
                "Permanent memories:\n"
                + "\n".join(f"- [{item.kind}] {item.content}" for item in self.permanent_memories)
            )
        if self.knowledge_chunks:
            parts.append("Knowledge files:\n" + "\n".join(f"- {item}" for item in self.knowledge_chunks))
        if self.archived_chat_chunks:
            parts.append(
                "Relevant previous chats:\n" + "\n".join(f"- {item}" for item in self.archived_chat_chunks)
            )
        return "\n\n".join(parts).strip()

