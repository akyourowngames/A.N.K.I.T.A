---
name: action-chain
description: Use for a task with dependent actions across apps, files or MCP tools, especially when progress must survive interruptions or partial failures.
suggested-tools: write_todos, find_tools, skill
---
# Carry a task through to a checked result

Capture the user's outcome, constraints, existing authorization and final evidence.
For substantial work, keep a short checklist with stable item IDs. Save useful
results and remaining steps there; avoid separate planning calls for trivial work.

Discover only missing tool families. Reuse loaded tools and observed IDs instead
of searching again. A skill explains how to use existing capabilities; it grants
no tool access. Prefer the user's connected service and its documented bulk
operation. Read its schema before deciding which actions can be grouped.

Group independent reads or stable, authorized actions when the tool advertises
batching. Keep dependencies sequential. An unknown menu, navigation, credential
prompt or consequential submission ends the current group. Parallel calls may
save time but still count as separate calls; never count them as call savings.

Keep a receipt ledger: requested effect, confirmed effect, uncertain effect and
next step. After a failure or interruption, inspect uncertain effects and resume
only unfinished work. Do not repeat sends, purchases, record creation or other
successful writes. Stop and report when their outcome cannot be established.

Use returned state as evidence when it proves the goal; otherwise read back once
at the relevant boundary. Check identity, values and completion rather than just
successful dispatch. Mark only proven work complete and report remaining blocks.
When comparing call counts include discovery, skill reads, recovery and final
checks on both sides; never remove verification merely to hit a savings target.
