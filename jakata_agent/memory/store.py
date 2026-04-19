from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from jakata_agent.memory.models import MemoryRecord


class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    content TEXT NOT NULL UNIQUE,
                    summary TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    source_session TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_used_at TEXT NOT NULL
                )
                """
            )

    def upsert(self, record: MemoryRecord) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, confidence FROM memories WHERE content = ?",
                (record.content,),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE memories
                    SET summary = ?, tags = ?, confidence = ?, source_session = ?, updated_at = ?, last_used_at = ?
                    WHERE id = ?
                    """,
                    (
                        record.summary,
                        json.dumps(record.tags),
                        max(float(row[1]), record.confidence),
                        record.source_session,
                        record.updated_at,
                        record.last_used_at,
                        row[0],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO memories (
                        kind, content, summary, tags, confidence, source_session,
                        created_at, updated_at, last_used_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.kind,
                        record.content,
                        record.summary,
                        json.dumps(record.tags),
                        record.confidence,
                        record.source_session,
                        record.created_at,
                        record.updated_at,
                        record.last_used_at,
                    ),
                )

    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        tokens = [token.lower() for token in query.split() if len(token) > 2]
        if not tokens:
            return self.recent(limit=limit)

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, kind, content, summary, tags, confidence, source_session, created_at, updated_at, last_used_at
                FROM memories
                ORDER BY updated_at DESC
                """
            ).fetchall()

        ranked: list[tuple[int, MemoryRecord]] = []
        for row in rows:
            haystack = f"{row[1]} {row[2]} {row[3]} {row[4]}".lower()
            score = sum(haystack.count(token) for token in tokens)
            if score > 0:
                ranked.append((score, self._row_to_record(row)))

        ranked.sort(key=lambda item: (-item[0], -item[1].confidence, item[1].updated_at), reverse=False)
        return [record for _, record in ranked[:limit]]

    def recent(self, limit: int = 5) -> list[MemoryRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, kind, content, summary, tags, confidence, source_session, created_at, updated_at, last_used_at
                FROM memories
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row: tuple) -> MemoryRecord:
        return MemoryRecord(
            id=row[0],
            kind=row[1],
            content=row[2],
            summary=row[3],
            tags=json.loads(row[4]) if row[4] else [],
            confidence=row[5],
            source_session=row[6],
            created_at=row[7],
            updated_at=row[8],
            last_used_at=row[9],
        )

