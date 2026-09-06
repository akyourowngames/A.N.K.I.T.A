import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path


def zumba_home() -> Path:
    home = Path.home() / ".zumba"
    home.mkdir(parents=True, exist_ok=True)
    return home


def db_path() -> Path:
    return zumba_home() / "zumba.db"


_lock = threading.Lock()

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT 'Untitled',
    model TEXT NOT NULL DEFAULT '',
    system TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at DESC);
"""


def connect() -> sqlite3.Connection:
    path = db_path()
    con = sqlite3.connect(str(path), timeout=30)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL;")
        con.execute("PRAGMA foreign_keys=ON;")
    except Exception:
        pass
    with _lock:
        con.executescript(_SCHEMA)
    try:
        con.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content, content='messages', content_rowid='id')"
        )
        con.execute(
            "CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN "
            "INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content); END"
        )
        con.execute(
            "CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN "
            "INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content); END"
        )
    except Exception:
        pass
    return con


def config_get(key: str, default: str = "") -> str:
    con = connect()
    try:
        row = con.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return str(row["value"]) if row else default
    finally:
        con.close()


def config_set(key: str, value: str) -> None:
    con = connect()
    try:
        con.execute("INSERT INTO config(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        con.commit()
    finally:
        con.close()


def config_all() -> dict:
    con = connect()
    try:
        return {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM config")}
    finally:
        con.close()


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


def make_title(first_text: str) -> str:
    cleaned = " ".join((first_text or "").strip().split())
    if not cleaned:
        return "Untitled"
    return cleaned[:48]


def create_session(session_id: str, model: str, system: str, title: str = "Untitled") -> dict:
    now = time.time()
    con = connect()
    try:
        con.execute(
            "INSERT INTO sessions(id, title, model, system, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)",
            (session_id, title or "Untitled", model, system or "", now, now),
        )
        con.commit()
    finally:
        con.close()
    return get_session(session_id) or {}


def get_session(session_id: str) -> dict | None:
    con = connect()
    try:
        row = con.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        msgs = con.execute("SELECT role, content, created_at FROM messages WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
        data["messages"] = [dict(m) for m in msgs]
        return data
    finally:
        con.close()


def add_message(session_id: str, role: str, content: str, tokens: int = 0) -> None:
    now = time.time()
    con = connect()
    try:
        con.execute("INSERT INTO messages(session_id, role, content, created_at) VALUES(?, ?, ?, ?)", (session_id, role, content, now))
        count = con.execute("SELECT COUNT(*) AS n FROM messages WHERE session_id=?", (session_id,)).fetchone()["n"]
        row = con.execute("SELECT title FROM sessions WHERE id=?", (session_id,)).fetchone()
        if row and row["title"] in ("Untitled", "", None) and role == "user":
            con.execute("UPDATE sessions SET title=? WHERE id=?", (make_title(content), session_id))
        con.execute("UPDATE sessions SET updated_at=?, message_count=?, total_tokens=total_tokens+? WHERE id=?", (now, count, tokens, session_id))
        con.commit()
    finally:
        con.close()


def set_session_model(session_id: str, model: str) -> None:
    con = connect()
    try:
        con.execute("UPDATE sessions SET model=?, updated_at=? WHERE id=?", (model, time.time(), session_id))
        con.commit()
    finally:
        con.close()


def list_sessions(limit: int = 20, search: str = "") -> list[dict]:
    con = connect()
    try:
        if search:
            query = search.strip()
            try:
                rows = con.execute(
                    "SELECT s.* FROM sessions s JOIN messages m ON m.session_id=s.id "
                    "JOIN messages_fts f ON f.rowid=m.id WHERE messages_fts MATCH ? "
                    "GROUP BY s.id ORDER BY s.updated_at DESC LIMIT ?",
                    (query, limit),
                ).fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except Exception:
                pass
            like = f"%{query}%"
            rows = con.execute(
                "SELECT DISTINCT s.* FROM sessions s LEFT JOIN messages m ON m.session_id=s.id "
                "WHERE s.title LIKE ? OR m.content LIKE ? ORDER BY s.updated_at DESC LIMIT ?",
                (like, like, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        rows = con.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def delete_session(session_id: str) -> bool:
    con = connect()
    try:
        cur = con.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        con.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def last_session_id() -> str:
    return config_get("last_session", "")


def set_last_session(session_id: str) -> None:
    config_set("last_session", session_id)


def import_legacy_json(path: Path) -> str | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    msgs = data.get("messages", []) if isinstance(data, dict) else []
    if not msgs:
        return None
    sid = new_session_id()
    model = str(data.get("model", "") or "")
    system = str(data.get("system", "") or "")
    title = "Untitled"
    for m in msgs:
        if isinstance(m, dict) and m.get("role") == "user" and m.get("content"):
            title = make_title(str(m["content"]))
            break
    create_session(sid, model, system, title)
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role", "user"))
        if role == "system":
            continue
        add_message(sid, role, str(m.get("content", "")))
    return sid


def migrate_legacy_dir(directory: Path) -> int:
    if config_get("legacy_migrated", "") == "1":
        return 0
    count = 0
    try:
        files = sorted(Path(directory).glob("*.json")) if Path(directory).exists() else []
    except Exception:
        files = []
    for f in files:
        if f.name.startswith("."):
            continue
        try:
            if import_legacy_json(f):
                count += 1
        except Exception:
            continue
    config_set("legacy_migrated", "1")
    return count
