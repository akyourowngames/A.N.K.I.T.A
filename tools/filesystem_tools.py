from __future__ import annotations

import os
import unicodedata
from pathlib import Path
from typing import Any

from .path_resolver import resolve_local_path
from .registry import ToolInputError, optional_text, require_text


def list_directory(params: dict[str, Any]) -> dict[str, Any]:
    path = resolve_path(optional_text(params, "path", "."))
    if not path.is_dir():
        raise ToolInputError(f"path is not a directory: {path}")
    limit = bounded_int(params.get("limit"), env_int("JARVIS_LIST_DIRECTORY_LIMIT", 10), 1, 500)
    children = sorted(path.iterdir(), key=lambda item: item.name.lower())
    entries = []
    for child in children[:limit]:
        entries.append(directory_entry_info(child))
    return {
        "path": str(path),
        "count": len(entries),
        "total_count": len(children),
        "truncated": len(children) > len(entries),
        "entries": entries,
        "summary": directory_summary(path, entries, len(children)),
    }


def read_text_file(params: dict[str, Any]) -> dict[str, Any]:
    path = resolve_path(require_text(params, "path"))
    if not path.is_file():
        raise ToolInputError(f"path is not a file: {path}")
    max_chars = bounded_int(params.get("max_chars"), 8000, 1, 200000)
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    return {
        "path": str(path),
        "chars": len(content),
        "truncated": len(content) > max_chars,
        "content": content[:max_chars],
    }


def get_file_info(params: dict[str, Any]) -> dict[str, Any]:
    path = resolve_path(require_text(params, "path"))
    if not path.exists():
        raise ToolInputError(f"path does not exist: {path}")
    return entry_info(path)


def search_text_files(params: dict[str, Any]) -> dict[str, Any]:
    root = resolve_path(optional_text(params, "path", "."))
    query = require_text(params, "query")
    if not root.exists():
        raise ToolInputError(f"path does not exist: {root}")
    max_files = bounded_int(params.get("max_files"), 100, 1, 1000)
    max_matches = bounded_int(params.get("max_matches"), 50, 1, 500)
    files = [root] if root.is_file() else sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: str(item))
    matches = []
    scanned = 0
    for file_path in files[:max_files]:
        scanned += 1
        try:
            text = file_path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if query in line:
                matches.append(
                    {
                        "path": str(file_path),
                        "line": line_number,
                        "text": line,
                    }
                )
                if len(matches) >= max_matches:
                    return {"root": str(root), "query": query, "scanned_files": scanned, "matches": matches}
    return {"root": str(root), "query": query, "scanned_files": scanned, "matches": matches}


def resolve_path(value: str) -> Path:
    return resolve_local_path(value)


def entry_info(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "name": path.name,
        "type": "directory" if path.is_dir() else "file",
        "size_bytes": stat.st_size,
        "modified": stat.st_mtime,
    }


def directory_entry_info(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": display_name(path.name),
        "type": "directory" if path.is_dir() else "file",
        "size_bytes": stat.st_size,
        "modified": stat.st_mtime,
    }


def directory_summary(path: Path, entries: list[dict[str, Any]], total_count: int) -> str:
    if not entries:
        return f"Directory {path.name or path} is empty."
    if total_count > len(entries):
        lines = [f"Directory {path.name or path} has {total_count} entries. Showing {len(entries)}:"]
    else:
        lines = [f"Directory {path.name or path} has {len(entries)} entries:"]
    for entry in entries:
        type_label = "dir" if entry.get("type") == "directory" else "file"
        lines.append(f"- {entry.get('name')} ({type_label}, {entry.get('size_bytes')} bytes)")
    return "\n".join(lines)


def display_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name)
    parts: list[str] = []
    last_space = False
    for char in normalized:
        category = unicodedata.category(char)
        if category.startswith("C") or category == "So":
            continue
        if char.isspace():
            if not last_space:
                parts.append(" ")
                last_space = True
            continue
        parts.append(char)
        last_space = False
    return "".join(parts).strip() or name


def env_int(name: str, fallback: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip():
        try:
            number = int(value.strip())
        except ValueError:
            number = fallback
    else:
        number = fallback
    return max(minimum, min(maximum, number))
