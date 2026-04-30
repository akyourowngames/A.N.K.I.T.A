from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TerminalTool:
    name: str = "terminal"
    description: str = "Runs an unrestricted terminal command."

    def run(self, command: str, cwd: str | None = None, timeout: int = 120) -> str:
        if not command.strip():
            return "FAILED: No terminal command provided."

        working_dir = Path(cwd).expanduser() if cwd else Path.cwd()
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as error:
            return f"FAILED: command timed out after {timeout}s\n{error}"
        except Exception as error:
            return f"FAILED: terminal error: {error}"

        output = [
            f"exit_code: {result.returncode}",
            "stdout:",
            result.stdout.strip() or "<empty>",
            "stderr:",
            result.stderr.strip() or "<empty>",
        ]
        return "\n".join(output)
