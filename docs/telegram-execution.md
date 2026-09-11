# Telegram execution and task memory

The Telegram backend uses the configured chat model and existing MCP tools. No frontend changes or keyword-based intent routing are involved.

## Chat controls

- `/status` shows your recent runs, actual tool steps and saved outcomes.
- `/cancel` stops your active and queued runs. The inline **Stop task** button targets one run.
- `/new` creates a new conversation after preceding work settles; it does not erase personal memory.
- `/memory <question>` retrieves saved context.

Progress comes from real context/model/tool events. Draft text is labelled as a draft. Updates are throttled to roughly one edit every 1.2 seconds. Telegram delivery does not block the start of the model request.

Tools with declared read-only capabilities run directly. External writes, shell commands and undeclared capabilities require an owner-bound **Approve once** action. Approval expires after 90 seconds and cannot be reused. Local memory/task updates can run directly when requested. Capability declarations live in `mcpclient/builtin.py`; external MCP servers provide `readOnlyHint`. These declarations are trusted integration metadata, not a sandbox for malicious servers.

## Reliability contract

Incoming messages are committed to SQLite before the Telegram cursor advances. `(channel, update_id)` deduplicates delivery; claiming a run is atomic. Runs in one chat are ordered, while control commands remain responsive. Edited text does not re-execute an earlier action.

The journal stores original input, run state, tool arguments/results, approval decisions, first-token timing and final outcomes. Intermediate tool context is retained in session history. An identical non-read call is suppressed within a run, including after a tool reports an uncertain failure. This is not a claim of universal exactly-once external execution.

On restart, an in-flight run becomes **interrupted**, never automatically replayed. Queued requests older than five minutes require a fresh request. Recent queued requests can proceed. Model/tool turns have a five-minute overall execution budget; individual network calls also have timeouts.

Cancellation prevents subsequent steps; it cannot undo a purchase, kill an arbitrary Python worker, or prove that a remote action already in flight stopped. Stateful tool locks remain held until the underlying operation settles. Late observations are saved where the transport returns them. Check `/status` and the external system before retrying an uncertain action.

Final reply delivery is tracked separately from execution. An ambiguous Telegram send is not automatically retried: the outcome stays available through `/status`, without repeating the tool action. This avoids blind duplicate messages but does not guarantee automatic delivery after a network failure.

The local run journal uses the existing application database, under the same filesystem permissions. It contains personal messages and tool evidence; include it in protected backups and do not share database copies or logs publicly.

## Memory lifecycle

Durable facts/preferences and unfinished tasks are treated differently. Original memories are retained; task attention is stored separately as **active**, **dormant**, **expired**, or **dismissed**.

Reflection and goal planning use the existing LLM to derive task usefulness and attention deadlines from original timestamps and exact source evidence. Legacy tasks are reviewed in small background batches. Until reviewed, an unfinished task has a conservative two-day attention window, bounded by its recorded deadline. That is a fallback policy, not a semantic classifier.

Past tasks are excluded from active follow-ups, proactive nudges, briefings and goal context. Goal-linked reminders stop when their goal is no longer eligible. Per-task nudge records prevent repeated requests for the same follow-up; completed milestones have a separate one-time notification budget. Explicit standalone reminders remain independent.

Reading or background reviewing a dormant task does not renew its attention window. `task_list` exposes lifecycle state; `task_update` lets the model dismiss a task or explicitly renew it in response to a current user request. Renewal requires a future attention deadline; expired actions need a new future usefulness window. “Forget that flight request” can dismiss the task without destroying historical evidence.

Telegram context includes persona, durable profile, current local time, dated history and relevant memory. Summaries retain temporal distinctions. Historical evidence may still be retrieved when relevant, but it is not an instruction to resume old work.

`memory_remember` returns after the original text reaches the durable inbox; extraction and indexing continue in the background. It does not claim that enrichment has already completed.

## Verification

```powershell
rtk proxy python -m pytest tests/test_telegram_execution.py tests/test_telegram_channel.py tests/test_execution_reliability.py tests/test_task_lifecycle.py tests/test_latency.py -q -p no:cacheprovider
rtk proxy python scripts/check_chat_latency.py --live-model
```

The latency script performs a read-only recall check and one short provider greeting, without sending a Telegram message or executing tools. Provider latency is measured, not guaranteed. On this implementation's check, local recall took 373–412 ms; `stepfun/step-3.7-flash:free` took 14.8 seconds to its first token. A faster provider may be necessary for consistently seconds-level answers; model settings are not changed automatically.
