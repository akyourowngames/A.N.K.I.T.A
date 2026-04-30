# Daemon Project Monitor

Use this when sir asks about project progress, what changed, what is pending, or how to continue work.

The daemon keeps its own separate state and publishes one clean project report for memory.

Behavior:

- Prefer the latest daemon project report for project progress.
- Use recent session messages for what happened in the current chat.
- Use PC activity for what sir appears to be doing now.
- Do not ask sir to manually update profile details for project progress.
- Keep progress answers concrete: completed, changed, pending, next step.
- Treat the report as project readings, not a code dump. Do not expose code excerpts unless sir explicitly asks to inspect code.
- If the report says tests passed, use that as current validation status instead of asking sir to run them again.
