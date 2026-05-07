from __future__ import annotations

from pathlib import Path
from typing import Any

from memory_system import MemoryConfig, append_extracted_memory, ensure_memory_workspace

from .registry import ToolInputError, optional_text, require_text


def save_memory(params: dict[str, Any]) -> dict[str, Any]:
    content = require_text(params, "content")
    source = optional_text(params, "source", "chat")
    config = MemoryConfig.from_env(Path.cwd())
    ensure_memory_workspace(config)
    append_extracted_memory(config, [content])
    return {
        "saved": True,
        "source": source,
        "path": str((config.root / "extracted.txt").resolve()),
        "content": content,
    }
