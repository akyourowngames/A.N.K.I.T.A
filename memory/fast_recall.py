"""Keep interactive recall bounded while preserving durable raw user evidence."""
from collections import OrderedDict
import threading
import sqlite3
from . import db, inbox

_cache = OrderedDict()
_lock = threading.Lock()
_active = None


def local_context(query):
    """Cold-start fallback: core blocks and lexical retrieval, no model call."""
    from .retrieval import _fts_query
    path = db.memory_db_path()
    if not path.exists():
        return ""
    con = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.05)
    try:
        sections = []
        try:
            for key, content in con.execute("SELECT key,content FROM core_blocks ORDER BY key"):
                sections.append(f"Saved core memory ({key}): {content[:1000]}")
        except sqlite3.Error:
            pass
        terms = _fts_query(query)
        if terms:
            try:
                rows = con.execute(
                    "SELECT e.id,e.user_text,e.created_at FROM fts_episodes f JOIN episodes e ON e.id=f.rowid "
                    "WHERE fts_episodes MATCH ? ORDER BY bm25(fts_episodes) LIMIT 4", (terms,)).fetchall()
                for ident, text, timestamp in rows:
                    sections.append(f"Original user message [episode {ident}, timestamp {timestamp}]: {text[:650]}")
            except sqlite3.Error:
                pass
        return "\n".join(sections)[:3800]
    finally:
        con.close()


def revision():
    path = db.memory_db_path()
    result = []
    for p in (path, path.with_name(path.name + "-wal")):
        try:
            stat = p.stat(); result.append((stat.st_mtime_ns, stat.st_size))
        except OSError:
            result.append(None)
    return tuple(result)


def recall(query, budget=.35):
    from identity.userprofile import profile_block
    from memory import get_memory
    baseline = "\n".join(filter(None, [profile_block(), local_context(query), inbox.recent_context()]))
    key = (query, revision())
    global _active
    with _lock:
        if key in _cache:
            return (_cache[key] + "\n" + baseline).strip()
        if _active is None or _active[1].is_set():
            finished = threading.Event()
            _active = (key, finished)
            def run():
                try:
                    text = get_memory().recall(query, top_k=6, max_bytes=3500) or ""
                    with _lock:
                        _cache[key] = text
                        while len(_cache) > 32:
                            _cache.popitem(last=False)
                except Exception:
                    pass
                finally:
                    finished.set()
            threading.Thread(target=run, daemon=True, name="zumba-recall").start()
        wait_for = _active[1] if _active[0] == key else None
    if wait_for:
        wait_for.wait(budget)
    with _lock:
        return (_cache.get(key, "") + "\n" + baseline).strip()
