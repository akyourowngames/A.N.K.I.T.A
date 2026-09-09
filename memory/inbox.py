"""Write-ahead inbox: accepted chat text survives a killed background worker."""
import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from . import db


@contextmanager
def connect():
    con = sqlite3.connect(db.memory_home() / "memory-inbox.db", timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=FULL")
    con.execute("CREATE TABLE IF NOT EXISTS captures (id TEXT PRIMARY KEY,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',error TEXT NOT NULL DEFAULT '',created_at REAL NOT NULL)")
    try:
        yield con
        con.commit()
    finally:
        con.close()


def save(user_text, assistant_text, session_id, kind):
    payload = json.dumps([user_text, assistant_text, session_id, kind], ensure_ascii=False)
    capture_id = hashlib.sha256(payload.encode()).hexdigest()
    with connect() as con:
        con.execute("INSERT OR IGNORE INTO captures(id,payload,created_at) VALUES(?,?,?)", (capture_id, payload, time.time()))
    return capture_id


def pending():
    with connect() as con:
        return [(r["id"], *json.loads(r["payload"])) for r in con.execute("SELECT * FROM captures WHERE status='pending' ORDER BY created_at")]


def finish(capture_id, error=""):
    with connect() as con:
        con.execute("UPDATE captures SET status=?,error=? WHERE id=?", ("failed" if error else "complete", error[:500], capture_id))


def recent_context(limit=6, max_chars=2200):
    """Recent unprocessed user statements, never assistant-generated claims."""
    with connect() as con:
        rows = con.execute("SELECT payload,created_at FROM captures WHERE status IN ('pending','failed') ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    if not rows:
        return ""
    lines = ["Recent saved user statements, newest first (not yet distilled; newer statements may correct older ones):"]
    for row in rows:
        user_text = json.loads(row["payload"])[0]
        lines.append(f"[{time.strftime('%Y-%m-%d %H:%M', time.localtime(row['created_at']))}] {user_text[:600]}")
    return "\n".join(lines)[:max_chars]


def retry_failed():
    with connect() as con:
        return con.execute("UPDATE captures SET status='pending',error='' WHERE status='failed'").rowcount


def status():
    """Visible durable capture state; assistant-generated text is never presented as user memory."""
    with connect() as con:
        counts = {r["status"]: r["n"] for r in con.execute("SELECT status,COUNT(*) AS n FROM captures GROUP BY status")}
        recent = [{"id": r["id"], "user_text": json.loads(r["payload"])[0][:800],
                   "status": r["status"], "error": r["error"], "created_at": r["created_at"]}
                  for r in con.execute("SELECT * FROM captures ORDER BY created_at DESC LIMIT 6")]
    return {"counts": counts, "recent": recent}
