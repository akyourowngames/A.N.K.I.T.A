"""
Terminal tool suite for JAKATA.

Five tools that collectively give the agent real shell access:
  shell        - run any command, track cwd, timeout, safety checks
  read_file    - read file with optional line range
  list_dir     - ls -la with metadata
  search_files - find by name pattern OR grep content across a tree
  write_file   - write / overwrite / append files

All follow the Tool contract: normalize_args(), run(), render().
Register all five via register_terminal_tools(registry, cwd).
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Shared state: working directory is shared across all terminal tools
# so `cd` in shell actually changes where the next command runs.
# ---------------------------------------------------------------------------

class _CwdState:
    def __init__(self, initial: Path) -> None:
        self.path: Path = initial.resolve()

    def chdir(self, target: str) -> None:
        candidate = (self.path / Path(target).expanduser()).resolve()
        if candidate.is_dir():
            self.path = candidate

    def __str__(self) -> str:
        return str(self.path)


# ---------------------------------------------------------------------------
# Safety: commands that are never allowed regardless of context
# ---------------------------------------------------------------------------

_BLOCKED_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\brm\s+-rf\s+/",           # rm -rf /
        r"\bmkfs\b",                  # format disk
        r"\bdd\b.*of=/dev/",          # disk write
        r"\bfork\s*bomb\b",
        r":\(\)\s*\{.*:\|:&",         # fork bomb syntax
        r"\bshutdown\b",
        r"\breboot\b",
        r"\bhalt\b",
        r"\bsudo\s+rm\s+-rf\s+/\s*$",  # only literal root
        r"\bsudo\s+dd\b",
    ]
)

_MAX_OUTPUT = 12_000   # chars — truncate beyond this
_TIMEOUT    = 30       # seconds per command


def _is_blocked(cmd: str) -> bool:
    return any(p.search(cmd) for p in _BLOCKED_PATTERNS)


def _truncate(text: str, limit: int = _MAX_OUTPUT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _run_cmd(cmd: str, cwd: _CwdState, timeout: int = _TIMEOUT) -> tuple[str, str, int]:
    """Run a shell command, return (stdout, stderr, returncode)."""
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            cwd=str(cwd.path),
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"},
        )
        return proc.stdout, proc.stderr, proc.returncode
    except subprocess.TimeoutExpired:
        return "", f"Command timed out after {timeout}s.", 124
    except Exception as exc:  # noqa: BLE001
        return "", str(exc), 1


# ---------------------------------------------------------------------------
# 1. ShellTool
# ---------------------------------------------------------------------------

class ShellTool(Tool):
    name = "shell"
    public = False
    description = (
        "Run any shell/terminal command. Tracks working directory across calls. "
        "Use for compiling, installing packages, running scripts, git, grep, etc."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute.",
            },
            "timeout": {
                "type": "integer",
                "description": "Max seconds to wait. Default 30.",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def __init__(self, cwd: _CwdState) -> None:
        self.cwd = cwd

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("timeout", _TIMEOUT)
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        cmd = str(args["command"]).strip()
        timeout = int(args.get("timeout", _TIMEOUT))

        if _is_blocked(cmd):
            return ToolResult(ok=False, summary="Blocked: command matches a safety rule.", data={}, error="blocked_command")

        # Handle `cd` specially — update shared cwd state
        if cmd.startswith("cd "):
            target = cmd[3:].strip().strip("'\"")
            self.cwd.chdir(target)
            return ToolResult(
                ok=True,
                summary=f"Changed directory to {self.cwd}",
                data={"cwd": str(self.cwd), "stdout": "", "stderr": "", "returncode": 0},
            )

        stdout, stderr, returncode = _run_cmd(cmd, self.cwd, timeout=timeout)
        out, truncated = _truncate(stdout)
        if truncated:
            out += f"\n\n[... output truncated at {_MAX_OUTPUT} chars ...]"

        ok = returncode == 0
        summary = out.strip() or stderr.strip() or ("Done." if ok else f"Exit code {returncode}.")
        return ToolResult(
            ok=ok,
            summary=summary[:300],
            data={
                "command": cmd,
                "stdout": out,
                "stderr": stderr[:2000],
                "returncode": returncode,
                "cwd": str(self.cwd),
                "truncated": truncated,
            },
            error=None if ok else f"exit_{returncode}",
        )

    def render(self, data: dict[str, Any]) -> str:
        cmd = data.get("command", "")
        stdout = str(data.get("stdout", "")).strip()
        stderr = str(data.get("stderr", "")).strip()
        rc = data.get("returncode", 0)
        cwd = data.get("cwd", "")
        parts = [f"$ {cmd}  (cwd: {cwd})"]
        if stdout:
            parts.append(stdout)
        if stderr and rc != 0:
            parts.append(f"[stderr] {stderr}")
        if rc != 0:
            parts.append(f"[exit {rc}]")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# 2. ReadFileTool
# ---------------------------------------------------------------------------

class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read the contents of a file. Supports line range (start_line, end_line). "
        "Handles text and binary files gracefully."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path, absolute or relative to current working directory.",
            },
            "start_line": {
                "type": "integer",
                "description": "First line to read (1-indexed). Default: start of file.",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to read (inclusive). Default: end of file.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, cwd: _CwdState) -> None:
        self.cwd = cwd

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        raw_path = str(args["path"]).strip()
        target = (self.cwd.path / Path(raw_path).expanduser()).resolve()

        if not target.exists():
            return ToolResult(ok=False, summary=f"File not found: {raw_path}", data={}, error="file_not_found")
        if not target.is_file():
            return ToolResult(ok=False, summary=f"Not a file: {raw_path}", data={}, error="not_a_file")

        try:
            raw = target.read_bytes()
        except PermissionError:
            return ToolResult(ok=False, summary=f"Permission denied: {raw_path}", data={}, error="permission_denied")

        # Detect binary
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = raw.decode("latin-1")
            except Exception:
                return ToolResult(
                    ok=True,
                    summary=f"Binary file ({len(raw)} bytes): {raw_path}",
                    data={"path": str(target), "binary": True, "size_bytes": len(raw), "content": ""},
                )

        lines = text.splitlines(keepends=True)
        total_lines = len(lines)
        start = max(1, int(args.get("start_line") or 1))
        end = min(total_lines, int(args.get("end_line") or total_lines))
        selected = lines[start - 1 : end]
        content = "".join(selected)

        content, truncated = _truncate(content)
        if truncated:
            content += f"\n[... truncated at {_MAX_OUTPUT} chars ...]"

        summary = f"{target.name} ({total_lines} lines)"
        if start > 1 or end < total_lines:
            summary += f", showing lines {start}-{end}"

        return ToolResult(
            ok=True,
            summary=summary,
            data={
                "path": str(target),
                "content": content,
                "total_lines": total_lines,
                "start_line": start,
                "end_line": end,
                "truncated": truncated,
                "size_bytes": len(raw),
            },
        )

    def render(self, data: dict[str, Any]) -> str:
        path = data.get("path", "")
        content = str(data.get("content", "")).strip()
        total = data.get("total_lines", "?")
        start = data.get("start_line", 1)
        end = data.get("end_line", total)
        header = f"# {path}  (lines {start}-{end} of {total})"
        return f"{header}\n\n{content}"


# ---------------------------------------------------------------------------
# 3. ListDirTool
# ---------------------------------------------------------------------------

class ListDirTool(Tool):
    name = "list_dir"
    description = (
        "List files and directories. Shows names, sizes, types, and modification times. "
        "Optionally recursive."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory path. Default: current working directory.",
            },
            "recursive": {
                "type": "boolean",
                "description": "Whether to recurse into subdirectories. Default false.",
            },
            "pattern": {
                "type": "string",
                "description": "Glob pattern filter, e.g. '*.py'. Default: all files.",
            },
        },
        "required": [],
        "additionalProperties": False,
    }

    def __init__(self, cwd: _CwdState) -> None:
        self.cwd = cwd

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("path", ".")
        args.setdefault("recursive", False)
        args.setdefault("pattern", "*")
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        raw_path = str(args.get("path", ".")).strip()
        target = (self.cwd.path / Path(raw_path).expanduser()).resolve()
        recursive = bool(args.get("recursive", False))
        pattern = str(args.get("pattern", "*"))

        if not target.exists():
            return ToolResult(ok=False, summary=f"Path not found: {raw_path}", data={}, error="not_found")
        if not target.is_dir():
            return ToolResult(ok=False, summary=f"Not a directory: {raw_path}", data={}, error="not_a_dir")

        try:
            if recursive:
                paths = sorted(target.rglob(pattern))
            else:
                paths = sorted(target.glob(pattern))
        except PermissionError:
            return ToolResult(ok=False, summary="Permission denied.", data={}, error="permission_denied")

        entries: list[dict[str, Any]] = []
        for p in paths[:500]:  # cap at 500 entries
            try:
                stat = p.stat()
                entries.append({
                    "name": str(p.relative_to(target)),
                    "type": "dir" if p.is_dir() else "file",
                    "size": stat.st_size if p.is_file() else None,
                    "modified": stat.st_mtime,
                })
            except Exception:  # noqa: BLE001
                continue

        return ToolResult(
            ok=True,
            summary=f"{len(entries)} item(s) in {target}",
            data={
                "path": str(target),
                "entries": entries,
                "count": len(entries),
                "recursive": recursive,
                "pattern": pattern,
            },
        )

    def render(self, data: dict[str, Any]) -> str:
        path = data.get("path", "")
        entries = data.get("entries", [])
        lines = [f"# {path}  ({len(entries)} items)\n"]
        for e in entries:
            kind = "d" if e["type"] == "dir" else "f"
            size = f"{e['size']:>10}" if e["size"] is not None else "          "
            lines.append(f"  [{kind}] {size}  {e['name']}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 4. SearchFilesTool
# ---------------------------------------------------------------------------

class SearchFilesTool(Tool):
    name = "search_files"
    description = (
        "Find files by name pattern OR search file contents with a text/regex query. "
        "Like find + grep. Use for exploring codebases, locating configs, searching logs."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text or regex to search for inside files (grep mode). Leave empty for name-only search.",
            },
            "file_pattern": {
                "type": "string",
                "description": "Glob pattern to filter filenames, e.g. '*.py', '*.json'. Default: all files.",
            },
            "path": {
                "type": "string",
                "description": "Root directory to search from. Default: current working directory.",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Whether the content search is case-sensitive. Default false.",
            },
            "max_results": {
                "type": "integer",
                "description": "Max number of matching lines/files to return. Default 50.",
            },
        },
        "required": [],
        "additionalProperties": False,
    }

    def __init__(self, cwd: _CwdState) -> None:
        self.cwd = cwd

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("query", "")
        args.setdefault("file_pattern", "*")
        args.setdefault("path", ".")
        args.setdefault("case_sensitive", False)
        args.setdefault("max_results", 50)
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        file_pattern = str(args.get("file_pattern", "*"))
        raw_path = str(args.get("path", ".")).strip()
        case_sensitive = bool(args.get("case_sensitive", False))
        max_results = int(args.get("max_results", 50))

        root = (self.cwd.path / Path(raw_path).expanduser()).resolve()
        if not root.exists():
            return ToolResult(ok=False, summary=f"Path not found: {raw_path}", data={}, error="not_found")

        # Find matching files
        try:
            all_files = [p for p in sorted(root.rglob(file_pattern)) if p.is_file()]
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary="Search failed.", data={}, error=str(exc))

        # Name-only mode: no query
        if not query:
            results = [{"file": str(p.relative_to(root)), "line": None, "text": None} for p in all_files[:max_results]]
            return ToolResult(
                ok=True,
                summary=f"Found {len(all_files)} file(s) matching '{file_pattern}' in {root}",
                data={"mode": "name", "root": str(root), "results": results, "total": len(all_files)},
            )

        # Content grep mode
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query, flags)
        except re.error as exc:
            return ToolResult(ok=False, summary="Invalid regex pattern.", data={}, error=str(exc))

        matches: list[dict[str, Any]] = []
        for file_path in all_files:
            if len(matches) >= max_results:
                break
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                continue
            for line_no, line in enumerate(text.splitlines(), 1):
                if pattern.search(line):
                    matches.append({
                        "file": str(file_path.relative_to(root)),
                        "line": line_no,
                        "text": line.strip()[:200],
                    })
                    if len(matches) >= max_results:
                        break

        return ToolResult(
            ok=True,
            summary=f"{len(matches)} match(es) for '{query}' in {root}",
            data={
                "mode": "grep",
                "root": str(root),
                "query": query,
                "results": matches,
                "total": len(matches),
                "capped": len(matches) >= max_results,
            },
        )

    def render(self, data: dict[str, Any]) -> str:
        mode = data.get("mode", "grep")
        root = data.get("root", "")
        results = data.get("results", [])
        total = data.get("total", len(results))
        capped = data.get("capped", False)

        if mode == "name":
            lines = [f"# Files in {root}  ({total} found)\n"]
            for r in results:
                lines.append(f"  {r['file']}")
            return "\n".join(lines)

        query = data.get("query", "")
        lines = [f"# Grep '{query}' in {root}  ({total} match(es){'  [capped]' if capped else ''})\n"]
        for r in results:
            lines.append(f"  {r['file']}:{r['line']}  {r['text']}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. WriteFileTool
# ---------------------------------------------------------------------------

class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Write, overwrite, or append content to a file. "
        "Creates parent directories automatically. Use for editing code, configs, notes."
    )
    safety = "write"
    input_schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path to write to.",
            },
            "content": {
                "type": "string",
                "description": "Content to write.",
            },
            "mode": {
                "type": "string",
                "enum": ["overwrite", "append", "create_only"],
                "description": "overwrite: replace file. append: add to end. create_only: fail if file exists.",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def __init__(self, cwd: _CwdState) -> None:
        self.cwd = cwd

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("mode", "overwrite")
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        raw_path = str(args["path"]).strip()
        content = str(args["content"])
        mode = str(args.get("mode", "overwrite"))

        target = (self.cwd.path / Path(raw_path).expanduser()).resolve()

        if mode == "create_only" and target.exists():
            return ToolResult(ok=False, summary=f"File already exists: {raw_path}", data={}, error="file_exists")

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if mode == "append":
                with target.open("a", encoding="utf-8") as f:
                    f.write(content)
            else:
                target.write_text(content, encoding="utf-8")
        except PermissionError:
            return ToolResult(ok=False, summary=f"Permission denied: {raw_path}", data={}, error="permission_denied")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary="Write failed.", data={}, error=str(exc))

        size = target.stat().st_size
        action = {"overwrite": "Written", "append": "Appended to", "create_only": "Created"}.get(mode, "Written")
        summary = f"{action} {target.name} ({size} bytes)"
        return ToolResult(
            ok=True,
            summary=summary,
            data={"path": str(target), "size_bytes": size, "mode": mode, "lines": content.count("\n") + 1},
        )

    def render(self, data: dict[str, Any]) -> str:
        path = data.get("path", "")
        size = data.get("size_bytes", 0)
        mode = data.get("mode", "overwrite")
        lines = data.get("lines", "?")
        action = {"overwrite": "Written", "append": "Appended", "create_only": "Created"}.get(mode, "Written")
        return f"{action}: {path}  ({lines} lines, {size} bytes)"


# ---------------------------------------------------------------------------
# Factory: register all five terminal tools
# ---------------------------------------------------------------------------

def register_terminal_tools(registry: ToolRegistry, initial_cwd: str | Path | None = None) -> _CwdState:
    """
    Register all five terminal tools sharing one cwd state.
    Returns the cwd state so the CLI can display it.

    Usage in cli.py:
        from jakata_agent.tools.terminal import register_terminal_tools
        cwd_state = register_terminal_tools(tools)
    """
    cwd = _CwdState(Path(initial_cwd or Path.cwd()))
    registry.register(ShellTool(cwd))
    registry.register(ReadFileTool(cwd))
    registry.register(ListDirTool(cwd))
    registry.register(SearchFilesTool(cwd))
    registry.register(WriteFileTool(cwd))
    return cwd
