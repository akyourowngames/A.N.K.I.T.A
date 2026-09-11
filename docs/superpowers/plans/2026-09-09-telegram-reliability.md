# Telegram execution and memory lifecycle implementation plan

Goal: deliver observable, cancellable Telegram runs and stop stale tasks from resurfacing as current obligations.

Architecture: retain the existing chat/model/tool pipeline, add a durable run journal and cooperative execution control, and dispatch Telegram work independently of polling. Store semantic task expiry separately from original memories. No frontend work or new dependencies.

Constraints: semantic classification uses memory.llm only; command parsing, timestamps and declared tool capabilities are structural. Preserve original memory/history. Never replay an interrupted side-effecting tool automatically. Current checkpoint f86a9771 was pushed to origin/zumba before these changes.

## 1. Execution control and journal

- [ ] Add core/execution.py with ExecutionControl.check(), cancel(), emit(), request_approval(), and typed cancellation/timeout outcomes; use durable records in core/run_store.py.
- [ ] Verify cancellation between tool calls, cancellation during model retries, duplicate update suppression, terminal-state monotonicity, and restart recovery using isolated SQLite and scripted model/tool boundaries.
- [ ] Update mcpclient/agent.py to emit real step events, preserve partial results, avoid replaying identical failed calls indefinitely, and check cancellation before each side effect.
- [ ] Replace the sync MCP bridge with one continuously running event loop and thread-safe submissions; serialize stateful built-in tools, permit concurrent independent external reads only when declared by their tool metadata.

## 2. Telegram integration

- [ ] Persist incoming updates before acknowledging their offset. Dispatch turns with per-chat ordering while callback queries and explicit /cancel and /status commands remain responsive.
- [ ] Add TelegramAPI edit_message and answer_callback methods with validated responses and rate-limit-aware idempotent retries. Use one throttled progress message, inline cancel/approve controls, and final reply delivery.
- [ ] Route Telegram through the streaming agent path with durable tool events, model timeout and cancellation. Keep original text/voice handling and allowlist enforcement.
- [ ] Exercise the complete channel using a fake Telegram transport and controlled model/tool implementations: slow task plus cancellation, unauthorized callbacks, duplicate updates, failed message delivery, and interrupted runs.

## 3. Memory lifecycle and personal context

- [ ] Add memory/task_lifecycle.py for active/dormant/expired/dismissed state, semantic expiry anchored to source time, finite follow-up lifetime, and persistent per-item nudge limits.
- [ ] Apply lifecycle filtering to follow-ups, proactive candidates, briefings and goal context. Preserve source records and allow explicit reactivation.
- [ ] Extend reflection/decomposition model outputs with lifecycle metadata; batch-review legacy entries in the background. Repeated reads do not extend task life.
- [ ] Compose the personal Telegram system prompt from existing persona and preferences, current local time, dated history and current request. Remove unconditional instructions to weave all open goals into every answer.
- [ ] Verify tomorrow's abandoned request expires, ignored requests become dormant, old durable preferences remain available, and stale entries do not appear in nudges or generic recall.

## Verification and handoff

- [ ] Run focused new regressions, then relevant Telegram, MCP, memory, chat and knowledge suites.
- [ ] Document commands, recovery behavior and cancellation limits; review git diff for frontend changes and credentials.
- [ ] Commit implementation independently from the already pushed checkpoint. Activate only the verified backend, retaining the existing Telegram configuration.
