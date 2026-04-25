from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from jakata_agent.tasks.models import utcnow_iso


def normalize_label(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip().lower())


class GraphStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    node_type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    label_norm TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE(node_type, label_norm)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS graph_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_node_id INTEGER NOT NULL,
                    target_node_id INTEGER NOT NULL,
                    edge_type TEXT NOT NULL,
                    metadata TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    UNIQUE(source_node_id, target_node_id, edge_type)
                )
                """
            )

    def upsert_node(
        self,
        node_type: str,
        label: str,
        *,
        metadata: dict[str, Any] | None = None,
        confidence: float = 0.6,
    ) -> int:
        cleaned = label.strip()
        if not cleaned:
            raise ValueError("graph node label cannot be empty")
        now = utcnow_iso()
        norm = normalize_label(cleaned)
        payload = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, confidence FROM graph_nodes
                WHERE node_type = ? AND label_norm = ?
                """,
                (node_type, norm),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE graph_nodes
                    SET label = ?, metadata = ?, confidence = ?, updated_at = ?, last_seen_at = ?
                    WHERE id = ?
                    """,
                    (cleaned, payload, max(float(row["confidence"]), confidence), now, now, row["id"]),
                )
                return int(row["id"])
            cur = conn.execute(
                """
                INSERT INTO graph_nodes (
                    node_type, label, label_norm, metadata, confidence,
                    created_at, updated_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (node_type, cleaned, norm, payload, confidence, now, now, now),
            )
        return int(cur.lastrowid)

    def upsert_edge(
        self,
        source_node_id: int,
        target_node_id: int,
        edge_type: str,
        *,
        metadata: dict[str, Any] | None = None,
        confidence: float = 0.6,
    ) -> int:
        now = utcnow_iso()
        payload = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, confidence FROM graph_edges
                WHERE source_node_id = ? AND target_node_id = ? AND edge_type = ?
                """,
                (source_node_id, target_node_id, edge_type),
            ).fetchone()
            if row:
                conn.execute(
                    """
                    UPDATE graph_edges
                    SET metadata = ?, confidence = ?, updated_at = ?, last_seen_at = ?
                    WHERE id = ?
                    """,
                    (payload, max(float(row["confidence"]), confidence), now, now, row["id"]),
                )
                return int(row["id"])
            cur = conn.execute(
                """
                INSERT INTO graph_edges (
                    source_node_id, target_node_id, edge_type, metadata,
                    confidence, created_at, updated_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (source_node_id, target_node_id, edge_type, payload, confidence, now, now, now),
            )
        return int(cur.lastrowid)

    def search(self, query: str, limit: int = 8) -> dict[str, list[dict[str, Any]]]:
        tokens = [token for token in normalize_label(query).split() if len(token) > 2]
        with self._connect() as conn:
            node_rows = conn.execute(
                "SELECT * FROM graph_nodes ORDER BY updated_at DESC LIMIT 200"
            ).fetchall()
            edge_rows = conn.execute(
                """
                SELECT e.*, s.label AS source_label, s.node_type AS source_type,
                       t.label AS target_label, t.node_type AS target_type
                FROM graph_edges e
                JOIN graph_nodes s ON s.id = e.source_node_id
                JOIN graph_nodes t ON t.id = e.target_node_id
                ORDER BY e.updated_at DESC
                LIMIT 200
                """
            ).fetchall()

        ranked_nodes: list[tuple[float, dict[str, Any]]] = []
        for row in node_rows:
            label = str(row["label"])
            haystack = f"{row['node_type']} {label}".lower()
            score = sum(haystack.count(token) for token in tokens) if tokens else 1
            if score <= 0:
                continue
            ranked_nodes.append(
                (
                    score + float(row["confidence"]),
                    {
                        "id": row["id"],
                        "node_type": row["node_type"],
                        "label": label,
                        "confidence": row["confidence"],
                    },
                )
            )
        ranked_nodes.sort(key=lambda item: item[0], reverse=True)

        ranked_edges: list[tuple[float, dict[str, Any]]] = []
        for row in edge_rows:
            haystack = (
                f"{row['source_type']} {row['source_label']} {row['edge_type']} "
                f"{row['target_type']} {row['target_label']}"
            ).lower()
            score = sum(haystack.count(token) for token in tokens) if tokens else 1
            if score <= 0:
                continue
            ranked_edges.append(
                (
                    score + float(row["confidence"]),
                    {
                        "id": row["id"],
                        "edge_type": row["edge_type"],
                        "source_label": row["source_label"],
                        "source_type": row["source_type"],
                        "target_label": row["target_label"],
                        "target_type": row["target_type"],
                        "confidence": row["confidence"],
                    },
                )
            )
        ranked_edges.sort(key=lambda item: item[0], reverse=True)
        return {
            "nodes": [item for _, item in ranked_nodes[:limit]],
            "edges": [item for _, item in ranked_edges[:limit]],
        }

    def render_search(self, query: str, limit: int = 8) -> str:
        found = self.search(query, limit=limit)
        parts: list[str] = []
        if found["nodes"]:
            parts.append(
                "Graph nodes:\n" + "\n".join(
                    f"- [{item['node_type']}] {item['label']}" for item in found["nodes"]
                )
            )
        if found["edges"]:
            parts.append(
                "Graph edges:\n" + "\n".join(
                    f"- [{item['edge_type']}] {item['source_label']} -> {item['target_label']}"
                    for item in found["edges"]
                )
            )
        return "\n\n".join(parts).strip() or "No graph context found."
