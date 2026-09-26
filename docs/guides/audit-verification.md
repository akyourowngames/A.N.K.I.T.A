# Security, responsiveness, and shutdown audit

Implemented against the user's 18-finding review on 2026-09-26. No new dependencies were added.

## Findings and evidence

| Finding | Change | Regression coverage |
| --- | --- | --- |
| 1 | Shared file-path resolver enforces the workspace for every file tool. Rejects outside absolute paths, traversal escapes, interior symlinks/junctions, device names, and alternate data streams. Git inventories receive the same checks. | `test/tools/workspace-security.test.mjs` |
| 2 | `edit_file`, `edit_lines`, `write_file`, and `apply_patch` retain the displayed plan in the individual call context. Execution checks arguments, workspace identity, file identity, permissions, and original bytes; changed files require approval again. | Changed/unchanged plan and new-file absence regressions in workspace security tests |
| 3 | A required gate remains required when `approval()` returns no detail. `mcp_manage` declares its action policy explicitly. Only boolean `true` from confirmation grants permission. | `test/core/agent-audit.test.mjs` |
| 4 | MCP stdout has a 16 MiB per-message limit, including unterminated frames. Oversize rejects pending calls and closes the transport. Split UTF-8 is decoded correctly. | `test/integrations/mcp-bounds.test.mjs` |
| 5 | The resident filesystem worker serializes inspection calls and applies a main-thread watchdog, normally 5 seconds. Timeout or Stop terminates the stuck thread, preserves queued healthy calls, and starts a replacement. Queue admission caps at 128 calls. | `test/tools/worker-watchdog.test.mjs`, existing file-worker tests |
| 6 | Stderr is decoded/buffered by complete line, redacts configured and recognizable credentials, and discards lines exceeding 16 KiB through their newline. | Split-credential, UTF-8, and oversized-line MCP tests |
| 7 | Delete/move compare canonical roots and refuse both the current directory and workspace root. | Workspace root aliases and nested-cwd tests |
| 8 | Approval fallback uses display formatting and credential redaction. Includes environment and config-file secrets; MCP previews also redact server credentials. Actual execution arguments remain intact. | Agent and MCP preview tests |
| 9 | Terminal streaming redraws coalesce on a fixed 20 ms frame deadline. Finish flushes synchronously, cancels the timer, removes the resize listener, and is idempotent. CLI replacement/error paths finish the renderer. | `test/core/markdown-performance.test.mjs`, real CLI stream-error regression |
| 10 | Language keyword/type Sets are created once per stable syntax specification. | Markdown performance tests |
| 11 | Agent skill catalogs load once per turn; disabled choices still filter the catalog. A new turn reloads the disk catalog. | Agent scan-count and existing skill-refresh tests |
| 12 | Schema snapshots are shared by history budgeting and requests within a model round, then rebuilt for the next round. Schema byte costs and call signatures are reused. History trimming measures groups once, subtracts discarded costs, caches image costs, and preserves attachment input objects. | Agent schema activation tests, `test/core/history-performance.test.mjs`, context-budget and attachment tests |
| 13 | All optional recall warming handles rejected promises, including failures before embedder construction. | Agent warm-up failure regression |
| 14 | Daemon mode excludes the interactive SIGINT handler. Shutdown wakes tick sleep and drains active turns/composition before cleanup. | `test/automation/daemon-reliability.test.mjs`, real CLI SIGINT subprocess |
| 15 | Stop settles queued concurrency permits as cancelled, denies pending approvals, and prevents queued work/composition from starting. | Daemon stop/waiter/approval regressions |
| 16 | Failed alert enqueue retains one prepared batch for delivery retry without another LLM call. New watch changes coalesce from the earliest baseline to the latest reading; the pending queue caps at 100 distinct changes and logs replacement of the oldest entry when full. | `test/automation/alerts.test.mjs` |
| 17 | Voice payload reads/writes/cleanup use awaited asynchronous I/O, including daemon staging. Stop/abort while writing cannot start delayed playback or transcription. | `test/channels/voice-io.test.mjs`, `test/automation/daemon-voice.test.mjs` |
| 18 | Auto-approval is intentional explicit opt-in, default false. Agent and daemon gates require boolean `true`, and file/process approval preparation still occurs under opt-in. | Agent audit, proactive permission, and existing process snapshot tests |

Review also reproduced an escape through the old predictable staging filename. Atomic file writes now create an unpredictable staging file exclusively, preserve permissions, and never fall back to a symlink-following direct write. A real file-symlink regression verifies the outside file stays untouched.

## Report claims that did not reproduce

Voice default configuration, normalized `PROVIDER`, and web fetch tests all passed without changing their expected behavior: 62/62 across those three suites. Voice defaults still use the existing Edge provider configuration. Config tests intentionally allow process environment overrides, so external environment settings can affect their expected defaults.

The review's claim that auto-approval skipped preview preparation did not match the current implementation. Preview preparation already occurred; it now additionally retains and verifies the approved file plan.

## Verification

- Final `npm test`: 661 tests, 660 passed, zero failed, one expected Windows skip for the POSIX executable-permission test (123.7 seconds).
- Desktop TypeScript checking and Vite production build passed. Vite reports the existing bundle-size advisory.
- A resident-worker sample of 30 README reads measured 3.37 ms median and 5.64 ms p95 after 174 ms initial startup. These are local measurements, not a universal latency guarantee.
- Final `git diff --check`: passed. The security, worker recovery, approval, renderer, shutdown, and audio regressions were observed failing before their fixes.

## Scope

File-tool containment is not an OS sandbox for approved shell commands or third-party MCP servers. Interior symlinks are deliberately unsupported; a junction at the workspace root is supported. Main-thread file inspection callers use the worker watchdog; direct synchronous imports of inspection tool modules must not run untrusted regexes on an application event loop.

Shutdown retains the existing bounded drain timeout. Alert retry batches remain in memory until successful enqueue, and persistent notification delivery uses the existing outbox.
