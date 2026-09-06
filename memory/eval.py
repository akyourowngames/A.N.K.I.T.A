"""T2.8 — Memory eval harness (the regression net, BUILD FIRST).

Golden Q/A generation from stored facts (single-hop, temporal,
contradiction/update cases) -> eval_pairs table. Run reads through the full
retrieval path per question with an LLM-judge (deterministic containment
fallback so the harness works offline). Scores stored in eval_runs.

RULE: every change to retrieval/extraction keeps eval green or improves it.
"""

from __future__ import annotations

import json
import time

from . import db as _db

CATEGORIES = ("single-hop", "temporal", "update")


def ensure_schema(con) -> None:
    _db.ensure_tier2(con)


def _row_facts(con):
    rows = con.execute(
        """SELECT r.id, e1.canonical_name AS s, r.type, e2.canonical_name AS t,
                  r.fact, r.valid_at, r.created_at
           FROM relations r JOIN entities e1 ON e1.id=r.source_id
           JOIN entities e2 ON e2.id=r.target_id
           WHERE r.invalid_at IS NULL ORDER BY r.id"""
    ).fetchall()
    return [dict(r) for r in rows]


def _row_episodes(con, limit: int = 20):
    try:
        rows = con.execute(
            "SELECT id, user_text, assistant_text, created_at FROM episodes ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def heuristic_pairs(con, limit_per_cat: int = 10) -> list[dict]:
    pairs: list[dict] = []
    for f in _row_facts(con)[: limit_per_cat * 2]:
        s, t, typ, fact = f["s"], f["t"], f["type"], f["fact"]
        pairs.append({
            "question": f"What is the relationship between {s} and {t}?",
            "expected": fact,
            "category": "single-hop",
            "evidence_ids": json.dumps([f["id"]]),
        })
        if len([p for p in pairs if p["category"] == "single-hop"]) >= limit_per_cat:
            break
    for f in _row_facts(con):
        if f.get("valid_at"):
            try:
                import datetime as _dt
                d = _dt.datetime.fromtimestamp(float(f["valid_at"])).strftime("%Y-%m")
            except Exception:
                d = "that time"
            pairs.append({
                "question": f"What was true about {f['s']} around {d}?",
                "expected": f["fact"],
                "category": "temporal",
                "evidence_ids": json.dumps([f["id"]]),
            })
            if len([p for p in pairs if p["category"] == "temporal"]) >= limit_per_cat:
                break
    if not any(p["category"] == "temporal" for p in pairs):
        for ep in _row_episodes(con, limit=limit_per_cat):
            txt = (ep.get("user_text") or "")[:120]
            if not txt:
                continue
            pairs.append({
                "question": f"What did I say in: '{txt}'?",
                "expected": txt,
                "category": "temporal",
                "evidence_ids": json.dumps([ep["id"]]),
            })
            if len([p for p in pairs if p["category"] == "temporal"]) >= limit_per_cat:
                break
    for f in _row_facts(con)[:limit_per_cat]:
        pairs.append({
            "question": f"Is it still true that: {f['fact']}?",
            "expected": f["fact"],
            "category": "update",
            "evidence_ids": json.dumps([f["id"]]),
        })
        if len([p for p in pairs if p["category"] == "update"]) >= limit_per_cat:
            break
    seen = set()
    out = []
    for p in pairs:
        k = p["question"]
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


_GENERATE_PROMPT = """Write eval questions from these stored facts. Cover single-hop recall,
temporal ("around <date>", "last month") and update/contradiction ("is it still true").
Return JSON: {{"pairs": [{{"question": "..", "expected": "..", "category": "single-hop|temporal|update", "evidence_ids": [<ids>]}}]}}

FACTS:
{facts}"""


def generate_pairs(con, use_llm: bool = True, limit_per_cat: int = 8) -> list[dict]:
    ensure_schema(con)
    facts = _row_facts(con)[:60]
    if use_llm and facts:
        try:
            from . import llm as _llm
            blob = "\n".join(f"{f['id']}: {f['s']} -[{f['type']}]-> {f['t']}: {f['fact']}" for f in facts)
            out = _llm.chat_json(
                _GENERATE_PROMPT.format(facts=blob[:6000]),
                system="You write precise memory-eval Q/A as valid JSON only.",
                max_tokens=2000,
            )
            llm_pairs = (out or {}).get("pairs") if isinstance(out, dict) else None
            if llm_pairs:
                cleaned = []
                for p in llm_pairs:
                    if not isinstance(p, dict) or not p.get("question") or not p.get("expected"):
                        continue
                    cat = str(p.get("category") or "single-hop")
                    if cat not in CATEGORIES:
                        cat = "single-hop"
                    try:
                        ev = json.dumps(list(p.get("evidence_ids") or [])[:8])
                    except Exception:
                        ev = "[]"
                    cleaned.append({"question": str(p["question"])[:500], "expected": str(p["expected"])[:800],
                                    "category": cat, "evidence_ids": ev})
                if cleaned:
                    _store_pairs(con, cleaned)
                    return cleaned
        except Exception:
            pass
    pairs = heuristic_pairs(con, limit_per_cat=limit_per_cat)
    _store_pairs(con, pairs)
    return pairs


def _store_pairs(con, pairs: list[dict]) -> int:
    ensure_schema(con)
    now = time.time()
    n = 0
    for p in pairs:
        try:
            con.execute(
                "INSERT INTO eval_pairs(question, expected, category, evidence_ids, created_at) VALUES(?,?,?,?,?)",
                (p["question"], p["expected"], p.get("category", "single-hop"), p.get("evidence_ids", "[]"), now),
            )
            n += 1
        except Exception:
            continue
    try:
        con.commit()
    except Exception:
        pass
    return n


def load_pairs(con) -> list[dict]:
    ensure_schema(con)
    try:
        rows = con.execute("SELECT id, question, expected, category, evidence_ids FROM eval_pairs ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _contain_judge(expected: str, retrieved_text: str) -> bool:
    import re as _re
    exp_toks = [t.lower() for t in _re.findall(r"[A-Za-z0-9_]{3,}", expected)]
    if not exp_toks:
        return False
    hay = retrieved_text.lower()
    stop = {"the", "and", "with", "from", "that", "this", "what", "when", "true", "still"}
    keys = [t for t in exp_toks if t not in stop][:8]
    if not keys:
        keys = exp_toks[:4]
    hits = sum(1 for t in keys if t in hay)
    return hits >= max(1, (len(keys) + 1) // 2)


_JUDGE_PROMPT = """Does the RETRIEVED context contain the answer to the QUESTION?
QUESTION: {q}
EXPECTED ANSWER: {exp}
RETRIEVED:
{ctx}

Respond JSON: {{"hit": true|false, "reason": ".."}}"""


def judge_pair(question: str, expected: str, retrieved_text: str, use_llm: bool = True) -> bool:
    if use_llm:
        try:
            from . import llm as _llm
            out = _llm.chat_json(
                _JUDGE_PROMPT.format(q=question[:500], exp=expected[:800], ctx=retrieved_text[:6000]),
                system="You judge memory retrieval strictly. Valid JSON only.",
                max_tokens=300,
            )
            if isinstance(out, dict) and isinstance(out.get("hit"), bool):
                return bool(out["hit"])
        except Exception:
            pass
    return _contain_judge(expected, retrieved_text)


def run_eval(mem=None, con=None, use_llm: bool = False, top_k: int = 6) -> dict:
    from . import retrieval as _ret
    own = False
    if con is None:
        if mem is not None and getattr(mem, "_con", None) is not None:
            con = mem._con
        else:
            con = _db.connect()
            own = True
    try:
        ensure_schema(con)
        pairs = load_pairs(con)
        if not pairs:
            pairs = heuristic_pairs(con)
            _store_pairs(con, pairs)
            pairs = load_pairs(con)
        per_cat: dict[str, dict] = {}
        details = []
        hits = 0
        for p in pairs:
            try:
                found = _ret.search(con, p["question"], top_k=top_k, max_bytes=6000)
                ctx = "\n".join(f"[{h.kind}] {h.text}" for h in found)
            except Exception:
                ctx = ""
            hit = judge_pair(p["question"], p["expected"], ctx, use_llm=use_llm)
            hits += 1 if hit else 0
            cat = p.get("category") or "single-hop"
            d = per_cat.setdefault(cat, {"total": 0, "hits": 0})
            d["total"] += 1
            d["hits"] += 1 if hit else 0
            details.append({"pair_id": p["id"], "question": p["question"][:200], "category": cat, "hit": bool(hit)})
        total = len(pairs)
        rate = (hits / total) if total else 0.0
        for d in per_cat.values():
            d["hit_rate"] = (d["hits"] / d["total"]) if d["total"] else 0.0
        try:
            con.execute(
                "INSERT INTO eval_runs(timestamp, total, hits, hit_rate, per_category, details) VALUES(?,?,?,?,?,?)",
                (time.time(), total, hits, rate, json.dumps(per_cat), json.dumps(details)),
            )
            con.commit()
        except Exception:
            pass
        return {"total": total, "hits": hits, "hit_rate": rate, "per_category": per_cat, "details": details}
    finally:
        if own:
            try:
                con.close()
            except Exception:
                pass


def last_runs(con, limit: int = 5) -> list[dict]:
    ensure_schema(con)
    try:
        rows = con.execute("SELECT id, timestamp, total, hits, hit_rate, per_category FROM eval_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["per_category"] = json.loads(d.get("per_category") or "{}")
            except Exception:
                d["per_category"] = {}
            out.append(d)
        return out
    except Exception:
        return []
