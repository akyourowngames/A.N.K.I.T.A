from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .registry import optional_text


def run_jarvis_qa(params: dict[str, Any]) -> dict[str, Any]:
    mode = optional_text(params, "mode", "live").lower()
    script = "scripts\\verify_jarvis_live.py" if os.name == "nt" else "scripts/verify_jarvis_live.py"
    command = [sys.executable, script] if mode == "live" else [sys.executable, "-m", "unittest", "discover"]
    completed = subprocess.run(
        command,
        cwd=str(Path.cwd()),
        capture_output=True,
        text=True,
        timeout=240,
        env=qa_env(),
    )
    output = (completed.stdout.strip() + "\n" + completed.stderr.strip()).strip()
    return {
        "mode": mode,
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "output": output[-20000:],
        "summary": qa_summary(mode, completed.returncode, output),
    }


def qa_env() -> dict[str, str]:
    env = os.environ.copy()
    env["MEMORY_EXTRACT_FROM_CHAT"] = "false"
    return env


def qa_summary(mode: str, exit_code: int, output: str) -> str:
    status = "passed" if exit_code == 0 else f"failed with exit code {exit_code}"
    tail = output[-1200:].strip()
    if tail:
        return f"Jarvis {mode} QA {status}.\n{tail}"
    return f"Jarvis {mode} QA {status}."
