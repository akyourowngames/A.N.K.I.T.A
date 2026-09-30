# Scheduled desktop jobs

Ask a teammate to schedule a task in chat. Ankita can call `schedule` directly to
create an active job, update it, pause/resume it, list jobs or run one now. It asks
for missing task or timing details. Creation returns a structured receipt and a
compact task card; it does not mean that the task has already executed.

Supported schedules include `daily 08:00`, `weekdays 09:30`, `every 30m` and cron
expressions. The task card shows timing and timezone. **View scheduled task** or
the header clock opens a compact upcoming list with next run, status and controls.
**Ask Ankita** starts a chat request. Advanced settings remain available for
manual editing, owner/project selection and execution budgets.

Retries of the same creation request return the same job. A changed request using
the same key is rejected; use update to change an existing job. Running jobs cannot
be removed, including when addressed by name. Stop their current run first.
Names resolve within the current teammate; use a canonical job id for another
owner or an ambiguous name. Updates accept the declared patch fields; empty,
unknown or conflicting patches are rejected instead of returning unchanged success.

## Browser access

Each job uses its own persistent isolated Chromium profile. New chat-created jobs
have autonomous browser access: they can navigate and interact without per-site
dialogs. Existing scoped jobs retain their permissions and URL patterns. Browser
isolation, private credential origin checks, cancellation and execution budgets
still apply. Chrome remains a foreground browser. Jobs do not attach to your Chrome
session or connect to mobile.

Switching app pages, teammates or foreground browser tabs does not stop a job.
Selecting a tab in **Watch live** changes the preview only; the worker keeps its
own active page and snapshot refs. **Take control** explicitly pauses browser
actions until handback. **Stop** stops the selected job.

For scoped jobs, requests to new sites can pause for an inline card or be denied, according to
the job setting. **Allow this step** applies to that request. **Always for this
job** updates only that routine's permission. **Skip run** stops it. Approvals
expire after one hour; time waiting for approval does not use the execution
deadline. Chat stays available while the job waits.

For login, first save credentials through desktop Secure store for the exact
website origin. Enable saved sign-in for a scoped job. The model selects observed
username/password refs; the vault fills privately. A job without saved credentials
stops with foreground guidance and never opens a new-password prompt. Username-first
and iframe password steps use the same private credential tool. A fresh MFA code or
CAPTCHA requires foreground input; Ankita records this as needing attention.
An omitted login URL binds the actual selected tab. Generic unattended password
fill/type cannot replace the saved-account tool, including after a site shows the
password. The model can still request login before a form appears.

Each worker receives fresh context from its owning teammate's project, or the
explicit project chosen for the job. Its conversation and browser remain separate
from foreground chat.

When a run finishes, the owning teammate uses its configured model and conversation
to write the final chat update from the worker's result. This writing pass has no
tools, so it cannot repeat the browser task. The raw run details and browser proof
remain in a collapsed evidence panel under that reply and in the job details.
If the model cannot write the update, delivery remains pending and can retry
without rerunning the browser task. An active chat turn finishes before this
handoff begins; a new turn cannot start while the teammate is writing.
The teammate's draft is saved before delivery is acknowledged so a restart can
finish delivery without asking the model to write the same update again.

## Heartbeat

Ask Ankita to create a heartbeat. Its default interval is every 30 minutes, with
editable timing and instructions. It checks the teammate's existing proactive and
project context while that teammate is idle. `HEARTBEAT_OK` produces a quiet receipt
without another chat message. Useful updates are delivered once; heartbeat does
not create more scheduled jobs by itself.

**Watch live** opens the job's browser stage. **Stop** or **Close and stop browser**
stops that job. Stopping a foreground chat does not cancel a background
worker or its permission request.

## Results, limits and recovery

Proof receipts include the final page URL and a bounded screenshot when available.
The URL and screenshot follow the worker's page even when you watch another tab.
URL credentials, query parameters and fragments are removed from proof links.
Raw snapshots, field values and credentials are not written into job audits.
The latest 30 delivered run files and copied proof receipts are retained per job.
Compact delivered-run IDs remain for deduplication.

Jobs run serially. Regular desktop jobs default to **Finish the task**: cumulative
token usage, elapsed time and fixed tool/search-call counts do not cut off a progressing
run. Usage remains recorded. Stop, application Quit, provider failures, real human
verification requirements and repeated calls with no progress can still stop it.

**Task instructions** shows the exact prompt Ankita writes and the worker executes:
objective, account/resource, working method, completion evidence and report format.
The latest successful result is supplied to a fresh worker for comparisons, even
after a later failed run. It must still observe the current value before reporting.

**Use explicit limits** is optional in advanced settings (`executionPolicy=bounded`
in the tool). Its defaults are three active minutes, 48 runs, 50,000 tokens and
60 active minutes per day. Heartbeats default to this bounded policy. Exceeding
an explicit limit pauses the routine; day rollover does not resume it. Legacy
regular desktop jobs use completion execution after reload; old budget-paused jobs
stay paused until you choose **Resume**. **Run now** can test a paused job without
resuming its recurring schedule.

After sleep, a scheduled fire up to 30 minutes late runs once and reports the
lateness. Older fires are marked missed. Overlapping fires are marked busy.
Timeout, browser error or interrupted execution never automatically repeats a
browser action. A rejected stale reference can return fresh refs to the model;
an uncertain browser failure stops the run. **Run now** starts an explicit new run;
previous proof remains visible. Delivery
can retry independently without repeating the task.
Form batches check every target before writing. A control rejected before any
write returns fresh refs; a page change after filling begins remains incomplete.
Printed pretend tool requests receive one bounded model correction, never direct
JSON execution. Repeated malformed requests or exhausted tool loops are reported
as incomplete runs.

If the owning teammate is removed, results use the newest remaining teammate and
show an owner warning. Re-home jobs in their settings. Results wait until an
active chat turn finishes, and reloads do not duplicate delivered receipts.

## Keep jobs running

Minimize or close the window to keep Ankita in the tray. The first close shows a
notice. Tray actions are **Show Ankita**, **Pause all jobs**, and **Quit**.
Quit stops workers and releases scheduler ownership. Startup at sign-in is an
opt-in setting under Background jobs. The app must remain running to execute a
schedule; there is no sidecar after Quit.

Only one scheduler owns the routine store. Stop the CLI daemon before desktop
jobs, or use the CLI's cooperative `--takeover` option to request owner shutdown.
A live owner's PID remains authoritative even after sleep; a stale crashed owner
can be recovered. Restarted active runs are reported as interrupted, not replayed.

## Verification

See the [assistant scheduling ledger](../plans/assistant-scheduling-security-implementation.md)
and [scheduler implementation ledger](../plans/desktop-background-jobs-implementation.md)
for exact test counts, actual application traces and platform limitations.
The teammate delivery regression lives in `test/desktop/scheduler-delivery.test.mjs`.
`node scripts/verify-desktop-background-jobs.mjs` exercises two real Chromium
submissions in the Electron app with a scripted HTTP model, including two tool-free
teammate result calls, collapsed proof and reload persistence.
On 2026-09-30 this check passed in both development and unpacked Windows builds
(`15` model requests and `2` confirmed posts each); the focused delivery tests
passed `9/9`. The final serial suite passed `850/851` with zero failures and one
POSIX permission skip on Windows, and `npm run desktop:build` passed. Skill
tests now inventory the installed catalog. The Windows launcher cleanup
regression failed before the fix and passed afterward; cleanup queries only the
root PID while retaining its creation-identity guard. The command-output test
now waits for its burst to finish before counting active jobs. The
separate complex-login app fixture stopped at its iframe password challenge
before reaching this result handoff, so that fixture does not verify this change.
Cross-device sync and a true-Quit sidecar are deferred.
