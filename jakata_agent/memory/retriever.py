from __future__ import annotations

import json
from pathlib import Path

from jakata_agent.memory.embedder import SemanticEmbedder
from jakata_agent.memory.graph_store import GraphStore
from jakata_agent.memory.models import RetrievedContext
from jakata_agent.memory.store import MemoryStore


class MemoryRetriever:
    def __init__(
        self,
        store: MemoryStore,
        chat_dir: Path,
        knowledge_chunks: list[str],
        embedder: SemanticEmbedder,
        graph_store: GraphStore,
    ) -> None:
        self.store = store
        self.chat_dir = chat_dir
        self.knowledge_chunks = knowledge_chunks
        self.embedder = embedder
        self.graph_store = graph_store

    def retrieve(self, query: str, session_id: str, memory_limit: int = 5, chunk_limit: int = 3) -> RetrievedContext:
        permanent_memories = self._hybrid_memory_search(query, limit=memory_limit)
        knowledge_chunks = self._hybrid_rank_chunks(self.knowledge_chunks, query, limit=chunk_limit)
        archived_chat_chunks = self._search_chats(query, session_id, limit=chunk_limit)
        graph_results = self.graph_store.search(query, limit=chunk_limit)
        graph_chunks = [
            f"[{item['node_type']}] {item['label']}" for item in graph_results["nodes"]
        ] + [
            f"[{item['edge_type']}] {item['source_label']} -> {item['target_label']}" for item in graph_results["edges"]
        ]
        return RetrievedContext(
            permanent_memories=permanent_memories,
            knowledge_chunks=knowledge_chunks,
            archived_chat_chunks=archived_chat_chunks,
            graph_chunks=graph_chunks[:chunk_limit * 2],
        )

    def _hybrid_memory_search(self, query: str, limit: int) -> list:
        lexical = self.store.search(query, limit=max(limit * 3, 10))
        recent = self.store.recent(limit=max(limit * 3, 10))
        pool = {item.content: item for item in [*lexical, *recent]}
        ranked: list[tuple[float, object]] = []
        for item in pool.values():
            lexical_score = self._token_score(query, f"{item.kind} {item.content} {item.summary}")
            semantic_score = self._semantic_score(query, item.content)
            score = lexical_score + semantic_score * 5.0 + item.confidence
            if score > 0:
                ranked.append((score, item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in ranked[:limit]]

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

    def _hybrid_rank_chunks(self, chunks: list[str], query: str, limit: int) -> list[str]:
        if not chunks:
            return []

        ranked: list[tuple[float, str]] = []
        for chunk in chunks:
            lexical_score = self._token_score(query, chunk)
            semantic_score = self._semantic_score(query, chunk)
            score = lexical_score + semantic_score * 5.0
            if score > 0:
                ranked.append((score, chunk))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [chunk for _, chunk in ranked[:limit]]

    @staticmethod
    def _token_score(query: str, text: str) -> int:
        tokens = [token.lower() for token in query.split() if len(token) > 2]
        haystack = text.lower()
        return sum(haystack.count(token) for token in tokens)

    def _semantic_score(self, query: str, text: str) -> float:
        try:
            return self.embedder.similarity(query, text)
        except Exception:
            return 0.0
