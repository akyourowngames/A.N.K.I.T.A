from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from tool.local_paths import allowed_roots, ensure_allowed_path, format_allowed_roots


SKIPPED_DIRECTORIES = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
}

ROOTS_ALIASES = {
    "allowed",
    "allowed folders",
    "allowed local folders",
    "local folders",
    "folders",
    "roots",
}


@dataclass(frozen=True)
class LocalFilesTool:
    name: str = "local_files"
    description: str = "Lists, searches, and reads files inside allowed local folders."

    def run(
        self,
        action: str,
        path: str = "",
        query: str = "",
        max_results: int = 20,
    ) -> str:
        action = action.strip().lower() or "roots"
        max_results = max(1, min(int(max_results or 20), 100))

        try:
            if action == "roots" or (action == "list" and self._is_roots_alias(path)):
                return "Allowed local folders:\n" + format_allowed_roots()
            if action == "list":
                return self._list(path=path, max_results=max_results)
            if action == "search":
                return self._search(path=path, query=query, max_results=max_results)
            if action == "read":
                return self._read(path=path)
        except Exception as error:
            return f"FAILED: {error}"

        return "FAILED: unsupported local_files action. Use roots, list, search, or read."

    def _list(self, path: str, max_results: int) -> str:
        if not path.strip():
            return "Allowed local folders:\n" + format_allowed_roots()

        target = ensure_allowed_path(path)
        if not target.exists():
            return f"FAILED: path does not exist: {target}"
        if not target.is_dir():
            return f"FAILED: path is not a folder: {target}"

        entries = sorted(target.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        lines = [f"Folder: {target}"]
        for item in entries[:max_results]:
            kind = "folder" if item.is_dir() else "file"
            size = "" if item.is_dir() else f", {item.stat().st_size} bytes"
            lines.append(f"- {kind}: {item.name}{size}")
        if len(entries) > max_results:
            lines.append(f"... {len(entries) - max_results} more entries")
        return "\n".join(lines)

    def _search(self, path: str, query: str, max_results: int) -> str:
        needle = query.strip().lower()
        if not needle:
            return "FAILED: search query is required."

        roots = [ensure_allowed_path(path)] if path.strip() else allowed_roots()
        matches: list[str] = []
        for root in roots:
            if root.is_file():
                if needle in root.name.lower():
                    matches.append(str(root))
                continue
            if not root.exists():
                continue
            for current, dirnames, filenames in os.walk(root):
                dirnames[:] = [name for name in dirnames if name not in SKIPPED_DIRECTORIES and not name.startswith(".")]
                current_path = Path(current)
                for dirname in dirnames:
                    candidate = current_path / dirname
                    if needle in dirname.lower():
                        matches.append(str(candidate))
                        if len(matches) >= max_results:
                            return self._format_search_results(query, matches)
                for filename in filenames:
                    candidate = current_path / filename
                    if needle in filename.lower():
                        matches.append(str(candidate))
                        if len(matches) >= max_results:
                            return self._format_search_results(query, matches)

        return self._format_search_results(query, matches)

    def _read(self, path: str) -> str:
        if not path.strip():
            return "FAILED: file path is required."

        target = ensure_allowed_path(path)
        if not target.exists():
            return f"FAILED: file does not exist: {target}"
        if not target.is_file():
            return f"FAILED: path is not a file: {target}"

        max_chars = max(1000, int(os.getenv("LOCAL_FILE_READ_MAX_CHARS", "8000")))
        text = target.read_text(encoding="utf-8", errors="replace")
        truncated = len(text) > max_chars
        body = text[:max_chars]
        suffix = f"\n\n... truncated after {max_chars} characters" if truncated else ""
        return f"File: {target}\n\n{body}{suffix}"

    @staticmethod
    def _format_search_results(query: str, matches: list[str]) -> str:
        if not matches:
            return f"No local files matched: {query}"
        lines = [f"Local file matches for: {query}"]
        lines.extend(f"{index}. {path}" for index, path in enumerate(matches, start=1))
        return "\n".join(lines)

    @staticmethod
    def _is_roots_alias(path: str) -> bool:
        text = path.strip().strip('"').strip("'").strip("`").lower().strip(".,;:!?")
        for prefix in ("my ", "the "):
            if text.startswith(prefix):
                text = text.removeprefix(prefix)
        return text in ROOTS_ALIASES
