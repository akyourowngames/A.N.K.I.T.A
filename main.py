from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _project_venv_python() -> Path | None:
    root = Path(__file__).resolve().parent
    if os.name == "nt":
        candidate = root / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = root / ".venv" / "bin" / "python"
    return candidate if candidate.exists() else None


def _bootstrap_project_venv() -> None:
    if os.environ.get("JAKATA_SKIP_VENV_BOOTSTRAP") == "1":
        return

    venv_python = _project_venv_python()
    if venv_python is None:
        return

    current_python = Path(sys.executable).resolve()
    if current_python == venv_python.resolve():
        return

    env = os.environ.copy()
    env["JAKATA_SKIP_VENV_BOOTSTRAP"] = "1"
    result = subprocess.run([str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]], env=env)
    raise SystemExit(result.returncode)


_bootstrap_project_venv()

def _run() -> None:
    if len(sys.argv) > 1 and sys.argv[1].lower() in {"web", "serve"}:
        from jakata_agent.web import main as web_main

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        web_main()
        return
    if len(sys.argv) > 1 and sys.argv[1].lower() in {"telegram", "bot"}:
        from jakata_agent.telegram_bot import main as telegram_main

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        telegram_main()
        return

    from jakata_agent.cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    _run()

