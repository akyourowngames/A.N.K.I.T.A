# TerminalAgent Upgrade Plan
### Full Polish + New Powers + Agent Cooperation

---

## Implementation Review First

### PlannerAgent Review ✅

**What's working well:**
- JSON plan generation with `depends_on`, `condition`, `artifacts_out` — exactly right
- `_run_planned_task()` in orchestrator with step-by-step execution
- HYDRA fallback to GeneralAgent on plan failure
- Plan preview output (the 📋 display)
- Audit trail entries per plan

**Issues found:**

**Issue 1 — Supervisor still failing multi-step detection (from your test output)**
Test showed requests like "research laptops, write a report, save it, email Raj" routed to `['WebAgent', 'ContentAgent', 'FileAgent', 'CommsAgent']` instead of `['PlannerAgent']`. The Supervisor is doing the right thing (chaining agents) but bypassing PlannerAgent entirely. Root cause: the Supervisor prompt's chain detection examples are too similar to the existing assembly-line examples. The LLM sees 4 agents and thinks "I already know how to chain these" and skips PlannerAgent. Fix: make the trigger rule explicitly count action verbs — if 3+ distinct agents are needed AND task has conditional/temporal language → force PlannerAgent.

**Issue 2 — Conditional evaluation is text-based, not result-based**
When a step has `condition: "only if step 2 exit_code == 0"`, the orchestrator needs to actually CHECK `step_results[2]["exit_code"]`. If it's doing string matching on the condition text, it'll always pass. Verify the condition evaluator reads real result data, not just the condition string.

**Issue 3 — Parallel steps need a timeout guard**
When two steps run in parallel via `_fan_out_parallel()`, if one hangs (e.g. a slow API call), it blocks the entire plan indefinitely. Add a per-step timeout of 120s max for planned tasks.

---

### FileAgent Upgrade Review ✅

**Phase 1 (Full PC Access) — Solid:**
- `resolve_any_path()` correctly implemented with env var expansion
- `unrestricted=True` flag passed through engine → fs_ops cleanly
- All 7 operations updated: list_files, read_file, search_text, move_path, copy_path, delete_path, file_info
- `_KNOWN_PATHS` injected into prompt — correct

**Issues found:**

**Issue 1 — `make_dir` still uses `resolve_safe_path`**
Looking at the code, `make_dir` was NOT updated to accept `unrestricted=True`. So `mkdir C:\Users\Krish\Reports` will fail with "path escapes workspace." Fix: add `unrestricted` param to `make_dir`.

**Issue 2 — Phase 2 tools not yet implemented**
`pc_search`, `trash_path`, `read_rich_file`, `disk_analysis`, `diff_files`, `bulk_op` are all still pending per the IMPLEMENTATION_SUMMARY. This is fine — Phase 1 was the priority. These are next.

**Issue 3 — HANDOFF signal not yet wired in orchestrator**
The `_extract_artifacts()` function doesn't yet read `HANDOFF:` lines. FileAgent's cooperation protocol is incomplete until this is added.

**Issue 4 — Double-save bug from ContentAgent still exists**
The `already_saved` flag fix and the `_build_prior_context_block()` change were in the Bug Fix Plan but the IMPLEMENTATION_SUMMARY doesn't mention them as done. Confirm these are implemented or they'll keep creating two files.

---

## TerminalAgent — Current State Assessment

### What It Has
- `execute_shell` — PowerShell system-wide, 15s timeout, blocked patterns
- `run_command` — workspace-sandboxed process runner with env injection
- `list_files`, `read_file` — basic file access
- Output guardrails — 500 line limit, head+tail truncation
- Blocked patterns: del /s, rm -rf, format c:, shutdown /s, etc.

### What's Missing / Broken

**Missing 1 — No working directory control**
TerminalAgent always runs from `Path.home()`. If user says "run this in my project folder" or "git status in C:\repos\myapp", there's no way to change the working directory for `execute_shell`. It just runs from home every time.

**Missing 2 — No multi-command chaining**
User says "cd into my project, activate venv, then run tests." TerminalAgent runs each as a separate subprocess — the `cd` has no effect on the next call. No session state between commands.

**Missing 3 — No environment variable management**
Can't set `$env:NODE_ENV=production` and have it persist for the next command. Can't read what env vars are currently set.

**Missing 4 — No process management**
Can't start a background process (e.g. a dev server) and then interact with it later. Can't check if a process is running, get its PID, or kill a specific process by name — only by exact process name via SystemAgent.

**Missing 5 — No git intelligence**
Git commands work (`git status`, `git log`) but TerminalAgent has no git-aware workflows. User says "show me what changed" and it runs raw `git diff` dumping everything. No smart formatting of git output.

**Missing 6 — No output parsing / insight**
TerminalAgent dumps raw output. User runs `netstat -an` and gets a wall of text. Nobody parses it to say "3 ports are listening, 1 established connection to 142.250.x.x (Google)." The output goes nowhere useful.

**Missing 7 — No long-running command support**
`execute_shell` has a 15-second hard timeout. Running `npm install`, `pip install -r requirements.txt`, `docker build`, or `pytest` on a large project will always timeout. No way to run something longer.

**Missing 8 — No piped command builder**
User says "find all Python files modified today" — TerminalAgent has to manually construct the right PowerShell pipeline. No smart command building from natural language intent.

**Missing 9 — No command history / recall**
Every TerminalAgent invocation starts fresh. No memory of what commands were run, what succeeded, what the current project directory is.

**Missing 10 — Timeout is fixed at 15s, not configurable**
The `timeout` param exists in the tool spec but the prompt never mentions it. Complex commands always hit the wall.

---

## The Upgrade Plan

---

### Upgrade 1 — Working Directory Control (The Foundation)

**Problem:** `execute_shell` always runs from `Path.home()`. No CWD control.

**Fix: `tools/terminal_ops.py`**

Add `cwd` parameter to `execute_shell_command()`:
- Accept an optional `cwd` path string
- Validate it exists and is a directory before running
- Use it as the subprocess `cwd` instead of `Path.home()`
- Apply `resolve_any_path()` (from FileAgent upgrade) for full PC access — not workspace-jailed

**Update `tools/engine.py` tool spec:**
Add `cwd` parameter to `execute_shell` spec:
```
"cwd": {
    "type": "string",
    "description": "Working directory for the command. Defaults to user home. Use absolute paths."
}
```

**TerminalAgent prompt addition:**
```
WORKING DIRECTORY RULE:
If user mentions a project, folder, or repo path:
→ Always set cwd to that path in execute_shell
→ Example: "git status in my ANKITA project" → execute_shell("git status", cwd="C:\...\A.N.K.I.T.A")
→ REMEMBER the working directory — use recall("current terminal cwd") at session start
→ If user says "stay in this folder" → remember("current terminal cwd", path)
```

---

### Upgrade 2 — Session State (Persistent CWD + Environment)

**Problem:** Each command runs in isolation. `cd` doesn't persist. Env vars don't carry over.

**New concept: Terminal Session**

Add a lightweight in-memory session store to `terminal_ops.py`:

```
_TERMINAL_SESSION = {
    "cwd": str(Path.home()),
    "env_overrides": {},
    "last_exit_code": 0,
}
```

**Commands that modify session state:**
- `cd <path>` → updates `_TERMINAL_SESSION["cwd"]`
- `$env:X = Y` or `export X=Y` → adds to `_TERMINAL_SESSION["env_overrides"]`
- `set X=Y` → same

Before every `execute_shell` call, merge `_TERMINAL_SESSION["env_overrides"]` into the subprocess env, and use `_TERMINAL_SESSION["cwd"]` as default if no explicit cwd is passed.

**TerminalAgent prompt addition:**
```
SESSION AWARENESS:
You have a persistent terminal session within this conversation.
- "cd into Documents" → execute_shell("cd Documents") → session cwd updates
- "set NODE_ENV to production" → execute_shell("$env:NODE_ENV='production'") → persists for next command
- "what's my current directory?" → execute_shell("pwd") or "Get-Location"
- After cd, all subsequent commands run from the new directory automatically
```

---

### Upgrade 3 — Smart Timeout Control

**Problem:** 15s timeout kills `npm install`, `pytest`, `docker build`.

**Fix: `tools/terminal_ops.py`**

Make timeout smarter — detect the command type and auto-adjust:

**Timeout tiers:**
| Command type | Auto-timeout |
|---|---|
| Quick diagnostics (ping, ipconfig, whoami, pwd) | 10s |
| Git operations (status, log, diff, add, commit) | 30s |
| Package install (pip install, npm install, yarn) | 300s (5 min) |
| Build commands (npm run build, cargo build, make) | 600s (10 min) |
| Test runners (pytest, jest, go test) | 180s (3 min) |
| Docker (build, pull, run) | 600s (10 min) |
| Default | 60s (upgraded from 15s) |

**Auto-detection logic:** keyword match on the command string before running. Check for `pip install`, `npm install`, `yarn`, `cargo build`, `docker`, `pytest`, `jest`, `mvn`, `gradle`.

**Explicit override still works:** user can say "run with 5 minute timeout" → pass `timeout=300`.

**TerminalAgent prompt addition:**
```
TIMEOUT INTELLIGENCE:
- For install/build/test commands, timeout is automatically extended (up to 10 min)
- Never tell the user "this might timeout" — just run it
- If command does timeout, report exactly what ran and suggest: "try running with longer timeout"
- For interactive commands (ssh, python REPL, node REPL) — warn user these need a real terminal
```

---

### Upgrade 4 — Output Intelligence (Parse, Don't Dump)

**Problem:** TerminalAgent dumps raw output. No insight extraction.

**New behavior: Smart Output Parsing**

Add output parsers to `terminal_ops.py` for common command types:

**Git output parser:**
When `git log`, `git diff`, `git status` output is returned:
- `git status` → categorize: "3 modified, 1 untracked, 0 staged"
- `git log --oneline -10` → format as: "Last 5 commits: [hash] message (2h ago)"
- `git diff` → summarize: "42 lines changed across 3 files"

**Network output parser:**
- `netstat -an` → "5 listening ports: 3000 (HTTP), 5432 (Postgres), 8080 (Alt-HTTP)..."
- `ipconfig` → extract just IP addresses and adapters: "Ethernet: 192.168.1.5 | WiFi: 192.168.1.6"
- `ping google.com` → extract average RTT: "Avg: 14ms, 0% packet loss"

**Process output parser:**
- `tasklist` → top 10 by memory, formatted as table
- `Get-Process` → same

**TerminalAgent prompt addition:**
```
OUTPUT INTELLIGENCE PROTOCOL:
NEVER echo raw terminal dumps. ALWAYS extract the key insight:
  git status output → "3 files modified: main.py, utils.py, config.json. Nothing staged."
  ping output → "google.com: 14ms avg, 0% loss ✅"
  ipconfig output → "Active connections: Ethernet 192.168.1.5, WiFi off"
  netstat output → "Listening: ports 3000, 5432, 8080. Active: 2 established connections."
  tasklist/Get-Process → "Top memory users: Chrome (1.2GB), Code (800MB), Python (200MB)"
Only show raw output if user explicitly says "show me the full output" or "raw output".
```

---

### Upgrade 5 — Git Intelligence Mode

**Problem:** Git commands work but there's no git-aware workflow. TerminalAgent treats git like any other shell command.

**New Git Decision Tree in prompt:**

```
GIT INTELLIGENCE MODE:
Detect git intent and pick the RIGHT git command:

"what changed" / "show changes" / "what did I modify"
  → git diff --stat (summary, not full diff)
  → then git diff if user wants details

"show history" / "recent commits" / "what was committed"
  → git log --oneline -15 --graph --decorate

"what branch am I on" / "branch status"
  → git branch -a (show all branches, mark current)

"stage everything" / "add all files"
  → git add -A (not git add . — captures deletions too)

"commit" / "save my progress"
  → ALWAYS ask for commit message if not provided
  → git add -A && git commit -m "<message>"
  → confirm: show resulting git log --oneline -1

"push" / "upload changes"
  → git push origin <current_branch>
  → if fails (no upstream) → git push --set-upstream origin <branch>

"pull" / "get latest" / "sync"
  → git pull --rebase (cleaner than merge by default)
  → if conflicts → report them clearly, don't auto-resolve

"undo last commit" / "revert"
  → ALWAYS confirm before running: "About to undo: '<commit message>'. Confirm?"
  → git reset --soft HEAD~1 (keeps changes staged, safer than --hard)

"stash" / "save work temporarily"
  → git stash push -m "ankita-stash-<timestamp>"
  → confirm: "Stashed 3 files. Run 'pop stash' to restore."
```

**New tool addition: `git_op` — `tools/terminal_ops.py`**

A dedicated git wrapper that handles common operations with proper error handling, output parsing, and safety confirmations. Wraps `execute_shell` internally but adds:
- Auto-detect git repo root from cwd
- Return structured data (branch name, commit hash, file list) not raw text
- Pre-flight check: is this actually a git repo?
- Handle common errors: "not a git repo", "nothing to commit", "merge conflicts"

**Parameters:**
- `action` — status, log, diff, add, commit, push, pull, branch, stash, reset
- `message` — for commit action
- `branch` — for branch/push/pull actions
- `path` — repo path (defaults to session cwd)
- `confirm` — for destructive actions (reset, force push)

---

### Upgrade 6 — Process Management

**Problem:** Can't start background processes, can't check if something is running, can't kill by name intelligently.

**New Tool: `process_op` — `tools/terminal_ops.py`**

**Actions:**
- `start_background` — starts a process detached (dev server, watcher)
  - Returns: PID, command, start time
  - Stores in session: `_TERMINAL_SESSION["background_procs"][name] = pid`
- `list_background` — shows all background processes started this session
- `kill_background` — kills a background process by name or PID
- `is_running` — check if a process name or PID is currently active
- `port_check` — check if a port is in use and what's using it

**TerminalAgent prompt addition:**
```
PROCESS MANAGEMENT:
"start the dev server" / "run in background" / "keep running"
  → process_op(action='start_background', command='npm run dev', name='dev-server')
  → report: "Dev server started (PID 12345) on port 3000 🚀"

"is the server running?" / "check if X is running"
  → process_op(action='is_running', name='dev-server')

"stop the server" / "kill the dev server"
  → process_op(action='kill_background', name='dev-server')

"what's on port 3000?" / "is port 8080 free?"
  → process_op(action='port_check', port=3000)
```

---

### Upgrade 7 — Package Manager Intelligence

**Problem:** TerminalAgent runs `pip install` etc. but has no awareness of which package manager to use, whether a venv exists, or how to set things up.

**New decision tree in prompt:**

```
PACKAGE MANAGER INTELLIGENCE:
Before running any install command — check the project structure:

Python project detection:
  requirements.txt exists → pip install -r requirements.txt
  pyproject.toml exists → pip install -e . OR poetry install
  .venv or venv folder exists → activate it first:
    Windows: .\.venv\Scripts\Activate.ps1 (then pip install)
    Linux/Mac: source .venv/bin/activate

Node.js project detection:
  package-lock.json → npm install
  yarn.lock → yarn install
  pnpm-lock.yaml → pnpm install

Auto-venv creation:
  If user says "set up this Python project" and no venv exists:
  1. python -m venv .venv
  2. activate it
  3. pip install -r requirements.txt
  Report: "Created venv, installed X packages ✅"

ALWAYS report what was installed and version numbers.
ALWAYS run inside the correct directory (use cwd from session).
```

---

### Upgrade 8 — Command Chaining (Multi-Step Shell Pipelines)

**Problem:** User says "activate venv and install packages" — needs two commands that depend on each other.

**Fix: `execute_shell` command chaining**

On Windows PowerShell, commands can be chained with `;` (sequential) or `&&` (conditional on success).

**TerminalAgent prompt addition:**
```
COMMAND CHAINING:
When multiple steps must run in sequence, chain them in ONE execute_shell call:
  "activate venv then install packages":
    → execute_shell(".\.venv\Scripts\Activate.ps1; pip install -r requirements.txt")
  
  "add and commit":
    → execute_shell('git add -A; git commit -m "message"')
  
  "only install if cd works":
    → execute_shell('Set-Location C:\myproject && pip install -r requirements.txt')
  
  Use ; for "run both regardless"
  Use && for "only run second if first succeeds"
  Use || for "only run second if first FAILS"
  
NEVER run two separate execute_shell calls for things that must happen in the same shell context.
```

---

### Upgrade 9 — Network Diagnostics Mode

**Problem:** TerminalAgent can ping and run netstat but gives raw output with no insight.

**New decision tree in prompt:**

```
NETWORK DIAGNOSTICS MODE:
"check my internet" / "is my connection working"
  1. execute_shell("ping 8.8.8.8 -n 4") → check latency
  2. execute_shell("ping google.com -n 4") → check DNS resolution
  Report: "Internet ✅ — 8.8.8.8: 12ms avg | DNS working | google.com: 14ms"

"what's my IP" / "show network info"
  → execute_shell("ipconfig") → extract IPv4 addresses only
  Report: "Local IP: 192.168.1.5 (Ethernet) | No WiFi adapter active"

"scan open ports" / "what's listening"
  → execute_shell("netstat -an | Select-String 'LISTENING'")
  → parse and group by port number

"trace route to X" / "why is X slow"
  → execute_shell("tracert X -d")
  → report: hop count, first slow hop, final destination RTT

"DNS lookup X" / "what IP is X"
  → execute_shell("Resolve-DnsName X")
  → report: domain → IP mapping cleanly
```

---

### Upgrade 10 — Memory Integration (Terminal Context)

**Problem:** TerminalAgent forgets everything between sessions. Every conversation, user has to re-explain their project setup.

**Memory protocol in prompt:**

```
TERMINAL MEMORY:
At the START of every TerminalAgent session, call:
  recall("terminal cwd") → restore working directory
  recall("terminal env") → restore key environment variables  
  recall("active project") → know which project we're in

After ANY of these happen, call remember():
  User says "always work in this folder":
    → remember("terminal cwd", "C:\Users\Krish\MyProject")
  User activates a venv:
    → remember("terminal venv", "C:\Users\Krish\MyProject\.venv\Scripts\Activate.ps1")
  User sets an env var persistently:
    → remember("terminal env NODE_ENV", "production")
  User completes a workflow:
    → remember("terminal last workflow", "activate venv → pytest → git commit")

This means: next session, TerminalAgent already knows your project setup without asking.
```

---

### Upgrade 11 — Agent Cooperation

**Problem:** TerminalAgent is isolated. When it produces output (test results, build output, error logs), nothing flows to CodeAgent or FileAgent automatically.

**Cooperation signals in prompt:**

```
HANDOFF PROTOCOL:
After running tests:
  If tests PASS:
    → SUGGEST_NEXT: CodeAgent → "All tests passed. Ready to commit."
  If tests FAIL:
    → SUGGEST_NEXT: CodeAgent → "Tests failed. Error: <traceback>. Fix needed."

After build succeeds:
  → SUGGEST_NEXT: FileAgent → "Build output at C:\...\dist\ — zip or deploy?"

After git commit:
  → SUGGEST_NEXT: TerminalAgent (self) → "Committed. Push to GitHub? (git push)"

After pip/npm install completes:
  → SUGGEST_NEXT: CodeAgent → "Dependencies installed. Ready to run."
```

**Receive signals in prompt:**

```
RECEIVE FROM CODEAGENT:
If prior context contains SUGGEST_NEXT from CodeAgent:
  "run and verify this file" → execute it with the right runner
  "restart the service" → find the process and restart it
  "apply config and reload" → reload the relevant service
```

---

## New `_TERMINAL_TOOLS` set in `specialists.py`

Add new tools to the TerminalAgent toolkit:
```python
_TERMINAL_TOOLS = {
    "execute_shell",
    "run_command",
    "list_files",
    "read_file",
    "git_op",          # NEW — git intelligence wrapper
    "process_op",      # NEW — background process management
} | _MEMORY_TOOLS
```

---

## Files To Create / Modify

| File | Action | What Changes |
|---|---|---|
| `tools/terminal_ops.py` | MODIFY | Add `cwd` to `execute_shell`, session state dict, smart timeout tiers, output parsers, `git_op()`, `process_op()` |
| `tools/engine.py` | MODIFY | Add `cwd` to `execute_shell` spec, register `git_op` and `process_op` tool specs + dispatch handlers |
| `agents/specialists.py` | MODIFY | Add `git_op` and `process_op` to `_TERMINAL_TOOLS`, full rewrite of `_TERMINAL_SYSTEM_PROMPT` |

3 files. Zero new pip dependencies (all uses subprocess, os, signal — stdlib only).

---

## Implementation Order

**Phase 1 — Foundation (do first)**
1. Add `cwd` parameter to `execute_shell_command()` in `terminal_ops.py`
2. Add smart timeout tiers (auto-detect command type)
3. Add session state dict (`_TERMINAL_SESSION`)
4. Update `execute_shell` tool spec in `engine.py`
5. Test: "git status in my ANKITA folder", "npm install with 5 min timeout"

**Phase 2 — Intelligence**
6. Add output parsers (git, network, process)
7. Add `git_op()` tool + spec
8. Add git decision tree to prompt
9. Add package manager intelligence to prompt
10. Test: "what changed in my repo", "check my internet", "install requirements"

**Phase 3 — Power Features**
11. Add `process_op()` tool + spec
12. Add command chaining guide to prompt
13. Add network diagnostics decision tree
14. Test: "start dev server in background", "check if port 3000 is free"

**Phase 4 — Cooperation + Memory**
15. Add HANDOFF signals to prompt
16. Add RECEIVE mode from CodeAgent
17. Add memory protocol (recall at start, remember on state change)
18. End-to-end test: full dev workflow "cd project, activate venv, run tests, commit if pass"

---

## What Stays Unchanged

- Blocked patterns: del /s, rm -rf, format c:, shutdown /s, etc. — still hard-blocked
- Output guardrails (500 line truncation) — still active
- Security rules in prompt — still present
- `run_command` (workspace-sandboxed) — still available for CodeAgent overlap
- All existing execute_shell behavior — CWD parameter is additive, default is still home

---

## The Killer Scenario After All Upgrades

```
User: "set up my Python project in C:\repos\myapp, install deps, run tests, commit if they pass"

TerminalAgent:
  1. Session CWD → C:\repos\myapp
  2. Detects: requirements.txt exists, .venv doesn't exist
  3. Creates venv: python -m venv .venv (timeout: 60s)
  4. Activates + installs: .venv\Scripts\Activate.ps1; pip install -r requirements.txt (timeout: 300s)
     ✅ Installed 23 packages
  5. Runs tests: python -m pytest (timeout: 180s)
     ✅ 47 passed, 0 failed
  6. Commits: git add -A; git commit -m "deps installed, all tests passing"
     ✅ Committed abc1234
  7. HANDOFF: "Push to GitHub? Run: git push"
  
Done! Set up project, installed 23 packages, 47 tests passed, committed. Push when ready.
```

Zero manual steps. Zero follow-up questions. One command, full workflow.