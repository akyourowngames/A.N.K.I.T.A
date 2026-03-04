"""
FactStore — SQLite-backed long-term fact store for A.N.K.I.T.A.

Schema:
  facts(id TEXT PK, timestamp REAL, fact TEXT UNIQUE, confidence REAL,
        interface TEXT, embedding_id TEXT)

Facts are never deleted automatically. Confidence is weighted so
contradictory facts sink over time. WAL mode for concurrent threads.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import List, Dict, Optional


_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS facts (
    id           TEXT PRIMARY KEY,
    timestamp    REAL NOT NULL,
    fact         TEXT NOT NULL,
    confidence   REAL NOT NULL DEFAULT 1.0,
    interface    TEXT NOT NULL DEFAULT 'unknown',
    embedding_id TEXT,
    UNIQUE(fact)
);
"""

_CREATE_IDX = """
CREATE INDEX IF NOT EXISTS idx_facts_timestamp ON facts(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_facts_confidence ON facts(confidence DESC);
"""

# SQLite FTS5 for fast full-text keyword search (replaces LIKE loop)
_CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
    id UNINDEXED,
    fact,
    content='facts',
    content_rowid='rowid'
);
"""

_FTS_TRIGGER_INSERT = """
CREATE TRIGGER IF NOT EXISTS facts_fts_insert AFTER INSERT ON facts BEGIN
    INSERT INTO facts_fts(rowid, id, fact) VALUES (new.rowid, new.id, new.fact);
END;
"""

_FTS_TRIGGER_UPDATE = """
CREATE TRIGGER IF NOT EXISTS facts_fts_update AFTER UPDATE ON facts BEGIN
    INSERT INTO facts_fts(facts_fts, rowid, id, fact) VALUES('delete', old.rowid, old.id, old.fact);
    INSERT INTO facts_fts(rowid, id, fact) VALUES (new.rowid, new.id, new.fact);
END;
"""


class FactStore:
    """Persistent SQLite fact store. Thread-safe via WAL mode + connection-per-call."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")   # concurrent reader/writer safety
        conn.execute("PRAGMA synchronous=NORMAL") # fast + safe
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript(_CREATE_TABLE)
            conn.executescript(_CREATE_IDX)
            # FTS5 table + triggers (idempotent)
            try:
                conn.executescript(_CREATE_FTS + _FTS_TRIGGER_INSERT + _FTS_TRIGGER_UPDATE)
            except Exception:
                pass  # FTS5 not compiled — LIKE fallback still works
            conn.commit()

    # ── Public API ────────────────────────────────────────────────────────────

    def upsert_fact(
        self,
        fact: str,
        confidence: float = 1.0,
        interface: str = "unknown",
        embedding_id: Optional[str] = None,
    ) -> str:
        """Insert or update a fact. Returns the fact ID."""
        fact = fact.strip()
        if not fact:
            return ""

        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id, confidence FROM facts WHERE fact = ?", (fact,)
            ).fetchone()

            if existing:
                fact_id = existing["id"]
                # Weighted bump: higher confidence = stronger bump
                old_conf = existing["confidence"]
                new_confidence = min(1.0, old_conf * 0.8 + confidence * 0.2 + 0.05)
                conn.execute(
                    "UPDATE facts SET timestamp=?, confidence=?, interface=? WHERE id=?",
                    (time.time(), new_confidence, interface, fact_id),
                )
            else:
                fact_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO facts(id, timestamp, fact, confidence, interface, embedding_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (fact_id, time.time(), fact, confidence, interface, embedding_id),
                )
            conn.commit()
        return fact_id

    def search_keyword(self, query: str, limit: int = 8) -> List[Dict]:
        """Fast FTS5 keyword search. Falls back to LIKE if FTS unavailable."""
        if not query or not query.strip():
            return []

        with self._conn() as conn:
            # Try FTS5 first
            try:
                rows = conn.execute(
                    "SELECT f.id, f.fact, f.confidence, f.interface, f.timestamp "
                    "FROM facts_fts fts JOIN facts f ON fts.id = f.id "
                    "WHERE facts_fts MATCH ? "
                    "ORDER BY f.confidence DESC, f.timestamp DESC LIMIT ?",
                    (query, limit),
                ).fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except Exception:
                pass  # FTS unavailable

            # LIKE fallback — single pass with OR across tokens
            tokens = [t for t in query.lower().split() if len(t) >= 3][:4]
            if not tokens:
                return []
            conditions = " OR ".join(["lower(fact) LIKE ?" for _ in tokens])
            params = [f"%{t}%" for t in tokens] + [limit]
            rows = conn.execute(
                f"SELECT id, fact, confidence, interface, timestamp FROM facts "
                f"WHERE {conditions} ORDER BY confidence DESC, timestamp DESC LIMIT ?",
                params,
            ).fetchall()
            return [dict(r) for r in rows]

    def all_facts(self) -> List[Dict]:
        """Return all facts ordered by recency (for ChromaDB sync)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, fact, confidence, interface, timestamp FROM facts "
                "ORDER BY timestamp DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_facts(self, limit: int = 20) -> List[Dict]:
        """Return the most recently seen facts, highest confidence first."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id, fact, confidence, interface, timestamp FROM facts "
                "ORDER BY confidence DESC, timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]
