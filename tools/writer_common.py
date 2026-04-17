"""Shared helpers for document and code artifact writers."""

from __future__ import annotations

import ctypes
import re
from pathlib import Path
from typing import Optional

_PLACEHOLDER_DESKTOP_MARKERS = (
    r"\path\to\desktop",
    r"\home\user\desktop",
    r"c:\path\to\desktop",
    r"c:\home\user\desktop",
)


def safe_filename(text: str, max_len: int = 60) -> str:
    """Convert arbitrary text into a safe filename fragment."""
    safe = re.sub(r'[\\/:*?"<>|]', "_", str(text or ""))
    safe = re.sub(r"\s+", "_", safe.strip())
    return safe[:max_len] or "artifact"


def default_desktop_dir() -> Path:
    return Path(_known_folder(0x10, str(Path.home() / "Desktop"))).expanduser().resolve()


def looks_like_placeholder_desktop(raw_path: str) -> bool:
    lowered = str(raw_path or "").strip().replace("/", "\\").lower()
    if not lowered:
        return False
    return any(marker in lowered for marker in _PLACEHOLDER_DESKTOP_MARKERS)


def resolve_output_dir(output_dir: Optional[str]) -> Path:
    if output_dir and not looks_like_placeholder_desktop(output_dir):
        return Path(output_dir).expanduser().resolve()
    return default_desktop_dir()


def normalize_absolute_path(path: Path) -> str:
    return str(path.resolve()).replace("/", "\\")


def _known_folder(csidl: int, fallback: str) -> str:
    if Path().anchor == "/":
        return fallback
    try:
        buf = ctypes.create_unicode_buffer(260)
        result = ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
        if result == 0 and buf.value:
            return buf.value
    except Exception:
        pass
    return fallback
