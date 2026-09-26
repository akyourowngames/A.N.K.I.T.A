# Audit fixes implementation plan

**Goal:** Address all 18 findings in the supplied security, performance, and reliability review and verify the affected behavior.

**Architecture:** Enforce filesystem containment in the shared path resolver; retain and recheck the exact approved edit; fail closed at approval gates. Bound and redact MCP transport diagnostics. Keep filesystem inspection off the main thread with a watchdog and recoverable worker. Coalesce terminal redraws, reuse stable metadata, and settle shutdown/cancellation consistently.

**Tech stack:** Node.js builtins, existing tools and node:test; no new dependencies.

**Spec:** User attachment `3ac78f75-f725-4176-b146-adffad9e8c79/Pasted text.txt`.

## Tasks and acceptance

- [x] 1, 7: All filesystem tools reject outside paths, traversal, and interior symlink/junction escapes; delete/move refuse roots.
- [x] 2: Approved edits execute the displayed plan or reject a changed file/path/arguments; include whole-file writes.
- [x] 3, 8: Required approval cannot be bypassed by an empty detail; fallback previews redact credentials.
- [x] 4, 6: MCP frames and diagnostics are bounded, UTF-8 is preserved, and secret values are redacted.
- [x] 5: A pathological regex times out without poisoning subsequent queued filesystem calls; Stop terminates active inspection.
- [x] 9, 10: Terminal redraws coalesce, finish cleans up, and syntax keyword sets are reused.
- [x] 11, 12: Skills load once per turn, schemas/signatures are reused where valid, and history trimming avoids repeated full measurement.
- [x] 13: Best-effort recall warming handles rejected promises.
- [x] 14, 15, 16: SIGINT drains daemon work, cancelled permit waiters settle, retries keep bounded alerts and reuse prepared output.
- [x] 17: Audio payload I/O is asynchronous and cancelled writes never start playback.
- [x] 18: Verify the explicit auto-approve setting and its default; preserve intentional user opt-in while preventing truthy non-booleans from granting permission.
- [x] Recheck the three reported baseline failures, run focused regressions, full tests, desktop build, and diff review.

## Delegation

Independent modules are assigned to bounded workers per the dispatching-parallel-agents skill. The primary agent owns filesystem security, approval policy, worker recovery, and Agent metadata caching. Final integration is verified together.

## Result

Final `npm test`: 660 passed, zero failed, one expected POSIX-only skip on Windows. Desktop build and diff checks passed. Item-by-item evidence and practical scope are in `docs/guides/audit-verification.md`.
