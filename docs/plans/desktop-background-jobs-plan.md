# Desktop Background Jobs — Deep Plan (Browser-First, Cron-At-Time)

> Status: P0–P2 implemented and exercised in development and a packaged Windows app.
> Evidence and remaining platform checks: [implementation ledger](desktop-background-jobs-implementation.md).
> User decision, 2026-09-27: background jobs use isolated Chromium only. The Chrome
> background options below are superseded; Chrome remains available for foreground work.
> Desktop only: no mobile connection, mobile scheduler or mobile UI is included.
> Scope lock: browser jobs first, cron-at-time first, no watches, no heartbeat nudge v1.
> Decisions locked: results land in owning teammate thread (Option A), run in background on
> minimize + close-to-tray, per-routine allowlist, full-parity browser tool, minimized jobs
> pill on the composer.

## 1. Goal

Ship scheduled browser work in the desktop app that:

1. Runs a user prompt at a specific time (`daily 08:00`, `0 9 * * 1-5`, `every 2h`).
2. Drives the full browser (open, read, fill, click, submit, login, batch) headless to do
   real tasks such as posting content at a set time.
3. Reports back into the owning teammate chat with proof, without blocking normal chat.
4. Asks for approval through calm inline UI, not blocking modal spam.
5. Keeps running when the window is minimized or closed-to-tray.

Non-goals v1: URL watches (`src/automation/watcher.mjs`), heartbeat idle nudges, true-quit
daemon sidecar, cross-device sync, full cron management page.

## 2. What already exists (reuse, don't fork)

| Piece | Location | Reuse |
|---|---|---|
| Cron parse/match/describe | `src/automation/cron.mjs:81` `normalizeSchedule`, `matchCron`, `describeCron` | Use as-is for trigger + labels |
| Durable routine store | `src/automation/routines.mjs:31` `RoutineStore`, `dueRoutines:195`, `_fresh:66` multi-writer guard | Extend schema, keep atomic JSON write |
| Daemon loop | `src/automation/daemon.mjs:61` `dispatchRoutines:288`, `chain:649` concurrency gate, `drain:684` | Wrap with desktop adapters, don't copy |
| Schedule tool (chat-native CRUD) | `tools/automation/schedule.mjs:47` `add/list/remove/enable/disable/run` | Extend params, keep action names |
| Desktop engine + agents | `desktop/electron/engine.mjs:227` `agentFor:672`, `send:707`, `browserManager:273`, `emit:262` | Background workers share `client/tool/mcp/browserManager` |
| Browser tool (full parity) | `tools/browser/browser.mjs:11` actions, `needsApproval:32`, `display:39` redaction | No subset — background gets all actions |
| Browser session/live preview | `tools/browser/session.mjs`, `desktop/renderer/src/components/BrowserStage.tsx:17` | Separate job tabs, shared preview component |
| Approval backend | `desktop/electron/approvals.mjs:9` `request/respond/cancelThread` | Keep; add routine-aware rendering |
| Approval modal (live chat only) | `desktop/renderer/src/components/ApprovalDialog.tsx:13` | Keep for live turns; scheduled jobs use inline cards |
| Chat + composer + store | `desktop/renderer/src/components/ChatPane.tsx:63`, `Composer.tsx:249`, `state/store.ts:6` | Add jobs pill + job cards, new events |
| IPC bridge | `desktop/electron/main.mjs:160`, `desktop/electron/preload.cjs:4` | Add `schedule*` actions |
| Alert copy pattern | `src/automation/alerts.mjs:35` model-composed + plaintext fallback | Same pattern for job result summaries |

## 3. Architecture

### 3.1 Host: Electron main process

New module `desktop/electron/scheduler.mjs` (`DesktopScheduler`):

```text
Electron main (Node)
├── DesktopEngine (chat agents, MCP, BrowserSessionManager, SecureStore)
└── DesktopScheduler (owns RoutineStore + Daemon tick)
    ├── runPrompt(prompt, routine) → isolated job worker Agent
    ├── deliver(text, routine)     → append summary+proof to owning thread
    └── confirm(tool, detail, routine) → allowlist check → auto-allow | pause + inline card
```

Why main, not renderer: survives window hide/reload, has Node fs + Electron
`Notification` + tray, shares the same authenticated `client/tool/mcp/browserManager`
as chat, no sandbox/CORS limits. Tick 20s (configurable, documented with unit).

Lifecycle:

* Start after `engine.init()` in `desktop/electron/main.mjs:createWindow`.
* Stop in `engine.close()` / `window-all-closed`: `scheduler.stop()` → `daemon.drain()` →
  `saveSession` for touched threads → log stats.
* Single-instance lock already prevents double-fire; `RoutineStore.lastRun`
  per-minute guard (`routines.mjs:195`) covers sleep-wake catch-up (run once, banner
  "ran late after sleep" if needed).

### 3.2 Job worker isolation (jobs never hinder main chat)

```text
main agent:  engine.agentFor(threadId) — drives ChatPane turns, turns.has(threadId)
job worker:  scheduler.createWorker(routine) — fresh Agent({
               client, tool, mcp, browserManager: engine.browserManager,
               config snapshot, browserThreadId: `job:{routine.id}:{runId}` })
```

Rules:

* Separate `Agent` instance, separate `Daemon.chain` key (`job:{id}` vs `chat:{threadId}`).
  Chat always has its own concurrency slot; `maxConcurrentJobs = 1` (named constant,
  serial browser jobs only — avoids two Chromiums fighting).
* Separate browser tab via `browserThreadId = job:{id}` so a posting job never steals
  the tab the user watches. `Watch live` explicitly calls `browserSessionTakeover`.
* Separate run transcript: `sessions/jobs/{routineId}-{ISO}.json`. Only the final
  summary + proof links are appended to the owning `teammate-{id}.json` thread.
* Retention cap (review fix): job transcripts are pruned to the last
  `JOB_HISTORY_KEEP` runs per routine (default 30 — named constant). Pruning runs on
  job completion (delete oldest beyond the cap), never while a run is in flight.
  Trivial now, painful to retrofit once disks fill with screenshots.
* Timeout kill per run (`JOB_TIMEOUT_MS`, default 3 min — named constant with unit
  comment). Timeout settles only the job promise and emits `routine-failed`; main
  thread gets a one-line failure card, never a stuck spinner.
* If `turns.has(threadId)` when a job finishes, queue delivery and emit
  `routine-queued`; flush at `turn-end`. Never interleave deltas.

### 3.3 Trigger: cron-at-time only v1

* Accept: `0 8 * * *`, `daily 08:00`, `weekdays 09:30`, `every 30m`, `@daily/@hourly`.
* Display: `describeCron()` label everywhere ("weekdays at 09:00").
* Timezone: resolve once from `config.timeZone`; note current `matchCron` uses local
  `Date` — scheduler must pass TZ-aware `now` or jobs fire at the wrong hour.
  Filed as build blocker in §7.
* Stale-run policy (review fix): "on wake run at most once" is not enough. Each run
  carries its nominal fire time; on tick compute `lateness = now - nominalFire`.
  If `lateness <= CATCH_UP_WINDOW_MS` (default 30 min — named constant with unit
  comment) run once and note "ran Xm late". If later, mark the run `missed`
  (`lastStatus: "missed"`, `lastSummary` keeps the nominal time), do NOT fire.
  Stale posts are worse than missed posts. Missed runs surface in the jobs pill
  (`○ Price check — missed 09:00 run (laptop asleep) [Run now]`) and in
  `schedule_status`, never silently.
* Overlap rule (new): if the previous run of the same routine is still in flight when
  the next fire arrives, skip the new fire (`lastStatus: "skipped-busy"`), note it in
  the transcript, do not queue a pile-up. Serial browser (`maxConcurrentJobs = 1`)
  plus this rule means a long posting job can delay but never duplicate itself.

## 4. Browser: full parity, zero exclusions

Background workers call the same `browser` tool with the same `parameters` schema:

`open, snapshot, act, fill_form, read, tabs, screenshot, close, batch, login`
plus `mode: auto/isolated/local`, same `normalizeBrowserArgs`, same snapshot `refs`
(`tools/browser/refs.mjs`), same `MAX_BROWSER_FORM_FIELDS` / `MAX_CREDENTIAL_FIELDS`
limits, same `display()` redaction (`[N characters hidden]` — what gets stored/shown,
never raw secrets).

Posting recipe (example "weekday 09:00 post"):

```text
batch: open(url) → snapshot → fill_form(fields) → act(click submit) → screenshot
```

* Default `headless: true`, `mode: isolated`. `local` (user Chrome) allowed only if the
  routine explicitly selects "My Chrome" and that Chrome is approved/connected.
* `login`/private credentials flow through the existing vault
  (`SecureStore` + `CredentialRequests`); `browserCredentialAllowed` is scoped to the
  routine's allowlist (see §5), never global.
* Proof on delivery: final `screenshot` thumbnail (size-capped; live frames stay in
  `BrowserStage`, chat keeps the `BrowserRunCard` pattern from `BrowserStage.tsx:8`),
  final URL, and a 1–2 sentence "what I posted" summary (model-composed with plaintext
  fallback, same pattern as `alerts.mjs`).
* The *capability* is identical; only the *approver* differs (§5).
* No-retry rule v1 (review fix — stated explicitly): a browser job is never
  auto-retried. Not on tool error, not on timeout, not on failed delivery. A retry of
  a half-completed post risks double-posting, and no per-day cap fixes that after the
  fact. Failure → `routine-failed` card with the redacted step it died on → human hits
  `Run now` (which is a deliberate new run with a new run number, not a hidden retry).
  Delivery-side retries (appending the already-produced summary to the thread) are
  allowed and must be idempotent via the run id — re-delivery never re-executes the
  browser.

## 5. Permissions: per-routine allowlist + calm UI (no popup spam)

### 5.1 Data model (extends `RoutineStore.addRoutine`)

```text
routine = {
  id, name, cron, prompt, threadId,            // threadId = owning teammate
  allow: {
    read:     true,                             // open/snapshot/read/tabs/screenshot
    interact: false,                            // act/fill_form/batch-with-writes
    login:    false,                            // login + SecureStore use
    sites:    ["https://app.example.com/*"],    // empty = ask on every new domain
    mode:     "isolated"                        // isolated | local
  },
  onNewRequest: "pause-ask",                    // pause-ask | deny | allow-once (v1: pause-ask default)
  headless: true,
  timeoutMs: 180000,
  budget: { maxRunsPerDay, maxTokensPerDay, maxMinutesPerDay },  // §10, defaults as constants
  spend: { day, runs, tokens, minutes },                         // reset on day rollover
  pausedReason: null,                          // "budget" when auto-paused by §10
  enabled, lastRun, lastStatus, lastSummary, runs
}
```

Default under debate (see §9): ship default `read:true, interact:true (current-site
only), login:false` for a smooth posting demo, or strict `read-only until ticked`.
Either way the sheet makes the default visible.

Schema migration for existing routines (review fix #7 — must-fix, not nice-to-have):
anyone already running CLI routines has records without `allow`, `threadId`,
`timeoutMs`, `budget`, etc. The desktop tick must never crash on them. Rule: normalize
on read, persist on next write. `RoutineStore.load()` (and every `_fresh()` reload)
passes each record through `normalizeRoutine()` which backfills missing fields with
the §9 v1 defaults (`allow: { read:true, interact:true current-site-only,
login:false, sites:[], mode:"isolated" }`, `threadId: null → orphan path per §5.5`,
`timeoutMs: JOB_TIMEOUT_MS`, `budget: default per §10`, `spend: zeroed for today`).
Additive change — no `STATE_VERSION` bump needed; if a future change is breaking,
bump the version with an explicit migrator instead of silent defaults. Regression
test: load a v0 record (id/name/cron/prompt only) and assert the first desktop tick
treats it as the default allowlist rather than throwing.

Enforcement point: `scheduler.confirm()` before `approvals.request()`:

1. `readOnly(args)` (`browser.mjs:33`) → auto-allow.
2. `needsApproval(args)` + `tool+site` inside `allow` → auto-allow silently.
3. Else → pause job chain, persist `pendingApproval { routineId, runId, tool, redactedDetail }`,
   emit `approval-request` with `routineId`, post inline card (§5.3), OS notify.

Never allow in background v1 even if ticked: fresh-password `login` prompts, unapproved
`local` Chrome attach, `run_command`/shell writes (browser jobs only). These resolve to
"open desktop to complete" guidance, not a vault prompt at 3 AM.

`Always` grants are per-routine (`allow` mutation), never global. Revoking one routine
never affects others or live chat.

### 5.2 Routine permission sheet (creation + edit)

Non-blocking drawer (sidebar or right panel), not `modal-backdrop`. Opened when the
agent drafts a routine ("post this every weekday at 9") and anytime via thread header
`⏰ N jobs` chip:

```text
⏰ Morning post — weekdays at 09:00 — in [Teammate ▾]
Prompt: [editable textarea — every instruction lives here, nothing else is passed]

Browser can:
  [x] Open & read pages        open / snapshot / read / tabs / screenshot
  [x] Fill & click             act / fill_form / batch
  [ ] Log in as me             login + saved credentials
  Sites: [app.example.com/*] [+ add]   (empty = ask on each new domain)
  Chrome: (•) Isolated   ( ) My Chrome

On something new: (•) Pause job + ask in chat   ( ) Deny silently
[Save] [Run now to test] [Pause routine]
```

Backed by extended `schedule` tool params
(`threadId, allow{read,interact,login,sites,mode}, timeoutMs`) so chat-native creation
("schedule this") and GUI edits share one truth. Every create/edit shows the
`describeCron` preview before save.

Run context injection (review fix): "every instruction lives in the prompt" breaks for
time-sensitive prompts ("post today's update") — the worker prepends a run header
automatically, never trusting the stored prompt to know the date:

```text
[Scheduled run: "Morning post" · run #42 · Tue 2026-09-29 09:00 Asia/Kolkata
 (nominal fire; actual start 09:01, 1m late inside catch-up window)]
<User's stored prompt follows verbatim below>
```

Includes: routine name, run number (`runs + 1`), nominal fire time + TZ, actual start +
lateness, attempt number (always 1 in v1 — see no-retry rule). The header is part of the
saved job transcript so "why did it say Tuesday?" is always answerable.

### 5.3 Inline approval / review cards (runtime)

Scheduled approvals render as transcript cards in the owning thread, never as the
blocking `ApprovalDialog` modal:

```text
⏰ Morning post needs more access — paused at step 3/5
Wants: Browser: fill 3 fields on https://new-site.example/post   (values hidden)
[Allow this step] [Always for this routine] [Edit permissions] [Skip run]
Last 5 runs: ok, ok, paused-needs-approval, ok, ok   [View proof]
```

* Persisted with an expiry (review fix): an unanswered card must never wedge the
  routine. Each run's approval window is `APPROVAL_TIMEOUT_MS` (default 1 hour —
  named constant). Unanswered at timeout → the worker settles the run as
  `skipped-no-approval`, keeps the routine enabled, posts a one-line transcript note
  ("09:00 run skipped — no answer within 1h"), and clears that run's pending entry.
  Answering applies to the in-flight run only; the next scheduled run raises its own
  card. When a new fire supersedes an old unanswered card, the old card is visibly
  marked `superseded` (greyed, actions disabled), not silently deleted, so the audit
  trail stays intact. `Esc` collapses, never denies.
* Same `ApprovalRegistry.requestId` underneath; answering from card or jobs pill
  calls the same `respondApproval`.
* Tray/blurred: OS `Notification` only for `needs-approval` and `failed`, never for
  routine success (success is a quiet transcript append + unread dot).

### 5.4 Audit + revoke

Routine detail shows: last-run status/summary/proof (screenshot thumb + URL + posted
text), tool calls made (redacted via `display()`), approvals granted. One-click
`Pause routine` / `Pause all jobs` (tray + settings). Audit log per routine allows
"why did it post that?" answers.

### 5.5 Orphaned routines (review fix #9)

Every routine delivers to an owning `threadId` — but teammates can be deleted, so a
job can fire, succeed, and deliver into the void. Rules:

* On fire and on delivery, resolve `threadId` against the live teammate list. If the
  owner is gone, the run still executes (no silent work loss) but delivery falls back
  to the most recently active teammate thread, else the first teammate, with a header
  note: "⏰ Morning post — its owner teammate was deleted. [Re-home routine]".
* The routine is flagged `ownerMissing: true` in `scheduleList`/`scheduleStatus`,
  the jobs pill shows `⚠ Morning post — owner missing [Re-home]`, and the routine
  sheet opens with a teammate picker focused. Re-homing is one click
  (`scheduleUpdate { id, patch: { threadId } }` clears the flag).
* `scheduleAdd`/`scheduleUpdate` with an unknown `threadId` rejects loudly at call
  time ("teammate not found") — orphans only ever arise from later deletion, never
  from bad creates. Deleting a teammate with routines attached warns first
  ("2 routines deliver here — they will fall back until re-homed") and offers
  re-home inline.

## 6. UX: minimized jobs pill + main-agent awareness

### 6.1 Jobs pill on the composer

Directly above `Composer.tsx:249 composer-shell`, collapsed by default, typing never
blocked:

```text
collapsed:  ⏰ 1 needs approval · 1 running · next in 25m   [expand ^]
expanded:
  ⏰ Evening post — needs approval: fill 3 fields on x.com      [Review][Allow][Deny]
  ▶ Morning brief — running step 3/5 (browser snapshot…)       [Watch live]
  ○ Price check — next 09:00 (in 14h 12m)                       [Run now][Pause]
```

* Source: engine events (`schedule-changed`, `routine-run-start/step/end`,
  `approval-request`) into a new `jobs[]` slice in `state/store.ts` (mirrors
  `running`/`unread` pattern, per-thread).
* `Review` scrolls to the inline card + opens `BrowserRunCard` preview for browser jobs.
* Failure card is one line + `[Review]`; success is quiet (transcript append only).

### 6.2 Main agent as reporter (separate but aware)

Main chat agent never executes jobs; it reports on them:

* New read-only tool `schedule_status` for the main agent:
  `[{ id, name, cronLabel, nextRunIn, lastStatus, needsApproval }]`,
  with `nextRunIn` from `matchCron` + due computation, formatted via
  `lib/relative-time.ts`.
* System prompt line: "You have background jobs. For 'what's next' call
  schedule_status. Never claim you ran a job — quote its last summary."
* Welcome suggestion: "What's scheduled next?" → calls the tool → "Evening post runs
  in 25 min; Morning brief last posted ok at 09:00."

Matches the reference mock: left nav (Main chat / Side chats), center transcript with
job result cards, right "Today" completed-jobs list, and the minimized `View scheduled
task` affordance becoming the jobs pill.

## 7. Background execution (minimize + close-to-tray)

* **V1 ship:** minimize-to-tray + close-to-tray. `window-all-closed`
  (`main.mjs:307`) hides instead of quitting; tray menu: `Show / Pause jobs / Quit`.
  `app.setLoginItemSettings` for autostart (opt-in). This covers minimize and X-close
  with zero new processes.
* **Explicit limit:** real Quit pauses jobs; settings states this plainly
  ("Jobs pause when you Quit — keep running in tray to stay scheduled").
* **V2 (not v1):** headless `ankita --daemon` sidecar sharing the same store file via
  `_fresh()` reload; desktop becomes viewer/approver. Do not build for v1.
* Sleep: `lastRun` guard dedupes; late runs follow the stale-run policy in §3.3
  (inside window → run once with "Xm late" note; outside → `missed`, no fire).
* Single-owner guard v1 (review fix — double-fire is the nightmare for posting jobs):
  the CLI daemon and `DesktopScheduler` tick the same `RoutineStore`, so running both
  fires every routine twice. V1 rule: desktop claims ownership with a lockfile
  (`CONFIG_DIR/scheduler.lock` — pid + heartbeat timestamp, stale after
  `LOCK_STALE_MS`); while the desktop lock is live the CLI `daemon` command refuses to
  start schedules with a loud error ("desktop scheduler owns routines — stop the
  desktop app or pass --takeover"). Document the same warning in `--help` and in the
  desktop settings screen. No silent dual-run, ever.

## 8. IPC + store contract deltas (build checklist)

Engine (`main.mjs:160`, `preload.cjs:4`):

* `scheduleList { threadId? } → Routine[]` (with `cronLabel`, `nextRunIn`, `lastStatus`,
  `ownerMissing`, `pausedReason`)
* `scheduleAdd { name, cron, prompt, threadId, allow, timeoutMs, budget } → Routine`
* `scheduleUpdate { id, patch } → Routine` (prompt/allow/enabled/sites/mode/budget/threadId re-home)
* `scheduleRemove { id }`, `scheduleEnable { id, enabled }`, `scheduleRunNow { id }`
* `scheduleStatus → [{ id, name, cronLabel, nextRunIn, lastStatus, needsApproval, ownerMissing, pausedReason }]`

Events (`shared/wire.ts`, `store.ts` reducer):

* `schedule-changed`, `routine-run-start`, `routine-run-step { step }`,
  `routine-result { threadId, routineId, text, proof }`, `routine-failed`,
  `routine-queued`, `approval-request { routineId? }` (extended, not replaced).

Renderer:

* `JobsPill` (collapsed/expanded) above composer; `JobCard` in transcript;
  `RoutineSheet` drawer; thread header `⏰ N jobs` chip; tray tooltip sync.

## 9. Defaults — locked (reviewer confirmed)

1. Allowlist default: `read:true, interact:true current-site-only, login:false`, with
   the permission sheet always shown at creation so the default is never silent.
2. Tray: hide-on-close with first-run notice + `Pause all jobs` in tray.
3. Serial browser: `maxConcurrentJobs = 1`.

## 10. Safety, privacy, limits (extended with review findings)

* Redaction: store/display only `display()` output; never persist filled secrets,
  snapshot bodies, or credential fields.
* Site allowlist enforced in `browserManager.run`, not just in the prompt.
* Per-run timeout, per-day run cap, per-routine site cap (named constants with units).
* Per-routine resource budget (review fix #8): unattended jobs burn tokens while you
  sleep — a `every 30m` job with a long prompt gets expensive fast. Each routine
  carries `budget: { maxRunsPerDay, maxTokensPerDay, maxMinutesPerDay }` (defaults as
  named constants, editable in the routine sheet) and a rolling `spend: { day, runs,
  tokens, minutes }` reset on calendar-day rollover (same TZ as the schedule).
  The job worker accumulates from the agent's existing `onUsage` callbacks (the same
  events `store.ts` already reduces into `usage`) plus wall-clock minutes. When any
  leg trips mid-run, the run finishes the current step then stops
  (`lastStatus: "stopped-budget"`); the routine auto-pauses (`enabled: false`,
  `pausedReason: "budget"`, `lastSummary` names the tripped leg) and the thread gets a
  card ("⏰ Price check paused — hit 50k tokens today. [Raise limit] [Resume]").
  Resume requires a human click; spend resets the next day but `enabled` never
  flips back on its own.
* First login to a new site always requires foreground (`Take control` flow in
  `BrowserStage`), never headless autofill.
* Run-now single-flight: `scheduleRunNow` while the same routine is in flight or has a
  pending approval is a no-op with a notice ("already running — watch it live"),
  never a second parallel run. Disabling a routine mid-run lets the run finish but
  records `disabled-mid-run`; it never starts another.
* Idempotency note for posters: `Run now` after a suspected-but-unconfirmed post must
  show the last proof first ("last run posted at 09:01 — [proof] — run again anyway?").
  The worker cannot know whether a killed run posted; the UI makes the human decide
  with evidence, per the no-retry rule.
* OS-lock behavior: when the OS session is locked, scheduled runs still fire headless
  (tray process is alive) but any step needing foreground/takeover or vault unlock
  resolves to `skipped-needs-foreground` with a transcript note — jobs degrade to
  read-only rather than failing on credentials they can't reach.
* All literals hoisted to named constants/config (repo rule); no magic strings,
  ports, timeouts, or paths inline. Constants introduced by review:
  `CATCH_UP_WINDOW_MS`, `APPROVAL_TIMEOUT_MS`, `JOB_TIMEOUT_MS`,
  `JOB_HISTORY_KEEP`, `LOCK_STALE_MS`, `BUDGET_DEFAULT_MAX_RUNS_PER_DAY`,
  `BUDGET_DEFAULT_MAX_TOKENS_PER_DAY`, `BUDGET_DEFAULT_MAX_MINUTES_PER_DAY` —
  each with unit + why in a comment.

## 11. Verification (repo gates)

* `node --test` for touched suites + live round trip per changed path.
* Reproduce-then-fix for scheduler bugs with before/after traces.
* New behavior ships with a regression test that fails without the fix.
* Cover both browser backends touched (Playwright isolated + Chrome local) — real run
  where possible, stub-driven where not; state which was which.
* Quote exact outputs/counts and file paths with line numbers; update this doc with
  what changed, what verified it, and what remains uncovered.
* End implementation reports with `**Confidence: X/100.**` plus the +/- ledger and
  residual risks (per `AGENTS.md`).

## 12. Phased build

* **P0:** `DesktopScheduler` + cron fire → isolated worker → deliver to owning thread.
  No UI beyond transcript append. Proves `runPrompt/deliver/confirm` path.
* **P1:** `schedule*` IPC + `schedule` tool extension + routine sheet + jobs pill
  (collapsed/expanded) + `schedule_status` for main agent.
* **P2:** Full-parity browser posting (batch + login restore + proof cards) + site
  allowlist enforcement + inline approval cards + tray BG + OS notifications.
* **P3 (later):** watches, heartbeat nudges, true-quit sidecar, Today digest panel.
