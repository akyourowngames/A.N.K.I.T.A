# AGENTS.md — Operating Rules for Coding Agents in This Repo

> Read this file before any task. These rules override default habits. If a rule
> blocks the request, say so plainly and name the blocker instead of guessing.

## 1. No Hardcoding — Ever

1. **No hardcoded values.** No magic strings, paths, ports, timeouts, versions,
   URLs, model names, or environment assumptions inline. Hoist them to named
   constants, config, or parameters with a comment stating the unit and why.
2. **No hardcoded environment.** Never assume OS, shell, username, home dir,
   workspace path, line endings, or installed software. Detect (`process.platform`,
   `CONFIG_DIR`, feature probes) or ask.
3. **No hardcoded test fixtures as production truth.** Temp dirs, stub servers,
   fake ports, and example URLs stay inside tests/scripts. Production code must
   work from config + runtime discovery.
4. **No copy-pasted literals across files.** The second occurrence becomes a shared
   constant or helper. Duplicated error strings, regexes, and timeout values are
   bugs waiting to diverge.
5. **Review gate:** before finishing, grep your own diff for literals you
   introduced. Every literal must justify why it is not a constant.

## 2. Verify Always — At the End of Every Task Implementation

1. **Nothing is done until it is executed.** After implementing, run the relevant
   suite (`node --test <file>`) plus a live round trip of the changed path. A
   passing typecheck or a confident re-read is not verification.
2. **Reproduce-then-fix discipline.** For bugs: first reproduce live and capture
   the trace, then fix, then re-run the same repro and show the before/after.
3. **Cover both backends/branches you touched.** If Playwright and Chrome share a
   contract, exercise both (real run where possible, stub-driven where not) and
   state which was which.
4. **New behavior gets a new test.** Every fix ships with a regression test that
   fails without the fix. Update existing assertions instead of leaving them stale.
5. **Evidence before claims.** Quote exact outputs, counts (`32/32`), and file
   paths with line numbers. Never write "verified" without the trace that proves it.
6. **Record it.** Update the relevant doc (e.g. `docs/browser-screenshot-findings.md`
   finding status) with what changed, what verified it, and what remains uncovered.

## 3. Confidence Out of 100 — Always

1. **End every implementation report with `Confidence: X/100`** — no exceptions,
   even for trivial changes (trivial = 95+ with one line of justification).
2. **Show the ledger.** Points added and subtracted, each tied to a concrete fact:
   `+live round trip`, `−untested Chrome-backend`, `−no packaged-desktop check`.
3. **Deductions are mandatory honesty.** List every unverified path, untested
   branch, and environmental assumption. A 100 requires: live verification of all
   touched paths, full suite green, doc updated, zero residual unknowns.
4. **Never inflate.** If the user pushes for a higher number, earn it with more
   verification (another backend, another suite, a hardening guard) — not with
   adjectives. State what would be needed for the next +5.
5. **Format:**
   `**Confidence: 82/100.**` followed by the +/- ledger, then residual risks.

## 4. Working Agreements

1. **Read before edit.** Use Read at least once per file before editing it; derive
   `oldString` from current content; keep replacements minimal.
2. **Don't break the suite.** Run affected tests before declaring done. Failing
   pre-existing tests are reported, not ignored.
3. **No scope creep.** Fix what was asked. Adjacent bugs go in the doc as findings,
   not in the diff — unless the user approves the expansion.
4. **Ask on forks.** When two valid designs exist (receipt shape, guard placement),
   state the trade-off and ask rather than silently picking.
5. **Concise reports.** Changed files, test counts, traces, confidence. No filler.
