"""
FileWatcher — Directory Monitor for A.N.K.I.T.A.

Watches configured directories for file system changes:
  - New files (including PDFs that trigger auto-summarise offer)
  - Deleted files
  - Modified files (mtime change)

Uses os.scandir() snapshot diff — zero extra dependencies.

Config (file_config.json):
    {
        "enabled": true,
        "poll_interval_sec": 30,
        "watch_dirs": [
            "C:/Users/anime/Desktop",
            "C:/Users/anime/Downloads"
        ],
        "auto_summarise_pdf": true
    }
"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path

from watchdog_manager import BaseWatcher
from proactive import ProactiveEngine


# File extensions that get a summarise offer when newly added
_SUMMARISE_EXTS = {".pdf", ".docx", ".txt", ".md"}
# Extensions to ignore (temp files, locks, etc.)
_IGNORE_EXTS = {".tmp", ".lock", ".lnk", ".ini", ".db", ".log", ".part"}
# Names to ignore
_IGNORE_NAMES = {"desktop.ini", "thumbs.db", ".ds_store"}


class FileWatcher(BaseWatcher):
    """
    Watches directories for new, deleted, or modified files.

    State stores a snapshot: {dir_path: {filename: mtime}}
    On each check, compares live scandir() output against stored snapshot.
    """

    def __init__(
        self,
        config: Dict[str, Any],
        proactive: ProactiveEngine,
        workspace_root: Path,
    ) -> None:
        super().__init__(
            name="FileWatcher",
            config=config,
            proactive=proactive,
            workspace_root=workspace_root,
        )
        self.poll_interval = float(config.get("poll_interval_sec", 30))
        self.auto_summarise_pdf = config.get("auto_summarise_pdf", True)

        # State: {"snapshots": {dir: {filename: mtime}}}
        # First run — build initial snapshot without alerting
        self.state.setdefault("snapshots", {})
        self._first_run = len(self.state["snapshots"]) == 0

    def update_config(self, new_config: Dict[str, Any]) -> None:
        super().update_config(new_config)
        self.auto_summarise_pdf = new_config.get("auto_summarise_pdf", self.auto_summarise_pdf)

    def _check(self) -> Optional[str]:
        """Scan all watched directories and detect changes."""
        watch_dirs: List[str] = self.config.get("watch_dirs", [])
        if not watch_dirs:
            return None

        all_alerts: List[str] = []

        for dir_path_str in watch_dirs:
            dir_path = Path(dir_path_str).expanduser()
            if not dir_path.exists() or not dir_path.is_dir():
                continue

            alerts = self._check_directory(dir_path)
            all_alerts.extend(alerts)

        self._save_state()

        if self._first_run:
            self._first_run = False
            return None  # Don't alert on first run — just build baseline snapshot

        if all_alerts:
            return "\n".join(all_alerts)
        return None

    def _check_directory(self, dir_path: Path) -> List[str]:
        """Compare current directory state against stored snapshot. Return alert strings."""
        key = str(dir_path)
        snapshots = self.state.setdefault("snapshots", {})
        old_snapshot: Dict[str, float] = snapshots.get(key, {})

        # Build current snapshot
        current_snapshot: Dict[str, float] = {}
        try:
            with os.scandir(dir_path) as it:
                for entry in it:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    name = entry.name
                    if self._should_ignore(name):
                        continue
                    try:
                        mtime = entry.stat().st_mtime
                    except OSError:
                        continue
                    current_snapshot[name] = mtime
        except PermissionError:
            return []

        alerts: List[str] = []

        if old_snapshot:  # Only diff if we have a baseline
            old_files = set(old_snapshot.keys())
            new_files = set(current_snapshot.keys())

            added = new_files - old_files
            deleted = old_files - new_files
            modified = {
                f for f in (old_files & new_files)
                if current_snapshot[f] > old_snapshot[f] + 1.0  # 1s tolerance
            }

            for fname in sorted(added):
                fpath = dir_path / fname
                ext = Path(fname).suffix.lower()
                emoji = self._file_emoji(ext)
                alert = f"{emoji} New file in {dir_path.name}: {fname}"
                if ext in _SUMMARISE_EXTS and self.auto_summarise_pdf:
                    alert += f"\n   💡 Say 'summarise {fname}' to read it!"
                alerts.append(alert)

            for fname in sorted(deleted):
                alerts.append(f"🗑️ Deleted from {dir_path.name}: {fname}")

            for fname in sorted(modified):
                alerts.append(f"✏️ Modified in {dir_path.name}: {fname}")

        # Update stored snapshot
        snapshots[key] = current_snapshot
        return alerts

    @staticmethod
    def _should_ignore(name: str) -> bool:
        """Return True if this file should be silently ignored."""
        if name.lower() in _IGNORE_NAMES:
            return True
        ext = Path(name).suffix.lower()
        if ext in _IGNORE_EXTS:
            return True
        if name.startswith("~") or name.startswith("."):
            return True
        return False

    @staticmethod
    def _file_emoji(ext: str) -> str:
        """Return a fitting emoji for a file extension."""
        mapping = {
            ".pdf": "📄", ".docx": "📝", ".doc": "📝",
            ".xlsx": "📊", ".csv": "📊", ".pptx": "📽️",
            ".py": "🐍", ".js": "⚡", ".ts": "⚡",
            ".mp3": "🎵", ".mp4": "🎬", ".wav": "🎵",
            ".png": "🖼️", ".jpg": "🖼️", ".jpeg": "🖼️", ".gif": "🖼️",
            ".zip": "📦", ".rar": "📦", ".7z": "📦",
            ".exe": "⚙️", ".msi": "⚙️",
            ".txt": "📄", ".md": "📄",
        }
        return mapping.get(ext, "📁")
