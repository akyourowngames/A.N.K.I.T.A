"""Memory service: the public orchestration layer.

Write path:  ingest_episode -> salience -> extraction -> entity resolution ->
             write decisions -> graph/note/index commits.
Read path:   recall -> hybrid retrieval -> formatted context block.
Maintenance: consolidate (communities, note links, core blocks, decay).
"""

from __future__ import annotations

import json
import queue
import threading
import time

from . import consolidation, db, embedder, extraction, graph, llm, resolve, retrieval

_cache = {}
_cache_lock = threading.Lock()


_CORRECTION_CUES = (" not ", " isnt", " isn't", "actually", "wrong", "correction", " no ", "instead", "rather ", "i meant", "correction:")


def _looks_like_correction(user_text: str, assistant_text: str = "") -> bool:
    t = f" {(user_text or '').lower()} {(assistant_text or '').lower()} "
    return any(c in t for c in _CORRECTION_CUES)


_FACT_CUES = ("my name is", "i am ", "i'm ", "i've ", "i'll ", "my project", "my favorite", "my favourite",
              "i build", "i prefer", "i use ", "i like ", "i live", "i work", "remember that", "remember this",
              "don't forget", "do not forget", "dont forget")


def _looks_like_fact(user_text: str, assistant_text: str = "") -> bool:
    t = f" {(user_text or '').lower()} {(assistant_text or '').lower()} "
    return any(c in t for c in _FACT_CUES)


_FIRST_PERSON = (" i ", " my ", " me ", " i'm ", " i've ", " i'll ", " mine ")


def prefilter_may_be_memorable(user_text: str, assistant_text: str = "") -> bool:
    """0-cost generic prefilter before the LLM salience gate.

    Returns True when the exchange *might* carry a durable fact (correction
    cue, first-person fact cue, or first-person pronoun present). Returns
    False only when nothing fires — callers skip extraction entirely then.
    Generic by design: no personal names, no per-user strings.
    """
    t = f" {(user_text or '').lower()} {(assistant_text or '').lower()} "
    if any(c in t for c in _CORRECTION_CUES):
        return True
    if any(c in t for c in _FACT_CUES):
        return True
    return any(p in t for p in _FIRST_PERSON)


class Memory:
    def __init__(self, con=None):
        self._own = con is None
        self._con = con
        self.consolidated_at = time.time()
        self._q: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._worker_lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()

    # ---- background capture (serialized single worker) ----
    def capture_async(self, user_text, assistant_text, session_id="", kind="chat") -> None:
        """Queue an exchange for background ingestion. Serialized on one worker
        thread so captures survive quick exits and never race each other."""
        self._idle.clear()
        self._q.put((user_text, assistant_text, session_id, kind))
        self._ensure_worker()

    def _ensure_worker(self):
        with self._worker_lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="zumba-memory")
                self._worker.start()

    def _worker_loop(self):
        while True:
            try:
                user_text, assistant_text, session_id, kind = self._q.get(timeout=30)
            except queue.Empty:
                self._idle.set()
                return
            try:
                self.ingest_episode(user_text, assistant_text, session_id=session_id, kind=kind)
                self.consolidate(min_interval_s=1800.0)
            except Exception:
                pass
            finally:
                self._q.task_done()
                if self._q.unfinished_tasks == 0:
                    self._idle.set()

    def flush(self, timeout: float = 30.0) -> bool:
        """Wait for queued captures to finish (called on chat exit)."""
        try:
            self._q.join()
        except Exception:
            pass
        return self._idle.wait(timeout)

    def _open(self):
        return self._con if self._con is not None else db.connect()

    def close(self):
        if self._own and self._con is not None:
            try:
                self._con.close()
            except Exception:
                pass
            self._con = None

    def stats(self) -> dict:
        con = self._open()
        try:
            def c(sql):
                return con.execute(sql).fetchone()[0]

            return {
                "episodes": c("SELECT COUNT(*) FROM episodes"),
                "entities": c("SELECT COUNT(*) FROM entities"),
                "relations": c("SELECT COUNT(*) FROM relations"),
                "active_relations": c("SELECT COUNT(*) FROM relations WHERE invalid_at IS NULL"),
                "notes": c("SELECT COUNT(*) FROM notes"),
                "communities": c("SELECT COUNT(*) FROM communities"),
                "core_blocks": c("SELECT COUNT(*) FROM core_blocks"),
                "database": str(db.memory_db_path()),
            }
        finally:
            if self._own:
                con.close()
# ---- ingestion ----
    def ingest_episode(self, user_text, assistant_text, session_id="", kind="chat") -> dict:
        """Capture an exchange into memory. Returns a small status dict."""
        con = self._open()
        try:
            h = extraction.content_hash(user_text, assistant_text)
            exists = con.execute("SELECT id FROM episodes WHERE hash=?", (h,)).fetchone()
            if exists:
                return {"stored": False, "reason": "duplicate"}
            cur = con.execute(
                "INSERT INTO episodes(session_id, kind, user_text, assistant_text, context, hash, created_at) VALUES(?,?,?,?,?,?,?)",
                (session_id, kind, user_text, assistant_text, "", h, db.now()),
            )
            episode_id = cur.lastrowid
            self._index_episode(con, episode_id, user_text, assistant_text)

            if kind == "tool":
                return {"stored": True, "extracted": False, "episode": episode_id, "reason": "tool-turn"}
            if not prefilter_may_be_memorable(user_text, assistant_text):
                return {"stored": True, "extracted": False, "episode": episode_id, "reason": "prefilter"}
            memorable = extraction.should_remember(user_text, assistant_text)
            if not memorable:
                return {"stored": True, "extracted": False, "episode": episode_id}

            try:
                known = [r["canonical_name"] for r in con.execute("SELECT canonical_name FROM entities LIMIT 40").fetchall()]
            except Exception:
                known = []
            ents, rels = extraction.extract_graph(user_text, assistant_text, known=known)
            if not ents and not rels:
                ents, rels = extraction.extract_graph(user_text, assistant_text, known=known)
            if not ents and not rels:
                return {"stored": True, "extracted": False, "episode": episode_id}

            ent_id_of = self._reconcile_entities(con, ents, episode_id)
            n_relations = self._reconcile_relations(con, rels, ent_id_of, episode_id)
            note_id = self._make_note(con, user_text, assistant_text, ents)
            if note_id:
                consolidation.link_notes(con, note_id)
            return {"stored": True, "extracted": True, "entities": len(ent_id_of), "relations": n_relations, "note": note_id, "episode": episode_id}
        finally:
            if self._own:
                con.commit()
                con.close()

    def _index_episode(self, con, episode_id, user_text, assistant_text) -> None:
        try:
            vec = embedder.embed_text(f"{user_text}\n{assistant_text}")
            if vec:
                try:
                    con.execute(
                        "INSERT OR REPLACE INTO vec_episodes(episode_id, embedding) VALUES(?, ?)",
                        (episode_id, db.pack_vec(vec)),
                    )
                except Exception:
                    pass
            con.execute(
                "INSERT OR REPLACE INTO fts_episodes(rowid, user_text, assistant_text) VALUES(?,?,?)",
                (episode_id, user_text, assistant_text),
            )
        except Exception:
            pass
    def _reconcile_entities(self, con, ents, episode_id) -> dict:
        ent_id_of = {}
        for e in ents:
            name = (e.get("name") or "").strip()
            if not name:
                continue
            etype = (e.get("type") or "").strip() or "unknown"
            desc = (e.get("description") or "").strip()
            eid = resolve.resolve_entity(con, name)
            now = db.now()
            if eid is None:
                c = con.execute(
                    "INSERT INTO entities(name, canonical_name, type, description, confidence, importance, created_at, updated_at, access_count, last_access, decay) VALUES(?,?,?,?,?,?,?,?,0,0,1.0)",
                    (name, name, etype, desc, 0.7, 0.6, now, now),
                )
                eid = c.lastrowid
                con.execute("INSERT OR IGNORE INTO aliases(alias, entity_id) VALUES(?,?)", (name, eid))
                vec = embedder.embed_text(f"{name} {desc}" if desc else name)
                if vec:
                    try:
                        con.execute("INSERT OR IGNORE INTO vec_entities(entity_id, embedding) VALUES(?,?)", (eid, db.pack_vec(vec)))
                    except Exception:
                        pass
            else:
                con.execute(
                    "UPDATE entities SET updated_at=?, description=? WHERE id=? AND length(?) > length(description)",
                    (now, desc, eid, desc),
                )
            ent_id_of[name] = eid
            con.execute(
                "INSERT OR IGNORE INTO episode_entities(episode_id, entity_id, salience) VALUES(?,?,?)",
                (episode_id, eid, 0.7),
            )
        return ent_id_of

    def _reconcile_relations(self, con, rels, ent_id_of, episode_id) -> int:
        new_facts = []
        for r in rels:
            s = (r.get("source") or "").strip()
            t = (r.get("target") or "").strip()
            if s not in ent_id_of or t not in ent_id_of:
                continue
            new_facts.append({
                "source": s, "target": t,
                "source_id": ent_id_of[s], "target_id": ent_id_of[t],
                "type": (r.get("type") or "related").strip().lower(),
                "fact": (r.get("fact") or f"{s} {r.get('type', 'related')} {t}").strip(),
                "confidence": float(r.get("confidence") or 0.6),
            })
        if not new_facts:
            return 0
        existing = self._existing_facts(con)
        ops = extraction.decide_writes(new_facts, existing)
        now = db.now()
        applied = 0
        for op in ops:
            idx = op.get("index")
            if not isinstance(idx, int) or not (0 <= idx < len(new_facts)):
                continue
            f = new_facts[idx]
            kind = (op.get("op") or "ADD").upper()
            if kind == "NOOP" and op.get("target_id") is None:
                fb = self._overlap_fallback(con, f)
                if fb is not None:
                    kind, op = "UPDATE", {"index": idx, "op": "UPDATE", "target_id": fb, "reason": "same-entity new fact supersedes"}
            if kind == "NOOP":
                continue
            con.execute(
                "INSERT INTO relations(source_id, target_id, type, fact, weight, confidence, valid_at, invalid_at, created_at, source_episode) VALUES(?,?,?,?,?,?,?,NULL,?,?)",
                (f["source_id"], f["target_id"], f["type"], f["fact"], 1.0, f["confidence"], now, now, episode_id),
            )
            applied += 1
            if kind in ("UPDATE", "INVALIDATE") and op.get("target_id"):
                con.execute("UPDATE relations SET invalid_at=? WHERE id=?", (now, op.get("target_id")))
        self._reindex_relation_vectors(con)
        graph.reinforce(con, [f["source_id"] for f in new_facts] + [f["target_id"] for f in new_facts])
        return applied
    def _existing_facts(self, con) -> list:
        return [
            f"{r['id']}: {r['s']} --{r['type']}--> {r['t']} :: {r['fact']}"
            for r in con.execute(
                """SELECT r.id, e1.canonical_name AS s, e2.canonical_name AS t, r.type, r.fact
                   FROM relations r JOIN entities e1 ON e1.id=r.source_id
                   JOIN entities e2 ON e2.id=r.target_id
                   WHERE r.invalid_at IS NULL"""
            ).fetchall()
        ]

    def _overlap_fallback(self, con, f) -> int | None:
        try:
            rows = con.execute(
                """SELECT id, fact FROM relations
                   WHERE invalid_at IS NULL AND source_id=? AND target_id=? AND type=? LIMIT 5""",
                (f["source_id"], f["target_id"], f["type"]),
            ).fetchall()
        except Exception:
            return None
        for r in rows:
            try:
                if (r["fact"] or "").strip().lower() != (f["fact"] or "").strip().lower():
                    return int(r["id"])
            except Exception:
                continue
        return None

    def _reindex_relation_vectors(self, con) -> None:
        for r in con.execute("SELECT id, fact, type FROM relations WHERE id NOT IN (SELECT relation_id FROM vec_relations)").fetchall():
            v = embedder.embed_text(f"{r['fact']} {r['type']}")
            if v:
                try:
                    con.execute("INSERT OR IGNORE INTO vec_relations(relation_id, embedding) VALUES(?,?)", (r["id"], db.pack_vec(v)))
                except Exception:
                    pass
        for r in con.execute("SELECT id, type, fact FROM relations WHERE fact!=''").fetchall():
            try:
                con.execute("INSERT OR REPLACE INTO fts_relations(rowid, fact, type) VALUES(?,?,?)", (r["id"], r["fact"], r["type"]))
            except Exception:
                pass

    def _make_note(self, con, user_text, assistant_text, ents) -> int | None:
        try:
            title = " ".join(user_text.split())[:60] or "Note"
            content = (assistant_text or user_text)[:500]
            vec = embedder.embed_text((user_text + " " + assistant_text))
            now = db.now()
            kw = json.dumps([e.get("name") for e in ents[:8]])
            cur = con.execute(
                "INSERT INTO notes(title, content, keywords, tags, embedding, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                (title, content, kw, "[]", db.pack_vec(vec) if vec else None, now, now),
            )
            return cur.lastrowid
        except Exception:
            return None

    def _summarize_for_note(self, user_text, assistant_text):
        try:
            return None  # notes use the exchange text directly (no extra LLM cost)
        except Exception:
            return None
# ---- recall ----
    def recall_with_hits(self, query, top_k=6, max_bytes=5000):
        """Recall + per-hit provenance (kind, score, meta, snippet).

        Zero extra cost over recall(): same search, hits passed through
        instead of being flattened into text. Powers `/why`."""
        con = self._open()
        try:
            hits = retrieval.search(con, query, top_k=top_k, max_bytes=max_bytes)
            if not hits:
                return self._core_text(con), []
            lines = []
            prove = []
            for h in hits:
                lines.append(f"[{h.kind}] {h.text}")
                try:
                    prove.append({"kind": h.kind, "score": round(float(h.score), 4),
                                  "meta": dict(h.meta or {}), "snippet": h.text[:200]})
                except Exception:
                    prove.append({"kind": h.kind, "score": 0.0, "meta": {}, "snippet": h.text[:200]})
            return "\n".join(lines), prove
        finally:
            if self._own:
                con.close()

    def recall(self, query, top_k=6, max_bytes=5000):
        text, _ = self.recall_with_hits(query, top_k=top_k, max_bytes=max_bytes)
        return text

    def _core_text(self, con=None):
        con = con or self._open()
        try:
            blocks = con.execute("SELECT key, content FROM core_blocks").fetchall()
            return "\n".join(f"{b['key']}: {b['content']}" for b in blocks)
        finally:
            if con is not self._con:
                con.close()

    def core_context(self):
        return self._core_text()

    # ---- maintenance ----
    def consolidate(self, min_interval_s=300.0) -> dict:
        if time.time() - self.consolidated_at < min_interval_s:
            return {"ran": False}
        con = self._open()
        try:
            graph.apply_time_decay(con)
            links = consolidation.link_notes(con)
            invalidations = consolidation.sweep_contradictions(con)
            communities = consolidation.rebuild_communities(con)
            core = consolidation.rewrite_core(con)
            self.consolidated_at = time.time()
            return {"ran": True, "links": links, "invalidations": invalidations, "communities": communities, "core_blocks": core}
        finally:
            if self._own:
                con.commit()
                con.close()

    def forget(self, target):
        con = self._open()
        try:
            row = con.execute("SELECT id FROM entities WHERE canonical_name=? OR name=? LIMIT 1", (target, target)).fetchone()
            if not row:
                return {"forgot": False, "reason": "not found"}
            eid = row["id"]
            con.execute(
                "UPDATE relations SET invalid_at=? WHERE (source_id=? OR target_id=?) AND invalid_at IS NULL",
                (db.now(), eid, eid),
            )
            return {"forgot": True, "entity": eid}
        finally:
            if self._own:
                con.commit()
                con.close()

    def clear(self):
        con = self._open()
        try:
            for t in ["episode_entities", "relations", "entities", "aliases", "episodes", "notes",
                      "note_links", "communities", "community_members", "core_blocks"]:
                con.execute(f"DELETE FROM {t}")
            for vt in ["vec_episodes", "vec_entities", "vec_relations", "vec_notes",
                       "fts_episodes", "fts_relations", "fts_notes"]:
                try:
                    con.execute(f"DELETE FROM {vt}")
                except Exception:
                    pass
        finally:
            if self._own:
                con.commit()
                con.close()
        self.consolidated_at = 0.0
        return {"cleared": True}


def get_memory():
    with _cache_lock:
        if "mem" not in _cache:
            _cache["mem"] = Memory()
        return _cache["mem"]