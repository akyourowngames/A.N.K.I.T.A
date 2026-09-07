import time
import core.store as store


_SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_cursors (
    channel TEXT PRIMARY KEY,
    next_offset INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS channel_seen (
    channel TEXT NOT NULL,
    update_id INTEGER NOT NULL,
    seen_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (channel, update_id)
);
CREATE TABLE IF NOT EXISTS channel_map (
    channel TEXT NOT NULL,
    external_chat_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    updated_at REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (channel, external_chat_id)
);
"""


def _ensure():
    con = store.connect()
    try:
        con.executescript(_SCHEMA)
        con.commit()
    finally:
        con.close()


def get_next_offset(channel: str) -> int:
    _ensure()
    con = store.connect()
    try:
        row = con.execute("SELECT next_offset FROM channel_cursors WHERE channel=?", (channel,)).fetchone()
        return int(row["next_offset"]) if row else 0
    finally:
        con.close()


def set_next_offset(channel: str, next_offset: int) -> None:
    _ensure()
    con = store.connect()
    try:
        con.execute(
            "INSERT INTO channel_cursors(channel, next_offset, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(channel) DO UPDATE SET next_offset=max(next_offset, excluded.next_offset), updated_at=excluded.updated_at",
            (channel, int(next_offset), time.time()),
        )
        con.commit()
    finally:
        con.close()


def claim_update(channel: str, update_id: int) -> bool:
    """Return True exactly once per (channel, update_id). Shared across
    processes via SQLite, so duplicate pollers can't double-handle."""
    if update_id <= 0:
        return True
    _ensure()
    con = store.connect()
    try:
        cur = con.execute(
            "INSERT OR IGNORE INTO channel_seen(channel, update_id, seen_at) VALUES(?, ?, ?)",
            (channel, int(update_id), time.time()),
        )
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def get_session_for_chat(channel: str, external_chat_id: str) -> str:
    _ensure()
    con = store.connect()
    try:
        row = con.execute(
            "SELECT session_id FROM channel_map WHERE channel=? AND external_chat_id=?",
            (channel, str(external_chat_id)),
        ).fetchone()
        return str(row["session_id"]) if row else ""
    finally:
        con.close()


def set_session_for_chat(channel: str, external_chat_id: str, session_id: str) -> None:
    _ensure()
    con = store.connect()
    try:
        con.execute(
            "INSERT INTO channel_map(channel, external_chat_id, session_id, updated_at) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(channel, external_chat_id) DO UPDATE SET session_id=excluded.session_id, updated_at=excluded.updated_at",
            (channel, str(external_chat_id), session_id, time.time()),
        )
        con.commit()
    finally:
        con.close()


def resolve_session(channel: str, external_chat_id: str, model: str = "", system: str = "") -> str:
    sid = get_session_for_chat(channel, external_chat_id)
    if sid and store.get_session(sid):
        return sid
    sid = f"tg-{external_chat_id}"
    if not store.get_session(sid):
        from core.config import get_default_model
        store.create_session(sid, model or get_default_model(), system or "")
    set_session_for_chat(channel, external_chat_id, sid)
    return sid
