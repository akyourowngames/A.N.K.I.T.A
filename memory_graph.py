from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def stable_id(kind: str, *parts: object) -> str:
    text = "\n".join(str(part) for part in parts)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
    return f"{kind}_{digest}"


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def read_json_text(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    if os.environ.get("MEMORY_BRAIN_SQLITE_WAL", "").strip().casefold() in {"1", "true", "yes", "on"}:
        connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=OFF")
    return connection


@contextmanager
def graph_connection(db_path: Path):
    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_graph(db_path: Path) -> None:
    with graph_connection(db_path) as connection:
        create_schema(connection)


def create_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS entities (
            id TEXT PRIMARY KEY,
            canonical_name TEXT NOT NULL,
            aliases_json TEXT NOT NULL,
            type TEXT NOT NULL,
            summary TEXT NOT NULL,
            confidence REAL NOT NULL,
            source_paths_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            normalized_key TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_entities_key ON entities(normalized_key)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS facts (
            id TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            type TEXT NOT NULL,
            subject_entity_ids_json TEXT NOT NULL,
            object_entity_ids_json TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_line INTEGER,
            source_span_json TEXT NOT NULL,
            confidence REAL NOT NULL,
            importance REAL NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            valid_from TEXT,
            valid_to TEXT,
            supersedes_fact_id TEXT,
            contradicted_by_json TEXT NOT NULL
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_facts_type ON facts(type)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_facts_source ON facts(source_path)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS edges (
            id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            confidence REAL NOT NULL,
            evidence_fact_id TEXT,
            source_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            valid_from TEXT,
            valid_to TEXT
        )
        """
    )
    connection.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)")
    connection.execute("CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation_type)")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS episodes (
            id TEXT PRIMARY KEY,
            session_day TEXT NOT NULL,
            user_summary TEXT NOT NULL,
            assistant_summary TEXT NOT NULL,
            extracted_decisions_json TEXT NOT NULL,
            extracted_tasks_json TEXT NOT NULL,
            linked_entity_ids_json TEXT NOT NULL,
            source_transcript_path TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )
        """
    )
    ensure_fts(connection)
    connection.execute(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )


def ensure_fts(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS fact_fts
            USING fts5(fact_id UNINDEXED, text, source_path UNINDEXED, fact_type UNINDEXED)
            """
        )
        connection.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("fts", "true"))
        return True
    except sqlite3.DatabaseError:
        connection.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("fts", "false"))
        return False


def write_graph_index(
    db_path: Path,
    graph_json_path: Path,
    entity_index_path: Path,
    conflicts_path: Path,
    entities: list[dict[str, Any]],
    facts: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    episodes: list[dict[str, Any]],
    conflicts: list[dict[str, Any]],
) -> dict[str, Any]:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with graph_connection(db_path) as connection:
        create_schema(connection)
        connection.execute("DELETE FROM entities")
        connection.execute("DELETE FROM facts")
        connection.execute("DELETE FROM edges")
        connection.execute("DELETE FROM episodes")
        if fts_enabled(connection):
            connection.execute("DELETE FROM fact_fts")
        for entity in entities:
            insert_entity(connection, entity)
        for fact in facts:
            insert_fact(connection, fact)
        for edge in edges:
            insert_edge(connection, edge)
        for episode in episodes:
            insert_episode(connection, episode)
        updated_at = utc_now()
        connection.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", ("updated_at", updated_at))
        connection.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
            (
                "counts",
                json_text(
                    {
                        "entities": len(entities),
                        "facts": len(facts),
                        "edges": len(edges),
                        "episodes": len(episodes),
                        "conflicts": len(conflicts),
                    }
                ),
            ),
        )
        connection.commit()

    graph = graph_json_from_db(db_path)
    graph_json_path.write_text(json.dumps(graph, ensure_ascii=True, indent=2), encoding="utf-8")
    entity_index_path.write_text(
        json.dumps(entity_index_payload(entities), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    conflicts_path.write_text(json.dumps(conflicts, ensure_ascii=True, indent=2), encoding="utf-8")
    return {
        "db_path": str(db_path.resolve()),
        "graph_json_path": str(graph_json_path.resolve()),
        "entity_index_path": str(entity_index_path.resolve()),
        "conflicts_path": str(conflicts_path.resolve()),
        "entities": len(entities),
        "facts": len(facts),
        "edges": len(edges),
        "episodes": len(episodes),
        "conflicts": len(conflicts),
    }


def insert_entity(connection: sqlite3.Connection, entity: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO entities(
            id, canonical_name, aliases_json, type, summary, confidence,
            source_paths_json, created_at, updated_at, normalized_key
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity["id"],
            entity["canonical_name"],
            json_text(entity.get("aliases", [])),
            entity.get("type", "topic"),
            entity.get("summary", ""),
            float(entity.get("confidence", 0.7)),
            json_text(entity.get("source_paths", [])),
            entity.get("created_at") or utc_now(),
            entity.get("updated_at") or utc_now(),
            entity.get("normalized_key", ""),
        ),
    )


def insert_fact(connection: sqlite3.Connection, fact: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO facts(
            id, text, type, subject_entity_ids_json, object_entity_ids_json,
            source_path, source_line, source_span_json, confidence, importance,
            created_at, updated_at, valid_from, valid_to, supersedes_fact_id,
            contradicted_by_json
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fact["id"],
            fact["text"],
            fact.get("type", "fact"),
            json_text(fact.get("subject_entity_ids", [])),
            json_text(fact.get("object_entity_ids", [])),
            fact.get("source_path", ""),
            fact.get("source_line"),
            json_text(fact.get("source_span", {})),
            float(fact.get("confidence", 0.7)),
            float(fact.get("importance", 0.5)),
            fact.get("created_at") or utc_now(),
            fact.get("updated_at") or utc_now(),
            fact.get("valid_from"),
            fact.get("valid_to"),
            fact.get("supersedes_fact_id"),
            json_text(fact.get("contradicted_by", [])),
        ),
    )
    if fts_enabled(connection):
        connection.execute(
            "INSERT INTO fact_fts(fact_id, text, source_path, fact_type) VALUES(?, ?, ?, ?)",
            (
                fact["id"],
                fact["text"],
                fact.get("source_path", ""),
                fact.get("type", "fact"),
            ),
        )


def insert_edge(connection: sqlite3.Connection, edge: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO edges(
            id, source_id, target_id, relation_type, confidence, evidence_fact_id,
            source_path, created_at, valid_from, valid_to
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            edge["id"],
            edge["source_id"],
            edge["target_id"],
            edge.get("relation_type", "related_to"),
            float(edge.get("confidence", 0.7)),
            edge.get("evidence_fact_id"),
            edge.get("source_path", ""),
            edge.get("created_at") or utc_now(),
            edge.get("valid_from"),
            edge.get("valid_to"),
        ),
    )


def insert_episode(connection: sqlite3.Connection, episode: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO episodes(
            id, session_day, user_summary, assistant_summary, extracted_decisions_json,
            extracted_tasks_json, linked_entity_ids_json, source_transcript_path, timestamp
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            episode["id"],
            episode.get("session_day", ""),
            episode.get("user_summary", ""),
            episode.get("assistant_summary", ""),
            json_text(episode.get("extracted_decisions", [])),
            json_text(episode.get("extracted_tasks", [])),
            json_text(episode.get("linked_entity_ids", [])),
            episode.get("source_transcript_path", ""),
            episode.get("timestamp") or utc_now(),
        ),
    )


def fts_enabled(connection: sqlite3.Connection) -> bool:
    try:
        row = connection.execute("SELECT value FROM metadata WHERE key = ?", ("fts",)).fetchone()
    except sqlite3.DatabaseError:
        return False
    return bool(row and row["value"] == "true")


def metadata(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    try:
        with graph_connection(db_path) as connection:
            create_schema(connection)
            rows = connection.execute("SELECT key, value FROM metadata").fetchall()
    except sqlite3.DatabaseError:
        return {}
    return {str(row["key"]): str(row["value"]) for row in rows}


def graph_status(db_path: Path, graph_json_path: Path, conflicts_path: Path) -> dict[str, Any]:
    data = metadata(db_path)
    counts = read_json_text(data.get("counts"), {})
    return {
        "enabled": True,
        "db_path": str(db_path.resolve()),
        "db_exists": db_path.exists(),
        "graph_json_path": str(graph_json_path.resolve()),
        "graph_json_exists": graph_json_path.exists(),
        "conflicts_path": str(conflicts_path.resolve()),
        "conflicts_exists": conflicts_path.exists(),
        "schema_version": data.get("schema_version"),
        "updated_at": data.get("updated_at"),
        "fts": data.get("fts") == "true",
        "counts": counts if isinstance(counts, dict) else {},
    }


def entity_index_payload(entities: list[dict[str, Any]]) -> dict[str, Any]:
    by_key: dict[str, str] = {}
    aliases: dict[str, str] = {}
    for entity in entities:
        entity_id = str(entity.get("id", ""))
        key = str(entity.get("normalized_key", ""))
        if key and entity_id:
            by_key[key] = entity_id
        for alias in entity.get("aliases", []):
            if isinstance(alias, str) and alias.strip():
                aliases[alias.casefold()] = entity_id
    return {
        "version": SCHEMA_VERSION,
        "updated_at": utc_now(),
        "entity_count": len(entities),
        "by_normalized_key": by_key,
        "aliases": aliases,
    }


def graph_json_from_db(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return empty_graph_payload()
    with graph_connection(db_path) as connection:
        create_schema(connection)
        entities = [entity_from_row(row) for row in connection.execute("SELECT * FROM entities")]
        facts = [fact_from_row(row) for row in connection.execute("SELECT * FROM facts")]
        edges = [edge_from_row(row) for row in connection.execute("SELECT * FROM edges")]
        episodes = [episode_from_row(row) for row in connection.execute("SELECT * FROM episodes")]
        rows = connection.execute("SELECT key, value FROM metadata").fetchall()
        data = {str(row["key"]): str(row["value"]) for row in rows}
    nodes = []
    for entity in entities:
        nodes.append(
            {
                "id": entity["id"],
                "kind": "entity",
                "label": entity["canonical_name"],
                "type": entity["type"],
                "summary": entity["summary"],
                "confidence": entity["confidence"],
                "source_paths": entity["source_paths"],
            }
        )
    for fact in facts:
        nodes.append(
            {
                "id": fact["id"],
                "kind": "fact",
                "label": short_fact_label(fact["text"]),
                "type": fact["type"],
                "summary": fact["text"],
                "confidence": fact["confidence"],
                "source_paths": [fact["source_path"]],
                "source_line": fact.get("source_line"),
            }
        )
    return {
        "version": SCHEMA_VERSION,
        "updated_at": data.get("updated_at"),
        "stats": {
            "entities": len(entities),
            "facts": len(facts),
            "edges": len(edges),
            "episodes": len(episodes),
        },
        "nodes": nodes,
        "edges": edges,
        "episodes": episodes,
    }


def empty_graph_payload() -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "updated_at": None,
        "stats": {"entities": 0, "facts": 0, "edges": 0, "episodes": 0},
        "nodes": [],
        "edges": [],
        "episodes": [],
    }


def entity_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "canonical_name": row["canonical_name"],
        "aliases": read_json_text(row["aliases_json"], []),
        "type": row["type"],
        "summary": row["summary"],
        "confidence": float(row["confidence"]),
        "source_paths": read_json_text(row["source_paths_json"], []),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "normalized_key": row["normalized_key"],
    }


def fact_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "text": row["text"],
        "type": row["type"],
        "subject_entity_ids": read_json_text(row["subject_entity_ids_json"], []),
        "object_entity_ids": read_json_text(row["object_entity_ids_json"], []),
        "source_path": row["source_path"],
        "source_line": row["source_line"],
        "source_span": read_json_text(row["source_span_json"], {}),
        "confidence": float(row["confidence"]),
        "importance": float(row["importance"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "supersedes_fact_id": row["supersedes_fact_id"],
        "contradicted_by": read_json_text(row["contradicted_by_json"], []),
    }


def edge_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "source_id": row["source_id"],
        "target_id": row["target_id"],
        "relation_type": row["relation_type"],
        "confidence": float(row["confidence"]),
        "evidence_fact_id": row["evidence_fact_id"],
        "source_path": row["source_path"],
        "created_at": row["created_at"],
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
    }


def episode_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_day": row["session_day"],
        "user_summary": row["user_summary"],
        "assistant_summary": row["assistant_summary"],
        "extracted_decisions": read_json_text(row["extracted_decisions_json"], []),
        "extracted_tasks": read_json_text(row["extracted_tasks_json"], []),
        "linked_entity_ids": read_json_text(row["linked_entity_ids_json"], []),
        "source_transcript_path": row["source_transcript_path"],
        "timestamp": row["timestamp"],
    }


def load_entity(db_path: Path, entity_id: str) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    with graph_connection(db_path) as connection:
        create_schema(connection)
        row = connection.execute("SELECT * FROM entities WHERE id = ?", (entity_id,)).fetchone()
    return entity_from_row(row) if row else None


def load_fact(db_path: Path, fact_id: str) -> dict[str, Any] | None:
    if not db_path.exists():
        return None
    with graph_connection(db_path) as connection:
        create_schema(connection)
        row = connection.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()
    return fact_from_row(row) if row else None


def list_entities(db_path: Path, limit: int = 200) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with graph_connection(db_path) as connection:
        create_schema(connection)
        rows = connection.execute(
            "SELECT * FROM entities ORDER BY updated_at DESC, canonical_name LIMIT ?",
            (max(1, limit),),
        ).fetchall()
    return [entity_from_row(row) for row in rows]


def list_facts(db_path: Path, limit: int = 200) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with graph_connection(db_path) as connection:
        create_schema(connection)
        rows = connection.execute(
            "SELECT * FROM facts ORDER BY COALESCE(valid_from, created_at) DESC, source_path, source_line LIMIT ?",
            (max(1, limit),),
        ).fetchall()
    return [fact_from_row(row) for row in rows]


def connected_edges(db_path: Path, node_id: str, limit: int = 100) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    with graph_connection(db_path) as connection:
        create_schema(connection)
        rows = connection.execute(
            """
            SELECT * FROM edges
            WHERE source_id = ? OR target_id = ?
            ORDER BY confidence DESC, created_at DESC
            LIMIT ?
            """,
            (node_id, node_id, max(1, limit)),
        ).fetchall()
    return [edge_from_row(row) for row in rows]


def short_fact_label(text: str, limit: int = 86) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[: max(12, limit - 3)].rstrip() + "..."
