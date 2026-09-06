# ZUMBA — TIER 1 GOD-TIER PLAN
Scope: Tier 1 polish, **user-profile injection deferred** + a new unrestricted "god-mode" shell tool.
Grounded in: actual code scan + research on Claude Code / Anthropic Bash tool design and Open Interpreter execution control.

---

## FEATURE 0 (HEADLINE): `shell` — GOD-MODE COMMAND TOOL
Unrestricted, fast, persistent command execution exposed to the model as a built-in tool
(and via `/shell <cmd>` for you). No allowlists, no blocklists, no approval prompts.

### Design (research-backed)
| Decision | Choice | Why (source) |
|---|---|---|
| Execution model | **Persistent shell session** — one long-lived `powershell` subprocess kept alive across tool calls | Claude Code / Anthropic bash tool: state (cwd, env vars, files) persists between commands |
| Restrictions | **None.** No command filtering. Audit-only. | Open Interpreter `auto_run=True` pattern; safety = audit log, not gates |
| Output cap | Truncate to `ZUMBA_SHELL_MAX_OUTPUT` (default 8000 chars, keep head+tail) | Open Interpreter `max_output=2800`; Anthropic: "truncate in your application before returning to model" |
| Timeout | Default 60s (`ZUMBA_SHELL_TIMEOUT`), per-call override; on timeout return partial output + note | Anthropic bash tool `timeout` param |
| Background jobs | `run_in_background: true` -> job id immediately; `shell_jobs` / `shell_kill` tools poll/stop it | Anthropic `run_in_background` param |
| Speed | `subprocess.Popen` with pipes, non-blocking reads via a reader thread; PowerShell `-NoProfile -NoLogo` startup flag (cuts ~300-800ms cold start) | Windows perf best practice |
| Cwd | Session remembers `cwd`; tool accepts optional `cwd` param that does `Set-Location` and persists | Claude Code Bash tool cwd persistence |
| Audit | Every command + exit code + timestamp appended to `~/.zumba/shell_audit.log` | Open Interpreter conversation-history-as-audit pattern |
| Interactive cmds | Not supported (no stdin) — clear error on stdin-hang timeout | Anthropic limitation note |

### New module: `shelltool.py` (root, ~250 lines)
```python
class ShellSession:                 # singleton, lazy
    start()  -> spawn powershell -NoProfile -NoLogo
    run(cmd, timeout_s=60, cwd=None) -> {exit_code, stdout, stderr, truncated, duration_ms, timed_out}
    run_background(cmd) -> job_id
    job_status(job_id) / job_output(job_id)
    interrupt()                     # kill current foreground proc (Ctrl-C equivalent)
    close()
```
- Reader thread per stream feeding a `queue.Queue` so output can be live-tailed into the chat UI (same style as `main.py:_mcp_agent_turn.on_tool`).
- Exit code + duration always returned; errors use the existing `ERROR:` text convention (`mcpclient/builtin.py:handle`).

### Integration
1. **As builtin tools** (fits the virtual-server pattern in `mcpclient/builtin.py`):
   - `zumba__shell_run`   {command, timeout_s?, cwd?, run_in_background?}
   - `zumba__shell_jobs`   {} (list background jobs + status)
   - `zumba__shell_kill`   {job_id}
   Registered in `BUILTIN_TOOLS` + dispatched in `handle()` — zero new plumbing.
2. **`/shell <cmd>`** in-chat command: runs directly (bypasses model), Panel with output + exit code + timing.
3. **`python main.py shell "cmd"`** one-shot CLI subcommand (exit code propagates for scripting).
4. Kill-switch: `ZUMBA_NO_SHELL=1` removes the tools (same graceful-degrade convention as memory/MCP).
5. System preamble gains one line: shell is persistent + unrestricted, so chain state (`cd`, `$env:X=...`) instead of re-stating it.

### Tests (`tests/test_shell.py`)
- cwd persistence across two `run()` calls; env var set in call 1 visible in call 2
- timeout returns partial output + `timed_out: true`
- head+tail truncation at cap
- background job: start -> poll -> complete
- `ZUMBA_NO_SHELL=1` hides tools
- audit log written (mock `~/.zumba`)

### Acceptance
"Check my python version, create a venv, pip install rich in it" -> model chains 3+ commands in one persistent session, sees real output, per-command overhead < 100ms after warm start.

---

## TASK 1: KILL THE OVERFIT SALIENCE KEYWORDS
**Problem (code):** `memory/service.py:22-35` — `_CORRECTION_CUES` / `_FACT_CUES` hardcode `"krish"`, `"ankit"`, `"not game"`, `"agent not game"`. One user's chat log, fossilized in source. Misses real facts, false positives.
**Fix:**
1. Delete `_looks_like_correction` / `_looks_like_fact` and the cue tuples.
2. `ingest_episode` (service.py:136-138) trusts `extraction.should_remember()` (the LLM salience gate) alone.
3. Harden the gate in `memory/extraction.py` `SALIENCE_PROMPT`: few-shot contrast pairs (memorable vs not) covering corrections, identity, preferences, projects, people — generic, no personal names; plus "bias toward memorable for first-person statements: false negatives lose the user's identity forever, false positives only cost tokens."
4. **Speed guard** (replaces the keyword fast path): 0-cost check before the LLM call — embed-similarity vs ~8 generic templates ("user corrected a previous fact", "user stated a stable personal fact", ...) + first-person pronoun check. Skip extraction only if all miss. Pure generic logic.
**Tests:** update `tests/test_memory.py` — corrections with unseen names get extracted; chit-chat doesn't; no test references personal names.

## TASK 2: CONTEXT WINDOW MANAGER (reliability fix)
**Problem (code):** `chat.py:41-45` token estimate is `len//4` and nothing consumes it; long sessions + memory block + 10 retained tool transcripts (main.py:138-148) grow unbounded until the API rejects.
**Fix — new module `context_budget.py`:**
1. `estimate_tokens(text)`: chars/4, code/JSON blocks ~3.5, non-ASCII ~1.5 chars/token. No tokenizer dep.
2. `build_window(messages, model_limit, reserve_out=1500)` -> fit-to-budget list:
   - always keep: system messages, first user message (session anchor), last N turns
   - middle overflow -> **rolling summary**: one LLM call condenses dropped turns into a `Session so far:` system note (cached; rebuilt only when >= 6 new turns dropped since last build)
   - tool transcripts older than the last 2 tool exchanges truncated to 200 chars
3. Wire into `_mcp_agent_turn` (main.py:102) and the plain chat path before `chat_completion`.
4. Limit from `ZUMBA_CONTEXT_LIMIT`, fallback 8192 (safe for free models).
**Tests:** 50-turn synthetic convo collapses under limit; system + anchor + last 2 turns always survive; summary injected exactly once; estimator monotonic.

## TASK 3: PERSONA LAYER (identity only — profile injection deferred)
**Problem (code):** `main.py:584` system prompt is `"You are Zumba, a concise helpful personal assistant."` No identity, no tone.
**Fix:**
1. New `persona.py`: `build_system(base: str) -> str` composes:
   - **Identity block** (constant): name Zumba; voice (direct, warm, zero fluff, uses your context without being asked); memory-aware behavior ("you have long-term memory; reference remembered facts naturally, never say 'as an AI'"); tool behavior (shell + MCP, be decisive)
   - **Style prefs** from `store.py config_get('style')` so tone is editable via `zumba config` without code changes
2. Apply in `chat` default; `--system` flag still overrides everything (current behavior preserved).
3. **Deferred on purpose:** injecting user profile / core blocks into the persona — Tier 2's user-model work. Mark `# TODO(tier2-profile)`.
**Tests:** composes with empty config; `--system` wins; no network calls.

## TASK 4: `/why` — MEMORY PROVENANCE
After each reply Zumba injects a recall block; make it inspectable.
1. Chat turn stashes the exact injected memory text + hit kinds/scores (retrieval already returns `MemoryHit.score/meta` — pass through, don't recompute).
2. `/why` prints a Panel: memories that fired, kind, score, recall query used.
3. `/why off|on` toggles capture (default on; zero extra cost — data is already in hand).
**Tests:** recall-hit passthrough; `/why` renders with and without hits.

---

## BUILD ORDER (dependency-driven)
| # | Task | Effort | Depends on |
|---|------|--------|-----------|
| 1 | TASK 1 salience cleanup | S | none |
| 2 | FEATURE 0 shell tool core (`shelltool.py` + tests) | M | none |
| 3 | FEATURE 0 integration (builtin tools, /shell, CLI, preamble) | M | 2 |
| 4 | TASK 2 context budget | M | none |
| 5 | TASK 3 persona | S | none |
| 6 | TASK 4 /why | S | none |

Tasks 1, 4, 5 are independent. Shell tool is the headline — build its core module first so ZUMBA can dogfood it while building the rest.

## DEFINITION OF DONE (whole tier)
- `python -m pytest tests -q` green, incl. new `test_shell.py`, updated `test_memory.py`, new `test_context_budget.py`
- One full session: memory capture -> mid-session shell chaining -> 40+ turn session without context blowup -> `/why` explains the last recall
- No hardcoded personal names anywhere in `memory/` (grep clean)
- README: shell tool section + updated architecture notes
