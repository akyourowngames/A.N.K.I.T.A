# Developer Tools Implementation Plan

> **For agentic workers:** Use the executing-plans workflow; independent tool modules are delegated under the dispatching-parallel-agents skill.

**Goal:** Commands must release the conversation while running; supply Git, atomic patches, HTTP APIs and process management as first-class tools.

**Architecture:** A session job manager owns every shell process, keeps bounded output with byte cursors, and emits lifecycle events to the CLI. `run_command` waits briefly then returns a job ID. Specialized tools use structured arguments and existing approval flow; Git/HTTP approval and read-only scheduling depend on the action.

**Tech stack:** Node built-ins, PowerShell on Windows, native Git/process utilities. No new dependencies.

**Spec:** User request in the current conversation: all five tool groups, with background commands and visible/accesssible CLI jobs first.

## Constraints

- Preserve existing uncommitted memory, UI and voice work.
- No topic-based intent router; expose tool schemas and let the model select actions.
- Read-only operations auto-run; state changes show an actionable approval preview.
- All tool output is bounded; waits are bounded and cancellable.
- Commands that outlive a turn remain session-owned and are cleaned up on CLI exit.

## Task 1: Job lifecycle and CLI

Files: `tools/run-command.mjs`, `tools/job-status.mjs`, new `tools/_jobs.mjs`, `tools/job-input.mjs`, `tools/job-wait.mjs`, existing job-stop/registry, `src/cli.mjs`, `src/ui.mjs`, `test/jobs.test.mjs`.

- [ ] Write/run regressions: slow command returns while still alive, input reaches a child, incremental output excludes previous bytes, truncation reports lost offsets, cancellation/stop kills descendants.
- [ ] Track every command with stable ID, PID, cwd, lifecycle timestamps, bounded byte output and async notifications. Foreground waits default 1 second; explicit background returns immediately. Execution timeout is optional and distinct from yield time.
- [ ] Add list/status/tail/since-offset, input/EOF, bounded wait and stop. Preserve old text result conventions where practical.
- [ ] Surface running/completed jobs and `/jobs`, `/job <id> [offset]`, `/input <id> <text>`, `/stop <id>` in the interactive CLI. Show active count in prompt. Never poll output into model history automatically.
- [ ] Verify actual Windows child stdin, output, exit and cleanup.

## Task 2: Git and process tools

Files: new `tools/git.mjs`, `tools/port-status.mjs`, `tools/kill-process.mjs`, optional process helper, `test/git-process.test.mjs`.

- [ ] Write/run temp-repository tests and child TCP listener tests.
- [ ] Implement requested Git actions with shell-free argv and action-sensitive approval.
- [ ] Implement platform port owner lookup, explicit PID/port kill preview and tree termination. Avoid killing unrelated processes or the CLI itself.
- [ ] Verify mutations and read-only operations in isolated fixtures.

## Task 3: Unified patches

Files: new `tools/apply-patch.mjs`, optional parser helper, `test/apply-patch.test.mjs`.

- [ ] Write/run multi-file, multi-hunk, rename, newline, invalid context and path-escape tests.
- [ ] Validate entire patch, stage writes, apply and roll back on failures. Keep exact context matching and explicit unsupported format errors.
- [ ] Verify non-Git directories and Windows paths.

## Task 4: HTTP requests

Files: new `tools/http-request.mjs`, `test/http-request.test.mjs`, optional fetch_url compatibility wrapper.

- [ ] Write/run local-server tests for JSON/form POST, auth, status/headers, redirects, bounded binary/text responses and cancellation.
- [ ] Implement structured requests, action-dependent approval, redacted display, safe redirect credential handling and one deadline.
- [ ] Preserve fetch_url compatibility without paying for its schema on every turn.

## Task 5: Integration and verification

Files: `tools/catalog.mjs`, `tools/index.mjs`, `src/agent.mjs`, README and tool-loading tests.

- [ ] Add deferred Git/process categories and core patch/HTTP/job controls; support boolean or function approval/read-only metadata.
- [ ] Check approval previews use the same context as execution; protect hidden auth fields in CLI traces.
- [ ] Run focused integration tests, full test suite, `git diff --check`, and actual CLI job smoke check. Review independent tool changes before completion.
