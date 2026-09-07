"""SQLite store for geo pings + visits (channel_store style)."""
from __future__ import annotations
import os
import time
import core.store as store

_SCHEMA = """
CREATE TABLE IF NOT EXISTS geo_pings (
    chat_id TEXT NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, accuracy REAL,
    source TEXT NOT NULL DEFAULT 'point',
    ts REAL NOT NULL,
    PRIMARY KEY (chat_id, ts)
);
CREATE TABLE IF NOT EXISTS geo_visits (
    chat_id TEXT NOT NULL, place_name TEXT NOT NULL, lat REAL, lon REAL,
    arrived_at REAL NOT NULL, departed_at REAL, note TEXT DEFAULT '',
    PRIMARY KEY (chat_id, arrived_at)
);
CREATE TABLE IF NOT EXISTS geo_tracks (
    chat_id TEXT PRIMARY KEY, until_ts REAL NOT NULL DEFAULT 0, started_at REAL NOT NULL DEFAULT 0
);
"""

def db_path_override() -> str:
    return (os.getenv("ZUMBA_GEO_DB") or "").strip()

def _connect():
    if db_path_override():
        import sqlite3
        con = sqlite3.connect(db_path_override(), timeout=30)
        con.row_factory = sqlite3.Row
        return con
    return store.connect()

def _ensure(con=None):
    own = con is None
    con = con or _connect()
    try:
        con.executescript(_SCHEMA)
        con.commit()
    finally:
        if own:
            try: con.close()
            except Exception: pass

def track_max_min() -> int:
    try: return max(5, int(os.getenv("ZUMBA_GEO_TRACK_MAX_MIN", "90") or 90))
    except Exception: return 90

def record_ping(chat_id: str, lat: float, lon: float, accuracy: float = 0.0,
                source: str = "point", ts: float = 0.0) -> float:
    _ensure()
    ts = float(ts or time.time())
    con = _connect()
    try:
        con.execute("INSERT OR REPLACE INTO geo_pings(chat_id,lat,lon,accuracy,source,ts) VALUES(?,?,?,?,?,?)",
                    (str(chat_id), float(lat), float(lon), float(accuracy or 0), source, ts))
        con.commit()
        return ts
    finally:
        try: con.close()
        except Exception: pass

def last_ping(chat_id: str, max_age_s: float = 0.0):
    _ensure()
    con = _connect()
    try:
        row = con.execute("SELECT lat,lon,accuracy,source,ts FROM geo_pings WHERE chat_id=? ORDER BY ts DESC LIMIT 1",
                          (str(chat_id),)).fetchone()
        if not row: return None
        d = dict(row)
        if max_age_s and (time.time() - float(d["ts"])) > max_age_s: return None
        return d
    finally:
        try: con.close()
        except Exception: pass

def track_start(chat_id: str, minutes: float) -> float:
    minutes = max(1, min(float(minutes or 15), track_max_min()))
    until = time.time() + minutes * 60
    _ensure()
    con = _connect()
    try:
        con.execute("INSERT INTO geo_tracks(chat_id,until_ts,started_at) VALUES(?,?,?) "
                    "ON CONFLICT(chat_id) DO UPDATE SET until_ts=excluded.until_ts, started_at=excluded.started_at",
                    (str(chat_id), until, time.time()))
        con.commit()
        return until
    finally:
        try: con.close()
        except Exception: pass

def track_stop(chat_id: str) -> None:
    _ensure()
    con = _connect()
    try:
        con.execute("UPDATE geo_tracks SET until_ts=0 WHERE chat_id=?", (str(chat_id),))
        con.commit()
    finally:
        try: con.close()
        except Exception: pass

def track_active(chat_id: str) -> bool:
    _ensure()
    con = _connect()
    try:
        row = con.execute("SELECT until_ts FROM geo_tracks WHERE chat_id=?", (str(chat_id),)).fetchone()
        return bool(row and float(row["until_ts"]) > time.time())
    finally:
        try: con.close()
        except Exception: pass

def log_visit(chat_id: str, place_name: str, lat: float = 0.0, lon: float = 0.0,
              arrived_at: float = 0.0, departed_at: float = 0.0, note: str = "") -> float:
    _ensure()
    arrived_at = float(arrived_at or time.time())
    con = _connect()
    try:
        con.execute("INSERT OR REPLACE INTO geo_visits(chat_id,place_name,lat,lon,arrived_at,departed_at,note) VALUES(?,?,?,?,?,?,?)",
                    (str(chat_id), place_name, float(lat or 0), float(lon or 0), arrived_at,
                     float(departed_at or 0) or None, note or ""))
        con.commit()
        return arrived_at
    finally:
        try: con.close()
        except Exception: pass

def query_visits(chat_id: str, since: float = 0.0, limit: int = 20):
    _ensure()
    con = _connect()
    try:
        rows = con.execute("SELECT place_name,lat,lon,arrived_at,departed_at,note FROM geo_visits "
                           "WHERE chat_id=? AND arrived_at>=? ORDER BY arrived_at DESC LIMIT ?",
                           (str(chat_id), float(since or 0), max(1, int(limit or 20)))).fetchall()
        return [dict(r) for r in rows]
    finally:
        try: con.close()
        except Exception: pass

def purge(chat_id: str) -> int:
    _ensure()
    con = _connect()
    try:
        n = 0
        for t in ("geo_pings", "geo_visits"):
            cur = con.execute(f"DELETE FROM {t} WHERE chat_id=?", (str(chat_id),))
            n += cur.rowcount or 0
        con.execute("DELETE FROM geo_tracks WHERE chat_id=?", (str(chat_id),))
        con.commit()
        return n
    finally:
        try: con.close()
        except Exception: pass
