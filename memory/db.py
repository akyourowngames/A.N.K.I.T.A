"""SQLite persistence for the Zumba memory graph.

Single embedded database at ``~/.zumba/memory.db`` (WAL). Everything is stored
in tables plus a ``sqlite-vec`` virtual table for vectors and FTS5 for keyword
search. All state is algorithmic to transport — no logic here, just schema and
CRUD.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

# Embedding dimension for the local model (bge-small-en-v1.5).
EMBED_DIM = 384

_lock = threading.RLock()


def memory_home() -> Path:
    home = Path(os.path.expanduser("~")) / ".zumba"
    home.mkdir(parents=True, exist_ok=True)
    return home


def memory_db_path() -> Path:
    return memory_home() / "memory.db"


_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Episodes: one user turn paired with the assistant reply that followed it.
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    kind TEXT NOT NULL DEFAULT 'chat',        -- chat | ask | consolidated
    user_text TEXT NOT NULL DEFAULT '',
    assistant_text TEXT NOT NULL DEFAULT '',
    context TEXT NOT NULL DEFAULT '',          -- optional surrounding context json
    hash TEXT NOT NULL UNIQUE,                 -- content hash for de-dup / caching
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_episodes_time ON episodes(created_at);
CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id);

-- Entities: nodes in the knowledge graph. canonical_name is the resolved
-- identity used for de-duplication across aliases.
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'unknown',
    description TEXT NOT NULL DEFAULT '',
    embedding BLOB,                             -- packed float32 vector
    confidence REAL NOT NULL DEFAULT 0.5,
    importance REAL NOT NULL DEFAULT 0.5,       -- prior salience
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_access REAL NOT NULL DEFAULT 0,
    decay REAL NOT NULL DEFAULT 1.0,            -- reinforced confidence (HippoRAG-ish)
    details TEXT NOT NULL DEFAULT '{}'          -- extra json
);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_canon ON entities(canonical_name);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);

-- Aliases map surface names -> canonical entity (entity resolution).
CREATE TABLE IF NOT EXISTS aliases (
    alias TEXT PRIMARY KEY,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_aliases_entity ON aliases(entity_id);

-- Relations: temporal edges (facts). Bi-temporal: valid_at (when the fact was
-- true in the world) and created_at (when it was ingested). invalid_at marks
-- when a fact stopped being true (contradiction handling without delete).
CREATE TABLE IF NOT EXISTS relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    type TEXT NOT NULL,
    fact TEXT NOT NULL DEFAULT '',
    weight REAL NOT NULL DEFAULT 1.0,
    confidence REAL NOT NULL DEFAULT 0.5,
    embedding BLOB,
    valid_at REAL,
    invalid_at REAL,
    created_at REAL NOT NULL,
    source_episode INTEGER REFERENCES episodes(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_relations_src ON relations(source_id);
CREATE INDEX IF NOT EXISTS idx_relations_tgt ON relations(target_id);
CREATE INDEX IF NOT EXISTS idx_relations_active ON relations(invalid_at);

-- Provenance: which entities appeared in which episodes (PPR seeds + grounding).
CREATE TABLE IF NOT EXISTS episode_entities (
    episode_id INTEGER NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    salience REAL NOT NULL DEFAULT 0.5,
    PRIMARY KEY (episode_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_epent_entity ON episode_entities(entity_id);

-- A-Mem style notes with Zettelkasten-style links.
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    keywords TEXT NOT NULL DEFAULT '[]',
    tags TEXT NOT NULL DEFAULT '[]',
    embedding BLOB,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title);

CREATE TABLE IF NOT EXISTS note_links (
    source_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    target_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    strength REAL NOT NULL DEFAULT 0.5,
    PRIMARY KEY (source_id, target_id)
);
CREATE INDEX IF NOT EXISTS idx_links_target ON note_links(target_id);

-- GraphRAG-style communities (Leiden clusters) with multi-level summaries.
CREATE TABLE IF NOT EXISTS communities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT,
    level INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS community_members (
    community_id INTEGER NOT NULL REFERENCES communities(id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (community_id, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_comm_mem_entity ON community_members(entity_id);

-- L1 "core memory" blocks always injected into context (MemGPT/Letta style).
CREATE TABLE IF NOT EXISTS core_blocks (
    key TEXT PRIMARY KEY,
    content TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);

-- Vector search virtual tables.
CREATE VIRTUAL TABLE IF NOT EXISTS vec_entities USING vec0(
    entity_id integer primary key, embedding float[{EMBED_DIM}]
);
CREATE VIRTUAL TABLE IF NOT EXISTS vec_relations USING vec0(
    relation_id integer primary key, embedding float[{EMBED_DIM}]
);
CREATE VIRTUAL TABLE IF NOT EXISTS vec_episodes USING vec0(
    episode_id integer primary key, embedding float[{EMBED_DIM}]
);
CREATE VIRTUAL TABLE IF NOT EXISTS vec_notes USING vec0(
    note_id integer primary key, embedding float[{EMBED_DIM}]
);

-- FTS5 keyword search.
CREATE VIRTUAL TABLE IF NOT EXISTS fts_episodes USING fts5(
    user_text, assistant_text, content='episodes', content_rowid='id'
);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_relations USING fts5(
    fact, type, content='relations', content_rowid='id'
);
CREATE VIRTUAL TABLE IF NOT EXISTS fts_notes USING fts5(
    title, content, keywords, content='notes', content_rowid='id'
);
"""


def connect() -> sqlite3.Connection:
    import sqlite_vec  # local import to keep hard dependency surface clear

    con = sqlite3.connect(str(memory_db_path()), timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    try:
        con.enable_load_extension(True)
        sqlite_vec.load(con)
    except Exception:
        try:
            con.enable_load_extension(False)
        except Exception:
            pass
    with _lock:
        con.executescript(_SCHEMA.replace("{EMBED_DIM}", str(EMBED_DIM)))
    return con


def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(con: sqlite3.Connection, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return str(row["value"]) if row else default


def now() -> float:
    return time.time()


def new_id() -> str:
    return uuid.uuid4().hex


# Pack / unpack embedding float32 -> blob and vice versa.
def pack_vec(v) -> bytes:
    import array

    return array.array("f", [float(x) for x in v]).tobytes()


def unpack_vec(b) -> list:
    import array

    if not b:
        return []
    return list(array.array("f", b))


def match_vec(v) -> bytes:
    """sqlite-vec MATCH query vector as a packed float32 blob."""
    return pack_vec(v)