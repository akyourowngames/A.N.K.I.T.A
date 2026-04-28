import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from config import BASE_DIR, TERMINAL_COMMAND_TIMEOUT, TERMINAL_OUTPUT_MAX_CHARS, TERMINAL_TOOL_ENABLED

logger = logging.getLogger("J.A.R.V.I.S")


@dataclass
class TerminalResult:
    ok: bool
    message: str
    command: str = ""
    stdout: str = ""
    stderr: str = ""
    returncode: Optional[int] = None


class TerminalControl:
    def run(self, command: str, cwd: Optional[str] = None, timeout: Optional[int] = None) -> TerminalResult:
        command = (command or "").strip()

        if not TERMINAL_TOOL_ENABLED:
            return TerminalResult(False, "Terminal access is disabled.", command=command)

        if not command:
            return TerminalResult(False, "No terminal command was provided.", command=command)

        if "\x00" in command:
            return TerminalResult(False, "That terminal command is invalid.", command=command)

        workdir = self._resolve_workdir(cwd)
        run_timeout = max(1, int(timeout or TERMINAL_COMMAND_TIMEOUT))

        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                cwd=str(workdir),
                capture_output=True,
                text=True,
                timeout=run_timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            logger.warning("[TERMINAL] Timed out after %ss: %s", run_timeout, command[:160])
            return TerminalResult(False, f"Terminal command timed out after {run_timeout}s.", command=command)
        except Exception as exc:
            logger.warning("[TERMINAL] Failed to run command %s: %s", command[:160], exc)
            return TerminalResult(False, "Terminal command failed to start.", command=command)

        stdout = self._limit(completed.stdout or "")
        stderr = self._limit(completed.stderr or "")
        ok = completed.returncode == 0
        body = stdout or stderr or "(no output)"
        status = "finished" if ok else f"exited with code {completed.returncode}"
        message = f"Terminal command {status}.\n{body}"

        logger.info("[TERMINAL] Command %s in %s: %s", status, workdir, command[:160])
        return TerminalResult(ok, message, command=command, stdout=stdout, stderr=stderr, returncode=completed.returncode)

    def _resolve_workdir(self, cwd: Optional[str]) -> Path:
        if not cwd:
            return BASE_DIR

        try:
            path = Path(cwd).expanduser()
            return path if path.exists() and path.is_dir() else BASE_DIR
        except Exception:
            return BASE_DIR

    def _limit(self, value: str) -> str:
        if len(value) <= TERMINAL_OUTPUT_MAX_CHARS:
            return value.strip()
        return value[:TERMINAL_OUTPUT_MAX_CHARS].rstrip() + "\n...output truncated..."
