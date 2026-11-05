# Sub-agents

Ankita can hand a self-contained piece of work to a child agent. The child runs
its own tool loop with a fresh context. Background children exchange messages
with the parent while independent work happens in parallel, then return a
bounded final result.

## Discovery

Delegation is not always-on. The parent calls `find_tools` (query it wants, or
`subagents`) and the `subagents` group becomes callable:

```text
find_tools(query="delegate parallel research")
delegate_task(subagent_type="explore", description="Locate the retry policy", prompt="...")
```

Background jobs and Telegram DMs have no delegation host. Children receive only
the message control tool, with permission to send to their own parent.

## Background work and messages

```text
delegate_task(subagent_type="explore", description="Inspect retries", prompt="...", background=true)
subagent_control(action="list")
subagent_control(action="send", subagent_id="<returned child ID>", message="Also inspect cancellation.")
subagent_control(action="wait", subagent_id="<returned child ID>", wait_ms=1000)
subagent_control(action="cancel", subagent_id="<returned child ID>")
```

`background=true` returns a child ID and `queued` or `running` status promptly.
Omitting it retains blocking delegation. Independent read-only children overlap.
Workers share the existing workspace lock, including background workers.
Parent tool calls that can change state wait in the same workspace queue.
Read-only calls and child message, wait and cancellation controls remain usable.

A child sends progress, findings or questions with
`subagent_control(action="send", subagent_id="parent", message="...")`. Its
parent can reply while it works. Messages are delivered once at the next model
decision, after any active tool replies. A queued child's messages wait until
it starts. Delivery never interrupts an HTTP response or an active command.

A successful send returns `queued`, which acknowledges mailbox acceptance.
It does not claim the recipient has read the message. Each recipient accepts up
to 64 queued messages, with an 8,000-byte UTF-8 limit per message. Full mailboxes
reject new sends explicitly. Accepted messages retain arrival order.

Only the owning parent can list, wait for, cancel or message its children.
Children can send only to their parent. Foreign IDs and sibling control attempts
return an error. Controls and mailboxes are local to the active agent runtime.
Completed handles are retired at the next parent request. They cannot resume a
child after an app restart.

`wait` returns the terminal envelope when ready, or the current status when its
bounded wait expires. The default is one second and the maximum is 30 seconds.
Before a final reply, the parent automatically waits for outstanding background
work and processes messages or results as they arrive. Unfinished reply drafts
stay internal. Cancellation, request failure and forced turn limits cancel
remaining children. Completed background receipts are refreshed in the parent
history so saved cards carry terminal status.

## Presets

| Preset | Tools | Concurrency | Use it for |
|---|---|---|---|
| `explore` | read-only (`read_file`, `list_dir`, `search_files`, `glob`, `git` reads, `web_search`, `web_fetch`, `scrape`) | parallel | codebase and web reconnaissance |
| `reviewer` | read-only | parallel | correctness, regression and test-coverage review |
| `worker` | every local tool except parent-only ones | serialized | implementation, tests, commands |

Read-only presets overlap because the parent loop already batches contiguous
read-only tool calls. A `worker` acts as a mutation barrier. One worker or parent
mutation runs at a time across the whole process, keyed by the canonical workspace path (symlinks,
junctions and Windows case variants share one lock). A worker holds that lock
through its whole child loop. Its own tools use that ownership, while the parent
can launch another delegation without acquiring a second lock around it.
For parent calls, the lock lasts until the tool returns. A command that starts
a background operating-system process can keep changing files after returning
its receipt. That process lifetime remains outside the parent tool-call lock.

## The brief

A child starts with `prompt` and can receive later parent messages. It cannot
delegate. Write
the brief as if handing the task to a competent stranger: goal, absolute paths,
constraints, what "done" means, and the exact shape of the answer you want.
Briefs must never contain secrets; the child writes its transcript to disk.

Each completed delegation returns a result envelope. Background results also
arrive in the parent's inbox.

```json
{
  "subagentId": "…", "parentCallId": "…", "subagentType": "explore",
  "description": "…", "status": "completed", "summary": "…",
  "result": "full final answer, capped", "toolsUsed": ["read_file"],
  "usage": { "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0 },
  "durationMs": 1234, "transcript": "…/sessions/subagent-<id>.json",
  "depth": 1
}
```

Terminal `status` is one of `completed`, `failed`, `timeout`, `cancelled`,
`budget_exceeded`, `rejected`. A `note` explains non-completion. The parent must
verify the report before claiming the work is done.

## Limits and safety

- Depth is capped at one by default: a child cannot spawn grandchildren.
- Per-turn fan-out and concurrent slots are bounded; the extras wait, they do
  not fail.
- Each child has its own tool-step, tool-call, wall-clock and token budgets.
- Children inherit the parent's selected primary model and its discovered context limit.
- Children run with `memoryEnabled: false`: pinned personal facts and the memory
  store never enter a child prompt, and `remember`/`recall` are blocked.
- Children have no browser, MCP, connectors, skills, scheduling or project tools.
- Child tool calls keep the parent's approval gate. An approval requested by a
  child is labelled with its type and description.
- Audit records carry `subagent` and `subagentType` attribution.
- Transcripts are written as `subagent-<id>.json` and scrubbed with the same
  secret cleaner as normal sessions; teammate session files are never touched.
- Scheduled jobs, the daemon and one-shot routines force `subagentsEnabled:
  false`; there is no unattended delegation.

## Configuration

Advanced knobs live in `config.env`; the desktop settings UI is unchanged.

| Key | Default | Range |
|---|---|---|
| `SUBAGENTS_ENABLED` | `true` | boolean |
| `MAX_SUBAGENT_DEPTH` | `1` | 0–3 (guard only; children never delegate) |
| `MAX_CONCURRENT_SUBAGENTS` | `8` | 1–16 |
| `MAX_SUBAGENTS_PER_TURN` | `24` | 1–64 |
| `SUBAGENT_MAX_TOOL_STEPS` | `100` | 1–400 |
| `SUBAGENT_MAX_TOOL_CALLS` | `200` | 1–500 |
| `SUBAGENT_TIMEOUT_MS` | `1800000` | 10s–2h |
| `SUBAGENT_MAX_TOKENS` | `1000000` | 1k–10M |
| `SUBAGENT_MAX_RESULT_BYTES` | `48000` | 1k–128k |

`delegate_task` also accepts optional `max_steps` and `timeout_ms`. They can
only tighten the configured cap for that one call, never raise it.

Transcripts are pruned to the newest 200 `subagent-*.json` files per session
store; teammate sessions and unrelated files are never touched.

## Surfaces

- **CLI:** dim `⇢` lines show starts, child tool calls and terminal status;
  message lines show direction and content. `--json` adds a `subagents` array to
  the turn outcome.
- **Desktop:** a `delegate_task` tool card renders the child's streamed text,
  tool rows, usage and duration. Live activity is ephemeral; after a reload the
  card is rebuilt from the stored result envelope. Child tool rows stop spinning
  when the child ends, and a stopped row never shows a success checkmark. Card
  and side panel message sections show parent-to-agent and agent-to-parent
  messages during a live run. Synthetic inbox entries stay out of chat bubbles.
  The live message list is ephemeral. Child transcripts retain their delivered
  inbox entries and sent message tool calls.

## Tests

```text
node --test --test-concurrency=1 test/core/subagents.test.mjs \
  test/core/subagent-messaging.test.mjs test/core/tool-loading.test.mjs \
  test/core/subagent-workspace-mutations.test.mjs \
  test/desktop/subagent-state.test.mjs test/desktop/subagent-panel-ui.test.mjs
```

`test/core/subagents.test.mjs` covers presets, discovery parity, read-only
scoping, envelopes, transcripts, approval attribution, depth/fan-out guards,
parallel overlap, worker serialization (cancellation included), workspace
aliases and the parent batching contract.

The workspace mutation regression reproduced a parent write running during a
background worker and then being overwritten. Its initial focused run passed
1/3 and failed 2/3, with
`WORKSPACE_MUTATION_API parent_during_worker=true final=child finished`.
After the shared parent guard, the trace became
`WORKSPACE_MUTATION_API parent_during_worker=false final=parent finished`.
The regression exercises real file writes through both API and native ToolHost
entry points, cancellation of queued parent writes and running workers, and a
second parent using a workspace alias. It also checks stubbed MCP mutations and
reads, runtime capability read-only flags, and an unrelated workspace. Model
decisions are controlled in this test. The five new cases and the existing
sub-agent, ToolHost and tool-discovery cases passed 51/51 together. Node syntax
checks and the desktop typecheck passed.

The messaging regression initially failed 0/2 because no control host existed.
The focused backend run passed 35/35 after implementation. A real local HTTP
streaming round trip ran two child requests concurrently, sent parent messages
while both requests were active, and confirmed both children received their
replies before finishing. Its trace was
`MESSAGING_HTTP_OK children=2 messages=6 requests=11 pending=0`.
The two desktop suites passed 10/10, including real Chromium assertions for
both message directions. The desktop typecheck and `git diff --check` passed.
The final messaging file passed 5/5 with a CLI subprocess check. Its trace was
`MESSAGING_CLI_OK directions=2 waited=1 requests=10 exit=0`. It executes the
actual `chat.mjs` entry point, checks both direction labels and waits for the child
before the final answer. Direct one-shot shutdown originally reproduced a Windows
native-handle assertion three times after the messages succeeded. Graceful
cleanup now closes owned jobs, browser sessions, MCP connections and the terminal
before letting the process exit. Real-entry checks cover both messaging and
resource cleanup, including a real Chromium session and real child processes.
A separate anonymous hosted-model scenario also exchanged one message each way
and finished with the child's updated result after eight HTTP 200 requests.
The parent briefly attempted an unavailable tool, which the runtime refused.
The initial brief leaked the update as a prohibited assumption, so changed-detail
secrecy was not proved. Other hosted models and a packaged desktop run remain
uncovered. The consolidated verification record contains the full sample details.

## Deferred

Worktree-isolated parallel workers, resuming or forking parent context into a child, custom user-defined
agent presets, per-call model overrides, and depth greater than one.
