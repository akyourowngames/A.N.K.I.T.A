from __future__ import annotations

import re
from typing import Any

from tool.local_paths import KNOWN_FOLDER_ALIASES


TERMINAL_WORDS = {"terminal", "powershell", "shell", "command", "cmd", "git", "install"}
LIST_WORDS = {"list", "show", "display", "open"}
FILE_CONTEXT_WORDS = {"file", "files", "folder", "folders", "directory", "directories", "contents"}


def decide_common_tool(user_text: str) -> dict[str, Any]:
    """Deterministic routing for common requests the planner often overthinks."""
    words = normalized_words(user_text)
    if not words or TERMINAL_WORDS.intersection(words):
        return {}

    if is_allowed_folders_request(words):
        return _tool_decision("local_files", {"action": "roots"})

    if LIST_WORDS.intersection(words) and FILE_CONTEXT_WORDS.intersection(words):
        folder = mentioned_known_folder(words)
        if folder:
            return _tool_decision("local_files", {"action": "list", "path": folder, "max_results": 20})

    return {}


def normalized_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def is_allowed_folders_request(words: list[str]) -> bool:
    word_set = set(words)
    has_allowed = "allowed" in word_set or "permission" in word_set or "access" in word_set
    has_folder = bool({"folder", "folders", "directory", "directories"}.intersection(word_set))
    has_local_intent = bool({"browse", "browsing", "look", "access", "local"}.intersection(word_set))
    return has_allowed and has_folder and has_local_intent


def mentioned_known_folder(words: list[str]) -> str:
    for word in words:
        folder = KNOWN_FOLDER_ALIASES.get(word)
        if folder:
            return folder
    return ""


def _tool_decision(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "tool": tool,
        "args": args,
        "needs_memory": False,
        "needs_pc": False,
        "needs_skills": False,
    }
