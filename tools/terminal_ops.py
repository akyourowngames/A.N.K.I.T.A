import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List


APP_ALIASES = {
    "vscode": ["code", "Code.exe"],
    "vs code": ["code", "Code.exe"],
    "visual studio code": ["code", "Code.exe"],
    "chrome": ["chrome", "chrome.exe"],
    "google chrome": ["chrome", "chrome.exe"],
    "edge": ["msedge", "msedge.exe", "edge"],
    "microsoft edge": ["msedge", "msedge.exe"],
    "notepad": ["notepad", "notepad.exe"],
    "calculator": ["calc", "calc.exe"],
    "calc": ["calc", "calc.exe"],
}

SHELL_FALLBACK_ALLOW = {
    "code",
    "code.exe",
    "chrome",
    "chrome.exe",
    "msedge",
    "msedge.exe",
    "notepad",
    "notepad.exe",
    "calc",
    "calc.exe",
}


def resolve_safe_cwd(workspace_root: Path, raw_cwd: str | None) -> Path:
    target = workspace_root if not raw_cwd else (workspace_root / raw_cwd).resolve()
    try:
        target.relative_to(workspace_root)
    except ValueError as err:
        raise ValueError(f"cwd escapes workspace: {raw_cwd}") from err
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError(f"cwd not found: {raw_cwd or '.'}")
    return target


def _trim_output(text: str, limit: int = 12000) -> Dict[str, Any]:
    if len(text) <= limit:
        return {"text": text, "truncated": False}
    head = text[: limit // 2]
    tail = text[-(limit // 2) :]
    return {"text": f"{head}\n... [truncated] ...\n{tail}", "truncated": True}


def _normalize_search_root(raw_path: str | None) -> Dict[str, Any]:
    if not raw_path:
        return {"ok": True, "path": str(Path.cwd().resolve())}
    expanded = os.path.expandvars(str(raw_path)).strip().strip('"').strip("'")
    target = Path(expanded).resolve()
    if not target.exists() or not target.is_dir():
        return {"ok": False, "error": f"Search path does not exist or is not a directory: {raw_path}"}
    return {"ok": True, "path": str(target)}


def _compile_pattern(pattern: str, case_sensitive: bool) -> Dict[str, Any]:
    try:
        flags = 0 if case_sensitive else re.IGNORECASE
        return {"ok": True, "regex": re.compile(pattern, flags)}
    except re.error as err:
        return {"ok": False, "error": f"Invalid search pattern: {err}"}


def _safe_max_results(value: int | None) -> int:
    try:
        n = int(value or 50)
    except Exception:
        n = 50
    return max(1, min(n, 200))


def fast_file_search(
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
    max_results: int = 50,
    case_sensitive: bool = False,
) -> Dict[str, Any]:
    """
    Fast file search with bounded output. Uses ripgrep if available, otherwise PowerShell fallback.

    Returns:
        {
            "ok": bool,
            "kind": "fast_file_search",
            "root": "<absolute path>",
            "pattern": "<pattern>",
            "glob": "<glob or None>",
            "case_sensitive": bool,
            "max_results": int,
            "matches_found": int,
            "truncated": bool,
            "results": [<absolute paths>],
            "error": "<error msg>" (if ok is False)
        }
    """
    if not pattern or not str(pattern).strip():
        return {
            "ok": False,
            "kind": "fast_file_search",
            "error": "pattern is required",
        }

    root_res = _normalize_search_root(path)
    if not root_res.get("ok"):
        return {
            "ok": False,
            "kind": "fast_file_search",
            "error": root_res["error"],
        }
    root = root_res["path"]

    pat_res = _compile_pattern(str(pattern), case_sensitive)
    if not pat_res.get("ok"):
        return {
            "ok": False,
            "kind": "fast_file_search",
            "error": pat_res["error"],
        }
    regex = pat_res["regex"]
    limit = _safe_max_results(max_results)

    def _record_hits(candidates: List[str]) -> Dict[str, Any]:
        matches: List[str] = []
        count = 0
        for p in candidates:
            if not p:
                continue
            if regex.search(p):
                count += 1
                if len(matches) < limit:
                    matches.append(p)
        return {
            "matches_found": count,
            "results": matches,
            "truncated": count > len(matches),
        }

    rg_path = shutil.which("rg")
    if rg_path:
        args = [rg_path, "--files"]
        if glob:
            args.extend(["-g", str(glob)])
        args.append(root)
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode not in (0, 1):
                return {
                    "ok": False,
                    "kind": "fast_file_search",
                    "error": (proc.stderr or "").strip() or "rg failed",
                }
            lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
            hits = _record_hits(lines)
            return {
                "ok": True,
                "kind": "fast_file_search",
                "root": root,
                "pattern": pattern,
                "glob": glob,
                "case_sensitive": case_sensitive,
                "max_results": limit,
                "matches_found": hits["matches_found"],
                "truncated": hits["truncated"],
                "results": hits["results"],
            }
        except Exception as err:
            return {
                "ok": False,
                "kind": "fast_file_search",
                "error": f"rg execution failed: {err}",
            }

    # PowerShell fallback: Get-ChildItem with optional -Filter for glob
    filter_clause = f"-Filter '{glob}'" if glob else ""
    cmd = f"Get-ChildItem -Path '{root}' -Recurse -File {filter_clause} | Select-Object -ExpandProperty FullName"
    try:
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode not in (0, 1):
            return {
                "ok": False,
                "kind": "fast_file_search",
                "error": (proc.stderr or "").strip() or "PowerShell search failed",
            }
        lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
        hits = _record_hits(lines)
        return {
            "ok": True,
            "kind": "fast_file_search",
            "root": root,
            "pattern": pattern,
            "glob": glob,
            "case_sensitive": case_sensitive,
            "max_results": limit,
            "matches_found": hits["matches_found"],
            "truncated": hits["truncated"],
            "results": hits["results"],
        }
    except Exception as err:
        return {
            "ok": False,
            "kind": "fast_file_search",
            "error": f"PowerShell search failed: {err}",
        }


def _candidate_app_names(raw: str) -> List[str]:
    value = str(raw or "").strip()
    if not value:
        return []
    lower = value.lower()
    words = [w for w in lower.replace("-", " ").split(" ") if w]
    candidates: List[str] = [value, lower, lower.replace(" ", "")]
    if words:
        candidates.extend([words[-1], words[0]])
    if lower in APP_ALIASES:
        candidates.extend(APP_ALIASES[lower])
    out: List[str] = []
    seen = set()
    for c in candidates:
        c2 = c.strip().strip("\"'")
        if not c2:
            continue
        if c2 not in seen:
            seen.add(c2)
            out.append(c2)
    return out


def _resolve_executable_windows(name: str) -> str | None:
    p = Path(name)
    if p.exists():
        return str(p)
    direct = shutil.which(name)
    if direct:
        return direct
    reg = _lookup_app_path_registry(name)
    if reg:
        return reg
    common = _lookup_common_install_path(name)
    if common:
        return common
    if not name.lower().endswith(".exe"):
        with_exe = shutil.which(f"{name}.exe")
        if with_exe:
            return with_exe
        reg2 = _lookup_app_path_registry(f"{name}.exe")
        if reg2:
            return reg2
        common2 = _lookup_common_install_path(f"{name}.exe")
        if common2:
            return common2
    return None


def _lookup_app_path_registry(name: str) -> str | None:
    if os.name != "nt":
        return None
    try:
        import winreg  # type: ignore
    except Exception:
        return None

    exe = Path(name).name
    if not exe.lower().endswith(".exe"):
        exe = f"{exe}.exe"
    keys = [
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
    ]
    for hive, root in keys:
        try:
            with winreg.OpenKey(hive, f"{root}\\{exe}") as key:
                val, _ = winreg.QueryValueEx(key, "")
                path = str(val).strip()
                if path and Path(path).exists():
                    return path
        except Exception:
            continue
    return None


def _lookup_common_install_path(name: str) -> str | None:
    exe = Path(name).name
    if not exe.lower().endswith(".exe"):
        exe = f"{exe}.exe"
    local = os.environ.get("LOCALAPPDATA", "")
    pf = os.environ.get("ProgramFiles", "")
    pfx86 = os.environ.get("ProgramFiles(x86)", "")
    candidates = [
        Path(local) / "Google/Chrome/Application/chrome.exe",
        Path(pf) / "Google/Chrome/Application/chrome.exe",
        Path(pfx86) / "Google/Chrome/Application/chrome.exe",
        Path(local) / "Programs/Microsoft VS Code/Code.exe",
        Path(pf) / "Microsoft VS Code/Code.exe",
        Path(pfx86) / "Microsoft VS Code/Code.exe",
        Path(pf) / "Microsoft/Edge/Application/msedge.exe",
        Path(pfx86) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for c in candidates:
        try:
            if c.exists() and c.name.lower() == exe.lower():
                return str(c)
        except Exception:
            continue
    return None


def run_command(
    workspace_root: Path,
    command: str,
    args: List[str] | None = None,
    cwd: str | None = None,
    timeout_ms: int = 20000,
    use_shell: bool = False,
    env: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    cmd = str(command or "").strip()
    if not cmd:
        raise ValueError("command is required")

    safe_cwd = resolve_safe_cwd(workspace_root, cwd)
    timeout_s = max(1.0, min(float(timeout_ms) / 1000.0, 120.0))
    final_env = os.environ.copy()
    if env:
        for k, v in env.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise ValueError("env keys and values must be strings")
            final_env[k] = v

    argv: List[str]
    if use_shell:
        if os.name == "nt":
            argv = ["powershell", "-NoProfile", "-Command", cmd]
        else:
            argv = ["/bin/sh", "-lc", cmd]
    else:
        argv = [cmd] + [str(a) for a in (args or [])]

    started = time.time()
    try:
        proc = subprocess.run(
            argv,
            cwd=str(safe_cwd),
            env=final_env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            shell=False,
            check=False,
        )
        duration_ms = int((time.time() - started) * 1000)
        stdout = _trim_output(proc.stdout or "")
        stderr = _trim_output(proc.stderr or "")
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "timed_out": False,
            "duration_ms": duration_ms,
            "cwd": str(safe_cwd.relative_to(workspace_root)).replace("\\", "/") or ".",
            "argv": argv,
            "stdout": stdout["text"],
            "stderr": stderr["text"],
            "stdout_truncated": stdout["truncated"],
            "stderr_truncated": stderr["truncated"],
        }
    except subprocess.TimeoutExpired as err:
        duration_ms = int((time.time() - started) * 1000)
        stdout = _trim_output((err.stdout or "") if isinstance(err.stdout, str) else "")
        stderr = _trim_output((err.stderr or "") if isinstance(err.stderr, str) else "")
        return {
            "ok": False,
            "exit_code": None,
            "timed_out": True,
            "duration_ms": duration_ms,
            "cwd": str(safe_cwd.relative_to(workspace_root)).replace("\\", "/") or ".",
            "argv": argv,
            "stdout": stdout["text"],
            "stderr": stderr["text"],
            "stdout_truncated": stdout["truncated"],
            "stderr_truncated": stderr["truncated"],
        }


def launch_app(
    workspace_root: Path,
    app: str,
    args: List[str] | None = None,
    cwd: str | None = None,
) -> Dict[str, Any]:
    target = str(app or "").strip()
    if not target:
        raise ValueError("app is required")
    safe_cwd = resolve_safe_cwd(workspace_root, cwd)
    final_args = [str(a) for a in (args or [])]
    candidates = _candidate_app_names(target)

    if os.name == "nt":
        attempts: List[str] = []
        for cand in candidates:
            resolved = _resolve_executable_windows(cand) or cand
            attempts.append(resolved)
            try:
                proc = subprocess.Popen(
                    [resolved] + final_args,
                    cwd=str(safe_cwd),
                    env=os.environ.copy(),
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return {
                    "ok": True,
                    "launched": True,
                    "pid": proc.pid,
                    "app": resolved,
                    "requested": target,
                    "args": final_args,
                    "cwd": str(safe_cwd.relative_to(workspace_root)).replace("\\", "/") or ".",
                }
            except FileNotFoundError:
                continue
        # Final fallback: let Windows shell resolve app aliases/registered handlers.
        for cand in candidates:
            key = Path(cand).name.lower()
            if key not in SHELL_FALLBACK_ALLOW:
                continue
            try:
                proc = subprocess.Popen(
                    ["cmd", "/c", "start", "", cand] + final_args,
                    cwd=str(safe_cwd),
                    env=os.environ.copy(),
                    shell=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return {
                    "ok": True,
                    "launched": True,
                    "pid": proc.pid,
                    "app": cand,
                    "requested": target,
                    "args": final_args,
                    "cwd": str(safe_cwd.relative_to(workspace_root)).replace("\\", "/") or ".",
                    "launcher": "cmd-start",
                }
            except Exception:
                continue
        raise FileNotFoundError(f"application not found: {target} (tried: {', '.join(attempts[:8])})")

    argv = [target] + final_args
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(safe_cwd),
            env=os.environ.copy(),
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as err:
        raise FileNotFoundError(f"application not found: {target}") from err
    return {
        "ok": True,
        "launched": True,
        "pid": proc.pid,
        "app": target,
        "requested": target,
        "args": final_args,
        "cwd": str(safe_cwd.relative_to(workspace_root)).replace("\\", "/") or ".",
    }


# ---------------------------------------------------------------------------
# Security: commands blocked regardless of what the LLM asks
# ---------------------------------------------------------------------------
_BLOCKED_PATTERNS = [
    "del /s", "del /f /s", "format c", "format d",
    "rmdir /s", "rd /s", "rd /q", "rm -rf",
    "Remove-Item -Recurse -Force",
    "remove-item -recurse",
    ":(){:|:&};:",  # fork bomb
    "dd if=",
    "shutdown /s", "shutdown -s",
    "reg delete hklm", "reg delete hkcu",
]

# Output size guardrails — prevent context window blowout
_MAX_OUTPUT_LINES = 500
_KEEP_HEAD_LINES = 200
_KEEP_TAIL_LINES = 50

# ─────────────────────────────────────────────────────────────────────────────
# TERMINAL SESSION STATE — persistent CWD + environment across commands
# ─────────────────────────────────────────────────────────────────────────────
_TERMINAL_SESSION = {
    "cwd": str(Path.home()),
    "env_overrides": {},
    "last_exit_code": 0,
}

# ─────────────────────────────────────────────────────────────────────────────
# SMART TIMEOUT TIERS — auto-detect command type and adjust timeout
# ─────────────────────────────────────────────────────────────────────────────
_TIMEOUT_TIERS = {
    # Quick diagnostics
    "quick": (10, ["ping", "ipconfig", "whoami", "pwd", "hostname", "date", "time"]),
    # Git operations
    "git": (30, ["git status", "git log", "git diff", "git add", "git commit", "git branch"]),
    # Package install
    "install": (300, ["pip install", "npm install", "yarn install", "yarn add", "pnpm install", "cargo install"]),
    # Build commands
    "build": (600, ["npm run build", "yarn build", "cargo build", "make", "mvn package", "gradle build", "docker build"]),
    # Test runners
    "test": (180, ["pytest", "jest", "npm test", "yarn test", "go test", "cargo test", "mvn test"]),
    # Docker operations
    "docker": (600, ["docker build", "docker pull", "docker run", "docker-compose"]),
}


def _detect_timeout(command: str) -> int:
    """Auto-detect appropriate timeout based on command type."""
    cmd_lower = command.lower()
    for tier_name, (timeout, keywords) in _TIMEOUT_TIERS.items():
        if any(kw in cmd_lower for kw in keywords):
            return timeout
    return 60  # Default upgraded from 15s


def _truncate_output_lines(text: str) -> str:
    """
    Truncate large command output to prevent LLM context blowout.
    Keeps first _KEEP_HEAD_LINES + last _KEEP_TAIL_LINES with a summary in between.
    """
    lines = text.splitlines()
    total = len(lines)
    if total <= _MAX_OUTPUT_LINES:
        return text
    head = lines[:_KEEP_HEAD_LINES]
    tail = lines[-_KEEP_TAIL_LINES:]
    skipped = total - _KEEP_HEAD_LINES - _KEEP_TAIL_LINES
    return (
        "\n".join(head)
        + f"\n\n... [{skipped} lines truncated — use Select-Object -First 50 or head to limit output] ...\n\n"
        + "\n".join(tail)
    )


def execute_shell_command(command: str, timeout: int | None = None, cwd: str | None = None) -> Dict[str, Any]:
    """
    Execute any PowerShell/CMD command system-wide and return its output.

    Unlike run_command(), this is NOT workspace-sandboxed — it can reach any system path.
    
    Args:
        command: The shell command to execute
        timeout: Max seconds to wait (auto-detected if None, max 600)
        cwd: Working directory for the command (defaults to session CWD or home)

    Safety: smart timeout + block list of destructive commands + session state.
    """
    cmd = str(command or "").strip()
    if not cmd:
        return {"ok": False, "output": "", "error": "No command provided.", "exit_code": -1}

    # Safety check — block destructive patterns
    cmd_lower = cmd.lower()
    for pattern in _BLOCKED_PATTERNS:
        if pattern.lower() in cmd_lower:
            return {
                "ok": False,
                "output": "",
                "error": f"Blocked: command contains a destructive pattern ('{pattern}'). Refusing to execute.",
                "exit_code": -1,
            }

    # Smart timeout detection
    if timeout is None:
        timeout_sec = _detect_timeout(cmd)
    else:
        timeout_sec = max(1, min(int(timeout), 600))  # Max 10 minutes

    # Working directory resolution
    if cwd:
        # Expand environment variables in path
        expanded_cwd = os.path.expandvars(cwd)
        target_cwd = Path(expanded_cwd).resolve()
        if not target_cwd.exists() or not target_cwd.is_dir():
            return {
                "ok": False,
                "output": "",
                "error": f"Working directory does not exist or is not a directory: {cwd}",
                "exit_code": -1,
            }
        working_dir = str(target_cwd)
        # Update session CWD if command is 'cd'
        if cmd_lower.startswith("cd ") or cmd_lower == "cd":
            _TERMINAL_SESSION["cwd"] = working_dir
    else:
        # Use session CWD
        working_dir = _TERMINAL_SESSION["cwd"]

    # Detect session state changes from command
    # cd command updates session CWD
    if cmd_lower.startswith("cd "):
        cd_target = cmd[3:].strip().strip('"').strip("'")
        if cd_target:
            expanded_target = os.path.expandvars(cd_target)
            if os.path.isabs(expanded_target):
                new_cwd = Path(expanded_target).resolve()
            else:
                new_cwd = (Path(working_dir) / expanded_target).resolve()
            if new_cwd.exists() and new_cwd.is_dir():
                _TERMINAL_SESSION["cwd"] = str(new_cwd)
                working_dir = str(new_cwd)

    # Detect environment variable sets (PowerShell: $env:X = Y)
    env_match = re.match(r'\$env:(\w+)\s*=\s*["\']?(.+?)["\']?$', cmd, re.IGNORECASE)
    if env_match:
        var_name, var_value = env_match.groups()
        _TERMINAL_SESSION["env_overrides"][var_name] = var_value.strip('"').strip("'")

    # Build environment with session overrides
    final_env = os.environ.copy()
    final_env.update(_TERMINAL_SESSION["env_overrides"])

    # On Windows, wrap in PowerShell so all cmds work naturally
    if os.name == "nt":
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
    else:
        argv = ["/bin/sh", "-c", cmd]

    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            shell=False,
            check=False,
            cwd=working_dir,
            env=final_env,
        )
        output = _truncate_output_lines((result.stdout or "").strip())
        error = (result.stderr or "").strip()
        
        # Update session state
        _TERMINAL_SESSION["last_exit_code"] = result.returncode
        
        if result.returncode == 0:
            return {
                "ok": True,
                "output": output if output else "(No output)",
                "error": error,
                "exit_code": result.returncode,
                "cwd": working_dir,
            }
        else:
            return {
                "ok": False,
                "output": output,
                "error": error if error else f"Command exited with code {result.returncode}",
                "exit_code": result.returncode,
                "cwd": working_dir,
            }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "output": "",
            "error": f"Command '{cmd}' timed out after {timeout_sec} seconds.",
            "exit_code": -1,
            "cwd": working_dir,
        }
    except Exception as e:
        return {
            "ok": False,
            "output": "",
            "error": f"Execution failed: {e}",
            "exit_code": -1,
            "cwd": working_dir,
        }



# Process names that must NEVER be killed — doing so destroys the Windows UI
# or the OS itself (blank screen / BSOD territory).
_BLOCKED_PROCESS_NAMES: frozenset = frozenset({
    # Windows shell + UI
    "explorer", "explorer.exe",
    # Core OS / session management
    "csrss", "csrss.exe",
    "wininit", "wininit.exe",
    "winlogon", "winlogon.exe",
    "services", "services.exe",
    "lsass", "lsass.exe",
    "svchost", "svchost.exe",
    "smss", "smss.exe",
    "system", "system idle process",
    # Wildcards / empty strings — nuclear buttons
    "*", "", " ",
    # ANKITA's own process
    "python", "python.exe", "pythonw", "pythonw.exe",
})


def _is_blocked(name: str) -> bool:
    """Return True if the process name is on the protected blocklist."""
    stripped = name.strip().lower()
    base = Path(stripped).stem  # e.g. "explorer.exe" → "explorer"
    return stripped in _BLOCKED_PROCESS_NAMES or base in _BLOCKED_PROCESS_NAMES


def terminate_app(
    app: str,
    force: bool = False,
) -> Dict[str, Any]:
    target = str(app or "").strip()
    if not target or target in ("*", ""):
        raise ValueError("app is required — empty or wildcard target is not allowed")

    # NUCLEAR BUG GUARD: block dangerous targets before any command is built
    if _is_blocked(target):
        raise PermissionError(
            f"Refused to terminate '{target}' — this process is protected. "
            f"Killing it would destroy the Windows UI or the OS session."
        )

    candidates = _candidate_app_names(target)
    process_names: List[str] = []
    for c in candidates:
        base = Path(c).name
        if not base.lower().endswith(".exe"):
            base = f"{base}.exe"
        # Double-check each resolved candidate against the blocklist
        if _is_blocked(base):
            continue  # Skip protected names silently
        if base not in process_names:
            process_names.append(base)

    if not process_names:
        raise PermissionError(
            f"All resolved process names for '{target}' are on the protected list. "
            f"Refusing to execute."
        )

    if os.name == "nt":
        tried: List[str] = []
        for proc_name in process_names:
            tried.append(proc_name)
            cmd = ["taskkill", "/IM", proc_name, "/T"]
            if force:
                cmd.append("/F")
            res = subprocess.run(cmd, capture_output=True, text=True, shell=False)
            if res.returncode == 0:
                return {
                    "ok": True,
                    "terminated": True,
                    "process": proc_name,
                    "requested": target,
                    "stdout": (res.stdout or "").strip(),
                }
        raise FileNotFoundError(f"running app/process not found: {target} (tried: {', '.join(tried[:8])})")

    # POSIX fallback
    cmd = ["pkill"]
    if force:
        cmd.append("-9")
    cmd.append(target)
    res = subprocess.run(cmd, capture_output=True, text=True, shell=False)
    if res.returncode == 0:
        return {
            "ok": True,
            "terminated": True,
            "process": target,
            "requested": target,
            "stdout": (res.stdout or "").strip(),
        }
    raise FileNotFoundError(f"running app/process not found: {target}")


# ─────────────────────────────────────────────────────────────────────────────
# GIT INTELLIGENCE — git_op tool for smart git workflows
# ─────────────────────────────────────────────────────────────────────────────

def git_op(action: str, message: str | None = None, branch: str | None = None, path: str | None = None, confirm: bool = False) -> Dict[str, Any]:
    """
    Smart git wrapper with proper error handling and structured output.
    
    Args:
        action: Git operation (status, log, diff, add, commit, push, pull, branch, stash, reset)
        message: Commit message (required for commit action)
        branch: Branch name (for branch/push/pull actions)
        path: Repository path (defaults to session CWD)
        confirm: Required for destructive actions (reset, force push)
        
    Returns:
        Dict with structured git data
    """
    # Determine working directory
    if path:
        repo_path = Path(os.path.expandvars(path)).resolve()
    else:
        repo_path = Path(_TERMINAL_SESSION["cwd"])
    
    if not repo_path.exists() or not repo_path.is_dir():
        return {"ok": False, "error": f"Path does not exist: {repo_path}"}
    
    # Check if it's a git repo
    git_check = execute_shell_command("git rev-parse --git-dir", cwd=str(repo_path))
    if not git_check["ok"]:
        return {"ok": False, "error": f"Not a git repository: {repo_path}"}
    
    # Execute git action
    if action == "status":
        result = execute_shell_command("git status --short", cwd=str(repo_path))
        if result["ok"]:
            lines = [l for l in result["output"].split("\n") if l.strip()]
            modified = [l for l in lines if l.startswith(" M") or l.startswith("M ")]
            untracked = [l for l in lines if l.startswith("??")]
            staged = [l for l in lines if l.startswith("A ") or l.startswith("M ")]
            return {
                "ok": True,
                "action": "status",
                "modified": len(modified),
                "untracked": len(untracked),
                "staged": len(staged),
                "files": lines,
                "summary": f"{len(modified)} modified, {len(untracked)} untracked, {len(staged)} staged",
            }
        return result
    
    elif action == "log":
        count = 15
        result = execute_shell_command(f"git log --oneline --graph --decorate -n {count}", cwd=str(repo_path))
        if result["ok"]:
            return {
                "ok": True,
                "action": "log",
                "commits": result["output"],
                "count": len([l for l in result["output"].split("\n") if l.strip()]),
            }
        return result
    
    elif action == "diff":
        result = execute_shell_command("git diff --stat", cwd=str(repo_path))
        if result["ok"]:
            return {
                "ok": True,
                "action": "diff",
                "summary": result["output"],
            }
        return result
    
    elif action == "add":
        result = execute_shell_command("git add -A", cwd=str(repo_path))
        if result["ok"]:
            return {
                "ok": True,
                "action": "add",
                "message": "All changes staged",
            }
        return result
    
    elif action == "commit":
        if not message:
            return {"ok": False, "error": "Commit message is required"}
        # Escape quotes in message
        safe_message = message.replace('"', '\\"')
        result = execute_shell_command(f'git commit -m "{safe_message}"', cwd=str(repo_path))
        if result["ok"]:
            # Get the commit hash
            hash_result = execute_shell_command("git log --oneline -1", cwd=str(repo_path))
            return {
                "ok": True,
                "action": "commit",
                "message": message,
                "commit": hash_result["output"] if hash_result["ok"] else "unknown",
            }
        return result
    
    elif action == "push":
        # Get current branch if not specified
        if not branch:
            branch_result = execute_shell_command("git branch --show-current", cwd=str(repo_path))
            if branch_result["ok"]:
                branch = branch_result["output"].strip()
            else:
                return {"ok": False, "error": "Could not determine current branch"}
        
        result = execute_shell_command(f"git push origin {branch}", cwd=str(repo_path))
        if not result["ok"] and "no upstream branch" in result["error"].lower():
            # Try with --set-upstream
            result = execute_shell_command(f"git push --set-upstream origin {branch}", cwd=str(repo_path))
        
        if result["ok"]:
            return {
                "ok": True,
                "action": "push",
                "branch": branch,
                "message": f"Pushed to origin/{branch}",
            }
        return result
    
    elif action == "pull":
        if not branch:
            branch_result = execute_shell_command("git branch --show-current", cwd=str(repo_path))
            if branch_result["ok"]:
                branch = branch_result["output"].strip()
        
        cmd = f"git pull --rebase origin {branch}" if branch else "git pull --rebase"
        result = execute_shell_command(cmd, cwd=str(repo_path))
        if result["ok"]:
            return {
                "ok": True,
                "action": "pull",
                "branch": branch or "current",
                "message": "Pulled latest changes",
            }
        return result
    
    elif action == "branch":
        result = execute_shell_command("git branch -a", cwd=str(repo_path))
        if result["ok"]:
            branches = [l.strip() for l in result["output"].split("\n") if l.strip()]
            current = [b for b in branches if b.startswith("*")]
            return {
                "ok": True,
                "action": "branch",
                "branches": branches,
                "current": current[0].replace("* ", "") if current else "unknown",
            }
        return result
    
    elif action == "stash":
        timestamp = int(time.time())
        stash_msg = f"ankita-stash-{timestamp}"
        result = execute_shell_command(f'git stash push -m "{stash_msg}"', cwd=str(repo_path))
        if result["ok"]:
            return {
                "ok": True,
                "action": "stash",
                "message": f"Stashed changes as: {stash_msg}",
            }
        return result
    
    elif action == "reset":
        if not confirm:
            return {
                "ok": False,
                "error": "Reset is destructive. Set confirm=True to proceed.",
                "warning": "This will undo the last commit but keep changes staged.",
            }
        result = execute_shell_command("git reset --soft HEAD~1", cwd=str(repo_path))
        if result["ok"]:
            return {
                "ok": True,
                "action": "reset",
                "message": "Last commit undone (changes kept staged)",
            }
        return result
    
    else:
        return {"ok": False, "error": f"Unknown git action: {action}"}


# ─────────────────────────────────────────────────────────────────────────────
# PROCESS MANAGEMENT — process_op tool for background processes
# ─────────────────────────────────────────────────────────────────────────────

# Store background processes started this session
_BACKGROUND_PROCESSES: Dict[str, Dict[str, Any]] = {}


def process_op(action: str, command: str | None = None, name: str | None = None, port: int | None = None, pid: int | None = None) -> Dict[str, Any]:
    """
    Process management tool for starting, stopping, and checking processes.
    
    Args:
        action: Operation (start_background, list_background, kill_background, is_running, port_check)
        command: Command to run (for start_background)
        name: Process name/label (for start_background, kill_background, is_running)
        port: Port number (for port_check)
        pid: Process ID (for kill_background, is_running)
        
    Returns:
        Dict with process information
    """
    if action == "start_background":
        if not command:
            return {"ok": False, "error": "command is required for start_background"}
        if not name:
            name = f"proc_{int(time.time())}"
        
        # Start process detached
        cwd = _TERMINAL_SESSION["cwd"]
        env = os.environ.copy()
        env.update(_TERMINAL_SESSION["env_overrides"])
        
        try:
            if os.name == "nt":
                # Windows: use CREATE_NEW_PROCESS_GROUP to detach
                proc = subprocess.Popen(
                    ["powershell", "-NoProfile", "-Command", command],
                    cwd=cwd,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
                )
            else:
                proc = subprocess.Popen(
                    ["/bin/sh", "-c", command],
                    cwd=cwd,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL,
                    start_new_session=True,
                )
            
            _BACKGROUND_PROCESSES[name] = {
                "pid": proc.pid,
                "command": command,
                "started": time.time(),
                "cwd": cwd,
            }
            
            return {
                "ok": True,
                "action": "start_background",
                "name": name,
                "pid": proc.pid,
                "command": command,
                "message": f"Started background process '{name}' (PID {proc.pid})",
            }
        except Exception as e:
            return {"ok": False, "error": f"Failed to start process: {e}"}
    
    elif action == "list_background":
        # Clean up dead processes
        for proc_name in list(_BACKGROUND_PROCESSES.keys()):
            proc_info = _BACKGROUND_PROCESSES[proc_name]
            try:
                # Check if process is still running
                if os.name == "nt":
                    result = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {proc_info['pid']}", "/NH"],
                        capture_output=True,
                        text=True,
                    )
                    if str(proc_info['pid']) not in result.stdout:
                        del _BACKGROUND_PROCESSES[proc_name]
                else:
                    os.kill(proc_info['pid'], 0)  # Signal 0 just checks if process exists
            except (OSError, subprocess.SubprocessError):
                del _BACKGROUND_PROCESSES[proc_name]
        
        return {
            "ok": True,
            "action": "list_background",
            "count": len(_BACKGROUND_PROCESSES),
            "processes": [
                {
                    "name": n,
                    "pid": p["pid"],
                    "command": p["command"],
                    "uptime_seconds": int(time.time() - p["started"]),
                }
                for n, p in _BACKGROUND_PROCESSES.items()
            ],
        }
    
    elif action == "kill_background":
        if not name and not pid:
            return {"ok": False, "error": "name or pid is required for kill_background"}
        
        # Find process
        target_pid = None
        target_name = None
        
        if name and name in _BACKGROUND_PROCESSES:
            target_pid = _BACKGROUND_PROCESSES[name]["pid"]
            target_name = name
        elif pid:
            for n, p in _BACKGROUND_PROCESSES.items():
                if p["pid"] == pid:
                    target_pid = pid
                    target_name = n
                    break
        
        if not target_pid:
            return {"ok": False, "error": f"Background process not found: {name or pid}"}
        
        # Kill process
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(target_pid), "/F", "/T"], check=True)
            else:
                os.kill(target_pid, 9)  # SIGKILL
            
            if target_name:
                del _BACKGROUND_PROCESSES[target_name]
            
            return {
                "ok": True,
                "action": "kill_background",
                "name": target_name,
                "pid": target_pid,
                "message": f"Killed background process '{target_name}' (PID {target_pid})",
            }
        except Exception as e:
            return {"ok": False, "error": f"Failed to kill process: {e}"}
    
    elif action == "is_running":
        if not name and not pid:
            return {"ok": False, "error": "name or pid is required for is_running"}
        
        # Check if process is running
        if name and name in _BACKGROUND_PROCESSES:
            proc_info = _BACKGROUND_PROCESSES[name]
            try:
                if os.name == "nt":
                    result = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {proc_info['pid']}", "/NH"],
                        capture_output=True,
                        text=True,
                    )
                    running = str(proc_info['pid']) in result.stdout
                else:
                    os.kill(proc_info['pid'], 0)
                    running = True
            except (OSError, subprocess.SubprocessError):
                running = False
                del _BACKGROUND_PROCESSES[name]
            
            return {
                "ok": True,
                "action": "is_running",
                "name": name,
                "pid": proc_info['pid'],
                "running": running,
            }
        elif pid:
            try:
                if os.name == "nt":
                    result = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                        capture_output=True,
                        text=True,
                    )
                    running = str(pid) in result.stdout
                else:
                    os.kill(pid, 0)
                    running = True
            except (OSError, subprocess.SubprocessError):
                running = False
            
            return {
                "ok": True,
                "action": "is_running",
                "pid": pid,
                "running": running,
            }
        else:
            return {"ok": False, "error": "Process not found"}
    
    elif action == "port_check":
        if port is None:
            return {"ok": False, "error": "port is required for port_check"}
        
        # Check what's using the port
        if os.name == "nt":
            result = execute_shell_command(f"netstat -ano | Select-String ':{port}'")
        else:
            result = execute_shell_command(f"lsof -i :{port}")
        
        if result["ok"]:
            in_use = bool(result["output"].strip())
            return {
                "ok": True,
                "action": "port_check",
                "port": port,
                "in_use": in_use,
                "details": result["output"] if in_use else "Port is free",
            }
        return result
    
    else:
        return {"ok": False, "error": f"Unknown process action: {action}"}
