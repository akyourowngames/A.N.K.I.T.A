"""
Cognitive Operations Engine for A.N.K.I.T.A

This is the brain that puts ANKITA in the same league as OpenClaw.
While autonomous_ops handles "run things", cognitive_ops handles "think about things":
  - Smart error analysis and auto-recovery
  - Deep workspace intelligence
  - Multi-step goal planning with verification
  - Code analysis and security scanning
  - Full project scaffolding
  - Runtime self-extension (create new tools)
  - Process monitoring with pattern-matching actions

OpenClaw's secret: it doesn't just execute — it UNDERSTANDS, ADAPTS, and RECOVERS.
"""
from __future__ import annotations

import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _run(cmd: str, timeout: int = 30, cwd: str | None = None) -> Dict[str, Any]:
    """Execute command and return structured result."""
    try:
        if os.name == "nt":
            argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
        else:
            argv = ["/bin/sh", "-c", cmd]
        proc = subprocess.Popen(
            argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=cwd, encoding="utf-8", errors="replace",
        )
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except Exception:
                stdout, stderr = "", ""
            return {"ok": False, "stdout": "", "stderr": f"timeout after {timeout}s", "exit_code": -1}
        return {
            "ok": proc.returncode == 0,
            "stdout": (stdout or "").strip(),
            "stderr": (stderr or "").strip(),
            "exit_code": proc.returncode,
        }
    except Exception as e:
        return {"ok": False, "stdout": "", "stderr": str(e), "exit_code": -1}


# ──────────────────────────────────────────────────────────────────────────────
# ERROR PATTERN DATABASE — OpenClaw's secret weapon
# Every time a command fails, ANKITA checks this database for a known fix.
# ──────────────────────────────────────────────────────────────────────────────

_ERROR_PATTERNS: List[Dict[str, Any]] = [
    # ── Permission / Access ──
    {"pattern": r"EACCES|Permission denied|Access is denied",
     "category": "permission",
     "diagnosis": "Insufficient permissions",
     "fixes": ["Run with execute_elevated()", "Check file ownership", "Run as administrator"]},

    {"pattern": r"requires elevation|is not recognized as an internal or external command",
     "category": "permission",
     "diagnosis": "Command requires admin privileges or is not in PATH",
     "fixes": ["Run with execute_elevated()", "Add to PATH", "Use full path to executable"]},

    # ── Missing Dependencies ──
    {"pattern": r"ModuleNotFoundError: No module named '(\w+)'",
     "category": "missing_module",
     "diagnosis": "Python module not installed",
     "auto_fix": "auto_install_python_package('{match_1}')"},

    {"pattern": r"ImportError: cannot import name '(\w+)' from '(\w+)'",
     "category": "import_error",
     "diagnosis": "Module exists but function/class not found — version mismatch or wrong import",
     "fixes": ["Upgrade the package: pip install --upgrade {match_2}", "Check API docs for correct import"]},

    {"pattern": r"command not found|is not recognized|not found in current PATH",
     "category": "missing_tool",
     "diagnosis": "CLI tool not installed",
     "auto_fix": "auto_install_tool('{command_name}')"},

    {"pattern": r"Cannot find module|Module not found|Cannot resolve",
     "category": "missing_node_module",
     "diagnosis": "Node.js module not installed",
     "fixes": ["npm install {module_name}", "Run environment_setup('node')"]},

    # ── Network ──
    {"pattern": r"ECONNREFUSED|Connection refused|Failed to connect",
     "category": "connection_refused",
     "diagnosis": "Service not running on the target port",
     "fixes": ["Start the service first", "Check if port is correct", "Check firewall"]},

    {"pattern": r"ETIMEDOUT|Operation timed out|Connection timed out",
     "category": "timeout",
     "diagnosis": "Network timeout — host unreachable or slow",
     "fixes": ["Check network connectivity", "Increase timeout", "Verify host/port"]},

    {"pattern": r"ENOTFOUND|getaddrinfo|Name or service not known|could not resolve host",
     "category": "dns_failure",
     "diagnosis": "DNS resolution failed",
     "fixes": ["Check hostname spelling", "Verify DNS settings", "Try IP address directly"]},

    {"pattern": r"SSL|certificate|CERT_",
     "category": "ssl_error",
     "diagnosis": "SSL/TLS certificate issue",
     "fixes": ["Use --insecure for testing only", "Update certificates", "Check system time"]},

    # ── Git ──
    {"pattern": r"fatal: not a git repository",
     "category": "not_git_repo",
     "diagnosis": "Current directory is not a git repository",
     "fixes": ["cd to the repo root first", "Run git init to create one"]},

    {"pattern": r"CONFLICT|Merge conflict|merge conflict",
     "category": "merge_conflict",
     "diagnosis": "Git merge conflict",
     "fixes": ["Open conflicted files and resolve markers", "Use git mergetool", "Abort with git merge --abort"]},

    {"pattern": r"Your branch is behind|Updates were rejected",
     "category": "git_behind",
     "diagnosis": "Remote has newer changes",
     "fixes": ["git pull --rebase origin main", "git fetch then merge manually"]},

    {"pattern": r"fatal: Authentication failed|Permission to .* denied",
     "category": "git_auth",
     "diagnosis": "Git authentication failure",
     "fixes": ["Check SSH keys: ssh -T git@github.com", "Update credentials", "Use gh auth login"]},

    # ── Build / Compile ──
    {"pattern": r"SyntaxError|IndentationError",
     "category": "python_syntax",
     "diagnosis": "Python syntax error in the code",
     "fixes": ["Check the file and line number in the error", "Run: python -m py_compile <file>"]},

    {"pattern": r"error\[E\d+\]|cannot find type|does not implement",
     "category": "rust_compile",
     "diagnosis": "Rust compilation error",
     "fixes": ["Check the error code", "Run cargo check for full diagnostics"]},

    {"pattern": r"error TS\d+|Cannot find name",
     "category": "typescript_error",
     "diagnosis": "TypeScript type error",
     "fixes": ["Check tsconfig.json strictness", "Add type declarations", "Run tsc --noEmit for full check"]},

    # ── Docker ──
    {"pattern": r"Cannot connect to the Docker daemon|docker daemon is not running",
     "category": "docker_not_running",
     "diagnosis": "Docker Desktop is not running",
     "fixes": ["Start Docker Desktop", "Run: net start docker"]},

    {"pattern": r"port is already allocated|address already in use|Bind for .* failed",
     "category": "port_conflict",
     "diagnosis": "Port already in use by another process",
     "fixes": ["Find the process: netstat -ano | findstr {port}", "Kill it or use a different port"]},

    # ── Disk / Memory ──
    {"pattern": r"No space left on device|not enough space|disk full|insufficient storage",
     "category": "disk_full",
     "diagnosis": "Disk is full",
     "fixes": ["Clear temp files: Remove-Item $env:TEMP\\* -Recurse", "Run docker system prune", "Check disk: Get-PSDrive"]},

    {"pattern": r"MemoryError|out of memory|OutOfMemoryException|heap out of memory",
     "category": "out_of_memory",
     "diagnosis": "Process ran out of memory",
     "fixes": ["Reduce batch size/data", "Increase Node heap: NODE_OPTIONS='--max-old-space-size=4096'", "Close other applications"]},

    # ── Package Managers ──
    {"pattern": r"Could not find a version that satisfies|No matching distribution",
     "category": "pip_version",
     "diagnosis": "Python package version constraint unsatisfiable",
     "fixes": ["Check available versions: pip index versions <pkg>", "Relax version constraint", "Upgrade pip"]},

    {"pattern": r"npm ERR! peer dep|ERESOLVE unable to resolve dependency",
     "category": "npm_peer_dep",
     "diagnosis": "npm peer dependency conflict",
     "fixes": ["npm install --legacy-peer-deps", "npm install --force", "Check package.json versions"]},

    {"pattern": r"npm WARN deprecated",
     "category": "npm_deprecated",
     "diagnosis": "Using deprecated npm packages (warning, not fatal)",
     "fixes": ["Update to newer alternatives", "This is usually safe to ignore"]},
]


def resolve_error(
    error_text: str,
    command: str = "",
    context: str = "",
) -> Dict[str, Any]:
    """
    Analyze an error message, match it against known patterns, and provide
    diagnosis + actionable fixes. This is ANKITA's error intelligence.

    Unlike basic tools that just return stderr, this UNDERSTANDS the error
    and tells the agent exactly what to do — like OpenClaw does.

    Args:
        error_text: The error output (stderr or exception text)
        command: The command that produced the error (optional, for context)
        context: Additional context (e.g., project type, current directory)
    """
    if not error_text.strip():
        return {"ok": True, "diagnosis": "No error to analyze"}

    matches = []
    for entry in _ERROR_PATTERNS:
        m = re.search(entry["pattern"], error_text, re.IGNORECASE)
        if m:
            fix_info = {
                "category": entry["category"],
                "diagnosis": entry["diagnosis"],
                "fixes": entry.get("fixes", []),
            }

            # Auto-fix template expansion
            auto_fix = entry.get("auto_fix", "")
            if auto_fix:
                # Replace {match_N} with regex group captures
                for i, group in enumerate(m.groups(), 1):
                    auto_fix = auto_fix.replace(f"{{match_{i}}}", group or "")
                # Replace {command_name} with first word of the command
                if command:
                    cmd_name = command.strip().split()[0] if command.strip() else ""
                    auto_fix = auto_fix.replace("{command_name}", cmd_name)
                fix_info["auto_fix"] = auto_fix

            matches.append(fix_info)

    if not matches:
        # Unknown error — provide general guidance
        return {
            "ok": True,
            "kind": "error_analysis",
            "matched": False,
            "diagnosis": "Unknown error pattern — not in ANKITA's knowledge base",
            "error_preview": error_text[:500],
            "suggestions": [
                "Search the web for the exact error message",
                "Check if all dependencies are installed",
                "Verify the command syntax is correct for this platform",
            ],
        }

    return {
        "ok": True,
        "kind": "error_analysis",
        "matched": True,
        "match_count": len(matches),
        "analysis": matches,
        "error_preview": error_text[:300],
        "command": command[:200] if command else "",
    }


# ──────────────────────────────────────────────────────────────────────────────
# SMART RETRY — The core of self-healing execution
# When a command fails, analyze WHY and try a different approach.
# ──────────────────────────────────────────────────────────────────────────────

def smart_retry(
    command: str,
    max_retries: int = 3,
    timeout: int = 60,
    cwd: str | None = None,
    auto_fix: bool = True,
) -> Dict[str, Any]:
    """
    Execute a command with intelligent retry. On failure:
    1. Analyze the error against the pattern database
    2. If auto-fix available, apply it before retrying
    3. Try command adaptations (elevated, different shell, etc.)
    4. Return detailed diagnosis if all retries fail

    This is what makes OpenClaw different — it doesn't give up on first failure.
    """
    attempts = []
    current_cmd = command

    for attempt_num in range(1, max_retries + 1):
        result = _run(current_cmd, timeout=timeout, cwd=cwd)

        attempt_record = {
            "attempt": attempt_num,
            "command": current_cmd,
            "ok": result["ok"],
            "output": result["stdout"][:1000],
            "error": result["stderr"][:500],
        }

        if result["ok"]:
            attempt_record["status"] = "success"
            attempts.append(attempt_record)
            return {
                "ok": True,
                "kind": "smart_retry",
                "command": command,
                "succeeded_on_attempt": attempt_num,
                "final_output": result["stdout"][:4000],
                "attempts": attempts,
            }

        # Analyze the error
        error_full = f"{result['stderr']}\n{result['stdout']}"
        analysis = resolve_error(error_full, command=current_cmd)

        attempt_record["error_analysis"] = analysis
        attempts.append(attempt_record)

        if not auto_fix or attempt_num >= max_retries:
            continue

        # Try to apply auto-fixes
        if analysis.get("matched") and analysis.get("analysis"):
            for fix in analysis["analysis"]:
                if "auto_fix" in fix:
                    # We have an auto-fix suggestion — note it but can't call tools from here
                    # Instead we try command adaptations
                    attempt_record["suggested_auto_fix"] = fix["auto_fix"]
                    break

            # Command adaptations based on error category
            categories = {f["category"] for f in analysis["analysis"]}

            if "permission" in categories:
                # Try elevated execution
                if os.name == "nt":
                    current_cmd = f"gsudo {command}" if _run("gsudo --version").get("ok") else command
                else:
                    current_cmd = f"sudo {command}"
                attempt_record["adaptation"] = "Trying elevated execution"

            elif "missing_module" in categories:
                # Try to install the missing module first
                for fix in analysis["analysis"]:
                    af = fix.get("auto_fix", "")
                    m = re.search(r"auto_install_python_package\('(\w+)'\)", af)
                    if m:
                        pkg = m.group(1)
                        _run(f"pip install {pkg}", timeout=120)
                        attempt_record["adaptation"] = f"Auto-installed Python package: {pkg}"
                        current_cmd = command  # Retry original
                        break

            elif "missing_tool" in categories:
                # Extract tool name and try to install
                cmd_parts = command.strip().split()
                if cmd_parts:
                    tool_name = cmd_parts[0]
                    # Try winget first (most reliable on Windows)
                    _run(f"winget install {tool_name} --accept-package-agreements --accept-source-agreements", timeout=120)
                    attempt_record["adaptation"] = f"Attempted auto-install of: {tool_name}"
                    current_cmd = command  # Retry original

            elif "port_conflict" in categories:
                attempt_record["adaptation"] = "Port conflict detected — cannot auto-fix"
                break  # No point retrying

            elif "disk_full" in categories:
                attempt_record["adaptation"] = "Disk full — cannot auto-fix"
                break

    # All retries exhausted
    final_analysis = resolve_error(
        attempts[-1]["error"] if attempts else "",
        command=command,
    )

    return {
        "ok": False,
        "kind": "smart_retry",
        "command": command,
        "total_attempts": len(attempts),
        "final_error": attempts[-1]["error"][:500] if attempts else "No attempts made",
        "diagnosis": final_analysis,
        "attempts": attempts,
    }


# ──────────────────────────────────────────────────────────────────────────────
# WORKSPACE INTELLIGENCE — Deep project understanding
# OpenClaw scans and UNDERSTANDS the project before working on it.
# ──────────────────────────────────────────────────────────────────────────────

def workspace_scan(path: str | None = None) -> Dict[str, Any]:
    """
    Deep-scan a workspace/project directory and return comprehensive intelligence:
    - Tech stack detection
    - Dependency analysis
    - Git state
    - CI/CD configuration
    - Docker setup
    - Environment variables
    - Project structure summary
    - Entry points and scripts
    - Code statistics

    This is how ANKITA understands a project BEFORE making changes — 
    exactly like OpenClaw does.
    """
    proj = Path(path).resolve() if path else Path.cwd()
    if not proj.exists():
        return {"ok": False, "error": f"Path not found: {proj}"}

    scan: Dict[str, Any] = {
        "ok": True,
        "kind": "workspace_scan",
        "path": str(proj),
        "name": proj.name,
    }

    # ── File inventory ──
    all_files: List[str] = []
    file_types: Dict[str, int] = {}
    total_size = 0
    skip_dirs = {".git", "node_modules", ".venv", "__pycache__", ".next", "dist", "build", ".tox", "venv", "env"}

    try:
        for root, dirs, files in os.walk(proj):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for f in files:
                fp = Path(root) / f
                rel = str(fp.relative_to(proj)).replace("\\", "/")
                all_files.append(rel)
                ext = fp.suffix.lower()
                file_types[ext] = file_types.get(ext, 0) + 1
                try:
                    total_size += fp.stat().st_size
                except OSError:
                    pass
    except PermissionError:
        scan["warnings"] = ["Some directories not accessible"]

    scan["total_files"] = len(all_files)
    scan["total_size_mb"] = round(total_size / (1024 * 1024), 2)
    scan["file_types"] = dict(sorted(file_types.items(), key=lambda x: -x[1])[:20])

    # ── Root-level files ──
    root_files = {f.name for f in proj.iterdir() if f.is_file()} if proj.is_dir() else set()
    root_dirs = {d.name for d in proj.iterdir() if d.is_dir()} if proj.is_dir() else set()
    scan["root_files"] = sorted(root_files)[:50]
    scan["root_dirs"] = sorted(root_dirs - skip_dirs)[:30]

    # ── Tech stack detection ──
    stack = []
    frameworks = []
    
    # Python
    if any(f in root_files for f in ("requirements.txt", "pyproject.toml", "setup.py", "Pipfile", "setup.cfg")):
        stack.append("python")
        if "pyproject.toml" in root_files:
            try:
                toml_content = (proj / "pyproject.toml").read_text(encoding="utf-8", errors="replace")[:4000]
                for fw in ["django", "flask", "fastapi", "streamlit", "dash", "celery", "scrapy"]:
                    if fw in toml_content.lower():
                        frameworks.append(fw)
            except OSError:
                pass
        if "requirements.txt" in root_files:
            try:
                reqs = (proj / "requirements.txt").read_text(encoding="utf-8", errors="replace").lower()
                for fw in ["django", "flask", "fastapi", "streamlit", "tensorflow", "torch", "pandas", "numpy"]:
                    if fw in reqs:
                        frameworks.append(fw)
            except OSError:
                pass

    # Node.js
    if "package.json" in root_files:
        stack.append("node")
        try:
            pkg_json = json.loads((proj / "package.json").read_text(encoding="utf-8"))
            all_deps = {**pkg_json.get("dependencies", {}), **pkg_json.get("devDependencies", {})}
            scan["node_dependencies"] = len(all_deps)
            scan["node_scripts"] = list(pkg_json.get("scripts", {}).keys())[:20]
            for fw in ["react", "next", "vue", "nuxt", "angular", "svelte", "express", "fastify", "nest", "electron"]:
                if any(fw in d for d in all_deps):
                    frameworks.append(fw)
        except (json.JSONDecodeError, OSError):
            pass

    # Rust
    if "Cargo.toml" in root_files:
        stack.append("rust")
    
    # Go
    if "go.mod" in root_files:
        stack.append("go")
        try:
            gomod = (proj / "go.mod").read_text(encoding="utf-8", errors="replace")[:2000]
            m = re.search(r"^module\s+(\S+)", gomod, re.MULTILINE)
            if m:
                scan["go_module"] = m.group(1)
        except OSError:
            pass

    # Java
    if any(f in root_files for f in ("pom.xml", "build.gradle", "build.gradle.kts")):
        stack.append("java")
        if "pom.xml" in root_files:
            frameworks.append("maven")
        if "build.gradle" in root_files or "build.gradle.kts" in root_files:
            frameworks.append("gradle")
    
    # C/C++
    if any(f in root_files for f in ("CMakeLists.txt", "Makefile", "meson.build")):
        stack.append("c/c++")

    # Fallback: if no config files found, detect by file extensions
    if not stack:
        ext_counts = scan.get("file_types", {})
        if ext_counts.get(".py", 0) > 3:
            stack.append("python")
        if ext_counts.get(".js", 0) + ext_counts.get(".ts", 0) > 3:
            stack.append("node")
        if ext_counts.get(".rs", 0) > 1:
            stack.append("rust")
        if ext_counts.get(".go", 0) > 1:
            stack.append("go")
        if ext_counts.get(".java", 0) > 1:
            stack.append("java")

    # Docker
    if any(f in root_files for f in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")):
        stack.append("docker")
        scan["has_docker"] = True

    scan["tech_stack"] = stack
    scan["frameworks"] = list(set(frameworks))

    # ── Git state ──
    git_dir = proj / ".git"
    if git_dir.exists():
        scan["is_git_repo"] = True
        git_result = _run("git rev-parse --abbrev-ref HEAD", cwd=str(proj))
        scan["git_branch"] = git_result["stdout"] if git_result["ok"] else "unknown"

        status = _run("git status --porcelain", cwd=str(proj))
        if status["ok"]:
            lines = [l for l in status["stdout"].splitlines() if l.strip()]
            scan["git_dirty_files"] = len(lines)
            scan["git_changes_preview"] = lines[:15]

        recent = _run("git log --oneline -5", cwd=str(proj))
        scan["git_recent_commits"] = recent["stdout"].splitlines()[:5] if recent["ok"] else []

        remotes = _run("git remote -v", cwd=str(proj))
        scan["git_remotes"] = remotes["stdout"][:500] if remotes["ok"] else ""
    else:
        scan["is_git_repo"] = False

    # ── CI/CD detection ──
    ci_configs = []
    ci_checks = {
        ".github/workflows": "github_actions",
        ".gitlab-ci.yml": "gitlab_ci",
        "Jenkinsfile": "jenkins",
        ".circleci": "circleci",
        ".travis.yml": "travis",
        "azure-pipelines.yml": "azure_devops",
        "bitbucket-pipelines.yml": "bitbucket",
        "vercel.json": "vercel",
        "netlify.toml": "netlify",
        "fly.toml": "fly.io",
        "railway.json": "railway",
        "render.yaml": "render",
    }
    for check_path, ci_name in ci_checks.items():
        if (proj / check_path).exists():
            ci_configs.append(ci_name)
    scan["ci_cd"] = ci_configs

    # ── Environment / Config files ──
    config_files = []
    for f in root_files:
        if f.startswith(".env") or f.endswith(".env") or f in (".editorconfig", ".prettierrc", "tsconfig.json", "webpack.config.js", "vite.config.ts", "jest.config.js", ".eslintrc.json", "tox.ini", "mypy.ini", ".flake8"):
            config_files.append(f)
    scan["config_files"] = sorted(config_files)

    has_env = (proj / ".env").exists()
    has_env_example = (proj / ".env.example").exists() or (proj / ".env.sample").exists()
    scan["has_env_file"] = has_env
    scan["has_env_example"] = has_env_example

    # ── Entry points ──
    entry_points = []
    common_entries = ["main.py", "app.py", "server.py", "index.js", "index.ts", "main.go", "main.rs", "Main.java", "Program.cs"]
    for ep in common_entries:
        if ep in root_files:
            entry_points.append(ep)
    if "package.json" in root_files:
        try:
            pkg = json.loads((proj / "package.json").read_text(encoding="utf-8"))
            if "main" in pkg:
                entry_points.append(f"package.json:main → {pkg['main']}")
        except (json.JSONDecodeError, OSError):
            pass
    scan["entry_points"] = entry_points

    # ── Code stats (fast estimate) ──
    code_exts = {".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go", ".java", ".c", ".cpp", ".h", ".cs"}
    code_files = sum(1 for f in all_files if Path(f).suffix.lower() in code_exts)
    test_files = sum(1 for f in all_files if "test" in f.lower() or "spec" in f.lower())
    scan["code_files"] = code_files
    scan["test_files"] = test_files

    # ── Summary ──
    scan["summary"] = (
        f"{proj.name}: {', '.join(stack) or 'unknown stack'} project"
        f"{' + ' + ', '.join(frameworks) if frameworks else ''}"
        f" | {len(all_files)} files ({scan['total_size_mb']}MB)"
        f" | {code_files} code, {test_files} test files"
        f"{' | git: ' + scan.get('git_branch', '') if scan.get('is_git_repo') else ''}"
        f"{' | CI: ' + ', '.join(ci_configs) if ci_configs else ''}"
    )

    return scan


# ──────────────────────────────────────────────────────────────────────────────
# PLAN & EXECUTE — Autonomous multi-step goal decomposition
# This is what separates a real AI agent from a command runner.
# ──────────────────────────────────────────────────────────────────────────────

def plan_and_execute(
    goal: str,
    steps: List[Dict[str, str]],
    stop_on_error: bool = False,
    verify_command: str | None = None,
    cwd: str | None = None,
) -> Dict[str, Any]:
    """
    Execute a multi-step plan with self-healing retry on each step.
    
    Unlike execute_pipeline (which just chains commands), this:
    - Retries failed steps with error analysis
    - Adapts commands based on platform
    - Tracks cumulative state across steps
    - Runs a verification command at the end
    - Provides a full execution report

    Args:
        goal: The high-level objective (for reporting)
        steps: List of {"command": "...", "description": "...", "retries": N}
        stop_on_error: If True, abort plan on first unrecoverable failure
        verify_command: Optional command to verify success at the end
        cwd: Working directory for all commands
    """
    if not steps:
        return {"ok": False, "error": "Plan requires at least one step"}

    plan_start = time.time()
    results = []
    failed_steps = 0

    for i, step in enumerate(steps):
        cmd = step.get("command", "").strip()
        desc = step.get("description", f"Step {i + 1}")
        max_retries = int(step.get("retries", 2))
        step_timeout = int(step.get("timeout", 60))

        if not cmd:
            results.append({"step": i + 1, "description": desc, "ok": False, "error": "Empty command", "skipped": True})
            continue

        # Use smart_retry for each step
        step_result = smart_retry(
            command=cmd,
            max_retries=max_retries,
            timeout=step_timeout,
            cwd=cwd,
            auto_fix=True,
        )

        record = {
            "step": i + 1,
            "description": desc,
            "command": cmd,
            "ok": step_result["ok"],
            "attempts": step_result.get("succeeded_on_attempt", step_result.get("total_attempts", 0)),
            "output": step_result.get("final_output", step_result.get("final_error", ""))[:500],
        }

        if not step_result["ok"]:
            failed_steps += 1
            record["diagnosis"] = step_result.get("diagnosis", {})
            if stop_on_error:
                record["plan_aborted"] = True
                results.append(record)
                break

        results.append(record)

    # Verification step
    verification = None
    if verify_command:
        v_result = _run(verify_command, timeout=30, cwd=cwd)
        verification = {
            "command": verify_command,
            "ok": v_result["ok"],
            "output": v_result["stdout"][:500],
        }

    elapsed = round(time.time() - plan_start, 1)
    succeeded = sum(1 for r in results if r.get("ok"))

    return {
        "ok": failed_steps == 0,
        "kind": "plan_execution",
        "goal": goal,
        "total_steps": len(steps),
        "succeeded": succeeded,
        "failed": failed_steps,
        "elapsed_seconds": elapsed,
        "results": results,
        "verification": verification,
    }


# ──────────────────────────────────────────────────────────────────────────────
# CODE ANALYSIS — Static analysis, security scan, dependency audit
# ──────────────────────────────────────────────────────────────────────────────

def code_analysis(
    path: str,
    focus: str = "all",
) -> Dict[str, Any]:
    """
    Analyze code quality, security, and dependencies.
    
    Focus options:
    - "all": Full analysis
    - "security": Security vulnerabilities only
    - "dependencies": Dependency audit
    - "quality": Code quality & linting
    - "complexity": File/function complexity analysis

    Uses available tools (ruff, mypy, eslint, npm audit, pip-audit, etc.)
    and falls back to built-in analysis when tools aren't available.
    """
    proj = Path(path).resolve()
    if not proj.exists():
        return {"ok": False, "error": f"Path not found: {proj}"}

    analysis: Dict[str, Any] = {
        "ok": True,
        "kind": "code_analysis",
        "path": str(proj),
        "focus": focus,
        "results": {},
    }

    targets = {"all", focus} if focus != "all" else {"all", "security", "dependencies", "quality"}

    # ── Python Code Quality ──
    if targets & {"all", "quality"}:
        # Try ruff (fastest Python linter)
        if _run("ruff --version")["ok"]:
            ruff_result = _run(f'ruff check "{proj}" --output-format json 2>$null', timeout=60)
            if ruff_result["ok"] or ruff_result["stdout"]:
                try:
                    issues = json.loads(ruff_result["stdout"]) if ruff_result["stdout"].startswith("[") else []
                    analysis["results"]["ruff"] = {
                        "tool": "ruff",
                        "issues": len(issues),
                        "preview": [{"file": i.get("filename",""), "code": i.get("code",""), "message": i.get("message","")} for i in issues[:10]],
                    }
                except json.JSONDecodeError:
                    analysis["results"]["ruff"] = {"tool": "ruff", "raw": ruff_result["stdout"][:1000]}
        
        # Try mypy for type checking (skip when focus is security — too slow, not relevant)
        if _run("mypy --version")["ok"] and focus != "security":
            mypy_result = _run(f'mypy "{proj}" --ignore-missing-imports --no-error-summary 2>$null', timeout=45)
            lines = [l for l in mypy_result["stdout"].splitlines() if "error:" in l]
            analysis["results"]["mypy"] = {
                "tool": "mypy",
                "type_errors": len(lines),
                "preview": lines[:10],
            }

    # ── Security Analysis ──
    if targets & {"all", "security"}:
        # Python: pip-audit or safety
        if (proj / "requirements.txt").exists():
            if _run("pip-audit --version")["ok"]:
                audit = _run(f'pip-audit -r "{proj / "requirements.txt"}" --format json 2>$null', timeout=60)
                if audit["stdout"]:
                    try:
                        vulns = json.loads(audit["stdout"])
                        analysis["results"]["pip_audit"] = {
                            "tool": "pip-audit",
                            "vulnerabilities": len(vulns) if isinstance(vulns, list) else vulns,
                        }
                    except json.JSONDecodeError:
                        analysis["results"]["pip_audit"] = {"tool": "pip-audit", "raw": audit["stdout"][:500]}

        # Node: npm audit
        if (proj / "package.json").exists():
            npm_audit = _run(f'cd "{proj}"; npm audit --json 2>$null', timeout=60)
            if npm_audit["stdout"]:
                try:
                    audit_data = json.loads(npm_audit["stdout"])
                    vuln_meta = audit_data.get("metadata", {}).get("vulnerabilities", {})
                    analysis["results"]["npm_audit"] = {
                        "tool": "npm audit",
                        "total": sum(vuln_meta.values()) if isinstance(vuln_meta, dict) else 0,
                        "by_severity": vuln_meta,
                    }
                except json.JSONDecodeError:
                    analysis["results"]["npm_audit"] = {"tool": "npm audit", "raw": npm_audit["stdout"][:500]}

        # Built-in: scan for common security issues in Python files
        security_flags = []
        dangerous_patterns = [
            (r"\beval\s*\(", "eval() usage — potential code injection"),
            (r"\bexec\s*\(", "exec() usage — potential code injection"),
            (r"subprocess\..*shell\s*=\s*True", "subprocess with shell=True — command injection risk"),
            (r"pickle\.load", "pickle.load — deserialization vulnerability"),
            (r"yaml\.load\((?!.*Loader)", "yaml.load without safe Loader — code execution risk"),
            (r"password\s*=\s*['\"]", "Hardcoded password detected"),
            (r"api_key\s*=\s*['\"]", "Hardcoded API key detected"),
            (r"secret\s*=\s*['\"]", "Hardcoded secret detected"),
            (r"os\.system\s*\(", "os.system() usage — prefer subprocess"),
        ]

        code_exts = {".py"}
        scanned = 0
        for root, dirs, files in os.walk(proj):
            dirs[:] = [d for d in dirs if d not in {".git", "node_modules", ".venv", "__pycache__", "venv"}]
            for f in files:
                if Path(f).suffix not in code_exts:
                    continue
                fp = Path(root) / f
                try:
                    content = fp.read_text(encoding="utf-8", errors="replace")
                    scanned += 1
                    for pattern, desc in dangerous_patterns:
                        matches = list(re.finditer(pattern, content))
                        for match in matches:
                            line_no = content[:match.start()].count("\n") + 1
                            rel_path = str(fp.relative_to(proj)).replace("\\", "/")
                            security_flags.append({
                                "file": rel_path,
                                "line": line_no,
                                "issue": desc,
                            })
                except OSError:
                    pass

        analysis["results"]["builtin_security_scan"] = {
            "files_scanned": scanned,
            "issues_found": len(security_flags),
            "issues": security_flags[:25],  # Cap at 25 for output size
        }

    # ── Dependency Analysis ──
    if targets & {"all", "dependencies"}:
        deps: Dict[str, Any] = {}

        if (proj / "requirements.txt").exists():
            try:
                reqs = (proj / "requirements.txt").read_text(encoding="utf-8").strip().splitlines()
                deps["python"] = {
                    "file": "requirements.txt",
                    "count": len([r for r in reqs if r.strip() and not r.strip().startswith("#")]),
                    "packages": [r.strip() for r in reqs if r.strip() and not r.strip().startswith("#")][:30],
                }
            except OSError:
                pass

        if (proj / "package.json").exists():
            try:
                pkg = json.loads((proj / "package.json").read_text(encoding="utf-8"))
                deps["node"] = {
                    "file": "package.json",
                    "dependencies": len(pkg.get("dependencies", {})),
                    "devDependencies": len(pkg.get("devDependencies", {})),
                    "packages": list(pkg.get("dependencies", {}).keys())[:30],
                }
            except (json.JSONDecodeError, OSError):
                pass

        # Check for outdated packages
        if "python" in deps:
            outdated = _run("pip list --outdated --format json 2>$null", timeout=30)
            if outdated["ok"] and outdated["stdout"]:
                try:
                    outdated_pkgs = json.loads(outdated["stdout"])
                    deps["python_outdated"] = {
                        "count": len(outdated_pkgs),
                        "packages": [{"name": p["name"], "current": p["version"], "latest": p["latest_version"]} for p in outdated_pkgs[:15]],
                    }
                except json.JSONDecodeError:
                    pass

        analysis["results"]["dependencies"] = deps

    # ── Complexity (built-in file-level analysis) ──
    if targets & {"all", "complexity"}:
        large_files = []
        for f in all_files if 'all_files' in dir() else []:
            fp = proj / f
            if fp.suffix == ".py" and fp.exists():
                try:
                    lines = len(fp.read_text(encoding="utf-8", errors="replace").splitlines())
                    if lines > 300:
                        large_files.append({"file": f, "lines": lines})
                except OSError:
                    pass
        large_files.sort(key=lambda x: -x["lines"])
        analysis["results"]["complexity"] = {
            "large_files_over_300_lines": large_files[:20],
        }

    return analysis


# ──────────────────────────────────────────────────────────────────────────────
# PROJECT SCAFFOLDING — Create full projects from templates
# ──────────────────────────────────────────────────────────────────────────────

_TEMPLATES = {
    "python-api": {
        "description": "FastAPI REST API with async support",
        "files": {
            "main.py": textwrap.dedent("""\
                from fastapi import FastAPI
                from pydantic import BaseModel

                app = FastAPI(title="{name}", version="1.0.0")

                class HealthResponse(BaseModel):
                    status: str
                    version: str

                @app.get("/health", response_model=HealthResponse)
                async def health():
                    return HealthResponse(status="ok", version="1.0.0")

                @app.get("/")
                async def root():
                    return {{"message": "Welcome to {name}"}}

                if __name__ == "__main__":
                    import uvicorn
                    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
            """),
            "requirements.txt": "fastapi>=0.104.0\nuvicorn[standard]>=0.24.0\npydantic>=2.5.0\nhttpx>=0.25.0\npython-dotenv>=1.0.0\n",
            ".env.example": "APP_ENV=development\nDATABASE_URL=sqlite:///./app.db\nSECRET_KEY=change-me\n",
            "Dockerfile": textwrap.dedent("""\
                FROM python:3.12-slim
                WORKDIR /app
                COPY requirements.txt .
                RUN pip install --no-cache-dir -r requirements.txt
                COPY . .
                EXPOSE 8000
                CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
            """),
            ".gitignore": "__pycache__/\n*.pyc\n.env\n.venv/\n*.db\n",
            "README.md": "# {name}\n\n## Quick Start\n```bash\npip install -r requirements.txt\npython main.py\n```\n\nAPI docs at http://localhost:8000/docs\n",
        },
        "post_create": ["python -m venv .venv", ".venv\\Scripts\\pip install -r requirements.txt"],
    },

    "python-cli": {
        "description": "Python CLI tool with typer",
        "files": {
            "main.py": textwrap.dedent("""\
                import typer

                app = typer.Typer(name="{name}", help="{name} CLI tool")

                @app.command()
                def hello(name: str = typer.Argument("World", help="Name to greet")):
                    \"\"\"Say hello.\"\"\"
                    typer.echo(f"Hello {{name}}!")

                @app.command()
                def version():
                    \"\"\"Show version.\"\"\"
                    typer.echo("{name} v1.0.0")

                if __name__ == "__main__":
                    app()
            """),
            "requirements.txt": "typer>=0.9.0\nrich>=13.0.0\n",
            ".gitignore": "__pycache__/\n*.pyc\n.env\n.venv/\n",
            "README.md": "# {name}\n\nA CLI tool.\n\n```bash\npip install -r requirements.txt\npython main.py --help\n```\n",
        },
        "post_create": ["python -m venv .venv", ".venv\\Scripts\\pip install -r requirements.txt"],
    },

    "node-api": {
        "description": "Express.js REST API with TypeScript",
        "files": {
            "src/index.ts": textwrap.dedent("""\
                import express from 'express';
                import cors from 'cors';

                const app = express();
                const PORT = process.env.PORT || 3000;

                app.use(cors());
                app.use(express.json());

                app.get('/health', (req, res) => {{
                    res.json({{ status: 'ok', timestamp: new Date().toISOString() }});
                }});

                app.get('/', (req, res) => {{
                    res.json({{ message: 'Welcome to {name}' }});
                }});

                app.listen(PORT, () => {{
                    console.log(`Server running on port ${{PORT}}`);
                }});
            """),
            "package.json": json.dumps({
                "name": "{name}",
                "version": "1.0.0",
                "scripts": {
                    "dev": "tsx watch src/index.ts",
                    "build": "tsc",
                    "start": "node dist/index.js",
                },
                "dependencies": {
                    "express": "^4.18.0",
                    "cors": "^2.8.5",
                },
                "devDependencies": {
                    "typescript": "^5.3.0",
                    "@types/express": "^4.17.0",
                    "@types/cors": "^2.8.0",
                    "tsx": "^4.7.0",
                },
            }, indent=2).replace('"{name}"', '"{name}"'),
            "tsconfig.json": json.dumps({
                "compilerOptions": {
                    "target": "ES2022",
                    "module": "commonjs",
                    "outDir": "./dist",
                    "rootDir": "./src",
                    "strict": True,
                    "esModuleInterop": True,
                },
                "include": ["src/**/*"],
            }, indent=2),
            ".gitignore": "node_modules/\ndist/\n.env\n",
            ".env.example": "PORT=3000\nNODE_ENV=development\n",
            "README.md": "# {name}\n\n```bash\nnpm install\nnpm run dev\n```\n\nAPI at http://localhost:3000\n",
        },
        "post_create": ["npm install"],
    },

    "react-app": {
        "description": "React + TypeScript + Vite app",
        "files": {},  # Use create-vite directly
        "use_cli": "npm create vite@latest {name} -- --template react-ts",
        "post_create": ["cd {name}", "npm install"],
    },

    "static-site": {
        "description": "Simple HTML/CSS/JS static site",
        "files": {
            "index.html": textwrap.dedent("""\
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>{name}</title>
                    <link rel="stylesheet" href="style.css">
                </head>
                <body>
                    <main>
                        <h1>{name}</h1>
                        <p>Welcome to {name}.</p>
                    </main>
                    <script src="main.js"></script>
                </body>
                </html>
            """),
            "style.css": textwrap.dedent("""\
                :root {{ --primary: #3b82f6; --bg: #0f172a; --text: #e2e8f0; }}
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ font-family: system-ui, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; align-items: center; justify-content: center; }}
                main {{ text-align: center; padding: 2rem; }}
                h1 {{ font-size: 2.5rem; margin-bottom: 1rem; color: var(--primary); }}
            """),
            "main.js": 'console.log("{name} loaded");\n',
            ".gitignore": ".DS_Store\nnode_modules/\n",
            "README.md": "# {name}\n\nOpen `index.html` in a browser.\n",
        },
    },
}


def project_scaffold(
    template: str,
    name: str,
    path: str | None = None,
    auto_setup: bool = True,
) -> Dict[str, Any]:
    """
    Create a full project from a template. Like 'create-react-app' but for ANY stack.

    Templates: python-api, python-cli, node-api, react-app, static-site
    """
    template = template.strip().lower()
    if template not in _TEMPLATES:
        return {
            "ok": False,
            "error": f"Unknown template: {template}",
            "available": list(_TEMPLATES.keys()),
            "descriptions": {k: v["description"] for k, v in _TEMPLATES.items()},
        }

    tmpl = _TEMPLATES[template]
    proj_dir = Path(path or Path.home() / "Projects" / name).resolve()

    # Check if directory exists
    if proj_dir.exists() and any(proj_dir.iterdir()):
        return {"ok": False, "error": f"Directory already exists and is not empty: {proj_dir}"}

    proj_dir.mkdir(parents=True, exist_ok=True)
    created_files = []

    # If template uses a CLI tool (like create-vite), run it
    if "use_cli" in tmpl:
        cli_cmd = tmpl["use_cli"].replace("{name}", name)
        result = _run(cli_cmd, timeout=120, cwd=str(proj_dir.parent))
        if not result["ok"]:
            return {"ok": False, "error": f"CLI scaffold failed: {result['stderr'][:500]}"}
        created_files.append(f"[via CLI: {cli_cmd}]")
    else:
        # Create files from template
        for file_path, content in tmpl["files"].items():
            content = content.replace("{name}", name)
            full_path = proj_dir / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            created_files.append(file_path)

    # Post-create commands (install deps, etc.)
    post_results = []
    if auto_setup and "post_create" in tmpl:
        for cmd in tmpl["post_create"]:
            cmd = cmd.replace("{name}", name)
            result = _run(cmd, timeout=300, cwd=str(proj_dir))
            post_results.append({
                "command": cmd,
                "ok": result["ok"],
                "output": result["stdout"][:200] if result["ok"] else result["stderr"][:200],
            })

    # Initialize git
    git_result = _run("git init", cwd=str(proj_dir))

    return {
        "ok": True,
        "kind": "project_scaffold",
        "template": template,
        "name": name,
        "path": str(proj_dir),
        "files_created": created_files,
        "post_setup": post_results,
        "git_initialized": git_result["ok"],
        "description": tmpl["description"],
    }


# ──────────────────────────────────────────────────────────────────────────────
# SELF-EXTENSION — ANKITA can create new tools at runtime
# This is OpenClaw's Skills system — the AI writes code to extend itself.
# ──────────────────────────────────────────────────────────────────────────────

# Registry of runtime-created tools
_RUNTIME_TOOLS: Dict[str, Dict[str, Any]] = {}


def self_extend(
    name: str,
    description: str,
    code: str,
) -> Dict[str, Any]:
    """
    Create a new tool at runtime by writing and registering a Python function.
    
    The code must define a function with the same name as `name`.
    It will be saved to disk and importable in future sessions.

    Args:
        name: Tool function name (snake_case, e.g. 'analyze_logs')
        description: What the tool does
        code: Python source code defining the function
    """
    # Validate name
    if not re.match(r'^[a-z_][a-z0-9_]*$', name):
        return {"ok": False, "error": f"Invalid tool name: {name}. Use snake_case."}

    # Security: basic code validation
    forbidden = ["os.system", "subprocess.call", "__import__('os').system", "eval(", "exec("]
    code_lower = code.lower()
    for f in forbidden:
        if f.lower() in code_lower and "subprocess.run" not in code_lower:
            return {"ok": False, "error": f"Security: forbidden pattern '{f}' in code. Use subprocess.run instead."}

    # Save to extensions directory
    ext_dir = Path(__file__).parent / "extensions"
    ext_dir.mkdir(exist_ok=True)
    ext_file = ext_dir / f"{name}.py"

    # Write the extension
    header = f'"""\nANKITA Runtime Extension: {name}\n{description}\nAuto-generated by self_extend()\n"""\n\n'
    ext_file.write_text(header + code, encoding="utf-8")

    # Try to load and validate it
    try:
        spec = importlib.util.spec_from_file_location(name, str(ext_file))
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            func = getattr(module, name, None)
            if func is None:
                ext_file.unlink(missing_ok=True)
                return {"ok": False, "error": f"Code must define a function named '{name}'"}
            if not callable(func):
                ext_file.unlink(missing_ok=True)
                return {"ok": False, "error": f"'{name}' is not callable"}

            # Register in runtime tools
            _RUNTIME_TOOLS[name] = {
                "function": func,
                "description": description,
                "file": str(ext_file),
            }

            return {
                "ok": True,
                "kind": "self_extend",
                "tool_name": name,
                "description": description,
                "file": str(ext_file),
                "registered": True,
                "note": f"Tool '{name}' is now available. Call execute_extension('{name}', args) to use it.",
            }
    except Exception as e:
        ext_file.unlink(missing_ok=True)
        return {"ok": False, "error": f"Failed to load extension: {e}"}

    return {"ok": False, "error": "Unknown error during extension registration"}


def execute_extension(
    name: str,
    args: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Execute a runtime-created tool extension."""
    if name not in _RUNTIME_TOOLS:
        # Try loading from disk
        ext_file = Path(__file__).parent / "extensions" / f"{name}.py"
        if ext_file.exists():
            try:
                spec = importlib.util.spec_from_file_location(name, str(ext_file))
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    func = getattr(module, name, None)
                    if func and callable(func):
                        _RUNTIME_TOOLS[name] = {"function": func, "description": "", "file": str(ext_file)}
            except Exception as e:
                return {"ok": False, "error": f"Failed to load extension '{name}': {e}"}

    tool = _RUNTIME_TOOLS.get(name)
    if not tool:
        available = list(_RUNTIME_TOOLS.keys())
        # Also check disk
        ext_dir = Path(__file__).parent / "extensions"
        if ext_dir.exists():
            available.extend(f.stem for f in ext_dir.glob("*.py") if f.stem not in available)
        return {"ok": False, "error": f"Extension '{name}' not found", "available": available}

    try:
        result = tool["function"](**(args or {}))
        return {
            "ok": True,
            "kind": "extension_result",
            "tool": name,
            "result": result if isinstance(result, (dict, list, str, int, float, bool)) else str(result),
        }
    except Exception as e:
        return {"ok": False, "error": f"Extension '{name}' raised: {e}"}


# ──────────────────────────────────────────────────────────────────────────────
# PROCESS WATCH — Monitor long-running processes with pattern actions
# ──────────────────────────────────────────────────────────────────────────────

def process_watch(
    command: str,
    duration: int = 60,
    success_pattern: str | None = None,
    failure_pattern: str | None = None,
    capture_last: int = 50,
) -> Dict[str, Any]:
    """
    Start a process, watch its output for patterns, return when pattern
    matches or duration expires. Perfect for:
    - Waiting for servers to start ("listening on port")
    - Watching build progress ("Build succeeded")
    - Monitoring deployments ("deployed successfully")

    Args:
        command: Command to run
        duration: Maximum seconds to watch
        success_pattern: Regex pattern — if matched, return immediately with success
        failure_pattern: Regex pattern — if matched, return immediately with failure
        capture_last: Number of output lines to keep in buffer
    """
    if os.name == "nt":
        argv = ["powershell", "-NoProfile", "-Command", command]
    else:
        argv = ["/bin/sh", "-c", command]

    output_lines: List[str] = []
    matched_pattern = None
    matched_line = None

    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        start = time.time()
        while time.time() - start < duration:
            if proc.stdout is None:
                break
            # Read with timeout
            proc.stdout.flush()
            import select
            if os.name == "nt":
                # Windows doesn't support select on pipes — use readline with short timeout
                line = proc.stdout.readline()
            else:
                ready, _, _ = select.select([proc.stdout], [], [], 1.0)
                line = proc.stdout.readline() if ready else ""

            if line:
                line = line.rstrip()
                output_lines.append(line)
                if len(output_lines) > capture_last:
                    output_lines.pop(0)

                if success_pattern and re.search(success_pattern, line, re.IGNORECASE):
                    matched_pattern = "success"
                    matched_line = line
                    break
                if failure_pattern and re.search(failure_pattern, line, re.IGNORECASE):
                    matched_pattern = "failure"
                    matched_line = line
                    break

            elif proc.poll() is not None:
                # Process ended
                break

        elapsed = round(time.time() - start, 1)

        # Read any remaining output
        if proc.stdout and proc.poll() is None:
            try:
                remaining = proc.stdout.read()
                if remaining:
                    output_lines.extend(remaining.strip().splitlines()[-capture_last:])
            except Exception:
                pass

        # Terminate if still running
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

        return {
            "ok": matched_pattern == "success" or (matched_pattern is None and proc.returncode == 0),
            "kind": "process_watch",
            "command": command,
            "elapsed_seconds": elapsed,
            "exit_code": proc.returncode,
            "pattern_matched": matched_pattern,
            "matched_line": matched_line,
            "output": output_lines,
            "timed_out": elapsed >= duration and matched_pattern is None,
        }

    except Exception as e:
        return {"ok": False, "kind": "process_watch", "error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# CROSS-PLATFORM COMMAND INTELLIGENCE
# Translate commands between platforms so ANKITA works anywhere.
# ──────────────────────────────────────────────────────────────────────────────

_COMMAND_TRANSLATIONS = {
    # Linux/Mac → Windows
    "ls": "Get-ChildItem",
    "ls -la": "Get-ChildItem -Force",
    "cat": "Get-Content",
    "head": "Get-Content -Head",
    "tail": "Get-Content -Tail",
    "grep": "Select-String",
    "find": "Get-ChildItem -Recurse -Filter",
    "rm": "Remove-Item",
    "rm -rf": "Remove-Item -Recurse -Force",
    "cp": "Copy-Item",
    "cp -r": "Copy-Item -Recurse",
    "mv": "Move-Item",
    "mkdir -p": "New-Item -ItemType Directory -Force",
    "touch": "New-Item -ItemType File",
    "pwd": "Get-Location",
    "which": "Get-Command",
    "whoami": "whoami",
    "env": "Get-ChildItem Env:",
    "export": "$env:",
    "chmod": "# No direct equivalent on Windows",
    "chown": "# No direct equivalent on Windows",
    "curl": "curl.exe",
    "wget": "Invoke-WebRequest",
    "sleep": "Start-Sleep -Seconds",
    "kill": "Stop-Process",
    "ps aux": "Get-Process",
    "df -h": "Get-PSDrive -PSProvider FileSystem",
    "du -sh": "(Get-ChildItem -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB",
    "free -h": "(Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB",
    "uname -a": "[System.Environment]::OSVersion",
    "ifconfig": "Get-NetIPAddress",
    "netstat": "Get-NetTCPConnection",
    "tar -xzf": "Expand-Archive",
    "zip": "Compress-Archive",
    "nano": "notepad",
    "vim": "notepad",
    "apt install": "winget install",
    "apt update": "winget upgrade --all",
    "brew install": "winget install",
    "systemctl status": "Get-Service",
    "systemctl start": "Start-Service",
    "systemctl stop": "Stop-Service",
    "systemctl restart": "Restart-Service",
    "crontab -l": "schtasks /query",
    "crontab -e": "schtasks /create",
}


def translate_command(
    command: str,
    from_platform: str = "linux",
    to_platform: str | None = None,
) -> Dict[str, Any]:
    """
    Translate a command from one platform to another.
    If to_platform is None, auto-detect current platform.
    """
    target = to_platform or ("windows" if os.name == "nt" else "linux")

    if from_platform == target:
        return {"ok": True, "command": command, "note": "Same platform, no translation needed"}

    # Try direct matches first
    cmd_base = command.strip()
    for src, dst in _COMMAND_TRANSLATIONS.items():
        if cmd_base.startswith(src):
            remainder = cmd_base[len(src):].strip()
            translated = f"{dst} {remainder}".strip() if remainder else dst
            return {
                "ok": True,
                "kind": "command_translation",
                "original": command,
                "translated": translated,
                "from": from_platform,
                "to": target,
                "exact_match": True,
            }

    # Try just the first word
    parts = cmd_base.split(None, 1)
    first_word = parts[0] if parts else ""
    rest = parts[1] if len(parts) > 1 else ""

    if first_word in _COMMAND_TRANSLATIONS:
        translated_base = _COMMAND_TRANSLATIONS[first_word]
        return {
            "ok": True,
            "kind": "command_translation",
            "original": command,
            "translated": f"{translated_base} {rest}".strip(),
            "from": from_platform,
            "to": target,
            "partial_match": True,
            "note": "Translated base command — arguments may need manual adjustment",
        }

    return {
        "ok": True,
        "kind": "command_translation",
        "original": command,
        "translated": command,
        "from": from_platform,
        "to": target,
        "no_translation": True,
        "note": "No known translation — command may work as-is or need manual adjustment",
    }


# ──────────────────────────────────────────────────────────────────────────────
# LIST EXTENSIONS — Show what runtime tools ANKITA has created
# ──────────────────────────────────────────────────────────────────────────────

def list_extensions() -> Dict[str, Any]:
    """List all runtime tool extensions (in memory + on disk)."""
    extensions = {}

    # In-memory
    for name, info in _RUNTIME_TOOLS.items():
        extensions[name] = {
            "description": info.get("description", ""),
            "file": info.get("file", ""),
            "loaded": True,
        }

    # On disk
    ext_dir = Path(__file__).parent / "extensions"
    if ext_dir.exists():
        for f in ext_dir.glob("*.py"):
            if f.stem not in extensions:
                extensions[f.stem] = {
                    "file": str(f),
                    "loaded": False,
                }

    return {
        "ok": True,
        "kind": "list_extensions",
        "count": len(extensions),
        "extensions": extensions,
    }
