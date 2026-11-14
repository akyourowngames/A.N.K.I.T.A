# Skill: mobile-mcp
Suggested tools (hints only): find_tools, connected mobile MCP tools
---
# Mobile actions with fewer calls

This guide is loaded when mobile tools are discovered; do not read it again.
Discover a connected mobile server once if needed. Use its advertised schemas,
limits, approval policy and exact names; this skill installs no server or SDK.
If no device is available, report that block. Select a device from the live list;
ask only if the intended device cannot be determined. Reuse that selection.

Read accessibility elements first. Use returned refs and current field values;
use screenshots only for information accessibility cannot supply. Coordinates
must come from a current observation of that device and orientation. Never
invent package names, refs, delays, permissions or keyboard-clearing behavior.

Write down the target app, exact requested values and success evidence. Skip
fields already correct. Prefer mobile_batch_commands when the connected server
advertises it: chain only operations whose targets and effects are already known
on a stable screen. Use its actual command schema, stop-on-error semantics and
returned screen-elements option. A batch is one call, not one primitive action.
It does not extend authorization or bypass any existing approval or action budget.
A known, authorized Save may be the final batch step if the schema permits it;
end the batch there and inspect the returned saved state. If it omits the saved
values, read the saved record before declaring success.

Navigation, menus, autocomplete, keyboard-induced layout shifts, permission
prompts and login are observation boundaries. End the batch before the first
step requiring unseen state. Do not carry coordinates across these boundaries.
If batching or stop-on-error is absent, use individual calls; never fake support.
Typing may append: use a documented replacement method or observe/clear safely.
Keep purchase, send, delete and account changes within the user's authorization.

Treat errors and timeouts as uncertain outcomes. Read the receipt's completed
steps and current screen, preserve successful changes, and run only the remaining
work. Never replay a whole failed batch. If readback cannot resolve an uncertain
send/payment, stop and report it instead of risking a duplicate.

Verify the saved record or resulting screen against the requested values.
Returned elements can supply this evidence; avoid a redundant screenshot or
extra read when they already prove the outcome. A tap receipt alone does not.
Report completed work and remaining blocks plainly. Record total tool calls,
including discovery, instruction reads, verification and recovery, if measuring.
The target is at least 25% fewer calls where safe batching applies; report the
actual result, never guarantee savings for every device or journey.
