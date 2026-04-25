from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


DEFAULT_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


class PromptLoadError(RuntimeError):
    pass


def prompt_root() -> Path:
    configured = os.getenv("JAKATA_PROMPTS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_PROMPTS_DIR.resolve()


@lru_cache(maxsize=64)
def load_prompt(relative_path: str) -> str:
    requested = Path(relative_path)
    if requested.is_absolute() or any(part == ".." for part in requested.parts):
        raise PromptLoadError(f"Prompt path must stay under prompts/: {relative_path}")

    prompt_path = (prompt_root() / requested).resolve()
    root = prompt_root()
    if root not in prompt_path.parents and prompt_path != root:
        raise PromptLoadError(f"Prompt path escaped prompts/: {relative_path}")
    if not prompt_path.is_file():
        raise PromptLoadError(f"Prompt file not found: {prompt_path}")

    text = prompt_path.read_text(encoding="utf-8").strip()
    if not text:
        raise PromptLoadError(f"Prompt file is empty: {prompt_path}")
    return text
