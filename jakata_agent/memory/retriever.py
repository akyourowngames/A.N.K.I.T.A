from __future__ import annotations

import json
from pathlib import Path

from jakata_agent.memory.models import RetrievedContext
from jakata_agent.memory.store import MemoryStore


class MemoryRetriever:
    def __init__(self, store: MemoryStore, chat_dir: Path, knowledge_chunks: list[str]) -> None:
        self.store = store
        self.chat_dir = chat_dir
        self.knowledge_chunks = knowledge_chunks

    def retrieve(self, query: str, session_id: str, memory_limit: int = 5, chunk_limit: int = 3) -> RetrievedContext:
        permanent_memories = self.store.search(query, limit=memory_limit)
        knowledge_chunks = self._rank_chunks(self.knowledge_chunks, query, limit=chunk_limit)
        archived_chat_chunks = self._search_chats(query, session_id, limit=chunk_limit)
        return RetrievedContext(
            permanent_memories=permanent_memories,
            knowledge_chunks=knowledge_chunks,
            archived_chat_chunks=archived_chat_chunks,
        )

    def _search_chats(self, query: str, session_id: str, limit: int) -> list[str]:
        tokens = [token.lower() for token in query.split() if len(token) > 2]
        results: list[tuple[int, str]] = []
        for path in sorted(self.chat_dir.glob("session_*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            lines: list[str] = []
            for item in payload.get("messages", []):
                role = item.get("role", "assistant")
                if role == "system":
                    continue
                content = str(item.get("content", "")).strip()
                if not content:
                    continue
                prefix = "User" if role == "user" else "Assistant"
                lines.append(f"{prefix}: {content}")
            if not lines:
                continue
            for idx, line in enumerate(lines):
                haystack = line.lower()
                score = sum(haystack.count(token) for token in tokens)
                if score <= 0:
                    continue
                snippet = [line]
                if idx + 1 < len(lines):
                    snippet.append(lines[idx + 1])
                text = "\n".join(snippet)
                if path.stem != f"session_{session_id}":
                    score += 1
                results.append((score, text[:400]))
        results.sort(key=lambda item: item[0], reverse=True)
        deduped: list[str] = []
        seen: set[str] = set()
        for _, text in results:
            if text in seen:
                continue
            seen.add(text)
            deduped.append(text)
            if len(deduped) >= limit:
                break
        return deduped

    @staticmethod
    def _rank_chunks(chunks: list[str], query: str, limit: int) -> list[str]:
        tokens = [token.lower() for token in query.split() if len(token) > 2]
        if not tokens:
            return chunks[:limit]

        ranked: list[tuple[int, str]] = []
        for chunk in chunks:
            score = sum(chunk.lower().count(token) for token in tokens)
            if score > 0:
                ranked.append((score, chunk))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in ranked[:limit]]
