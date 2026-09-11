"""Deep recall eval: does Zumba answer personal-fact questions from its graph?

Method (all live calls):
  1. Snapshot the real memory.db into a temp dir (test traffic never touches
     the real graph) and redirect memory.db there for this process.
  2. Sample relations stratified by confidence: top half = IMP, bottom = NONIMP.
  3. Knowledge model (free) turns each fact into {question, expected} phrased
     like the user (first person, requires personal memory).
  4. Chat model answers each question in a FRESH session through the real
     chat_pipeline.answer path (persona + recall + memory label).
  5. Score: every significant expected token present in the reply (case-ins).
  6. Eval sessions are deleted from the session store afterwards.

Usage:  python scripts/eval_graph_recall.py [--n 16]
"""

import argparse
import io
import json
import os
import sqlite3
import sys
import tempfile

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ["ZUMBA_NO_USER_MD"] = "1"

from memory import db  # noqa: E402


def snapshot_db(tmp_home):
    src = str(db.memory_db_path())
    dst = os.path.join(tmp_home, "memory.db")
    s = sqlite3.connect(src, timeout=30)
    d = sqlite3.connect(dst, timeout=30)
    try:
        s.backup(d)
    finally:
        d.close()
        s.close()
    import pathlib
    # NOTE: memory_home must stay a Path (inbox.py does path / str ops).
    db.memory_home = lambda: pathlib.Path(tmp_home)  # type: ignore
    db.memory_db_path = lambda: pathlib.Path(tmp_home) / "memory.db"  # type: ignore
    from memory import fast_recall
    fast_recall._cache.clear()


def sample_facts(n):
    from memory import db as _db
    con = _db.connect()
    try:
        rows = con.execute(
            "SELECT e1.canonical_name AS s, r.type, e2.canonical_name AS t, "
            "r.fact, r.confidence FROM relations r "
            "JOIN entities e1 ON e1.id=r.source_id "
            "JOIN entities e2 ON e2.id=r.target_id "
            "WHERE r.invalid_at IS NULL ORDER BY r.confidence DESC").fetchall()
    finally:
        con.close()
    facts = [dict(r) for r in rows if (r["fact"] or "").strip()]
    # Stratify: top half important, bottom half non-important; interleave.
    half = max(1, len(facts) // 2)
    imp, non = facts[:half], facts[half:]
    per = max(1, n // 2)
    picked = []
    for i in range(max(len(imp[:per]), len(non[:per]))):
        if i < len(imp[:per]):
            picked.append(("IMP", imp[i]))
        if i < len(non[:per]):
            picked.append(("NONIMP", non[i]))
    return picked[:n]


QGEN = ('You write test questions for a personal-assistant memory eval. '
        'Given ONE fact, write the question the user would ask to recover it '
        '(first person: "my", "I", "do I"), plus the minimal expected answer. '
        'The question must NEED personal memory (not general knowledge). '
        'Return ONLY valid JSON {{"question": "...", "expected": "..."}}. '
        'Fact: {fact}')


_META_MARKERS = ("test question", "format", "provide one fact", "such as",
                  "json", "fact should")


def _has_episode_numbers(text):
    import re
    return bool(re.search(r"\bepisodes?\s*\d+", text, re.IGNORECASE))


def _has_bare_demonstrative(question):
    """'Who is this person?' names nobody — unanswerable standalone, and any
    answer (even a clarifying one) fails a fact-anchored judge."""
    import re
    return bool(re.search(
        r"\bthis (person|place|thing|one|guy|man|woman)\b"
        r"|\bthat (person|place|thing|one|guy|man|woman)\b",
        question, re.IGNORECASE))


def llm_second_opinion(expected, reply):
    """Token judge misses paraphrases ('install' vs 'installation'). On FAIL,
    ask the free knowledge model whether the reply conveys the fact."""
    from memory import llm
    try:
        out = llm.chat_json(
            "Reply: " + reply[:1200] + "\nExpected fact: " + expected[:300] +
            "\nDoes the reply state the expected fact (paraphrase allowed, "
            "no extra requirements)? Return ONLY valid JSON {\"yes\": true/false}.",
            max_tokens=100)
    except Exception:
        return False
    return bool(isinstance(out, dict) and out.get("yes") is True)


def _gen_is_meta(question, expected):
    low = (question + " " + expected).lower()
    return any(m in low for m in _META_MARKERS)


def gen_question(fact):
    from memory import llm
    for _ in range(2):
        out = llm.chat_json(QGEN.format(fact=fact), max_tokens=300)
        if isinstance(out, dict) and out.get("question") and out.get("expected"):
            q, e = out["question"].strip(), out["expected"].strip()
            if q and e and not _gen_is_meta(q, e) and _grounded(e, fact):
                return q, e
    return None


_JUDGE_STOPWORDS = frozenset(
    "the a an yes no not are is was were be been am do does did have has had "
    "will would shall should can could may might must".split())


def significant_tokens(text):
    import re
    toks = []
    for t in re.findall(r"[A-Za-z0-9@.]{2,}", text.lower()):
        t = t.strip("@. ")
        if len(t) >= 3 and t not in _JUDGE_STOPWORDS:
            toks.append(t)
    return toks


def judge(expected, reply):
    toks = significant_tokens(expected)
    if not toks:
        # Trivial expected answers (e.g. "4"): plain substring check.
        return bool(expected.strip()) and expected.strip().lower() in reply.lower()
    low = reply.lower()
    hit = sum(1 for t in toks if t in low)
    return hit / len(toks) >= 0.7


def _grounded(expected, fact):
    """The expected answer must come from the fact, not the generator's
    imagination (it once invented '10.20.30.40:8443')."""
    toks = significant_tokens(expected)
    if not toks:
        return True
    low = fact.lower()
    hit = sum(1 for t in toks if t in low)
    return hit / len(toks) >= 0.5


def is_transport_error(reply):
    low = (reply or "").lower()
    return ("temporarily unreachable" in low or "tool-turn limit" in low
            or reply.startswith("ERROR:"))


def sample_episodes(n):
    from memory import db as _db
    con = _db.connect()
    try:
        rows = con.execute(
            "SELECT id, user_text, assistant_text FROM episodes "
            "WHERE length(user_text) > 30 AND length(assistant_text) > 30 "
            "ORDER BY id DESC LIMIT 60").fetchall()
    finally:
        con.close()
    rows = list(rows)
    # Spread across history: newest, middle, oldest slices.
    thirds = [rows[i::3] for i in range(3)]
    picked = []
    for i in range(max(len(t) for t in thirds)):
        for t in thirds:
            if i < len(t) and len(picked) < n:
                r = t[i]
                picked.append(("EP", {"id": r["id"],
                                      "text": f"U: {r['user_text']}\nA: {r['assistant_text']}"}))
    return picked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=16)
    ap.add_argument("--ep", type=int, default=0,
                    help="extra episode-based questions (raw chat recall, not graph facts)")
    args = ap.parse_args()

    from core.chat_pipeline import answer
    from core import store as core_store

    tmp = tempfile.mkdtemp(prefix="zumba-eval-")
    snapshot_db(tmp)
    items = sample_facts(args.n)
    if args.ep:
        items += sample_episodes(args.ep)
    print(f"sampled {len(items)} items (graph snapshot in {tmp})")

    sessions = []
    results = []
    for i, (tier, f) in enumerate(items):
        if tier == "EP":
            fact_text = f["text"][:1500]
        else:
            fact_text = f"{f['s']} -[{f['type']}]-> {f['t']}: {f['fact']}"
        qa = gen_question(fact_text)
        if not qa:
            print(f"[{tier}] SKIP gen-fail/meta: {fact_text[:100]}")
            continue
        if _has_episode_numbers(qa[1]):
            print(f"[{tier}] SKIP episode-numbers in expected: {fact_text[:100]}")
            continue
        if _has_bare_demonstrative(qa[0]):
            print(f"[{tier}] SKIP bare demonstrative: {qa[0][:100]!r}")
            continue
        question, expected = qa
        sid = f"eval-recall-{i}"
        sessions.append(sid)
        from core.chat_pipeline import recall_block
        mem_block = recall_block(question) or ""
        if os.getenv("ZUMBA_EVAL_DEBUG"):
            print(f"    [dbg] block_len={len(mem_block)} toks={significant_tokens(expected)}")
        ev_hit = all(t in mem_block.lower() for t in significant_tokens(expected))
        reply = ""
        for attempt in range(2):
            try:
                reply = answer(sid, question) or ""
            except Exception as exc:  # noqa: BLE001
                reply = f"ERROR: {exc}"
            if not is_transport_error(reply):
                break
            import time as _t
            _t.sleep(5)
        import time as _t2
        _t2.sleep(2)  # pacing: keep the gateway + MCP servers out of trouble
        try:
            n_tools = sum(1 for m in (core_store.get_session(sid) or {}).get("messages", [])
                          if m.get("role") == "tool")
        except Exception:
            n_tools = -1
        ok = judge(expected, reply)
        star = ""
        if not ok:
            if llm_second_opinion(expected, reply):
                ok, star = True, "*"
        ev = "EV+" if ev_hit else "EV-"
        results.append((tier, question, expected, reply, ok))
        mark = ("PASS" + star) if ok else "FAIL"
        print(f"[{tier}] {mark} {ev} tools={n_tools} Q={question!r} want={expected!r}")
        if not ok:
            print(f"       got: {reply[:220]!r}  [fact: {fact_text[:120]}]")

    for sid in sessions:
        try:
            core_store.delete_session(sid)
        except Exception:
            pass

    for tier in ("IMP", "NONIMP"):
        sub = [r for r in results if r[0] == tier]
        if sub:
            print(f"SCORE {tier}: {sum(1 for r in sub if r[4])}/{len(sub)}")
    print(f"SCORE ALL: {sum(1 for r in results if r[4])}/{len(results)}")
    return 0 if results and all(r[4] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
