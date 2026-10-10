# A guide for each scheduled task

Run `node chat.mjs runbook TASK_ID` to generate a Markdown page showing what the
task does, its schedule and next run, access settings, last five retained outcomes,
and recovery advice for the last status. Redirect it to a file to share it.
`--state-file`, `--runs-dir` and `--time-zone` select explicit resources for scripts.

The command reads the current durable task definition and matching retained desktop
receipts. The CLI store now retains a bounded history of new outcomes too. Existing
tasks with only a last result show that one result honestly; older deleted outcomes
cannot be reconstructed. Malformed, oversized or escaping receipt files are skipped
and the count is reported. ANKITA's existing secret detector scrubs recognized
credentials and labelled passwords before the page is returned. It cannot identify
every arbitrary low-entropy secret; review a page before sharing it.

Generating a guide does not enable, rerun or change the task. Recovery text is advice,
not an automatic retry; inspect the last proof before repeating an action.

Verification covers real store updates and reloads, last-five ordering, next-run
calculation, retained desktop receipts, secret scrubbing, unreadable records, paused
and never-run tasks, and real offline CLI success/failure paths.
Eight focused checks passed. Review reproduced a latest missed result disappearing
behind older history. The corrected guide merges that latest outcome and keeps its
recorded time stable when the next run is claimed; malformed history rows are skipped.
A desktop execution that advances the clock shares one completion timestamp
between state and receipt, so a completed run appears only once:
`RUNBOOK_DESKTOP_LIVE started=08:00:00 completed=08:00:05 distinctRuns=1 displayedOutcomes=1`.
Legacy desktop records use matching receipt completion times too, before and after
an update or new in-flight claim, rather than duplicating the same execution.
