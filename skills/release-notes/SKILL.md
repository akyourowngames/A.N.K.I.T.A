---
name: release-notes
description: Draft release notes from git history and the changelog. Use when cutting a release or summarizing what changed.
suggested-tools: git, read_file
---
# Release Notes

1. Call `find_tools("git")` if the git tool is not available yet.
2. Get the range: `git log` since the last release tag. Read `CHANGELOG.md` for the established format and tone.
3. Group changes: ✨ features, 🐛 fixes, ⚡ performance, 🔒 security, 📝 docs. Drop noise (merge commits, typo fixes) unless they matter.
4. Credit contributors by name — every contributor lands in the release notes.
5. Write the draft, keep it scannable. Never invent changes that aren't in the log; when in doubt, leave it out.
6. Stop after the draft. Don't tag or publish the release unless asked.
