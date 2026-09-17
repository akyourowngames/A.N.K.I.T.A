# Agent upgrade implementation plan

**Goal:** Implement every described requirement in `copilot-chat-agent-upgrade-audit.md`.
**Architecture:** Keep the self-describing tool registry and callback-driven agent. Add bounded output, protocol-safe history, explicit tool execution metadata, and small provider/session modules. Use existing search and diff implementations as the starting point.
**Tech stack:** Node.js >=18, ES modules, built-in `node:test`; no new dependencies.
**Spec:** `copilot-chat-agent-upgrade-audit.md`. Items 8–11 are absent and cannot be inferred.

- [x] Core safety (#1–5, #14, #18–20, #24): regression tests for bounded output, tool pairing, mid-loop trimming, auto approval, partial streaming, parallel reads, reasoning and usage. Implement in `src/agent.mjs`, `src/history.mjs`, `tools/_shared.mjs`, `src/ui.mjs`.
- [x] Tools (#12–17): tests for full approval diffs, fuzzy edits and ambiguity, search exclusions, filesystem verbs, fetch limits, todos, shell stdin/env/background/cancellation. Extend `tools/` with bounded job tracking and read-only metadata.
- [x] Plumbing (#6–7, #21–23): tests for capability-aware model selection, config layering, compatible endpoints and nonretryable failures. Update config/net/auth and add provider helpers. Read version from package metadata.
- [x] CLI/session (#25–27): tests using a local mock provider for JSON/plain output, errors, autosave and continue. Sanitize restored tool messages; add slash completion and explicit multiline paste mode.
- [x] Verification/docs: run `npm test`, syntax checks and CLI smoke tests; document configuration, commands, tools and audit coverage.

Execute inline using the executing-plans and test-driven-development skills. Each group starts with failing behavior tests, followed by implementation and targeted validation. No commits are possible: this workspace has no `.git` directory.
