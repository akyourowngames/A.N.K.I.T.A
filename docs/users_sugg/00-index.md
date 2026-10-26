# DEV.to comment problems — problem / design / solution docs

Every comment on all 30 DEV.to articles was re-read in full (55 comments, Oct 4–17, 2026).
Commenters' own words are paraphrased; file paths are the ones named in the threads.
Status "agreed in thread" means Krish already accepted the fix in his reply — the doc
formalises it. Nothing here invents a feature, a release, or a metric.

## The 10 documents

1. [Background-job guard is convention, not structure](01-background-job-guard.md) — JOB_TOOLS still advertises the schedule tool; no spawnedBy linkage. (launchgatecheck, "read-only-by-default scheduled jobs") **Implemented 2026-10-26; spawnedBy deferred (no producer exists).**
2. [Send ledger breaks silently with two processes on one profile](02-send-ledger-two-processes.md) — last-writer-wins; loser keeps believing its claim. (launchgatecheck, "at-most-once sends")
3. [Crash recovery has no observability or reconcile provenance](03-crash-recovery-observability.md) — unpinned crash window, invisible uncertain rows, provenance-free accepts. (launchgatecheck, "at-most-once sends")
4. [Scheduler lock can wedge forever](04-scheduler-lock-wedge.md) — PID reuse, orphaned .recovery sidecar, wedged owner. (arhancanli, "scheduler that can never double-fire")
5. [Memory keeps near-duplicates and contradicting facts](05-memory-duplicates-contradictions.md) — exact-text dedup only, no contradiction detector. (baumgaerben, "memory must quote the transcript")
6. [Secret scrubber misses split secrets and drifts with vendors](06-secret-scrubber-gaps.md) — runtime concatenation, hardcoded patterns, shape-only false positives. (cubl9snp71hm, "secret scrubber")
7. [Heartbeat silence is brittle, and empty updates still reach chat](07-heartbeat-brittleness.md) — exact-string match, no substance gate, stale last state. (ai_adam, baumgaerben, ywnigcsmku2m, "quiet heartbeat")
8. [Island doesn't follow the monitor you're working on](08-island-active-monitor.md) — anchors to the main window's display, not the active screen. (mp6nfjxhrlxc, "v2.5.0 island")
9. [Chat-thread "always" trusts the whole agent, not the tool](09-chat-always-too-coarse.md) — session-wide autoApprove, no per-tool persistent allow-list. (koev3kcjausd, "companion island")
10. [Heuristic can't tell a cache delete from an account delete](10-heuristic-cant-grade-writes.md) — crude verb regex, no argument inspection. (nikolovv, "v2.5.0 island")

## Answered, by design, or not a product problem — no doc

- **Axiru demo offer** (axiru, "4-tier approval gate"): commercial offer, handled separately. Not a product problem. The Tier-2 question it raised (yes covers one exact amount and payee) is already Ankita's behaviour by construction.
- **"Island as GitHub/Slack notifier" questions** (baumgaerben, mp6nfjxhrlxc, koev3kcjausd, ai_adam, "v2.5.0 island"): category mismatch, corrected in-thread. The island is the approval surface for the agent's own tool calls, not a notification feed. The real gaps hiding inside those threads are docs 8 and 10.
- **Heartbeat TTL** (baumgaerben): answered — HEARTBEAT_OK is never stored, so no stale "healthy" marker can survive a crash. The TTL-shaped problem one layer down (scheduler.lock, 2-minute staleness) is covered in doc 4.
- **Heartbeat jitter** (ywnigcsmku2m): answered — one routine per machine, one Electron process, no fleet to thundering-herd.
- **Approval single-use yes / EPERM handling**: already the behaviour; no work needed.
- **Small task, not a doc** (elijahbrown, "v2.4.4"): sweep docs and demo material for contact-shaped fixtures and use only reserved ranges (US 555-0100–0199, UK 020 7946 0xxx). Krish adopted the rule in-thread but had not run the sweep yet — put it on the pre-release checklist.

## One pattern worth knowing

Several commenters across different articles sign off with references to the same site
(labagent.tech). Their technical points stand on their own and were engaged on merit,
but the repeated signature is a pattern, not a coincidence — read future threads from
those accounts with that in mind.
