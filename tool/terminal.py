from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TerminalTool:
    name: str = "terminal"
    description: str = "Runs unrestricted local terminal commands with cwd, stdin, environment, timeout, and output controls."

    def run(
        self,
        command: str,
        cwd: str | None = None,
        timeout: Any = 120,
        shell: str = "powershell",
        stdin: str = "",
        env: dict[str, Any] | None = None,
        max_output_chars: Any = None,
    ) -> str:
        command = str(command or "").strip()
        if not command:
            return "FAILED: No terminal command provided."

        timeout_seconds = self._clamp_int(timeout, default=120, minimum=1, maximum=3600)
        output_limit = self._clamp_int(
            max_output_chars if max_output_chars is not None else os.getenv("TERMINAL_OUTPUT_MAX_CHARS", "24000"),
            default=24000,
            minimum=1000,
            maximum=200000,
        )
        working_dir = self._working_dir(cwd)
        if not working_dir.exists():
            return f"FAILED: working directory does not exist: {working_dir}"
        if not working_dir.is_dir():
            return f"FAILED: working directory is not a folder: {working_dir}"

        shell_name = self._shell_name(shell)
        process_env = os.environ.copy()
        if env:
            process_env.update({str(key): str(value) for key, value in env.items()})

        start = time.monotonic()
        try:
            result = subprocess.run(
                self._argv(command, shell_name),
                cwd=working_dir,
                input=stdin if stdin else None,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=process_env,
            )
        except subprocess.TimeoutExpired as error:
            elapsed = time.monotonic() - start
            stdout = self._decode_timeout_output(error.stdout)
            stderr = self._decode_timeout_output(error.stderr)
            return self._format_result(
                command=command,
                cwd=working_dir,
                shell=shell_name,
                exit_code=None,
                elapsed=elapsed,
                stdout=stdout,
                stderr=stderr,
                output_limit=output_limit,
                failure=f"FAILED: command timed out after {timeout_seconds}s",
            )
        except Exception as error:
            return f"FAILED: terminal error: {error}"

        elapsed = time.monotonic() - start
        return self._format_result(
            command=command,
            cwd=working_dir,
            shell=shell_name,
            exit_code=result.returncode,
            elapsed=elapsed,
            stdout=result.stdout,
            stderr=result.stderr,
            output_limit=output_limit,
        )

    @staticmethod
    def _working_dir(cwd: str | None) -> Path:
        return (Path(cwd).expanduser() if cwd else Path.cwd()).resolve(strict=False)

    @staticmethod
    def _shell_name(shell: str) -> str:
        normalized = str(shell or "powershell").strip().casefold()
        if normalized in {"cmd", "cmd.exe", "command prompt"}:
            return "cmd"
        if normalized in {"pwsh", "powershell", "powershell.exe", "ps"}:
            return "powershell"
        return "powershell"

    @staticmethod
    def _argv(command: str, shell: str) -> list[str]:
        if shell == "cmd":
            return ["cmd", "/d", "/s", "/c", command]
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]

    @classmethod
    def _format_result(
        cls,
        command: str,
        cwd: Path,
        shell: str,
        exit_code: int | None,
        elapsed: float,
        stdout: str,
        stderr: str,
        output_limit: int,
        failure: str = "",
    ) -> str:
        stdout_text, stdout_note = cls._truncate(stdout.strip(), output_limit)
        stderr_text, stderr_note = cls._truncate(stderr.strip(), output_limit)
        lines = []
        if failure:
            lines.append(failure)
        lines.extend(
            [
                f"command: {command}",
                f"cwd: {cwd}",
                f"shell: {shell}",
                f"exit_code: {exit_code if exit_code is not None else 'timeout'}",
                f"duration_seconds: {elapsed:.2f}",
                "stdout:",
                stdout_text or "<empty>",
            ]
        )
        if stdout_note:
            lines.append(stdout_note)
        lines.extend(["stderr:", stderr_text or "<empty>"])
        if stderr_note:
            lines.append(stderr_note)
        return "\n".join(lines)

    @staticmethod
    def _truncate(text: str, limit: int) -> tuple[str, str]:
        if len(text) <= limit:
            return text, ""
        head = max(1, limit // 2)
        tail = max(1, limit - head)
        omitted = len(text) - limit
        shortened = text[:head] + f"\n... truncated {omitted} characters ...\n" + text[-tail:]
        return shortened, f"... output truncated to {limit} characters"

    @staticmethod
    def _decode_timeout_output(value: bytes | str | None) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return value

    @staticmethod
    def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))
