---
name: commit-review
description: Review git diffs and staged changes for this repo. Use when asked to review, check, or summarize changes.
suggested-tools: git
---
# Commit Review

1. Call `find_tools("git")` if the git tool is not available yet.
2. Review the diff: check git status, then the working tree and staged diffs.
3. Read surrounding code when a changed line needs context.
4. Summarize changed files, behavior, and concrete risks. Point to affected files and lines.
5. Suggest the relevant test command and state which checks have already run.
6. Stop after the review. Never stage or commit unless the user asks.
