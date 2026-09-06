"""Vault persistence: ~/.zumba/vault.db (WAL) + sqlite-vec + FTS5.

docs(hash, path, mtime, kind, title, n_pages, summary, status)
sections(id, doc_id, heading, level, summary, parent_id)
chunks(id, doc_id, section_id, parent_id, ordinal, page, text, embed,
       context_line, hyp_questions)
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

from memory.db import EMBED_DIM, match_vec, pack_vec  # noqa: F401  (reuse memory stack)

_lock = threading.RLock()


def vault_home() -> Path:
    try:
        from core.store import zumba_home
        return zumba_home()
    except Exception:
        h = Path.home() / ".zumba"
        h.mkdir(parents=True, exist_ok=True)
        return h


def vault_db_path() -> Path:
    return vault_home() / "vault.db"


def vault_raw_dir() -> Path:
    d = vault_home() / "vault" / "raw"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_watch_dir() -> Path:
    d = vault_home() / "vault"
    d.mkdir(parents=True, exist_ok=True)
    return d


_SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hash TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL DEFAULT '',
    mtime REAL NOT NULL DEFAULT 0,
    kind TEXT NOT NULL DEFAULT 'txt',
    title TEXT NOT NULL DEFAULT '',
    n_pages INTEGER NOT NULL DEFAULT 1,
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ok',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_title ON docs(title);
CREATE INDEX IF NOT EXISTS idx_docs_status ON docs(status);

CREATE TABLE IF NOT EXISTS sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    heading TEXT NOT NULL DEFAULT '',
    level INTEGER NOT NULL DEFAULT 1,
    summary TEXT NOT NULL DEFAULT '',
    parent_id INTEGER REFERENCES sections(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_sections_doc ON sections(doc_id);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id INTEGER NOT NULL REFERENCES docs(id) ON DELETE CASCADE,
    section_id INTEGER REFERENCES sections(id) ON DELETE SET NULL,
    parent_id INTEGER REFERENCES sections(id) ON DELETE SET NULL,
    ordinal INTEGER NOT NULL DEFAULT 0,
    page INTEGER NOT NULL DEFAULT 1,
    text TEXT NOT NULL DEFAULT '',
    embedding BLOB,
    context_line TEXT NOT NULL DEFAULT '',
    hyp_questions TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_section ON chunks(section_id);

CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
    chunk_id integer primary key, embedding float[{EMBED_DIM}]
);
CREATE VIRTUAL TABLE IF NOT EXISTS vec_sections USING vec0(
    section_id integer primary key, embedding float[{EMBED_DIM}]
);
CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(
    text, context_line, title, content='chunks', content_rowid='id'
);
"""


def connect() -> sqlite3.Connection:
    import sqlite_vec

    con = sqlite3.connect(str(vault_db_path()), timeout=30, check_same_thread=False)
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


def now() -> float:
    return time.time()


def watch_paths() -> list[str]:
    raw = (os.getenv("ZUMBA_VAULT_PATHS", "") or "").strip()
    if raw:
        return [p.strip() for p in raw.split(",") if p.strip()]
    return [str(default_watch_dir())]
