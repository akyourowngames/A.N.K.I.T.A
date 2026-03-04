"""
VectorStore — ChromaDB semantic search wrapper for A.N.K.I.T.A.

Wraps ChromaDB with a graceful SQLite LIKE fallback so the system never
crashes if ChromaDB is not installed or fails to initialise.

Collection: "ankita_facts"
Embedding:  ChromaDB's built-in default (all-MiniLM-L6-v2 via sentence-transformers)
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Sentinel — set to None if ChromaDB unavailable
_chroma_available: Optional[bool] = None


def _try_import_chroma():
    global _chroma_available
    if _chroma_available is not None:
        return _chroma_available
    try:
        import chromadb  # noqa: F401
        _chroma_available = True
    except ImportError:
        _chroma_available = False
        logger.info("[VectorStore] chromadb not installed — SQLite LIKE fallback active.")
    return _chroma_available


class VectorStore:
    """
    Semantic vector search over long-term facts.

    Safe to construct even if ChromaDB is not installed — all methods
    return empty lists (caller then uses FactStore.search_keyword() instead).
    """

    def __init__(self, chroma_dir: Path) -> None:
        self.chroma_dir = chroma_dir
        self._client = None
        self._collection = None

        if _try_import_chroma():
            try:
                import chromadb
                chroma_dir.mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(path=str(chroma_dir))
                self._collection = self._client.get_or_create_collection(
                    name="ankita_facts",
                    metadata={"hnsw:space": "cosine"},
                )
                logger.info(
                    "[VectorStore] ChromaDB ready — %d facts indexed.",
                    self._collection.count(),
                )
            except Exception as exc:
                logger.warning("[VectorStore] ChromaDB init failed (%s) — SQLite fallback active.", exc)
                self._client = None
                self._collection = None

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        return self._collection is not None

    # ── Public API ────────────────────────────────────────────────────────────

    def upsert(self, fact_id: str, text: str, metadata: Optional[dict] = None) -> None:
        """Add or update a fact embedding in ChromaDB."""
        if not self.available:
            return
        try:
            self._collection.upsert(
                ids=[fact_id],
                documents=[text],
                metadatas=[metadata or {}],
            )
        except Exception as exc:
            logger.warning("[VectorStore] upsert failed: %s", exc)

    def upsert_batch(self, facts: List[dict]) -> None:
        """Bulk upsert a list of fact dicts with keys: id, fact, confidence, interface."""
        if not self.available or not facts:
            return
        try:
            self._collection.upsert(
                ids=[f["id"] for f in facts],
                documents=[f["fact"] for f in facts],
                metadatas=[
                    {
                        "confidence": float(f.get("confidence", 1.0)),
                        "interface": str(f.get("interface", "unknown")),
                        "timestamp": float(f.get("timestamp", 0.0)),
                    }
                    for f in facts
                ],
            )
            logger.debug("[VectorStore] Bulk upsert: %d facts", len(facts))
        except Exception as exc:
            logger.warning("[VectorStore] batch upsert failed: %s", exc)

    def search(self, query: str, n_results: int = 6) -> List[str]:
        """
        Semantic search. Returns list of fact strings ranked by relevance.
        Returns [] if ChromaDB unavailable or collection is empty.

        ChromaDB cosine distance ranges 0–2 (0 = identical, 2 = opposite).
        We keep results with distance < 1.2 (roughly > 40% similarity).
        """
        if not self.available:
            return []
        try:
            count = self._collection.count()
            if count == 0:
                return []
            n = min(n_results, count)
            results = self._collection.query(
                query_texts=[query],
                n_results=n,
                include=["documents", "distances"],
            )
            docs = results.get("documents", [[]])[0]
            dists = results.get("distances", [[]])[0]
            # Keep results where cosine distance < 1.2 (not opposite in meaning)
            # Previously was 0.75 which was far too strict — filtered out most valid facts
            return [
                doc for doc, dist in zip(docs, dists)
                if dist < 1.2
            ]
        except Exception as exc:
            logger.warning("[VectorStore] search failed: %s", exc)
            return []

    def count(self) -> int:
        if not self.available:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0
