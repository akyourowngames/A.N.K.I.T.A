# Skill: workspace-batch
Suggested tools (hints only): read_file, search_files, apply_patch, run_command
---
# Make related file changes together

Use supplied exact file paths; otherwise find files with one targeted search.
Read their current content
before editing; do not use stale line numbers or assume an operating system,
path, installed program or line ending. Preserve unrelated user changes.

Use one apply_patch with standard unified diffs for the task's independent edits
across files, including otherwise unrelated files the user asked to change.
Its approval preview covers the exact changes; do not hide extra operations in
scripts. Keep each file's expected old content in the patch so drift fails safely.
Do not batch changes whose inputs depend on the result of an earlier edit.

If patching fails, inspect the returned reason and changed content before making
a revised patch. Do not replay confirmed writes or overwrite unexpected edits.
Use a bounded existing formatter or helper only when the task warrants it and
its effects are reviewable. Never install dependencies just to reduce call count.

Run the focused behavior check and typecheck needed by the change, then inspect
the final diff for accidental edits and secrets. One combined check may cover
related files; retain required checks and approvals. File reads and parallel
calls still count individually. Report what ran, what changed and remaining risk.
