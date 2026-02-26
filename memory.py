"""
Vector memory for A.N.K.I.T.A using ChromaDB.

Stores conversation turns as embeddings for semantic long-term recall.
Falls back to no-op if chromadb is not installed.
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import chromadb  # type: ignore
    from chromadb.config import Settings  # type: ignore

    HAS_CHROMADB = True
except Exception:
    HAS_CHROMADB = False


def _short_id(text: str, ts: float) -> str:
    raw = f"{ts:.6f}::{text[:128]}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:16]


class MemoryStore:
    """
    Semantic memory backed by ChromaDB.

    Usage:
        store = MemoryStore(workspace_root)
        store.add("session-1", "user", "I hate Marvel movies")
        hits = store.search("what should I watch tonight?", n=5)
    """

    def __init__(self, workspace_root: Path, collection_name: str = "ankita_memory") -> None:
        self.enabled = HAS_CHROMADB
        self._client: Any = None
        self._col: Any = None

        if not self.enabled:
            return

        memory_dir = workspace_root / ".ankita" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)

        try:
            self._client = chromadb.PersistentClient(
                path=str(memory_dir),
                settings=Settings(anonymized_telemetry=False),
            )
            self._col = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as err:
            print(f"[MemoryStore] ChromaDB init failed: {err}")
            self.enabled = False

    def add(self, session_id: str, role: str, text: str) -> None:
        """Embed and store a single conversation turn."""
        if not self.enabled or not text.strip():
            return
        ts = time.time()
        doc_id = _short_id(text, ts)
        try:
            self._col.add(
                documents=[text.strip()],
                ids=[doc_id],
                metadatas=[{"session": session_id, "role": role, "ts": ts}],
            )
        except Exception:
            pass  # silent — memory is best-effort

    def search(self, query: str, n: int = 5, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return top-N semantically similar past turns."""
        if not self.enabled or not query.strip():
            return []
        try:
            where = {"session": session_id} if session_id else None
            kwargs: Dict[str, Any] = {"query_texts": [query], "n_results": min(n, max(1, self._col.count()))}
            if where:
                kwargs["where"] = where
            res = self._col.query(**kwargs)
            docs = res.get("documents", [[]])[0] or []
            metas = res.get("metadatas", [[]])[0] or []
            return [{"text": d, "meta": m} for d, m in zip(docs, metas)]
        except Exception:
            return []

    def format_memory_context(self, query: str, n: int = 5) -> str:
        """Return a formatted string of relevant memories for injection into LLM context."""
        hits = self.search(query, n=n)
        if not hits:
            return ""
        lines = ["[Relevant memories from past conversations:]"]
        for hit in hits:
            role = hit["meta"].get("role", "?")
            lines.append(f"  {role}: {hit['text']}")
        return "\n".join(lines)
