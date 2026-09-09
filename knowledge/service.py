"""Restart-safe ingestion, entity resolution, graph snapshots and source sync."""
import difflib
import hashlib
import json
import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading
import time
import unicodedata
import uuid

from memory import embedder
from . import extraction, parsers, storage, reasoning as llm

log = logging.getLogger(__name__)


def uid():
    return uuid.uuid4().hex


def normalized(name):
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def enqueue(name: str, kind: str, content: bytes, source_key: str = "upload"):
    digest = hashlib.sha256(content).hexdigest()
    with storage.connect() as con:
        row = con.execute("SELECT id FROM documents WHERE source_key=? AND hash=?", (source_key, digest)).fetchone()
        if row:
            return row["id"]
        doc_id = uid()
        con.execute("INSERT INTO documents VALUES(?,?,?,?,?,?,?)", (doc_id, name, kind, source_key, digest, content, time.time()))
        con.execute("INSERT INTO jobs(id,updated_at) VALUES(?,?)", (doc_id, time.time()))
        return doc_id


def stage(doc_id, label, **values):
    allowed = {"status", "completed", "total", "error", "warning"}
    assert set(values) <= allowed
    with storage.connect() as con:
        fields = ["stage=?", "updated_at=?", "lease_until=?"] + [f"{k}=?" for k in values]
        con.execute(f"UPDATE jobs SET {','.join(fields)} WHERE id=?", (label, time.time(), time.time() + 600, *values.values(), doc_id))


def resolve(con, entity, vector, chunk_id, context):
    name = entity["name"].strip()
    rows = [dict(r) for r in con.execute("SELECT * FROM entities")]
    def rank(row):
        aliases = [row["name"], *json.loads(row["aliases"])]
        lexical = max(difflib.SequenceMatcher(None, normalized(name), normalized(a)).ratio() for a in aliases)
        other = json.loads(row["embedding"] or "[]")
        semantic = 0
        if vector and len(vector) == len(other):
            denom = math.sqrt(sum(v*v for v in vector) * sum(v*v for v in other))
            semantic = sum(a*b for a, b in zip(vector, other)) / denom if denom else 0
        return max(lexical, semantic)
    candidates = sorted(rows, key=rank, reverse=True)[:8]
    match, reason = None, "No existing identity was confirmed"
    if candidates:
        payload = []
        for row in candidates:
            neighbors = [dict(r) for r in con.execute(
                "SELECT r.type,e.name FROM relations r JOIN entities e ON e.id=r.target WHERE r.source=? LIMIT 8", (row["id"],))]
            payload.append({k: row[k] for k in ("id", "name", "type", "description", "aliases")} | {"relationships": neighbors})
        decision = llm.chat_json(
            'Resolve entity identity. Return {"id": candidate id or null,"reason":"explanation"}. '
            'Identical names can denote different people. Use context, types, aliases and existing relations. '
            'Merge only when supported; semantic similarity alone is not identity.\n' + json.dumps(
                {"new": entity, "context": context, "candidates": payload}, ensure_ascii=False),
            system=extraction.SYSTEM, max_tokens=1200)
        if not isinstance(decision, dict):
            raise ValueError("Entity resolution returned invalid JSON")
        match = next((r for r in candidates if r["id"] == decision.get("id")), None)
        reason = str(decision.get("reason") or reason)
    now = time.time()
    aliases = [a for a in entity.get("aliases", []) if isinstance(a, str)] if isinstance(entity.get("aliases"), list) else []
    if match:
        entity_id = match["id"]
        aliases = sorted(set(aliases + json.loads(match["aliases"]) + [name]))
        con.execute("UPDATE entities SET aliases=?,updated_at=? WHERE id=?", (json.dumps(aliases), now, entity_id))
    else:
        entity_id = uid()
        con.execute("INSERT INTO entities VALUES(?,?,?,?,?,?,?,?,?,?)", (
            entity_id, name, normalized(name), str(entity.get("type") or "Concept"),
            str(entity.get("description") or ""), json.dumps(aliases), extraction.score(entity.get("confidence")),
            now, now, json.dumps(vector) if vector else None))
    con.execute("INSERT INTO resolution_audit(entity_id,mention,decision,reason,chunk_id,created_at) VALUES(?,?,?,?,?,?)",
                (entity_id, name, "merged" if match else "created", reason, chunk_id, now))
    con.execute("INSERT OR IGNORE INTO mentions VALUES(?,?,?)", (entity_id, chunk_id, entity["evidence"]))
    return entity_id


def _parallelism():
    try:
        return max(1, int(os.getenv("ZUMBA_KNOWLEDGE_PARALLELISM", "3") or 1))
    except ValueError:
        return 1


def _process_chunk(doc, c):
    """Run the slow, independent part of a chunk (LLM extraction + embeddings)
    without touching the database, so chunks can run concurrently."""
    llm.reset_trace()
    entities, relations, rejected = extraction.extract_graph(c["text"], doc["kind"])
    warning = f"{rejected} unsupported assertions rejected in this chunk. " if rejected else ""
    vectors, chunk_vector = [[] for _ in entities], []
    try:
        batch = embedder.embed_texts([c["text"], *[e["name"] + ": " + str(e.get("description", "")) for e in entities]])
        batch = [[float(v) for v in vector] for vector in batch]
        if len(batch) != len(entities) + 1 or any(not v or not all(math.isfinite(x) for x in v) for v in batch):
            raise ValueError("Invalid embedding result")
        chunk_vector, vectors = batch[0], batch[1:]
    except Exception:
        warning += "Embeddings unavailable; text search remains available."
    return {"chunk": c, "entities": entities, "relations": relations, "vectors": vectors,
            "chunk_vector": chunk_vector, "warning": warning.strip(), "trace": llm.trace()}


def _commit_chunk(payload):
    """Serialize all database work and LLM-backed identity resolution."""
    c, entities, relations, vectors = payload["chunk"], payload["entities"], payload["relations"], payload["vectors"]
    with storage.connect() as con:
        mapped = {e["name"]: resolve(con, e, v, c["id"], c["text"]) for e, v in zip(entities, vectors)}
        method = f"{', '.join(payload['trace']) or llm._memory_model()} / extraction + independent entailment / v1"
        for r in relations:
            source, target, typ = mapped[r["source"]], mapped[r["target"]], r["type"].strip()
            edge_id = hashlib.sha256(f"{source}\0{target}\0{typ}".encode()).hexdigest()[:32]
            con.execute("INSERT OR IGNORE INTO relations VALUES(?,?,?,?)", (edge_id, source, target, typ))
            con.execute("INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?,?,?)", (
                uid(), edge_id, c["id"], r["evidence"], extraction.score(r["confidence"]), method, time.time()))
        con.execute("UPDATE chunks SET done=1,embedding=? WHERE id=?", (json.dumps(payload["chunk_vector"]) if payload["chunk_vector"] else None, c["id"]))


def ingest(doc_id):
    try:
        with storage.connect() as con:
            doc = dict(con.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone())
            has_chunks = con.execute("SELECT COUNT(*) FROM chunks WHERE document_id=?", (doc_id,)).fetchone()[0]
        if not has_chunks:
            stage(doc_id, "Extracting text", status="processing", error="")
            sections = parsers.extract(doc["content"], doc["kind"])
            stage(doc_id, "Chunking sections")
            chunks = list(parsers.chunk(sections))
            with storage.connect() as con:
                for item in chunks:
                    chunk_id = uid()
                    con.execute("INSERT INTO chunks(id,document_id,page,section,text) VALUES(?,?,?,?,?)",
                                (chunk_id, doc_id, item.page, item.section, item.text))
                    con.execute("INSERT INTO chunks_fts VALUES(?,?)", (chunk_id, item.text))
        with storage.connect() as con:
            chunks = [dict(r) for r in con.execute("SELECT * FROM chunks WHERE document_id=?", (doc_id,))]
        done = sum(c["done"] for c in chunks)
        todo = [c for c in chunks if not c["done"]]
        stage(doc_id, "Extracting entities and relationships", status="processing", completed=done, total=len(chunks))
        workers = _parallelism()
        if workers > 1 and len(todo) > 1:
            # Extraction and embedding are independent per chunk and network-bound;
            # database commits and identity resolution stay serialized afterwards.
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for payload in pool.map(lambda c: _process_chunk(doc, c), todo):
                    stage(doc_id, "Resolving duplicate entities", warning=payload["warning"])
                    _commit_chunk(payload)
                    done += 1
                    stage(doc_id, "Updating graph", completed=done)
        else:
            for c in todo:
                payload = _process_chunk(doc, c)
                stage(doc_id, "Resolving duplicate entities", warning=payload["warning"])
                _commit_chunk(payload)
                done += 1
                stage(doc_id, "Updating graph", completed=done)
        stage(doc_id, "Complete", status="complete", completed=len(chunks))
    except Exception as exc:
        log.exception("Knowledge ingestion failed for %s", doc_id)
        stage(doc_id, "Needs attention", status="failed", error=str(exc)[:500])


def snapshot():
    with storage.connect() as con:
        docs = [dict(r) for r in con.execute(
            "SELECT d.id,d.name,d.kind,d.source_key,d.created_at,length(d.content) AS bytes,j.* FROM documents d JOIN jobs j ON j.id=d.id ORDER BY d.created_at DESC")]
        nodes = []
        for row in con.execute("SELECT * FROM entities WHERE id IN (SELECT entity_id FROM mentions)"):
            e = dict(row)
            refs = [dict(r) for r in con.execute(
                "SELECT m.chunk_id,m.quote,c.document_id,c.page,c.section,d.name AS document FROM mentions m "
                "JOIN chunks c ON c.id=m.chunk_id JOIN documents d ON d.id=c.document_id WHERE m.entity_id=?", (e["id"],))]
            e.update(aliases=json.loads(e["aliases"]), sourceDocuments=list({r["document_id"] for r in refs}),
                     sourceChunks=[r["chunk_id"] for r in refs], evidence=refs, hasEmbedding=bool(e.pop("embedding")))
            nodes.append(e)
        edges = []
        for row in con.execute("SELECT * FROM relations"):
            evidence = [dict(r) for r in con.execute(
                "SELECT e.*,c.document_id,c.page,c.section,d.name AS document FROM evidence e "
                "JOIN chunks c ON c.id=e.chunk_id JOIN documents d ON d.id=c.document_id WHERE e.relation_id=?", (row["id"],))]
            if evidence:
                edges.append(dict(row) | {"evidence": evidence, "confidence": max(e["confidence"] for e in evidence),
                                           "sourceCount": len({e["document_id"] for e in evidence})})
        audit = [dict(r) for r in con.execute("SELECT * FROM resolution_audit ORDER BY id DESC LIMIT 100")]
        state = {r["key"]: r["value"] for r in con.execute("SELECT * FROM sync_state")}
        profile = con.execute("SELECT content FROM documents WHERE kind='profile' ORDER BY created_at DESC LIMIT 1").fetchone()
        counts = {"chunks": con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0],
                  "embedded": con.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL").fetchone()[0]}
    data = {"nodes": nodes, "edges": edges, "documents": docs, "audit": audit, "sync": state,
            "profile": bytes(profile[0]).decode("utf-8") if profile else "", "counts": counts}
    data["revision"] = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]
    return data


def sync_sources():
    """Read Zumba's source databases without loading extensions or altering memory."""
    root = Path(os.getenv("ZUMBA_MEMORY_HOME", str(Path.home() / ".zumba")))
    profile = root / "user.md"
    if profile.is_file():
        enqueue("user.md", "profile", profile.read_bytes(), "profile:user.md")
    path = root / "memory.db"
    if path.is_file():
        with storage.connect() as con:
            row = con.execute("SELECT value FROM sync_state WHERE key='episode_cursor'").fetchone()
            cursor = int(row[0]) if row else 0
        source = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=5)
        source.row_factory = sqlite3.Row
        try:
            rows = source.execute("SELECT id,user_text,session_id FROM episodes WHERE id>? ORDER BY id LIMIT 100", (cursor,)).fetchall()
        finally:
            source.close()
        for row in rows:
            if row["user_text"].strip():
                enqueue(f"Conversation {row['id']}", "memory", row["user_text"].encode(), f"episode:{row['id']}")
            cursor = row["id"]
        with storage.connect() as con:
            con.execute("INSERT OR REPLACE INTO sync_state VALUES('episode_cursor',?)", (str(cursor),))
    with storage.connect() as con:
        con.execute("INSERT OR REPLACE INTO sync_state VALUES('memory_available',?)", (str(path.is_file()).lower(),))
        con.execute("INSERT OR REPLACE INTO sync_state VALUES('error','')")


_stop = threading.Event()
_threads = []


def start():
    if any(t.is_alive() for t in _threads):
        return
    _stop.clear()
    def watch():
        while not _stop.is_set():
            try:
                sync_sources()
            except Exception as exc:
                log.exception("Memory sync failed")
                with storage.connect() as con:
                    con.execute("INSERT OR REPLACE INTO sync_state VALUES('error',?)", (str(exc)[:400],))
            _stop.wait(5)
    def work():
        while not _stop.is_set():
            try:
                with storage.connect() as con:
                    con.execute("BEGIN IMMEDIATE")
                    row = con.execute("SELECT id FROM jobs WHERE status='queued' OR (status='processing' AND lease_until<?) ORDER BY updated_at LIMIT 1", (time.time(),)).fetchone()
                    if row:
                        con.execute("UPDATE jobs SET status='processing',lease_until=? WHERE id=?", (time.time() + 600, row[0]))
                if row:
                    ingest(row[0])
                else:
                    _stop.wait(1)
            except Exception:
                log.exception("Knowledge worker error")
                _stop.wait(5)
    for fn in (watch, work):
        t = threading.Thread(target=fn, name="zumba-knowledge-" + fn.__name__, daemon=True)
        _threads.append(t)
        t.start()


def stop():
    _stop.set()
    for t in _threads:
        t.join(timeout=1)
