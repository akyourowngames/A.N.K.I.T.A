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
            print(f"[MemoryStore] ⚠️  ChromaDB not installed — memory disabled.", flush=True)
            return

        memory_dir = workspace_root / ".ankita" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        print(f"[MemoryStore] Initializing ChromaDB at {memory_dir}", flush=True)

        try:
            self._client = chromadb.PersistentClient(
                path=str(memory_dir),
                settings=Settings(anonymized_telemetry=False),
            )
            self._col = self._client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            print(f"[MemoryStore] ✅ ChromaDB ready. Collection '{collection_name}' has {self._col.count()} entries.", flush=True)
        except Exception as err:
            print(f"[MemoryStore] ❌ ChromaDB init failed: {err}", flush=True)
            self.enabled = False

    # TTL: memories older than this many days are excluded from search results
    _TTL_DAYS: int = int(os.getenv("MEMORY_TTL_DAYS", "90"))

    def add(self, session_id: str, role: str, text: str) -> None:
        """Embed and store a single conversation turn.

        Upgrades:
        - Semantic deduplication: if a very similar entry exists (distance < 0.05
          in cosine space), skip storing to avoid noisy duplicates.
        - Entity tagging: auto-extract tool names, file paths, error types as metadata.
        """
        if not self.enabled:
            return
        if not text.strip():
            return
        ts = time.time()

        # Deduplication: check if near-identical memory already exists
        try:
            count = self._col.count()
            if count > 0:
                res = self._col.query(query_texts=[text.strip()], n_results=1)
                distances = res.get("distances", [[]])[0]
                if distances and float(distances[0]) < 0.05:
                    # Too similar — skip
                    return
        except Exception as _dedup_err:
            print(f"[MemoryStore] ⚠️  Dedup check failed (proceeding to store): {_dedup_err}", flush=True)

        # Entity tagging: extract meaningful metadata labels
        import re as _re
        tags: List[str] = []
        if _re.search(r'\bError\b|\bTraceback\b|\bException\b', text):
            tags.append("error")
        if _re.search(r'[A-Za-z]:\\|/home/|\.py\b|\.js\b|\.ts\b', text):
            tags.append("file_path")
        if _re.search(r'\btool\b|\brun_command\b|\bwrite_file\b|\blaunch_app\b', text, _re.IGNORECASE):
            tags.append("tool_call")

        doc_id = _short_id(text, ts)
        try:
            self._col.add(
                documents=[text.strip()],
                ids=[doc_id],
                metadatas=[{
                    "session": session_id,
                    "role": role,
                    "ts": ts,
                    "tags": ",".join(tags),
                }],
            )
        except Exception as _e:
            print(f"[MemoryStore] ❌ add() failed: {_e}", flush=True)

    def search(self, query: str, n: int = 5, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return top-N semantically similar past turns.

        Upgrades:
        - TTL filtering: entries older than MEMORY_TTL_DAYS are excluded.
        - Temporal decay: recent memories get a score boost in ranking.
        """
        if not self.enabled or not query.strip():
            return []
        try:
            where = {"session": session_id} if session_id else None
            # Fetch more than requested to allow TTL filtering + re-ranking
            fetch_n = min(n * 3, max(1, self._col.count()))
            kwargs: Dict[str, Any] = {"query_texts": [query], "n_results": fetch_n}
            if where:
                kwargs["where"] = where
            res = self._col.query(**kwargs)
            docs = res.get("documents", [[]])[0] or []
            metas = res.get("metadatas", [[]])[0] or []
            distances = res.get("distances", [[]])[0] or []

            now = time.time()
            ttl_cutoff = now - (self._TTL_DAYS * 86400)
            results = []
            for doc, meta, dist in zip(docs, metas, distances):
                ts_val = float(meta.get("ts", 0))
                # TTL filter: skip entries OLDER than the cutoff.
                # BUG FIX: was `ts_val < ttl_cutoff` which kept old entries and
                # discarded recent ones. Correct condition: skip if timestamp is
                # BEFORE the cutoff (i.e. older than TTL days).
                if ts_val > 0 and ts_val < ttl_cutoff:
                    continue  # older than TTL — skip
                # Temporal decay score: boost recent memories
                age_days = (now - ts_val) / 86400 if ts_val > 0 else 90
                recency_boost = max(0.0, 1.0 - (age_days / self._TTL_DAYS))
                semantic_score = 1.0 - float(dist)  # cosine similarity
                combined_score = (0.75 * semantic_score) + (0.25 * recency_boost)
                results.append({"text": doc, "meta": meta, "_score": combined_score})

            # Re-rank by combined score
            results.sort(key=lambda x: x["_score"], reverse=True)
            return [{"text": r["text"], "meta": r["meta"]} for r in results[:n]]
        except Exception as _search_err:
            print(f"[MemoryStore] ⚠️  search() failed: {_search_err}", flush=True)
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
