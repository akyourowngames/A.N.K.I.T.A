"""No write transaction may span a network (LLM) call.

Before the fix, `ingest_episode` and knowledge `_commit_chunk` held an open
write transaction while waiting on the LLM, so every concurrent writer got
`sqlite3.OperationalError: database is locked`. These tests pin the fixed
discipline: while one thread sits inside a (mocked, slow) LLM call, another
thread must still be able to write quickly.
"""

import sqlite3
import threading
import time


def _fast_writer(connect, sql, params=(), timeout_ms=200):
    """Concurrent writer with a tiny busy timeout. Accepts a plain connection
    factory (memory db.connect) or a context manager (knowledge storage)."""
    cm = connect()
    if hasattr(cm, "__enter__"):
        with cm as con:
            con.execute(f"PRAGMA busy_timeout={timeout_ms}")
            t = time.monotonic()
            con.execute(sql, params)
            return time.monotonic() - t
    con = cm
    try:
        con.execute(f"PRAGMA busy_timeout={timeout_ms}")
        t = time.monotonic()
        con.execute(sql, params)
        con.commit()
        return time.monotonic() - t
    finally:
        con.close()


def test_memory_ingest_holds_no_lock_during_llm(tmp_path, monkeypatch):
    from memory import db
    from memory import extraction
    from memory import resolve as resolve_mod
    from memory.service import Memory

    home = tmp_path / "memhome"
    home.mkdir()
    monkeypatch.setattr(db, "memory_home", lambda: home)
    monkeypatch.setattr(db, "memory_db_path", lambda: home / "memory.db")

    def slow_resolve(con, name):
        time.sleep(1.5)  # stands in for the LLM merge-decision call
        return None

    monkeypatch.setattr(resolve_mod, "resolve_entity", slow_resolve)
    monkeypatch.setattr(
        extraction, "should_remember", lambda u, a: True)
    monkeypatch.setattr(
        extraction, "extract_graph",
        lambda u, a, known=None: (
            [{"name": "Slow Entity", "type": "concept", "description": "d"}],
            [{"source": "Slow Entity", "target": "Slow Entity", "type": "is",
              "fact": "Slow Entity is slow", "confidence": 0.9}]))
    monkeypatch.setattr(
        extraction, "decide_writes",
        lambda facts, existing: [{"index": i, "op": "ADD", "target_id": None,
                                  "reason": "t"} for i in range(len(facts))])

    mem = Memory()
    errors = []

    def ingest():
        try:
            mem.ingest_episode("slow test episode", "noted", session_id="s-lock")
        except Exception as exc:  # noqa: BLE001 — collected, asserted below
            errors.append(exc)

    t = threading.Thread(target=ingest, daemon=True)
    t.start()
    time.sleep(0.4)  # let ingestion reach the slow resolve call
    # A concurrent writer must NOT hit "database is locked".
    dt = _fast_writer(
        db.connect,
        "INSERT INTO episodes(session_id, kind, user_text, assistant_text, context, hash, created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        ("s2", "chat", "concurrent", "ok", "", "concurrent-hash", db.now()))
    t.join(timeout=30)
    mem.close()
    assert not errors
    assert dt < 5.0


def test_knowledge_commit_holds_no_lock_during_resolve(tmp_path, monkeypatch):
    import time as _time

    from knowledge import service, storage

    home = tmp_path / "khome"
    monkeypatch.setenv("ZUMBA_KNOWLEDGE_HOME", str(home))

    with storage.connect() as con:
        con.execute(
            "INSERT INTO entities VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("seed", "Seed", "seed", "Concept", "d", "[]", 0.9,
             _time.time(), _time.time(), None))
        con.execute(
            "INSERT INTO documents VALUES(?,?,?,?,?,?,?)",
            ("d1", "Doc", "note", "test", "h", b"x", _time.time()))
        con.execute("INSERT INTO jobs(id,updated_at) VALUES(?,?)",
                    ("d1", _time.time()))
        con.execute(
            "INSERT INTO chunks(id,document_id,page,section,text) VALUES(?,?,?,?,?)",
            ("c1", "d1", None, "S", "Seed is a concept"))

    def slow_chat_json(prompt, **kw):
        time.sleep(1.5)  # stands in for the LLM identity decision
        return {"id": None, "reason": "test"}

    monkeypatch.setattr(service.llm, "chat_json", slow_chat_json)
    payload = {
        "chunk": {"id": "c1", "text": "Seed is a concept"},
        "entities": [{"name": "Seedling", "type": "Concept", "aliases": [],
                      "description": "d", "evidence": "Seedling", "confidence": 0.9}],
        "relations": [],
        "vectors": [[]],
        "chunk_vector": [],
        "trace": [],
    }
    errors = []

    def commit():
        try:
            service._commit_chunk(payload)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    t = threading.Thread(target=commit, daemon=True)
    t.start()
    time.sleep(0.4)
    dt = _fast_writer(
        storage.connect,
        "INSERT OR REPLACE INTO sync_state VALUES(?,?)", ("probe", "1"))
    t.join(timeout=30)
    assert not errors
    assert dt < 5.0


def test_execute_retry_recovers_from_locked():
    from knowledge import storage

    attempts = []

    class _FakeCon:
        def execute(self, sql, params=()):
            attempts.append(1)
            if len(attempts) < 3:
                raise sqlite3.OperationalError("database is locked")
            return "ok"

    assert storage.execute_retry(_FakeCon(), "INSERT INTO t VALUES(?)", (1,)) == "ok"
    assert len(attempts) == 3


def test_execute_retry_reraises_other_errors():
    from knowledge import storage

    class _FakeCon:
        def execute(self, sql, params=()):
            raise sqlite3.OperationalError("no such table: t")

    try:
        storage.execute_retry(_FakeCon(), "SELECT 1", ())
    except sqlite3.OperationalError as exc:
        assert "no such table" in str(exc)
        return
    raise AssertionError("should have raised")


def test_memory_plan_apply_dedupes_batch(tmp_path, monkeypatch):
    from memory import db
    from memory.service import Memory

    home = tmp_path / "memhome"
    home.mkdir()
    monkeypatch.setattr(db, "memory_home", lambda: home)
    monkeypatch.setattr(db, "memory_db_path", lambda: home / "memory.db")

    mem = Memory()
    con = db.connect()
    try:
        planned = mem._plan_entities(
            con, [{"name": "Atlas App", "type": "project", "description": "d1"},
                  {"name": "Atlas App", "type": "project", "description": "d2"}])
        # Planning performs no writes.
        assert con.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 0
        mapped = mem._apply_entities(con, planned, episode_id=1)
        con.commit()
        assert mapped["Atlas App"] is not None
        assert con.execute("SELECT COUNT(*) FROM entities").fetchone()[0] == 1
    finally:
        con.close()
        mem.close()


def test_knowledge_resolve_plan_is_read_only(tmp_path, monkeypatch):
    from knowledge import service, storage

    home = tmp_path / "khome"
    monkeypatch.setenv("ZUMBA_KNOWLEDGE_HOME", str(home))
    monkeypatch.setattr(service.llm, "chat_json",
                        lambda *a, **k: {"id": None, "reason": "new"})
    with storage.connect() as con:
        before = (con.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                  con.execute("SELECT COUNT(*) FROM resolution_audit").fetchone()[0],
                  con.execute("SELECT COUNT(*) FROM mentions").fetchone()[0])
        plan = service.resolve_plan(
            con, {"name": "Brand New", "type": "Concept", "aliases": [],
                  "description": "d", "evidence": "Brand New", "confidence": 0.9},
            [], "ctx")
        after = (con.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                 con.execute("SELECT COUNT(*) FROM resolution_audit").fetchone()[0],
                 con.execute("SELECT COUNT(*) FROM mentions").fetchone()[0])
    assert plan["match_id"] is None
    assert before == after


def test_sync_sources_skips_unchanged_writes(tmp_path, monkeypatch):
    import sqlite3 as _sqlite

    from knowledge import service, storage

    khome = tmp_path / "khome"
    memhome = tmp_path / "memhome"
    memhome.mkdir()
    monkeypatch.setenv("ZUMBA_KNOWLEDGE_HOME", str(khome))
    monkeypatch.setenv("ZUMBA_MEMORY_HOME", str(memhome))
    (memhome / "user.md").write_text("# User\n", encoding="utf-8")
    mdb = _sqlite.connect(str(memhome / "memory.db"))
    mdb.execute("CREATE TABLE episodes(id INTEGER PRIMARY KEY, user_text TEXT, session_id TEXT)")
    mdb.execute("INSERT INTO episodes VALUES(1, 'hello world', 's')")
    mdb.commit()
    mdb.close()

    service.sync_sources()
    writes = []
    orig = storage.execute_retry

    def counting(con, sql, params=(), retries=8):
        if "INSERT OR REPLACE INTO sync_state" in sql:
            writes.append(params)
        return orig(con, sql, params, retries)

    monkeypatch.setattr(storage, "execute_retry", counting)
    service.sync_sources()
    assert writes == []
