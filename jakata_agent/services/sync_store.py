from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class ServiceItem:
    provider: str
    item_type: str
    external_id: str
    title: str
    text: str = ""
    start_at: str = ""
    end_at: str = ""
    url: str = ""
    labels: list[str] | None = None
    raw: dict[str, Any] | None = None


class ExternalServiceStore:
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
                CREATE TABLE IF NOT EXISTS external_service_items (
                    provider TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    start_at TEXT NOT NULL,
                    end_at TEXT NOT NULL,
                    url TEXT NOT NULL,
                    labels TEXT NOT NULL,
                    raw_json TEXT NOT NULL,
                    synced_at TEXT NOT NULL,
                    PRIMARY KEY (provider, item_type, external_id)
                )
                """
            )

    def upsert_many(self, items: list[ServiceItem]) -> int:
        if not items:
            return 0
        now = utcnow_iso()
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO external_service_items (
                    provider, item_type, external_id, title, text, start_at, end_at,
                    url, labels, raw_json, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, item_type, external_id) DO UPDATE SET
                    title = excluded.title,
                    text = excluded.text,
                    start_at = excluded.start_at,
                    end_at = excluded.end_at,
                    url = excluded.url,
                    labels = excluded.labels,
                    raw_json = excluded.raw_json,
                    synced_at = excluded.synced_at
                """,
                [
                    (
                        item.provider,
                        item.item_type,
                        item.external_id,
                        item.title,
                        item.text,
                        item.start_at,
                        item.end_at,
                        item.url,
                        json.dumps(item.labels or [], ensure_ascii=False),
                        json.dumps(item.raw or {}, ensure_ascii=False),
                        now,
                    )
                    for item in items
                ],
            )
        return len(items)

    def query(
        self,
        *,
        provider: str,
        item_type: str,
        text_query: str = "",
        start_at: str = "",
        end_at: str = "",
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        clauses = ["provider = ?", "item_type = ?"]
        values: list[Any] = [provider, item_type]
        if text_query.strip():
            like = f"%{text_query.strip()}%"
            clauses.append("(title LIKE ? OR text LIKE ? OR labels LIKE ?)")
            values.extend([like, like, like])
        if start_at:
            clauses.append("(start_at = '' OR start_at >= ?)")
            values.append(start_at)
        if end_at:
            clauses.append("(start_at = '' OR start_at <= ?)")
            values.append(end_at)
        values.append(max(1, min(int(limit), 50)))
        sql = f"""
            SELECT provider, item_type, external_id, title, text, start_at, end_at, url, labels, raw_json, synced_at
            FROM external_service_items
            WHERE {" AND ".join(clauses)}
            ORDER BY CASE WHEN start_at = '' THEN synced_at ELSE start_at END ASC
            LIMIT ?
        """
        with self._connect() as conn:
            rows = conn.execute(sql, values).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT provider || ':' || item_type, COUNT(*)
                FROM external_service_items
                GROUP BY provider, item_type
                """
            ).fetchall()
        return {str(key): int(count) for key, count in rows}

    @staticmethod
    def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "provider": row[0],
            "item_type": row[1],
            "external_id": row[2],
            "title": row[3],
            "text": row[4],
            "start_at": row[5],
            "end_at": row[6],
            "url": row[7],
            "labels": json.loads(row[8]) if row[8] else [],
            "raw": json.loads(row[9]) if row[9] else {},
            "synced_at": row[10],
        }

