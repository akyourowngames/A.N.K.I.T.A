# Skill: bug-repro
Suggested tools (hints only): read_file, search_files, run_command, git
---
# Bug Repro

1. Read the bug report twice. Identify the claimed behavior vs expected behavior.
2. Find the relevant code with `search_files` — don't guess at file locations.
3. Write the smallest possible reproduction script that triggers the bug. Run it with `run_command` and confirm it fails the way the report says.
4. Only then fix the code. Re-run the repro to confirm it's green.
5. Add or extend a test in `test/` covering the regression, then run the focused test file plus `npm test`.
6. Report: root cause (file:line), the fix, repro result before/after, and test results. If you can't reproduce it, say so — don't ship a guess.
