# Skill: codebase-tour
Suggested tools (hints only): list_dir, glob, search_files, read_file
---
# Codebase Tour

1. Inspect the repository's top-level structure using `list_dir({"path":"."})`. Identify the main languages, project type, source directories, tests, and documentation from actual results. Do not assume a conventional layout.

2. Find documentation and relevant manifests with targeted calls:
   - `glob({"pattern":"**/README*","exclude":"**/node_modules/**","max_results":30})`
   - `glob({"pattern":"**/package.json","exclude":"**/node_modules/**","max_results":30})`
   - When Python files are present, use `glob({"pattern":"**/pyproject.toml","exclude":"**/.venv/**","max_results":30})`.
   Only investigate manifest types relevant to the discovered project.

3. Read the most relevant README and up to two manifest or configuration files using `read_file`. Use only paths returned by `glob`.

4. Locate entry points and tests with `glob`. If their purpose or relationships remain unclear, use `search_files` to trace specific imports, symbols, route handlers, or startup functions. Read only the files needed to answer those questions.

5. Write a concise architecture tour covering:
   - The project's purpose, based on its documentation.
   - Important directories and their responsibilities.
   - Main entry points and the high-level execution flow.
   - Build, run, and test commands confirmed by project files.
   - Important dependencies and relationships between components.

6. Support architectural claims with repository-relative paths. Distinguish observed facts from inferences, and explicitly mention anything that could not be verified. Never invent files, commands, dependencies, or relationships.

7. Do not modify project files, install dependencies, or execute project commands during the tour unless the user explicitly requests it.

8. Stop after reviewing one README (if present), up to two manifests or configuration files, and up to three source or test files. After three targeted searches, report remaining uncertainty rather than continuing indefinitely.