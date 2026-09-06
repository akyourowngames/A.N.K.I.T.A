# ZUMBA — TIER 2 PLAN: THE SOUL + THE LIVING MEMORY
Research-grounded: soul.md spec (aaronjmars/soul.md, OpenClaw/AgentOS), Zep/Graphiti (arXiv:2501.13956),
Mem0 (arXiv:2504.19413 — incl. its Zep async-latency critique), Letta memory blocks,
HippoRAG 2 (arXiv:2502.14802), A-Mem (arXiv:2502.12110), Generative Agents reflection.
Builds on Tier 1 (persona.py, shelltool.py, context_budget.py, /why, salience cleanup).

---

## FEATURE S: soul.md — SELF-AUTHORED IDENTITY
**Bootstrap flow (first message only, zero hardcoding):**
1. If `~/.zumba/soul.md` missing -> onboarding: Zumba asks 3 short questions (how should I sound?
   what should I always keep in mind about you? anything off-limits?). Skippable ("just wing it" ->
   LLM drafts from the first few exchanges).
2. Zumba writes soul.md ITSELF: one LLM call composes the file from the answers following the
   soul.md spec structure (YAML frontmatter + Identity / Voice / Values / Boundaries sections),
   then uses its own shell tool (`zumba__shell_run`) to write the file. Self-authored, not template-filled.
3. `persona.py` loads soul.md at session start -> identity system block (frontmatter parsed, prose verbatim).
4. **Companion `user.md`** — the user model. soul.md = who Zumba IS; user.md = who YOU are
   (AgentOS "what goes where" split). Same bootstrap creates it.
5. **Self-editing with consent** (Letta rethink_memory pattern): consolidation proposes updates ->
   `~/.zumba/soul.proposed.md` -> `/soul diff` -> `/soul accept|reject`. `/soul edit` opens $EDITOR,
   `/soul show` displays. Hard cap ~4k chars (context budget protection).

**New module `soul.py`:** exists(), bootstrap_flow(), load(), inject_block(), propose_update(),
apply()/reject(). Tests: onboarding triggers once then skips; injection ordering with memory block;
propose/accept/reject lifecycle; cap enforcement.

## T2.1 — STRUCTURED USER MODEL (Letta human-block pattern)
- user.md = authoritative profile: identity, projects, people, preferences, goals, current-focus.
- New `user_facts` table (key, value, confidence, source_episode, updated_at); consolidation writes it.
- LLM pass maintains user.md from graph + table.
- Recall ALWAYS prepends user.md (bounded) — profile is in context unconditionally, not query-gated.
- `/me` shows it.

## T2.2 — SESSION-END REFLECTION (Generative Agents)
On chat exit (after mem.flush()), ONE LLM pass over the session:
- Decisions made + reasons -> notes with kind=decision
- Open follow-ups -> new `follow_ups` table (text, created_at, done_at) -> powers daily briefing
- Importance score 1-10 (Park et al. poignancy) -> stored on episodes, feeds retrieval weighting
- Mood/energy read of the user this session -> T2.4
Cheap (1 call), runs in the existing background worker thread.

## T2.3 — RETRIEVAL UPGRADE: HippoRAG 2 + A-Mem evolution
- **Passages-in-graph (HippoRAG 2):** PPR currently seeds only entities and boosts relations
  (retrieval.py:97-123). V2: seed PPR with episode/note nodes TOO, per-node reset probabilities
  weighted by importance (T2.2) + recency. Fixes v1's factual-recall regression.
- **A-Mem memory evolution:** new note -> top-3 similar existing notes get descriptions/keywords
  updated by LLM (Zettelkasten evolution). Guard: max 3 updates per ingest, batched.
- **Temporal read-path:** time-range filter param on retrieval; as_of cutoff on valid_at;
  "what did I say last month" becomes first-class.
- **Latency discipline (Mem0's Zep critique):** episode text MUST be FTS+vector indexed
  synchronously before the next turn. Regression test: ingest -> immediate recall must hit.
  Enrichment lag must never block raw-text recall.

## T2.4 — MOOD / STATE TIMELINE
`session_moods` table (session_id, valence -1..1, energy, note, created_at). Valence via local
fastembed similarity to affect anchors (no LLM); optional LLM refinement in reflection.
`zumba mood` renders a 30-day terminal chart; recall boosts recent mood context so tone adapts.

## T2.5 — PROACTIVE: `zumba daily` BRIEFING
One composed generation from: open follow-ups, community summaries, on-this-day episode resurfacing
(bi-temporal data finally used read-side), mood trend, dates extracted from graph. `/brief` in chat.
Optional `--install-reminder` uses the shell tool to register a Windows Task Scheduler job.

## T2.6 — PREFERENCE LEARNING
Style corrections ("shorter", "no tables") -> extraction emits `prefers_*` typed relations ->
consolidation folds active preferences into soul.md Voice section via propose/accept flow.
Tone converges on the user, user in control.

## T2.7 — RELATIONSHIP VIEW: `zumba memory people`
Person entities ranked by interaction recency/frequency (episodes join), last-mentioned date,
top facts. The twin knows who matters.

## T2.8 — MEMORY EVAL HARNESS (the regression net — BUILD FIRST)
`zumba memory eval`:
1. Golden Q/A generation: LLM writes questions from stored facts (single-hop, temporal,
   contradiction/update cases) -> `eval_pairs` table with expected answers + evidence ids.
2. Run full read path per question, LLM-judge whether retrieved context contains the answer.
3. Report recall-hit-rate per category; store in `eval_runs` table (timestamp, scores).
RULE: every change to retrieval/extraction keeps eval green or visibly improves it.

---

## BUILD ORDER
| # | Task | Effort | Depends |
|---|------|--------|---------|
| 0 | T2.8 eval harness | M | none |
| 1 | FEATURE S soul.md bootstrap + loader | M | Tier 1 persona |
| 2 | T2.1 user model | M | 1 |
| 3 | T2.2 reflection + follow-ups + importance | M | 0 |
| 4 | T2.3 retrieval upgrades | L | 0, 3 |
| 5 | T2.4 mood timeline | S | 3 |
| 6 | T2.5 daily briefing | M | 2, 3 |
| 7 | T2.6 preference learning | S | 1, 3 |
| 8 | T2.7 people view | S | 2 |

## DEFINITION OF DONE
- `python -m pytest tests -q` green + new suites (test_soul.py, test_eval.py, test_reflection.py, test_retrieval_v2.py)
- `zumba memory eval` baseline recorded; all later changes >= baseline
- Fresh-install walkthrough: first message -> onboarding -> soul.md + user.md exist and are injected ->
  second session feels personalized with zero repeat questions
- Ingest -> immediate recall regression test green
- README updated (soul.md section, eval, daily)
