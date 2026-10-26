# Problem: chat-thread "always" trusts the whole agent, not the tool

## Problem

The approval dialog has three buttons — yes / no / always. For scheduled
routines, `always` writes a scoped persistent rule (category plus origin
site). For chat threads, `always` flips that agent's `autoApprove` for the
whole session (`respondApproval` in `desktop/electron/engine.mjs`). It trusts
the whole agent, not a specific tool or tier.

The tiers already do the job the commenter was actually asking about:
tier 0 auto-allows read-only tools, tier 1 asks once for unclassified tools,
tier 2 always asks for destructive verbs, tier 3 is a hard deny on an
explicit blocklist. Low-risk actions never reach the dialog, so there is
nothing to batch. The gap is purely the granularity of `always`: one
"always" for a harmless tool currently also covers the destructive ones for
the rest of the session.

Source: koev3kcjausd, Oct 11, 2026, on "I'm building a companion island for
my desktop AI assistant". Status: named as the real TODO in-thread, if
click-fatigue shows up in practice.

## Design

Mirror the scheduled-routine shape: `always` should write a scoped rule, not
a session-wide switch. Scoping must be visible and revocable, or it is just
a quieter version of the same over-trust.

## Solution

1. Add per-tool / per-tier persistent allow-lists for chat threads, in the
   same shape as the routine allow config (tool or category, plus scope).
2. Change chat-thread `always` to write a scoped rule for what was just
   approved, instead of flipping session-wide `autoApprove`.
3. Show what `always` currently covers (in the island or settings) so the
   user can see and revoke a scoped rule.

## Acceptance

- Fixture: approve `always` for one read-class tool → a destructive tool
  later in the same session still prompts.
- The scoped rule is visible and revocable; session-wide autoApprove is no
  longer the chat-thread behaviour.
