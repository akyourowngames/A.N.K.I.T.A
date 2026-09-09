"""Durable, independent graph storage. No optional vector extension required."""
from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3


def home() -> Path:
    path = Path(os.getenv("ZUMBA_KNOWLEDGE_HOME", str(Path.home() / ".zumba" / "knowledge")))
    path.mkdir(parents=True, exist_ok=True)
    return path


SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, source_key TEXT NOT NULL,
 hash TEXT NOT NULL, content BLOB NOT NULL, created_at REAL NOT NULL,
 UNIQUE(source_key, hash)
);
CREATE TABLE IF NOT EXISTS jobs (
 id TEXT PRIMARY KEY REFERENCES documents(id), status TEXT NOT NULL DEFAULT 'queued',
 stage TEXT NOT NULL DEFAULT 'Queued', completed INTEGER NOT NULL DEFAULT 0,
 total INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '', warning TEXT NOT NULL DEFAULT '',
 updated_at REAL NOT NULL, lease_until REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS chunks (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id),
 page INTEGER, section TEXT NOT NULL, text TEXT NOT NULL, embedding TEXT,
 done INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(document_id);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(chunk_id UNINDEXED, text);
CREATE TABLE IF NOT EXISTS entities (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, normalized_name TEXT NOT NULL, type TEXT NOT NULL,
 description TEXT NOT NULL, aliases TEXT NOT NULL, confidence REAL NOT NULL,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, embedding TEXT
);
CREATE INDEX IF NOT EXISTS entity_name ON entities(normalized_name);
CREATE TABLE IF NOT EXISTS mentions (
 entity_id TEXT NOT NULL REFERENCES entities(id), chunk_id TEXT NOT NULL REFERENCES chunks(id),
 quote TEXT NOT NULL, PRIMARY KEY(entity_id,chunk_id)
);
CREATE TABLE IF NOT EXISTS relations (
 id TEXT PRIMARY KEY, source TEXT NOT NULL REFERENCES entities(id), target TEXT NOT NULL REFERENCES entities(id),
 type TEXT NOT NULL, UNIQUE(source,target,type)
);
CREATE TABLE IF NOT EXISTS evidence (
 id TEXT PRIMARY KEY, relation_id TEXT NOT NULL REFERENCES relations(id),
 chunk_id TEXT NOT NULL REFERENCES chunks(id), quote TEXT NOT NULL, confidence REAL NOT NULL,
 method TEXT NOT NULL, created_at REAL NOT NULL, UNIQUE(relation_id,chunk_id,quote)
);
CREATE TABLE IF NOT EXISTS resolution_audit (
 id INTEGER PRIMARY KEY, entity_id TEXT NOT NULL, mention TEXT NOT NULL, decision TEXT NOT NULL,
 reason TEXT NOT NULL, chunk_id TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS sync_state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@contextmanager
def connect():
    con = sqlite3.connect(home() / "graph.db", timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=FULL")
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
