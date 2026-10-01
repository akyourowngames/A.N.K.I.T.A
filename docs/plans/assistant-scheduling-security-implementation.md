# Desktop scheduling, secret scrubber and command palette

Scope: desktop only. Source: secret-scrubber-command-palette-plan.md and the user's chat-first scheduling request. Existing worktree changes are retained.

## Decisions and interfaces

- Use the existing durable RoutineStore and desktop scheduler. Separate schedule definitions, execution claims and receipts; skip overlapping runs and bound catch-up. Research: [Temporal schedules](https://docs.temporal.io/workflow-execution/schedules).
- Expose a schema-described scheduling tool with structured receipts, ownership, idempotent creation, updates, pause/resume and explicit run-now. Ask the model to clarify missing task/time information. Tool descriptions follow [Anthropic's tool-use guidance](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview).
- User-authorized browser jobs can browse autonomously in isolated Chromium. Existing scoped jobs retain their explicit settings. Browser isolation, credential origin checks and cancellation remain enforced. Regular desktop jobs now use completion execution; explicit limits and heartbeat defaults remain bounded. See [completion fixes](scheduled-job-completion-fixes.md).
- Heartbeat uses the teammate's existing proactive context, checks only while idle, and stays quiet if there is nothing useful to report. Interval and instructions are editable.
- Ruling: core modules use .mjs plus declarations because this repository executes Node modules directly; the plan's TypeScript filename would not run in the current main-process setup.
- Ruling: labeled passwords are scrubbed even below the entropy threshold, as required by the plan's hunter2 example. Other generic tokens use the length and entropy threshold. Detection cannot cover arbitrary unlabeled or split secrets.
- Scrub copies at persistence/export boundaries; preserve raw live turns. Migration targets transcript/log/export artifacts, excluding operational provider configuration and encrypted vault files.
- Main-window palette uses existing theme and normal execution paths; it does not intercept shortcuts while another dialog is open.

## Completion ledger

1. Implemented deterministic scrubber and a 50-sample shaped/context/encoded corpus; normal text and sub-millisecond average checks pass.
2. Implemented copied persistence/export transforms, OS-encrypted save intent, transient echo protection, idempotent artifact migration, bounded text diagnostics and privacy settings. Ordinary pastes do not create vault records.
3. Implemented directly callable desktop scheduling, shared concrete update schema, active/idempotent creation, owner-scoped name resolution, canonical lifecycle guards, fresh project context, autonomous Chromium, heartbeat and compact cards/upcoming list. Empty/conflicting updates return errors; unambiguous flat updates normalize to a patch.
4. Implemented command/skill/job palette, validated manifests, fresh registry queries, main-process execution, keyboard/focus behavior and async result readiness guards.
5. Actual development and packaged Windows checks passed the local complex authentication system, repeated expired sessions and MFA. A real Kilo/Ling model independently created/updated the job, completed two expired-session sign-ins and posts, handed MFA back without guessing and completed a baseline browser task.
6. Fresh read-only review completed. Secret echo, legacy log, owner/name, detached-project, partial form, private shown-password, Chrome dialog/custom-toggle and bounded protocol findings have regression fixes. Final serial results are recorded below.

## Verification requirements

Capture failing regressions before implementation. Verify actual isolated browsers against multi-step authentication, expiring sessions and MFA requiring foreground input. Use a real configured model without printing/copying its API credentials. Verify model-created jobs and cards in the Electron renderer, reload persistence, independent foreground use, cancellation and no duplicate side effects. Record which paths are local test systems rather than public account sites.

## Executed evidence — 2026-09-28

| Path | Exact evidence |
| --- | --- |
| Focused scheduler/tool regression run | `30/30` passed, including shared schema, same-name owner isolation using the actual scheduler/store, normalized flat updates, conflicting/empty update rejection, canonical run receipt and detached project. |
| Browser hardening | `16/16` passed in `.commandcode/scheduled-browser-hardening.log`; `19/19` login/preflight tests passed after explicit-URL compatibility repair. RED traces included partial mutation, missing dialog rejection, lost shown-password classification and duplicate cleanup `2 !== 1`. |
| Final serial suite | `tests 832; pass 831; fail 0; cancelled 0; skipped 1` in `.commandcode/assistant-features-tests-ship.log`; exit 0. The skip is POSIX executable permission testing on Windows. |
| Desktop build | `tsc --noEmit` and Vite production build exited 0 in `.commandcode/assistant-features-build-final.log`. Existing bundle-size warning remains; no claim of bundle splitting. |
| Packaged app | `DESKTOP_ASSISTANT_FEATURES_OK: packaged=true; modelCalls=25; artifacts=...ankita-assistant-features-16z6wz` in `.commandcode/assistant-features-packaged-ship.log`; exit 0. Actual Electron UI, agent/tool execution, native OS encryption and isolated Chromium; model responses are scripted HTTP/SSE fixtures. Reload persistence, compact cards, thin upcoming rows, timezone/absolute next-run label, palette selection readiness and normal Enter execution all passed. |
| Local sign-in and MFA | `COMPLEX_SCHEDULED_LOGIN_OK` with exactly two posts, two password submissions, zero wrong credentials/query leaks; `MFA_NEEDS_FOREGROUND_OK` with no extra post or guessed code. Username-first, same-origin password iframe, CSRF, replaced control and expired session are all exercised. |
| Secret boundaries | `SECRET_BOUNDARIES_OK`: raw live input reaches the model fixture; generic and vendor-shaped save intent encrypts records; ordinary prefixed password echoes, legacy session/daemon migration, session/journal/job logs and exported chat contain none of the synthetic secrets. |
| Both browser contracts | `LIVE_JOB_BACKENDS_OK: Playwright + Chrome; posts=2; saved-login=1; shared connection preserved` in `.commandcode/job-browser-preflight-live.log`. Also `PRIVATE_PASSWORD_BACKEND_OK`, `FILL_PREFLIGHT_BACKEND_OK` for both, `CHROME_CUSTOM_TOGGLE_OK` and `CHROME_INTERRUPTED_FORM_OK` using the real bridge. Foreground tabs survive scope cleanup. Desktop scheduling still permits isolated Chromium only. |
| Real model scheduling and browser execution | `.commandcode/live-scheduling-provider-current.log`: `LIVE_MODEL_SCHEDULING_OK`; `LIVE_COMPLEX_LOGIN_OK: real model; username-first; password iframe; CSRF; expired session; posts=2; passwordSubmits=2; leaks=0`; `LIVE_MFA_BOUNDARY_OK`; `LIVE_PROVIDER_JOB_OK: provider=kilo; model=inclusionai/ling-3.0-flash-sante:free; browserSteps=25; posts=1; screenshot=true`. The final `posts=1` is a separate baseline form, in addition to the two complex-auth posts. |
| UI inspection | Viewed `scheduled-tasks.png` and `command-palette.png` from the final packaged artifacts `ankita-assistant-features-16z6wz`; compact task card, thin upcoming row, next-run label and selected palette result render correctly. Focus and normal Enter execution are exercised by the packaged verifier. |
| Independent review and whitespace | Fresh read-only reviewer reported no remaining blocker and `15/15` targeted tests passed. Final `git diff --check` exited 0. |

### Reproduction commands

```sh
npm test
npm run desktop:build
node scripts/verify-desktop-assistant-features.mjs --packaged --keep-artifacts
node scripts/verify-job-browser-isolation.mjs
node scripts/verify-desktop-job-provider.mjs --model inclusionai/ling-3.0-flash-sante:free --timeout-ms 600000 --keep-artifacts
git diff --check
```

The test script runs Node tests serially. The real-provider command uses the configured provider through IPC without printing or copying its API credentials. The timeout is a test-only upper bound in milliseconds.

## Scheduler UI restructure — 2026-09-30

Restructured the scheduled-task surfaces in `desktop/renderer/src/components` and their block in
`desktop/renderer/src/styles.css`:

- `JobsPanel` now groups tasks by state (Needs attention → Running now → Upcoming → Paused) with a
  count badge and a summary line, and replaces the raw `dl` with scannable stat tiles. The duplicated
  "Task instructions" prompt block was removed from the panel; the prompt stays visible and editable
  in the job editor (`RoutineSheet`).
- Latest-run receipt cards (`JobCard`) and inline task cards (`ScheduledTaskCard`) lead with a
  plain-language status badge and relative time instead of raw status/minute text.
- `JobsPill` gains an animated chevron and expand; `RoutineSheet` is regrouped into labelled sections
  with an animated disclosure. Motion is transform/opacity only and inherits the existing
  `prefers-reduced-motion` guard.

Evidence: `tsc --noEmit -p desktop/tsconfig.json` and `npm run desktop:build` exited 0.
`node --test test/desktop/*.test.mjs test/tools/*.test.mjs test/automation/*.test.mjs` →
`tests 441; pass 440; fail 0; skipped 1` (the skip is the existing POSIX-executable check on Windows).
A live Electron + Chromium round trip (`node scripts/verify-desktop-assistant-features.mjs
--keep-artifacts`) reached `MODEL_TASK_CARDS_OK` with the updated assertions — the group rows measure
under 65px, the detail renders `.job-stats` tiles including "Until complete", and `scheduled-tasks.png`
was captured. The run later failed in the scripted complex-login worker (`'error' !== 'ok'`), which is
browser/credential code untouched by this change; that scheduled-completion path is therefore not
re-verified here. The panel no longer mirroring the prompt required updating the corresponding
assertion in `scripts/verify-desktop-assistant-features.mjs` (prompt editability is still checked in
the editor via `getByLabel('Task instructions')`).

Follow-up after visual review: rows had no vertical gap, so adjacent hover/selected highlights
merged; the panel scroll gutter, group titles and detail padding were re-aligned to one 10/11px
gutter, and rows now sit in a 2px-gap flex column. The status colors I first used came from
`--success` (green), which is not the scheduler palette — they were replaced with theme tokens
(`--text-dim`/`--text-soft` for idle, `--gold`/`--accent-*` for running and attention, and the
neutral `--surface-hover`/`--edge-strong` for the completed badge). Re-ran `npm run desktop:build`
(exit 0) and the live verifier, which again reached `MODEL_TASK_CARDS_OK` with a fresh
`scheduled-tasks.png`; the scripted-login worker stopped at the same place as before this CSS change.

## Task ownership mismatch — 2026-09-30

**Reproduced:** opening **Scheduled tasks** from teammate A's conversation listed every teammate's
tasks. `ChatPane` (header chip + jobs pill) was passed `threadJobs` (filtered to the open teammate)
while `JobsPanel`/`RoutineSheet` were passed unfiltered `state.jobs` (`App.tsx:293`). Running a task
owned by teammate B from A's panel therefore executed as B's isolated worker and `deliverRoutine`
posted the narration into B's conversation — "jobs run in another agent and are delivered by another
agent". The chip could also read `2 jobs` while the panel listed five.

**Fix:** the panel and editor now receive `threadJobs`, matching the chip and pill, and `JobsPanel`
takes the open `threadId` so its empty state and footer name the teammate a task runs as. The isolated
worker plus owner narration were kept as designed.

**Regression test:** `scripts/verify-desktop-assistant-features.mjs` creates a second teammate and a
task owned by that teammate, then asserts it is absent from the open conversation's panel and that the
row count equals `scheduleList { threadId }`. RED (unscoped `state.jobs`, rebuilt):
`AssertionError: Another teammate's task is not listed in this conversation`. GREEN (scoped, rebuilt):
`MODEL_TASK_CARDS_OK`. `npm run desktop:build` exited 0. The verifier still stops later in the scripted
complex-login worker, so the scheduled-completion path remains un-re-verified.

**Open finding (not changed):** `DesktopScheduler.owner()` already flags `ownerMissing` and the UI warns
"Owner was deleted. Choose a teammate in job settings.", but it still falls back to the most recently
updated teammate, so an ownerless task runs and reports under that teammate. Changing it would alter
tested scheduler semantics (`orphan falls back and unknown owner mutations reject`), so it needs a
decision rather than a silent edit — options are to refuse the run until an owner is chosen, or to run
it with no delivery target.

## Remaining limits

- Local auth fixtures are realistic test systems, not proof that every public site's anti-bot, OAuth, passkey or payment flow works. MFA deliberately requires foreground input.
- Earlier real free-provider attempts encountered upstream HTTP 429 and inconsistent decisions, including guessed credentials, omitted URLs, premature tool markup and unnecessary foreground requests. The final real model passed; that proves this round trip, not every model or future provider capacity. Printed-tool recovery is deliberately bounded and does not parse or execute arbitrary text as code.
- Windows development and unsigned unpacked packaging are tested. macOS/Linux UI, signed installer installation, real OS sleep/lock and sign-in launch are not covered by this task's live checks; timer/locked-state branches have focused tests.
- Pattern/context detection cannot identify every arbitrary unlabeled or split secret. Operational provider configuration and encrypted vault files are excluded from migration; outside exports must be re-exported. OS encryption does not protect against another process running as the same user. Native binary crash dumps are not collected.
- The app must stay running, including in its tray. There is no mobile connection or independent service after Quit.
