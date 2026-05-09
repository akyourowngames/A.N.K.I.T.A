from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .path_resolver import resolve_local_path
from .registry import ToolInputError, optional_text, require_text


_BACKGROUND_PROCESSES: list[subprocess.Popen[Any]] = []


def run_terminal(params: dict[str, Any]) -> dict[str, Any]:
    reap_background_processes()
    command = require_text(params, "command")
    cwd = resolve_cwd(optional_text(params, "cwd", str(Path.cwd())))
    timeout_seconds = bounded_int(params.get("timeout_seconds"), env_int("JARVIS_TERMINAL_TIMEOUT_SECONDS", 30), 1, 3600)
    max_output_chars = bounded_int(
        params.get("max_output_chars"),
        env_int("JARVIS_TERMINAL_MAX_OUTPUT_CHARS", 20000),
        100,
        200000,
    )
    stdin = params.get("stdin")
    if stdin is not None and not isinstance(stdin, str):
        raise ToolInputError("stdin must be text")
    background = bool(params.get("background"))

    requested_shell = optional_text(params, "shell", "")
    shell_name = resolve_shell_name(requested_shell)
    argv = command_argv(command, shell_name)
    if background:
        process = subprocess.Popen(
            argv,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            shell=shell_name == "system",
        )
        remember_background_process(process)
        return with_user_output(
            {
                "command": command,
                "cwd": str(cwd),
                "shell": shell_name,
                "requested_shell": requested_shell,
                "background": True,
                "pid": process.pid,
                "exit_code": 0,
                "elapsed_seconds": 0,
                "stdout": "",
                "stderr": "",
                "stdout_truncated": False,
                "stderr_truncated": False,
            }
        )
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=shell_name == "system",
        )
        elapsed = time.perf_counter() - started
        return with_user_output(
            {
            "command": command,
            "cwd": str(cwd),
            "shell": shell_name,
            "requested_shell": requested_shell,
            "exit_code": completed.returncode,
            "elapsed_seconds": round(elapsed, 3),
            "stdout": clip_output(completed.stdout, max_output_chars),
            "stderr": clip_output(completed.stderr, max_output_chars),
            "stdout_truncated": len(completed.stdout) > max_output_chars,
            "stderr_truncated": len(completed.stderr) > max_output_chars,
            }
        )
    except subprocess.TimeoutExpired as error:
        elapsed = time.perf_counter() - started
        return with_user_output(
            {
            "command": command,
            "cwd": str(cwd),
            "shell": shell_name,
            "requested_shell": requested_shell,
            "exit_code": None,
            "elapsed_seconds": round(elapsed, 3),
            "timed_out": True,
            "stdout": clip_output(text_value(error.stdout), max_output_chars),
            "stderr": clip_output(text_value(error.stderr), max_output_chars),
            }
        )


def resolve_cwd(value: str) -> Path:
    resolved = resolve_local_path(value)
    if not resolved.exists() or not resolved.is_dir():
        raise ToolInputError(f"cwd is not a directory: {value}")
    return resolved


def command_argv(command: str, shell_name: str) -> str | list[str]:
    normalized = shell_name.strip().lower()
    if normalized == "system":
        return command
    if normalized == "powershell":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
    if normalized == "cmd":
        return ["cmd", "/c", command]
    raise ToolInputError(f"Unsupported shell: {shell_name}")


def resolve_shell_name(requested_shell: str) -> str:
    normalized = requested_shell.strip().lower()
    configured = os.environ.get("JARVIS_TERMINAL_SHELL", "").strip().lower()
    if not normalized or normalized == "system":
        if configured:
            return configured
        return "system"
    return normalized


def bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip():
        try:
            number = int(value.strip())
        except ValueError:
            number = fallback
    else:
        number = fallback
    return max(minimum, min(maximum, number))


def env_int(name: str, fallback: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def clip_output(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit]


def text_value(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def remember_background_process(process: subprocess.Popen[Any]) -> None:
    try:
        process.wait(timeout=0.05)
    except subprocess.TimeoutExpired:
        _BACKGROUND_PROCESSES.append(process)


def reap_background_processes() -> None:
    alive = []
    for process in _BACKGROUND_PROCESSES:
        if process.poll() is None:
            alive.append(process)
    _BACKGROUND_PROCESSES[:] = alive


def with_user_output(result: dict[str, Any]) -> dict[str, Any]:
    stdout = str(result.get("stdout", "")).strip()
    stderr = str(result.get("stderr", "")).strip()
    if stdout and stderr:
        result["user_output"] = stdout + "\n" + stderr
    elif stdout:
        result["user_output"] = stdout
    elif stderr:
        result["user_output"] = stderr
    elif result.get("background") and result.get("exit_code") == 0:
        result["user_output"] = "Started."
    elif result.get("timed_out"):
        result["user_output"] = "Command timed out."
    elif result.get("exit_code") == 0:
        result["user_output"] = "Done."
    else:
        result["user_output"] = f"Command exited with code {result.get('exit_code')}."
    return result
