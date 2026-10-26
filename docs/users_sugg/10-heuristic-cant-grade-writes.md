# Problem: heuristic can't tell a cache delete from an account delete

## Problem

The approval heuristic (`heuristicTier` in `src/integrations/mcp-tiers.mjs`)
is deliberately crude: it joins the tool name with the parsed app slug and
action and runs a substring regex of destructive verbs
(`send|delete|publish|pay|transfer|remove|destroy|revoke`) over that string.
Match → tier 2 ("always ask"). No match → tier 1 ("ask once"). Tier 0 is
auto-allow for tools whose metadata declares `readOnlyHint`.

What it deliberately does not inspect: file paths, argument values,
recipients. A send is a send whether it is a draft to oneself or something
irreversible. The real gap: it cannot distinguish a benign write from a
dangerous one under the same verb — deleting a cache file vs. deleting an
account both land on tier 2, and the gray zone relies entirely on the user
reading the card. The regex is also dumb in the other direction: `resend`
matches `send`, `payment` matches `pay` — false positives that cost one
prompt each, which is cheap but noisy.

The invariant to preserve: the heuristic can never deny. Only an explicit
user blocklist entry reaches tier 3. Argument inspection must refine
asking, never invent auto-allow for a destructive verb.

Source: nikolovv, Oct 7, 2026, on "Ankita v2.5.0: a desktop companion island
that never misses an approval". Status: agreed in thread ("argument-aware
classification would be better").

## Design

Grade the arguments, keep the ceiling. Classification moves on parsed
arguments — path scope, recipient, amount — so the same verb lands on
different tiers for different targets. Nothing in argument inspection may
turn a destructive verb into an auto-allow; it can only refine which kind
of asking applies, and it must keep the existing false-positive guards.

## Solution

1. Extend `heuristicTier` with argument inspection: path scope (cache/temp
   vs. account/data), recipient (self vs. external), amount/payload shape.
2. Fixtures for the pairs the thread implies:
   - delete cache file vs. delete account → different tiers;
   - send to self vs. send to an external payee → different handling;
   - `resend` / `payment` substring matches → still tier 2, no regression.
3. Keep tier 3 reachable only from the explicit blocklist, and keep the
   "what is it actually trying to do" unwrapping for meta-tools
   (`COMPOSIO_MULTI_EXECUTE_TOOL` enclosed actions) intact.

## Acceptance

- Benign/dangerous pairs under the same verb land on different tiers.
- No destructive verb becomes auto-allow through argument inspection.
- The meta-tool unwrapping and substring guards still behave as before.
