"""Agent system prompts — loaded from agents/prompts/*.md at import time.

To edit a prompt: open the corresponding .md file and save.
No Python changes needed.
"""
from __future__ import annotations
import os as _os
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def _load(filename: str) -> str:
    """Load a prompt from a .md file in this directory."""
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


# Path constants (used by ImageAgent prompt and tests)
_DESKTOP  = str(_os.path.join(_os.path.expanduser("~"), "Desktop")).replace("/", "\\")
_DOCUMENTS = str(_os.path.join(_os.path.expanduser("~"), "Documents")).replace("/", "\\")
_DOWNLOADS = str(_os.path.join(_os.path.expanduser("~"), "Downloads")).replace("/", "\\")
_PICTURES = str(_os.path.join(_os.path.expanduser("~"), "Pictures")).replace("/", "\\")
_MUSIC    = str(_os.path.join(_os.path.expanduser("~"), "Music")).replace("/", "\\")
_VIDEOS   = str(_os.path.join(_os.path.expanduser("~"), "Videos")).replace("/", "\\")
_HOME     = str(_os.path.expanduser("~")).replace("/", "\\")


# Prompt constants — lazily-loaded from .md files
_FILE_SYSTEM_PROMPT = _load("file_agent.md")
_WEB_SYSTEM_PROMPT = _load("web_agent.md")
_SYSTEM_SYSTEM_PROMPT = _load("system_agent.md")
_MUSIC_SYSTEM_PROMPT = _load("music_agent.md")
_CODE_SYSTEM_PROMPT = _load("code_agent.md")
_TERMINAL_SYSTEM_PROMPT = _load("terminal_agent.md")
_CRON_SYSTEM_PROMPT = _load("cron_agent.md")
_COMMS_SYSTEM_PROMPT = _load("comms_agent.md")
_CONTENT_SYSTEM_PROMPT = _load("content_agent.md")
_SCREEN_SYSTEM_PROMPT = _load("screen_agent.md")
_INTEGRATION_SYSTEM_PROMPT = _load("integration_agent.md")
_WATCHDOG_SYSTEM_PROMPT = _load("watchdog_agent.md")
_NAVIGATOR_SYSTEM_PROMPT = _load("navigator_agent.md")
_TASK_SYSTEM_PROMPT = _load("task_agent.md")
_REPORT_SYSTEM_PROMPT = _load("report_agent.md")
_GENERAL_SYSTEM_PROMPT = _load("general_agent.md")
_IMAGE_SYSTEM_PROMPT = _load("image_agent.md")
_TELEGRAM_DELIVERY_GUIDE = _load("telegram_delivery_guide.md")
