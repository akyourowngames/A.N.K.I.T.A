"""Agent system prompts — loaded from agents/prompts/*.md at import time.

To edit a prompt: open the corresponding .md file and save.
No Python changes needed.
"""
from __future__ import annotations
import os as _os
import ctypes as _ctypes
from pathlib import Path
from typing import Dict as _Dict

_PROMPTS_DIR = Path(__file__).parent


def _known_folder(csidl: int, fallback: str) -> str:
    if _os.name != "nt":
        return fallback
    try:
        buf = _ctypes.create_unicode_buffer(260)
        result = _ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
        if result == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return fallback


# Path constants (used by prompt substitution and tests)
_HOME = str(Path.home()).replace("/", "\\")
_DESKTOP = _known_folder(0x10, str(Path.home() / "Desktop")).replace("/", "\\")
_DOCUMENTS = _known_folder(0x05, str(Path.home() / "Documents")).replace("/", "\\")
_DOWNLOADS = str(Path.home() / "Downloads").replace("/", "\\")
_PICTURES = _known_folder(0x27, str(Path.home() / "Pictures")).replace("/", "\\")
_MUSIC = _known_folder(0x0D, str(Path.home() / "Music")).replace("/", "\\")
_VIDEOS = _known_folder(0x0E, str(Path.home() / "Videos")).replace("/", "\\")


def _apply_runtime_path_substitutions(text: str) -> str:
    replacements: _Dict[str, str] = {
        r"C:\Users\anime\Desktop": _DESKTOP,
        r"C:\Users\anime\Documents": _DOCUMENTS,
        r"C:\Users\anime\Downloads": _DOWNLOADS,
        r"C:\Users\anime\Pictures": _PICTURES,
        r"C:\Users\anime\Music": _MUSIC,
        r"C:\Users\anime\Videos": _VIDEOS,
        r"C:\Users\anime": _HOME,
    }
    out = text
    for source, target in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
        out = out.replace(source, target)
    return out


def _load(filename: str) -> str:
    """Load a prompt from a .md file in this directory."""
    return _apply_runtime_path_substitutions((_PROMPTS_DIR / filename).read_text(encoding="utf-8"))

# Prompt constants — lazily-loaded from .md files
_FILE_SYSTEM_PROMPT = _load("file_agent.md")
_WEB_SYSTEM_PROMPT = _load("web_agent.md")
_SYSTEM_SYSTEM_PROMPT = _load("system_agent.md")
_MUSIC_SYSTEM_PROMPT = _load("music_agent.md")
_CODE_SYSTEM_PROMPT = _load("code_agent.md")
_CODE_WRITER_SYSTEM_PROMPT = _load("code_writer_agent.md")
_TERMINAL_SYSTEM_PROMPT = _load("terminal_agent.md")
_CONTENT_SYSTEM_PROMPT = _load("content_agent.md")
_SCREEN_SYSTEM_PROMPT = _load("screen_agent.md")
_INTEGRATION_SYSTEM_PROMPT = _load("integration_agent.md")
_NAVIGATOR_SYSTEM_PROMPT = _load("navigator_agent.md")
_TASK_SYSTEM_PROMPT = _load("task_agent.md")
_REPORT_SYSTEM_PROMPT = _load("report_agent.md")
_GENERAL_SYSTEM_PROMPT = _load("general_agent.md")
_IMAGE_SYSTEM_PROMPT = _load("image_agent.md")
_TELEGRAM_DELIVERY_GUIDE = _load("telegram_delivery_guide.md")
