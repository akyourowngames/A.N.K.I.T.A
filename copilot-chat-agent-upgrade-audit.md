# copilot-chat — agent upgrade audit

Reviewed: `C:\Users\anime\3D Objects\copilot-chat` · 2026-09-17

---

I read the whole thing — `chat.mjs` → `src/cli.mjs` (REPL/slash commands) → `src/agent.mjs` (stream + tool loop) → `tools/*` (5 tools) → `src/markdown.mjs` + `src/ui.mjs` (rendering) → `src/auth.mjs` (Copilot device flow). All files pass `node --check`. Here's the audit.

## Verdict

Solid architecture for its size: tools are self-describing modules (`specs`/`get`/`names` in `tools/index.mjs`), the agent loop is decoupled from the UI via callbacks, and the stream renderer already does syntax highlighting, tables, and reflow-safe redraws. The upgrade headroom is mostly **context-window safety, approval ergonomics, and a few real bugs** — not missing features per se.

---

## A. Actual bugs (verified, not style opinions)

1. **`run_command` output is injected into the context unbounded.**
   `tools/run-command.mjs:54-66` accumulates every byte of stdout/stderr; `src/agent.mjs:216-218` pushes it straight into `messages`. `read_file` caps at 400 lines/5MB, but one `Get-ChildItem -Recurse`, `npm install`, or build log can dump megabytes in permanently. `onToolResult` clips only for *display* (`cli.mjs:289`, 4000 chars) — the model still gets all of it. Fix: cap in the tool (head+tail truncation, ~64KB) **and** a generic per-result cap in `Agent.runToolCall`.

2. **History trimming never runs mid-task.** `trimHistory` is called only on the terminal no-tool-call path (`agent.mjs:210`), so a 16-step loop with big tool results (`MAX_TOOL_STEPS`, `agent.mjs:7`) never trims. Combined with #1 this is the main way the context blows up.

3. **`history` file duplicates forever.** `ui.mjs:92-97` *appends* the newest 100 entries on every exit instead of rewriting. Already visible on this machine:

   ```
   total lines: 519   unique lines: 16
   ```

   Fix: rewrite the file trimmed to 500 (and dedupe).

4. **`Agent.autoApprove` is dead code.** Set in `agent.mjs:44`, never read in `agent.mjs` — only `cli.mjs:209` (inside the confirm callback) honors it. Any other consumer of `Agent` (tests, a future `--json` front-end) silently ignores `-y`/`AUTO_APPROVE`. Fix: check it in `runToolCall` before calling `confirm`.

5. **Partial replies are lost on a mid-stream failure.** If the stream drops, `streamTurn` throws, and `send` never pushes the partial text — you pay for the tokens and see nothing. Fix: catch in `send`, keep `content` as an assistant message, and tell the model it was cut off.

6. **`pickModel` can choose a tool-less model while tools are on.** `cli.mjs:101-111` filters nothing; the only protection is a warning *after* the fact (`cli.mjs:240`). The preference list is also stale (`claude-3.5-sonnet`, `gpt-4o`). `auth.mjs:150` already fetches `capabilities.limits.max_context_window_tokens` — nothing uses it.

7. **Version drift by construction.** `cli.mjs:10` hardcodes `2.0.0` alongside `package.json`. Read it from the package file.

---

## B. Safety / approval (highest-value work)

12. **Blind approvals.** `write_file` approval shows only the first 20 lines (`ui.mjs:29`); `edit_file` shows 400 chars of old/new (`edit-file.mjs:33-36`). For a large rewrite you're approving content you can't see. Render a unified diff against the current file.

---

## C. Tools (5 → the set that removes round trips)

13. **`search_files` / `glob`** — the missing piece. Today "where is X defined?" costs N×`run_command`, each dumping unbounded output (bug #1). A regex walker with include/exclude globs and a result cap pays for itself immediately. `list_dir` is also single-level only.

14. **Parallel tool execution.** `agent.mjs:214-219` awaits sequentially. Tag modules `readOnly: true` and run those batches with `Promise.all` — a 4-file read goes from 4 RTTs to 1.

15. **Fuzzy `edit_file` fallback.** `edit-file.mjs:49-55` is byte-exact only; whitespace/CRLF drift is the #1 failure for weaker models and each miss costs a full round trip. Ladder: exact → line-ending normalized → trailing-whitespace-trimmed → indentation-insensitive, still refusing on ambiguity, telling you which rung matched.

16. **Missing verbs:** delete/move/create-dir, `fetch_url` (right now docs/APIs need `run_command curl`), and a `write_todos` plan tool if you want it behaving like a real multi-step agent on big refactors.

17. **`run_command` gaps:** no stdin, no background jobs, no env override, no `pwsh` preference even when installed, and the abort path (`run-command.mjs:57-60`) doesn't `taskkill /T` — only the timeout path does, so Windows grandchildren can survive Ctrl-C.

---

## D. Model / API plumbing

18. **No `max_tokens`** in the body (`agent.mjs:80-89`) — add `MAX_TOKENS`.
19. **Reasoning models look frozen.** `consume` (`agent.mjs:126-139`) reads only `delta.content` and `delta.tool_calls`; `reasoning_content`/`reasoning_text` is dropped, so you stare at the spinner. Render it dimmed (and decide whether to persist it).
20. **No token/cost accounting.** `stream_options: {include_usage: true}` + a per-turn and session total on the existing status line (`cli.mjs:293`).
21. **Provider lock-in is optional.** `Agent` only needs `client.baseUrl` and `client.headers(stream)` — an `API_BASE`/`API_KEY` path for OpenAI-compatible endpoints (Ollama, LM Studio, OpenRouter) is ~40 lines and unlocks local models.
22. **Config layering:** `.env` is only read from cwd (`config.mjs:61`), so `/cd` + `/reload` silently switches config files. Add `CONFIG_DIR/config.env` as a fallback layer. Also `HISTORY_LINES` is really *messages* — rename/alias `HISTORY_MESSAGES`.
23. **`fetchWithRetry` retries hard failures 3× with backoff** — a bad base URL or DNS failure costs ~7s of pointless retries in one-shot `-p` mode.

---

## E. DX / polish

24. **No tests, no `npm test`.** `parseEnv`, `numbered`, `resolvePath`, `countOccurrences`, `trimHistory`, `renderMarkdown` are pure and dependency-free — `node:test` coverage for `edit_file` and history trimming (bugs #2/#3) would have caught both.
25. **No `--json` / `--plain` output**, so `-p` is useless in scripts (it emits box-drawing table/fence decorations even when piped).
26. **No autosave / `--continue`.** `/save` exists but nothing persists on exit, and `/load` doesn't sanitize `tool_calls`↔`tool` pairing, so a truncated session can 400.
27. **Terminal:** readline completes file paths but not slash commands, and there's no multiline paste mode.

---

## Suggested order

| Phase | Items | Why |
|---|---|---|
| 1 | #1, #2, #3, #4, #5 | Real bugs; two of them are already degrading your sessions |
| 2 | #8, #9, #10, #11, #12 | Makes auto-approve actually safe to use |
| 3 | #13, #14, #16 | Big capability jump for modest code |
| 4 | #18–#21, #24, #25 | Model ergonomics + tests that lock the fixes in |

Want me to start on Phase 1? I'd do it as one small commit-sized change: a per-result cap helper in `tools/_shared.mjs` used by `run_command`, a trim between tool steps plus an `autoApprove` check in `agent.mjs`, partial-content retention on stream failure, and `saveHistory` rewriting instead of appending. Say the word and I'll implement + verify it.