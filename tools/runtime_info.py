from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any


def get_runtime_info(params: dict[str, Any]) -> dict[str, Any]:
    include_env_keys = bool(params.get("include_env_keys"))
    result: dict[str, Any] = {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "cwd": str(Path.cwd()),
        "argv": list(sys.argv),
    }
    if include_env_keys:
        result["env_keys"] = sorted(os.environ.keys())
    return result
