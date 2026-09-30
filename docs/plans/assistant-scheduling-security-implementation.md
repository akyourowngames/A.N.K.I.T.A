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

## Remaining limits

- Local auth fixtures are realistic test systems, not proof that every public site's anti-bot, OAuth, passkey or payment flow works. MFA deliberately requires foreground input.
- Earlier real free-provider attempts encountered upstream HTTP 429 and inconsistent decisions, including guessed credentials, omitted URLs, premature tool markup and unnecessary foreground requests. The final real model passed; that proves this round trip, not every model or future provider capacity. Printed-tool recovery is deliberately bounded and does not parse or execute arbitrary text as code.
- Windows development and unsigned unpacked packaging are tested. macOS/Linux UI, signed installer installation, real OS sleep/lock and sign-in launch are not covered by this task's live checks; timer/locked-state branches have focused tests.
- Pattern/context detection cannot identify every arbitrary unlabeled or split secret. Operational provider configuration and encrypted vault files are excluded from migration; outside exports must be re-exported. OS encryption does not protect against another process running as the same user. Native binary crash dumps are not collected.
- The app must stay running, including in its tray. There is no mobile connection or independent service after Quit.
