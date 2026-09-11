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

from . import consolidation, db, embedder, extraction, graph, llm, resolve, retrieval, inbox

_cache = {}
_cache_lock = threading.Lock()


_EXPLICIT_KINDS = ("remember", "manual", "note")


def _checkpoint(con) -> None:
    """Commit pending writes so no lock is held across network (LLM) calls.

    SQLite (even in WAL mode) lets a single open write transaction block
    every other writer with "database is locked". All LLM traffic must run
    with a clean transaction — call this before each network phase.
    """
    try:
        con.commit()
    except Exception:
        pass


def prefilter_may_be_memorable(user_text: str, assistant_text: str = "") -> bool:
    from . import extraction as _extraction
    try:
        return bool(_extraction.should_remember(user_text, assistant_text))
    except Exception:
        return True


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
        self._queued_ids = set()
        if self._own:
            self._restore_captures()

    # ---- background capture (serialized single worker) ----
    def capture_async(self, user_text, assistant_text, session_id="", kind="chat") -> None:
        """Queue an exchange for background ingestion. Serialized on one worker
        thread so captures survive quick exits and never race each other."""
        if self._own:
            inbox.save(user_text, assistant_text, session_id, kind)
            self._restore_captures()
            return
        self._idle.clear()
        self._q.put((None, user_text, assistant_text, session_id, kind))
        self._ensure_worker()

    def _restore_captures(self):
        with self._worker_lock:
            for record in inbox.pending():
                if record[0] not in self._queued_ids:
                    self._queued_ids.add(record[0])
                    self._idle.clear()
                    self._q.put(record)
        if not self._q.empty():
            self._ensure_worker()

    def _ensure_worker(self):
        with self._worker_lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="zumba-memory")
                self._worker.start()

    def _worker_loop(self):
        while True:
            try:
                capture_id, user_text, assistant_text, session_id, kind = self._q.get(timeout=30)
            except queue.Empty:
                self._idle.set()
                return
            try:
                self.ingest_episode(user_text, assistant_text, session_id=session_id, kind=kind)
                if capture_id:
                    inbox.finish(capture_id)
                self.consolidate(min_interval_s=1800.0)
            except Exception as exc:
                if capture_id:
                    inbox.finish(capture_id, str(exc))
            finally:
                with self._worker_lock:
                    self._queued_ids.discard(capture_id)
                self._q.task_done()
                if self._q.unfinished_tasks == 0:
                    self._idle.set()

    def flush(self, timeout: float = 30.0) -> bool:
        """Wait for queued captures to finish (called on chat exit)."""
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

            def _safe(sql):
                try:
                    return c(sql)
                except Exception:
                    return 0
            return {
                "episodes": c("SELECT COUNT(*) FROM episodes"),
                "entities": c("SELECT COUNT(*) FROM entities"),
                "relations": c("SELECT COUNT(*) FROM relations"),
                "active_relations": c("SELECT COUNT(*) FROM relations WHERE invalid_at IS NULL"),
                "notes": c("SELECT COUNT(*) FROM notes"),
                "communities": c("SELECT COUNT(*) FROM communities"),
                "core_blocks": c("SELECT COUNT(*) FROM core_blocks"),
                "goals_active": _safe("SELECT COUNT(*) FROM goals WHERE status='active'"),
                "goals_total": _safe("SELECT COUNT(*) FROM goals"),
                "reminders_pending": _safe("SELECT COUNT(*) FROM reminders WHERE status IN ('pending','snoozed')"),
                "user_facts": _safe("SELECT COUNT(*) FROM user_facts"),
                "follow_ups_open": _safe("SELECT COUNT(*) FROM follow_ups WHERE done_at IS NULL"),
                "moods": _safe("SELECT COUNT(*) FROM session_moods"),
                "eval_pairs": _safe("SELECT COUNT(*) FROM eval_pairs"),
                "eval_runs": _safe("SELECT COUNT(*) FROM eval_runs"),
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
            # End phase 1 BEFORE indexing: the first embedding call loads the
            # model and is slow — it must never run inside a write txn.
            _checkpoint(con)
            self._index_episode(con, episode_id, user_text, assistant_text)
            # Everything below that touches the network runs lock-free;
            # writes re-open short transactions afterwards.
            _checkpoint(con)

            explicit = str(kind or "") in _EXPLICIT_KINDS
            try:
                from . import preferences as _pref0
                _style_hits = _pref0.detect_corrections(user_text + " " + assistant_text)
            except Exception:
                _style_hits = []
            if not explicit and not _style_hits:
                memorable = extraction.should_remember(user_text, assistant_text)
                if not memorable:
                    return {"stored": True, "extracted": False, "episode": episode_id}

            try:
                known = [r["canonical_name"] for r in con.execute("SELECT canonical_name FROM entities LIMIT 40").fetchall()]
            except Exception:
                known = []
            # The free extraction model flakes empty ~50% of the time on hard
            # exchanges (measured live): retry up to 4 attempts total so one
            # bad roll does not silently drop the whole exchange.
            ents, rels = [], []
            for _ in range(4):
                ents, rels = extraction.extract_graph(user_text, assistant_text, known=known)
                if ents or rels:
                    break
            if not ents and not rels and not _style_hits:
                return {"stored": True, "extracted": False, "episode": episode_id}
            if not ents and not rels:
                ents, rels = [], []

            try:
                from . import preferences as _prefs
                _found = _prefs.detect_corrections(user_text + " " + assistant_text)
                _names = {str(e.get("name") or "") for e in ents}
                for p in _found:
                    if p["target"] not in _names:
                        ents.append({"name": p["target"], "type": "style", "description": "assistant style target"})
                        _names.add(p["target"])
                    if "user" not in _names and p.get("source") == "user":
                        ents.append({"name": "user", "type": "person", "description": "the user"})
                        _names.add("user")
                    if not any(r.get("type") == p["type"] for r in rels):
                        s_name = p.get("source") or "user"
                        if s_name not in _names:
                            ents.append({"name": s_name, "type": "person", "description": "the user"})
                            _names.add(s_name)
                        rels.append({"source": s_name, "target": p["target"], "type": p["type"], "fact": p["fact"], "confidence": 0.85})
            except Exception:
                pass
            ent_id_of = self._reconcile_entities(con, ents, episode_id)
            _checkpoint(con)
            n_relations = self._reconcile_relations(con, rels, ent_id_of, episode_id)
            _checkpoint(con)
            try:
                from identity import userprofile as _up
                _up.extract_user_facts_from_relations(con, rels, episode_id)
            except Exception:
                pass
            _checkpoint(con)
            note_id = self._make_note(con, user_text, assistant_text, ents)
            if note_id:
                consolidation.link_notes(con, note_id)
                _checkpoint(con)
                try:
                    consolidation.evolve_notes(con, note_id, use_llm=True, max_updates=3)
                except Exception:
                    pass
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
    def _plan_entities(self, con, ents) -> list:
        """Resolve each entity to an existing id (reads + LLM merge checks).

        No writes: safe to run while other threads use the database.
        """
        planned = []
        for e in ents:
            name = (e.get("name") or "").strip()
            if not name:
                continue
            desc = (e.get("description") or "").strip()
            planned.append({
                "name": name,
                "type": (e.get("type") or "").strip() or "unknown",
                "desc": desc,
                "eid": resolve.resolve_entity(con, name),
                # Precompute while lock-free: embedding must never run
                # inside the apply-phase write transaction.
                "vec": embedder.embed_text(f"{name} {desc}" if desc else name),
            })
        return planned

    def _apply_entities(self, con, planned, episode_id) -> dict:
        """Insert planned entities. Short write-only phase (no network)."""
        ent_id_of = {}
        now = db.now()
        for p in planned:
            name = p["name"]
            eid = p["eid"]
            if eid is None:
                # Re-check: an earlier entity in this same batch may have
                # created it after planning (preserves sequential semantics).
                row = con.execute("SELECT entity_id FROM aliases WHERE alias=?", (name,)).fetchone()
                if row:
                    eid = row["entity_id"]
                else:
                    row = con.execute("SELECT id FROM entities WHERE canonical_name=?", (name,)).fetchone()
                    if row:
                        eid = row["id"]
            if eid is None:
                c = con.execute(
                    "INSERT INTO entities(name, canonical_name, type, description, confidence, importance, created_at, updated_at, access_count, last_access, decay) VALUES(?,?,?,?,?,?,?,?,0,0,1.0)",
                    (name, name, p["type"], p["desc"], 0.7, 0.6, now, now),
                )
                eid = c.lastrowid
                con.execute("INSERT OR IGNORE INTO aliases(alias, entity_id) VALUES(?,?)", (name, eid))
                if p.get("vec"):
                    try:
                        con.execute("INSERT OR IGNORE INTO vec_entities(entity_id, embedding) VALUES(?,?)", (eid, db.pack_vec(p["vec"])))
                    except Exception:
                        pass
            else:
                con.execute(
                    "UPDATE entities SET updated_at=?, description=? WHERE id=? AND length(?) > length(description)",
                    (now, p["desc"], eid, p["desc"]),
                )
            ent_id_of[name] = eid
            con.execute(
                "INSERT OR IGNORE INTO episode_entities(episode_id, entity_id, salience) VALUES(?,?,?)",
                (episode_id, eid, 0.7),
            )
        return ent_id_of

    def _reconcile_entities(self, con, ents, episode_id) -> dict:
        # Plan (reads + LLM merge decisions) with a clean transaction, then
        # one short write phase — never hold the lock across network calls.
        _checkpoint(con)
        planned = self._plan_entities(con, ents)
        _checkpoint(con)
        return self._apply_entities(con, planned, episode_id)

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
        # Embed everything first (no writes outstanding), then insert: the
        # embedding call must never run inside a write transaction.
        pending = []
        for r in con.execute("SELECT id, fact, type FROM relations WHERE id NOT IN (SELECT relation_id FROM vec_relations)").fetchall():
            v = embedder.embed_text(f"{r['fact']} {r['type']}")
            if v:
                pending.append((r["id"], v))
        for rid, v in pending:
            try:
                con.execute("INSERT OR IGNORE INTO vec_relations(relation_id, embedding) VALUES(?,?)", (rid, db.pack_vec(v)))
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
            try:
                cur = con.execute(
                    "INSERT INTO notes(title, content, keywords, tags, kind, description, embedding, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (title, content, kw, "[]", "note", "", db.pack_vec(vec) if vec else None, now, now),
                )
            except Exception:
                cur = con.execute(
                    "INSERT INTO notes(title, content, keywords, tags, embedding, created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                    (title, content, kw, "[]", db.pack_vec(vec) if vec else None, now, now),
                )
            nid = cur.lastrowid
            if vec:
                try:
                    con.execute("INSERT OR REPLACE INTO vec_notes(note_id, embedding) VALUES(?,?)", (nid, db.pack_vec(vec)))
                except Exception:
                    pass
            try:
                con.execute("INSERT OR REPLACE INTO fts_notes(rowid, title, content, keywords) VALUES(?,?,?,?)", (nid, title, content, kw))
            except Exception:
                pass
            return nid
        except Exception:
            return None

    def _summarize_for_note(self, user_text, assistant_text):
        try:
            return None  # notes use the exchange text directly (no extra LLM cost)
        except Exception:
            return None
# ---- recall ----
    def profile_text(self, con=None) -> str:
        try:
            from identity import userprofile as _up
            prof = _up.profile_block()
            if prof:
                return prof
        except Exception:
            pass
        return ""

    def mood_text(self, con=None) -> str:
        try:
            con = con or self._open()
            from . import mood as _mood
            return _mood.mood_context(con)
        except Exception:
            return ""

    def recall_with_hits(self, query, top_k=6, max_bytes=5000, time_range=None, as_of=None):
        """Recall + per-hit provenance (kind, score, meta, snippet).

        Zero extra cost over recall(): same search, hits passed through
        instead of being flattened into text. Powers `/why`.
        T2.1: user.md profile is ALWAYS prepended (bounded), not query-gated.
        T2.4: recent mood context is appended so tone adapts."""
        con = self._open()
        try:
            try:
                hits = retrieval.search(con, query, top_k=top_k, max_bytes=max_bytes, time_range=time_range, as_of=as_of)
            except TypeError:
                hits = retrieval.search(con, query, top_k=top_k, max_bytes=max_bytes)
            prefix_parts = []
            try:
                from identity import userprofile as _up
                prof = _up.profile_block()
                if prof:
                    prefix_parts.append(prof[:1800])
            except Exception:
                pass
            try:
                from . import mood as _mood
                mc = _mood.mood_context(con)
                if mc:
                    prefix_parts.append(mc[:600])
            except Exception:
                pass
            try:
                from . import goals as _goals
                gc = _goals.goal_context(con)
                if gc:
                    prefix_parts.append(gc[:1500])
            except Exception:
                pass
            prefix = ("\n".join(prefix_parts) + "\n" if prefix_parts else "") + self._core_text(con)
            prefix = prefix.strip()
            if not hits:
                return prefix, []
            lines = []
            prove = []
            for h in hits:
                lines.append(f"[{h.kind}] {h.text}")
                try:
                    prove.append({"kind": h.kind, "score": round(float(h.score), 4),
                                  "meta": dict(h.meta or {}), "snippet": h.text[:200]})
                except Exception:
                    prove.append({"kind": h.kind, "score": 0.0, "meta": {}, "snippet": h.text[:200]})
            body = "\n".join(lines)
            full = (prefix + "\n" + body).strip() if prefix else body
            if len(full) > max_bytes + 2500:
                full = full[: max_bytes + 2500]
            return full, prove
        finally:
            if self._own:
                con.close()

    def recall(self, query, top_k=6, max_bytes=5000, time_range=None, as_of=None):
        try:
            text, _ = self.recall_with_hits(query, top_k=top_k, max_bytes=max_bytes, time_range=time_range, as_of=as_of)
        except TypeError:
            text, _ = self.recall_with_hits(query, top_k=top_k, max_bytes=max_bytes)
        return text

    def _core_text(self, con=None):
        own_connection = con is None and self._con is None
        con = con if con is not None else self._open()
        try:
            blocks = con.execute("SELECT key, content FROM core_blocks").fetchall()
            return "\n".join(f"{b['key']}: {b['content']}" for b in blocks)
        finally:
            if own_connection:
                con.close()

    def core_context(self):
        return self._core_text()

    # ---- maintenance ----
    def consolidate(self, min_interval_s=300.0) -> dict:
        if time.time() - self.consolidated_at < min_interval_s:
            return {"ran": False}
        con = self._open()
        try:
            db.ensure_tier2(con)
            graph.apply_time_decay(con)
            try:
                from . import task_lifecycle
                task_lifecycle.review_pending(con)
            except Exception:
                pass
            # Each phase below fans out to LLM calls; checkpoint between them
            # so a phase never runs network I/O on top of an older phase's
            # uncommitted writes (the "database is locked" pattern).
            _checkpoint(con)
            links = consolidation.link_notes(con)
            _checkpoint(con)
            invalidations = consolidation.sweep_contradictions(con)
            _checkpoint(con)
            communities = consolidation.rebuild_communities(con)
            _checkpoint(con)
            core = consolidation.rewrite_core(con)
            _checkpoint(con)
            user_facts_n = 0
            try:
                from identity import userprofile as _up
                rows = con.execute(
                    """SELECT r.type, r.fact, r.confidence, r.source_episode FROM relations r
                       WHERE r.invalid_at IS NULL ORDER BY r.created_at DESC LIMIT 60""").fetchall()
                rels = [{"type": r["type"], "fact": r["fact"], "confidence": r["confidence"], "source": ""} for r in rows]
                user_facts_n = _up.extract_user_facts_from_relations(con, rels)
                _checkpoint(con)
                try:
                    _up.rewrite_user_md(con, use_llm=True)
                except Exception:
                    pass
            except Exception:
                pass
            try:
                from . import preferences as _prefs
                prefs = _prefs.active_preferences(con)
                if prefs:
                    _prefs.propose_voice_update(con, prefs)
            except Exception:
                pass
            self.consolidated_at = time.time()
            return {"ran": True, "links": links, "invalidations": invalidations, "communities": communities, "core_blocks": core, "user_facts": user_facts_n}
        finally:
            if self._own:
                con.commit()
                con.close()

    def reflect_on_session(self, exchanges: list, session_id: str = "", use_llm: bool = True) -> dict:
        con = self._open()
        try:
            from . import reflection as _ref
            return _ref.reflect_session(con, exchanges, session_id=session_id, use_llm=use_llm)
        finally:
            if self._own:
                try:
                    con.commit()
                except Exception:
                    pass
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
                      "note_links", "communities", "community_members", "core_blocks",
                      "user_facts", "follow_ups", "session_moods", "eval_pairs", "eval_runs",
                      "goals", "goal_steps", "reminders", "goal_research"]:
                try:
                    con.execute(f"DELETE FROM {t}")
                except Exception:
                    pass
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
