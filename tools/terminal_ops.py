import os
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


def execute_shell_command(command: str, timeout: int = 15) -> Dict[str, Any]:
    """
    Execute any PowerShell/CMD command system-wide and return its output.

    Unlike run_command(), this is NOT workspace-sandboxed — it runs in the
    user's home directory and can reach any system path (ping, ipconfig, git, etc.).

    Safety: hard 15-second timeout + block list of destructive commands.
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

    timeout_sec = max(1, min(int(timeout), 60))

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
            cwd=str(Path.home()),  # run from home — not workspace-sandboxed
        )
        output = _truncate_output_lines((result.stdout or "").strip())
        error = (result.stderr or "").strip()
        if result.returncode == 0:
            return {
                "ok": True,
                "output": output if output else "(No output)",
                "error": error,
                "exit_code": result.returncode,
            }
        else:
            return {
                "ok": False,
                "output": output,
                "error": error if error else f"Command exited with code {result.returncode}",
                "exit_code": result.returncode,
            }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "output": "",
            "error": f"Command '{cmd}' timed out after {timeout_sec} seconds.",
            "exit_code": -1,
        }
    except Exception as e:
        return {
            "ok": False,
            "output": "",
            "error": f"Execution failed: {e}",
            "exit_code": -1,
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
