from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from .registry import ToolInputError, optional_text, require_text


def workspace_inspect(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation").lower()
    path = resolve_path(optional_text(params, "path", "."))
    if operation == "git_status":
        return git_status(path)
    if operation == "project_tree":
        return project_tree(path, bounded_int(params.get("depth"), 2, 1, 5), bounded_int(params.get("limit"), 80, 1, 500))
    if operation == "file_hash":
        return file_hash(path, optional_text(params, "algorithm", "sha256").lower())
    if operation == "recent_files":
        return recent_files(path, bounded_int(params.get("limit"), 20, 1, 200))
    raise ToolInputError(f"unsupported workspace operation: {operation}")


def git_status(path: Path) -> dict[str, Any]:
    cwd = path if path.is_dir() else path.parent
    branch = run_git(cwd, ["branch", "--show-current"])
    status = run_git(cwd, ["status", "--short"])
    summary_lines = [f"Branch: {branch.strip() or '(detached)'}"]
    if status.strip():
        summary_lines.append(status.strip())
    else:
        summary_lines.append("Working tree clean.")
    return {
        "operation": "git_status",
        "path": str(cwd),
        "branch": branch.strip(),
        "status": status.strip(),
        "summary": "\n".join(summary_lines),
    }


def project_tree(path: Path, depth: int, limit: int) -> dict[str, Any]:
    if not path.is_dir():
        raise ToolInputError(f"path is not a directory: {path}")
    entries: list[str] = []
    walk_tree(path, path, depth, limit, entries)
    summary = "\n".join(entries) if entries else f"{path} has no shown entries."
    if len(entries) >= limit:
        summary += f"\n... stopped at {limit} entries."
    return {
        "operation": "project_tree",
        "path": str(path),
        "depth": depth,
        "shown": len(entries),
        "entries": entries,
        "summary": summary,
    }


def file_hash(path: Path, algorithm: str) -> dict[str, Any]:
    if not path.is_file():
        raise ToolInputError(f"path is not a file: {path}")
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    result = digest.hexdigest()
    return {
        "operation": "file_hash",
        "path": str(path),
        "algorithm": algorithm,
        "hash": result,
        "summary": f"{algorithm}: {result}",
    }


def recent_files(path: Path, limit: int) -> dict[str, Any]:
    root = path if path.is_dir() else path.parent
    if not root.exists():
        raise ToolInputError(f"path does not exist: {path}")
    files = sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.stat().st_mtime, reverse=True)
    shown = []
    for item in files[:limit]:
        stat = item.stat()
        shown.append({"path": str(item), "size_bytes": stat.st_size, "modified": stat.st_mtime})
    lines = [f"Recent files under {root}:"]
    for item in shown:
        lines.append(f"- {item['path']} ({item['size_bytes']} bytes)")
    return {
        "operation": "recent_files",
        "path": str(root),
        "shown": len(shown),
        "files": shown,
        "summary": "\n".join(lines) if shown else f"No files found under {root}.",
    }


def walk_tree(root: Path, current: Path, depth: int, limit: int, entries: list[str]) -> None:
    if len(entries) >= limit:
        return
    if current != root and len(current.relative_to(root).parts) > depth:
        return
    for child in sorted(current.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
        if len(entries) >= limit:
            return
        if should_skip(child):
            continue
        relative = child.relative_to(root).as_posix()
        suffix = "/" if child.is_dir() else ""
        entries.append(relative + suffix)
        if child.is_dir():
            walk_tree(root, child, depth, limit, entries)


def should_skip(path: Path) -> bool:
    name = path.name
    return name in {".git", "__pycache__", "node_modules", ".venv", "memory"}


def run_git(cwd: Path, args: list[str]) -> str:
    completed = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=20)
    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip() or "git command failed"
        raise ToolInputError(error)
    return completed.stdout


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


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
