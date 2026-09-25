---
name: ankita-dev
description: Develop and test the Ankita repository using its existing conventions. Use when changing code in this repo.
suggested-tools: read_file, edit_file, search_files, run_command
---
# Ankita Development

1. Read the relevant files before editing. Keep changes within the requested scope.
2. Map the path of the behavior you are changing:
   - `chat.mjs` starts the terminal app.
   - `src/core/cli.mjs` handles the REPL and slash commands.
   - `src/core/agent.mjs` builds prompts and runs the model and tool loop.
   - `tools/` keeps one module per tool. `tools/catalog.mjs` groups tools; `tools/index.mjs` exposes core and deferred tools.
   - `test/` groups Node's built-in test runner tests by subsystem.
3. Check existing tests for the behavior before adding code. Add or update a focused test for a behavior change.
4. Prefer `edit_file` for existing files and `apply_patch` for related multi-file changes. Use `write_file` for new files.
5. Keep the runtime dependency count at zero. Use Node built-ins rather than adding packages.
6. On Windows, commands run in PowerShell 5.1. Separate commands with `;`, not `&&`.
7. Run the focused test, then `npm test` before reporting completion.
8. Read the final diff and report what changed, the test result, and any remaining limitation.
