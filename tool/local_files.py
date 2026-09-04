from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from tool.local_paths import ensure_allowed_path, format_allowed_roots, resolve_local_path


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
    "access",
    "all folders",
    "browse roots",
    "folders",
    "local access",
    "local folders",
    "roots",
    "starting points",
}

TEXT_EXTENSIONS = {
    ".bat",
    ".cfg",
    ".csv",
    ".css",
    ".env",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".log",
    ".md",
    ".ps1",
    ".py",
    ".sql",
    ".toml",
    ".ts",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

FILE_TYPE_GROUPS = {
    "archive": {".7z", ".gz", ".rar", ".tar", ".zip"},
    "audio": {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".wav"},
    "code": {".bat", ".css", ".html", ".js", ".json", ".ps1", ".py", ".sql", ".ts"},
    "document": {".doc", ".docx", ".md", ".pdf", ".ppt", ".pptx", ".rtf", ".txt", ".xls", ".xlsx"},
    "image": {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".webp"},
    "text": TEXT_EXTENSIONS,
    "video": {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm", ".wmv"},
}

FILE_TYPE_ALIASES = {
    "archives": "archive",
    "docs": "document",
    "documents": "document",
    "images": "image",
    "pic": "image",
    "pics": "image",
    "picture": "image",
    "pictures": "image",
    "photos": "image",
    "songs": "audio",
    "videos": "video",
}


@dataclass(frozen=True)
class LocalFilesTool:
    name: str = "local_files"
    description: str = "Lists, searches, reads, previews, and inspects local files and folders."

    def run(
        self,
        action: str,
        path: str = "",
        query: str = "",
        max_results: Any = 20,
        recursive: Any = None,
        max_depth: Any = 2,
        include_hidden: Any = False,
        file_types: str = "",
        sort: str = "name",
        search_mode: str = "name",
        preview_chars: Any = 220,
    ) -> str:
        action = action.strip().lower() or "list"
        max_results = self._clamp_int(max_results, default=20, minimum=1, maximum=500)
        max_depth = self._clamp_int(max_depth, default=2, minimum=1, maximum=10)
        preview_chars = self._clamp_int(preview_chars, default=220, minimum=80, maximum=1000)
        include_hidden = self._bool(include_hidden)
        recursive = self._bool(recursive) if recursive is not None else action in {"search", "recent"}

        try:
            if action == "roots" or (action == "list" and self._is_roots_alias(path)):
                return "Local file access:\n" + format_allowed_roots()
            if action == "list":
                return self._list(path, max_results, include_hidden, file_types, sort, recursive, max_depth)
            if action == "tree":
                return self._tree(path, max_results, include_hidden, file_types, max_depth)
            if action == "search":
                return self._search(path, query, max_results, include_hidden, file_types, search_mode, max_depth)
            if action == "read":
                return self._read(path)
            if action in {"stat", "info", "metadata", "details"}:
                return self._stat(path)
            if action == "recent":
                return self._recent(path, max_results, include_hidden, file_types, max_depth)
        except Exception as error:
            return f"FAILED: {error}"

        return "FAILED: unsupported local_files action. Use roots, list, tree, search, read, stat, or recent."

    def _list(
        self,
        path: str,
        max_results: int,
        include_hidden: bool,
        file_types: str,
        sort: str,
        recursive: bool,
        max_depth: int,
    ) -> str:
        target = self._target(path)
        if not target.exists():
            return f"FAILED: path does not exist: {target}"
        if target.is_file():
            return self._stat(str(target))
        if not target.is_dir():
            return f"FAILED: path is not a folder: {target}"

        extensions = self._extension_filter(file_types)
        entries = list(self._iter_entries(target, recursive, max_depth, include_hidden, extensions))
        entries = self._sort_entries(entries, sort)

        scope = "recursive" if recursive else "folder"
        lines = [f"Folder: {target}", f"Mode: {scope}, max depth {max_depth}"]
        for item in entries[:max_results]:
            lines.append("- " + self._format_entry(item, target))
        if len(entries) > max_results:
            lines.append(f"... {len(entries) - max_results} more entries")
        if not entries:
            lines.append("(empty or no matching files)")
        return "\n".join(lines)

    def _tree(
        self,
        path: str,
        max_results: int,
        include_hidden: bool,
        file_types: str,
        max_depth: int,
    ) -> str:
        target = self._target(path)
        if not target.exists():
            return f"FAILED: path does not exist: {target}"
        if target.is_file():
            return self._stat(str(target))

        extensions = self._extension_filter(file_types)
        rows: list[tuple[int, Path]] = []
        for item in self._iter_entries(target, recursive=True, max_depth=max_depth, include_hidden=include_hidden, extensions=extensions):
            depth = len(item.relative_to(target).parts)
            rows.append((depth, item))
            if len(rows) >= max_results:
                break

        lines = [f"Tree: {target}", f"Depth: {max_depth}"]
        for depth, item in rows:
            marker = "[D]" if item.is_dir() else "[F]"
            indent = "  " * max(0, depth - 1)
            lines.append(f"{indent}- {marker} {item.name}")
        if not rows:
            lines.append("(empty or no matching files)")
        return "\n".join(lines)

    def _search(
        self,
        path: str,
        query: str,
        max_results: int,
        include_hidden: bool,
        file_types: str,
        search_mode: str,
        max_depth: int,
    ) -> str:
        needle = query.strip()
        if not needle:
            return "FAILED: search query is required."

        target = self._target(path)
        if not target.exists():
            return f"FAILED: path does not exist: {target}"

        mode = self._search_mode(search_mode)
        extensions = self._extension_filter(file_types)
        matches: list[str] = []
        for candidate in self._search_candidates(target, include_hidden, extensions, max_depth):
            name_hit = needle.casefold() in candidate.name.casefold()
            content_hit = ""
            if candidate.is_file() and mode in {"content", "both"}:
                content_hit = self._content_match(candidate, needle, preview_chars=180)

            if (mode == "name" and name_hit) or (mode == "content" and content_hit) or (mode == "both" and (name_hit or content_hit)):
                detail = self._format_entry(candidate, target)
                if content_hit:
                    detail = f"{detail} | match: {content_hit}"
                matches.append(detail)
                if len(matches) >= max_results:
                    break

        if not matches:
            return f"No local files matched: {needle}"
        lines = [f"Local file matches for: {needle}", f"Root: {target}", f"Search mode: {mode}"]
        lines.extend(f"{index}. {match}" for index, match in enumerate(matches, start=1))
        return "\n".join(lines)

    def _read(self, path: str) -> str:
        if not path.strip():
            return "FAILED: file path is required."

        target = ensure_allowed_path(path)
        if not target.exists():
            return f"FAILED: file does not exist: {target}"
        if not target.is_file():
            return f"FAILED: path is not a file: {target}"

        if not self._is_text_file(target):
            return self._binary_summary(target)

        max_chars = max(1000, int(os.getenv("LOCAL_FILE_READ_MAX_CHARS", "8000")))
        text = target.read_text(encoding="utf-8", errors="replace")
        if target.suffix.lower() == ".json":
            text = self._pretty_json(text)
        truncated = len(text) > max_chars
        body = text[:max_chars]
        suffix = f"\n\n... truncated after {max_chars} characters" if truncated else ""
        return f"File: {target}\nType: {self._type_label(target)}\nSize: {self._human_size(target.stat().st_size)}\n\n{body}{suffix}"

    def _stat(self, path: str) -> str:
        target = self._target(path)
        if not target.exists():
            return f"FAILED: path does not exist: {target}"

        stat = target.stat()
        lines = [
            f"Path: {target}",
            f"Kind: {'folder' if target.is_dir() else 'file'}",
            f"Modified: {self._format_time(stat.st_mtime)}",
            f"Created: {self._format_time(stat.st_ctime)}",
        ]
        if target.is_file():
            lines.extend(
                [
                    f"Size: {self._human_size(stat.st_size)}",
                    f"Type: {self._type_label(target)}",
                ]
            )
            image = self._image_metadata(target)
            if image:
                lines.append(f"Image: {image}")
        elif target.is_dir():
            folders = 0
            files = 0
            for item in target.iterdir():
                if item.is_dir():
                    folders += 1
                elif item.is_file():
                    files += 1
            lines.append(f"Immediate children: {folders} folders, {files} files")
        return "\n".join(lines)

    def _recent(
        self,
        path: str,
        max_results: int,
        include_hidden: bool,
        file_types: str,
        max_depth: int,
    ) -> str:
        target = self._target(path)
        if not target.exists():
            return f"FAILED: path does not exist: {target}"

        extensions = self._extension_filter(file_types)
        entries = [
            item
            for item in self._search_candidates(target, include_hidden, extensions, max_depth)
            if item.is_file()
        ]
        entries.sort(key=lambda item: item.stat().st_mtime, reverse=True)
        lines = [f"Recent files under: {target}"]
        for item in entries[:max_results]:
            lines.append("- " + self._format_entry(item, target))
        if not entries:
            lines.append("(no matching files)")
        return "\n".join(lines)

    def _target(self, path: str) -> Path:
        return ensure_allowed_path(path) if path.strip() else resolve_local_path(os.getenv("LOCAL_FILE_DEFAULT_PATH", ""))

    def _iter_entries(
        self,
        root: Path,
        recursive: bool,
        max_depth: int,
        include_hidden: bool,
        extensions: set[str] | None,
    ) -> Iterable[Path]:
        if not recursive:
            for item in self._safe_iterdir(root, include_hidden):
                if self._matches_extension(item, extensions):
                    yield item
            return

        pending: list[tuple[Path, int]] = [(root, 0)]
        while pending:
            current, depth = pending.pop(0)
            if depth >= max_depth:
                continue
            for item in self._safe_iterdir(current, include_hidden):
                if self._matches_extension(item, extensions):
                    yield item
                if item.is_dir() and item.name not in SKIPPED_DIRECTORIES:
                    pending.append((item, depth + 1))

    def _search_candidates(
        self,
        target: Path,
        include_hidden: bool,
        extensions: set[str] | None,
        max_depth: int,
    ) -> Iterable[Path]:
        if target.is_file():
            if self._matches_extension(target, extensions):
                yield target
            return
        yield from self._iter_entries(target, recursive=True, max_depth=max_depth, include_hidden=include_hidden, extensions=extensions)

    def _safe_iterdir(self, root: Path, include_hidden: bool) -> list[Path]:
        try:
            entries = list(root.iterdir())
        except OSError:
            return []
        visible = []
        for item in entries:
            if not include_hidden and item.name.startswith("."):
                continue
            if item.is_dir() and item.name in SKIPPED_DIRECTORIES:
                continue
            visible.append(item)
        return visible

    def _format_entry(self, item: Path, root: Path) -> str:
        relative = item.relative_to(root) if self._is_relative_to(item, root) else item
        if item.is_dir():
            return f"folder: {relative}"

        try:
            stat = item.stat()
            size = self._human_size(stat.st_size)
            modified = self._format_time(stat.st_mtime)
        except OSError:
            size = "unknown size"
            modified = "unknown modified time"
        details = [f"file: {relative}", size, self._type_label(item), f"modified {modified}"]
        image = self._image_metadata(item)
        if image:
            details.append(image)
        return ", ".join(details)

    def _content_match(self, path: Path, needle: str, preview_chars: int) -> str:
        if not self._is_text_file(path):
            return ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        index = text.casefold().find(needle.casefold())
        if index < 0:
            return ""
        start = max(0, index - preview_chars // 2)
        end = min(len(text), index + len(needle) + preview_chars // 2)
        snippet = " ".join(text[start:end].split())
        return snippet

    def _binary_summary(self, target: Path) -> str:
        lines = [
            f"File: {target}",
            f"Type: {self._type_label(target)}",
            f"Size: {self._human_size(target.stat().st_size)}",
            "Content: binary file, not displayed as text.",
        ]
        image = self._image_metadata(target)
        if image:
            lines.append(f"Image: {image}")
        return "\n".join(lines)

    def _is_text_file(self, path: Path) -> bool:
        if path.suffix.lower() in TEXT_EXTENSIONS:
            return True
        try:
            sample = path.read_bytes()[:2048]
        except OSError:
            return False
        if b"\x00" in sample:
            return False
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            return False
        return True

    def _image_metadata(self, path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix not in FILE_TYPE_GROUPS["image"]:
            return ""
        size = self._image_size(path)
        if not size:
            return "image file"
        width, height = size
        return f"{width}x{height} image"

    def _image_size(self, path: Path) -> tuple[int, int] | None:
        suffix = path.suffix.lower()
        try:
            if suffix == ".png":
                data = path.read_bytes()[:32]
                if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
                    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
            if suffix == ".gif":
                data = path.read_bytes()[:10]
                if data[:6] in {b"GIF87a", b"GIF89a"} and len(data) >= 10:
                    return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")
            if suffix == ".bmp":
                data = path.read_bytes()[:26]
                if data.startswith(b"BM") and len(data) >= 26:
                    return int.from_bytes(data[18:22], "little"), int.from_bytes(data[22:26], "little")
            if suffix in {".jpg", ".jpeg"}:
                return self._jpeg_size(path)
        except OSError:
            return None
        return None

    def _jpeg_size(self, path: Path) -> tuple[int, int] | None:
        try:
            with path.open("rb") as handle:
                if handle.read(2) != b"\xff\xd8":
                    return None
                while True:
                    marker_start = handle.read(1)
                    if not marker_start:
                        return None
                    if marker_start != b"\xff":
                        continue
                    marker = handle.read(1)
                    while marker == b"\xff":
                        marker = handle.read(1)
                    if marker in {b"\xc0", b"\xc1", b"\xc2", b"\xc3", b"\xc5", b"\xc6", b"\xc7", b"\xc9", b"\xca", b"\xcb", b"\xcd", b"\xce", b"\xcf"}:
                        length = int.from_bytes(handle.read(2), "big")
                        frame = handle.read(length - 2)
                        if len(frame) >= 5:
                            return int.from_bytes(frame[3:5], "big"), int.from_bytes(frame[1:3], "big")
                    if marker in {b"\xd8", b"\xd9", b"\x01"}:
                        continue
                    length_bytes = handle.read(2)
                    if len(length_bytes) != 2:
                        return None
                    length = int.from_bytes(length_bytes, "big")
                    handle.seek(max(0, length - 2), os.SEEK_CUR)
        except OSError:
            return None

    def _extension_filter(self, file_types: str) -> set[str] | None:
        terms = self._split_terms(file_types)
        if not terms:
            return None
        extensions: set[str] = set()
        for term in terms:
            normalized = FILE_TYPE_ALIASES.get(term, term)
            if normalized in FILE_TYPE_GROUPS:
                extensions.update(FILE_TYPE_GROUPS[normalized])
            elif normalized.startswith("."):
                extensions.add(normalized)
            else:
                extensions.add(f".{normalized}")
        return extensions

    @staticmethod
    def _split_terms(text: str) -> list[str]:
        terms: list[str] = []
        current: list[str] = []
        for char in text.casefold():
            if char.isalnum() or char == ".":
                current.append(char)
            elif current:
                terms.append("".join(current))
                current = []
        if current:
            terms.append("".join(current))
        return terms

    @staticmethod
    def _matches_extension(path: Path, extensions: set[str] | None) -> bool:
        return path.is_dir() or not extensions or path.suffix.lower() in extensions

    @staticmethod
    def _type_label(path: Path) -> str:
        if path.is_dir():
            return "folder"
        suffix = path.suffix.lower()
        for label, extensions in FILE_TYPE_GROUPS.items():
            if suffix in extensions:
                return label
        return suffix.removeprefix(".") or "file"

    @staticmethod
    def _sort_entries(entries: list[Path], sort: str) -> list[Path]:
        normalized = sort.strip().casefold()
        if normalized in {"modified", "mtime", "recent"}:
            return sorted(entries, key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
        if normalized == "size":
            return sorted(entries, key=lambda item: item.stat().st_size if item.is_file() else -1, reverse=True)
        if normalized == "type":
            return sorted(entries, key=lambda item: (item.is_file(), LocalFilesTool._type_label(item), item.name.casefold()))
        return sorted(entries, key=lambda item: (item.is_file(), item.name.casefold()))

    @staticmethod
    def _pretty_json(text: str) -> str:
        try:
            return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
        except json.JSONDecodeError:
            return text

    @staticmethod
    def _format_time(timestamp: float) -> str:
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _human_size(size: int) -> str:
        value = float(size)
        for unit in ("bytes", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                if unit == "bytes":
                    return f"{int(value)} bytes"
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{size} bytes"

    @staticmethod
    def _search_mode(search_mode: str) -> str:
        normalized = search_mode.strip().casefold()
        return normalized if normalized in {"name", "content", "both"} else "name"

    @staticmethod
    def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _is_roots_alias(path: str) -> bool:
        text = path.strip().strip('"').strip("'").strip("`").lower().strip(".,;:!?")
        for prefix in ("my ", "the "):
            if text.startswith(prefix):
                text = text.removeprefix(prefix)
        return text in ROOTS_ALIASES
