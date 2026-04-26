"""
Terminal tool suite for JAKATA.

Six tools that collectively give the agent real shell access:
  shell        - run any command, track cwd, timeout
  read_file    - read file with optional line range
  list_dir     - ls -la with metadata
  search_files - find by name pattern OR grep content across a tree
  write_file   - write / overwrite / append files
  open_path    - open files, folders, and URLs in the default app

All follow the Tool contract: normalize_args(), run(), render().
Register all six via register_terminal_tools(registry, cwd).
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
import time
from collections import deque
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.opening import is_url_target, open_target
from jakata_agent.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Shared state: working directory is shared across all terminal tools
# so `cd` in shell actually changes where the next command runs.
# ---------------------------------------------------------------------------

class _CwdState:
    def __init__(self, initial: Path) -> None:
        self.path: Path = initial.resolve()

    def chdir(self, target: str) -> None:
        candidate = _resolve_path(self, target)
        if not candidate.is_dir():
            discovered, _ = _discover_existing_path(self, target, want="dir")
            if discovered is not None:
                candidate = discovered
        if candidate.is_dir():
            self.path = candidate

    def __str__(self) -> str:
        return str(self.path)


PLATFORM = platform.system()
_MAX_OUTPUT = 24_000
_TIMEOUT = 60
_MAX_TIMEOUT = 1_800
_DEFAULT_EXCLUDES = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"}
_DISCOVERY_MAX_DEPTH = 6
_DISCOVERY_MAX_VISITS = 50_000
FILE_REFERENCE_RE = re.compile(r"(?:[A-Za-z]:[\\/])?(?:[A-Za-z0-9_. -]+[\\/])*[A-Za-z0-9_. -]+\.[A-Za-z0-9]{1,8}")
_DISCOVERY_MIN_SCORE = 0.62
_SEARCH_MAX_FILES = 20_000
_SEARCH_MAX_SECONDS = 8.0


def _truncate(text: str, limit: int = _MAX_OUTPUT) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _bounded_timeout(value: Any) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = _TIMEOUT
    return max(1, min(requested, _MAX_TIMEOUT))


def _bounded_output_limit(value: Any) -> int:
    try:
        requested = int(value)
    except (TypeError, ValueError):
        requested = _MAX_OUTPUT
    return max(1_000, min(requested, 200_000))


def _coerce_env(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if str(key).strip()}


def _resolve_base(cwd: _CwdState, raw_cwd: str = "") -> Path:
    if not raw_cwd:
        return cwd.path
    candidate = Path(raw_cwd).expanduser()
    if not candidate.is_absolute():
        candidate = cwd.path / candidate
    return candidate.resolve()


def _resolve_path(cwd: _CwdState, raw_path: str, raw_cwd: str = "") -> Path:
    base = _resolve_base(cwd, raw_cwd)
    cleaned = _clean_path_text(raw_path)
    candidate = Path(cleaned).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _clean_path_text(raw_path: str) -> str:
    cleaned = str(raw_path or "").strip().strip("'\"")
    return cleaned or "."


def _env_path(name: str) -> Path | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    try:
        return Path(value).expanduser().resolve()
    except OSError:
        return None


def _configured_search_roots() -> list[Path]:
    roots: list[Path] = []
    raw = os.getenv("JAKATA_PATH_SEARCH_ROOTS", "")
    for item in raw.split(os.pathsep):
        item = item.strip()
        if not item:
            continue
        try:
            roots.append(Path(item).expanduser().resolve())
        except OSError:
            continue
    return roots


def _windows_drive_roots() -> list[Path]:
    if PLATFORM != "Windows":
        return [Path("/")]
    try:
        drives = list(os.listdrives())  # type: ignore[attr-defined]
    except AttributeError:
        drives = [f"{chr(letter)}:\\" for letter in range(ord("A"), ord("Z") + 1)]
    return [Path(drive) for drive in drives if Path(drive).exists()]


def _path_search_roots(cwd: _CwdState) -> list[Path]:
    candidates: list[Path] = []
    candidates.extend(_configured_search_roots())
    candidates.append(cwd.path)
    candidates.extend(cwd.path.parents)
    for name in ("USERPROFILE", "HOME", "OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        env_path = _env_path(name)
        if env_path is not None:
            candidates.append(env_path)
            candidates.extend(env_path.parents)
    try:
        home = Path.home().resolve()
        candidates.append(home)
        candidates.extend(home.parents)
    except OSError:
        pass
    candidates.extend(_windows_drive_roots())

    seen: set[str] = set()
    roots: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = os.path.normcase(str(resolved))
        if key in seen or not resolved.exists() or not resolved.is_dir():
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def _kind_matches(path: Path, want: str) -> bool:
    if want == "dir":
        return path.is_dir()
    if want == "file":
        return path.is_file()
    return path.exists()


def _norm_match_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _path_match_score(raw_path: str, candidate: Path) -> float:
    wanted = _clean_path_text(raw_path)
    wanted_name = _norm_match_text(Path(wanted).name or wanted)
    candidate_name = _norm_match_text(candidate.name)
    if not wanted_name or not candidate_name:
        return 0.0
    if wanted_name == candidate_name:
        return 1.0
    shorter = min(len(wanted_name), len(candidate_name))
    longer = max(len(wanted_name), len(candidate_name))
    if shorter >= 4 and shorter / longer >= 0.5 and (wanted_name in candidate_name or candidate_name in wanted_name):
        return 0.9

    score = SequenceMatcher(None, wanted_name, candidate_name).ratio()
    wanted_parts = [_norm_match_text(part) for part in Path(wanted).parts if _norm_match_text(part)]
    if len(wanted_parts) > 1:
        suffix = _norm_match_text(" ".join(candidate.parts[-len(wanted_parts) :]))
        wanted_suffix = _norm_match_text(" ".join(wanted_parts))
        score = max(score, SequenceMatcher(None, wanted_suffix, suffix).ratio())
    return score


def _direct_candidate_paths(cwd: _CwdState, raw_path: str, raw_cwd: str = "") -> list[Path]:
    cleaned = _clean_path_text(raw_path)
    candidates = [_resolve_path(cwd, cleaned, raw_cwd)]
    path = Path(cleaned).expanduser()
    if path.is_absolute():
        return candidates
    for root in _path_search_roots(cwd):
        try:
            candidates.append((root / path).resolve())
        except OSError:
            continue
    return _dedupe_paths(candidates)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        key = os.path.normcase(str(path))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, min(value, maximum))


def _discovery_excludes() -> set[str]:
    raw = os.getenv("JAKATA_PATH_DISCOVERY_EXCLUDE_DIRS", "")
    if not raw.strip():
        return set(_DEFAULT_EXCLUDES)
    return {item.strip() for item in raw.split(",") if item.strip()}


def _discover_existing_path(cwd: _CwdState, raw_path: str, *, want: str = "any", raw_cwd: str = "") -> tuple[Path | None, dict[str, Any]]:
    cleaned = _clean_path_text(raw_path)
    checked: list[str] = []
    direct = _resolve_path(cwd, cleaned, raw_cwd)
    checked.append(str(direct))
    if _kind_matches(direct, want):
        return direct, {"resolved_from": cleaned, "discovered": False, "checked": checked}

    if len([part for part in Path(cleaned).parts if part not in {".", ""}]) == 1:
        for root in _path_search_roots(cwd):
            if _kind_matches(root, want) and _path_match_score(cleaned, root) >= 0.995:
                return root, {"resolved_from": cleaned, "discovered": True, "checked": checked, "score": 1.0, "search_root": str(root)}

    for candidate in _direct_candidate_paths(cwd, cleaned, raw_cwd):
        if candidate == direct:
            continue
        checked.append(str(candidate))
        if _kind_matches(candidate, want):
            return candidate, {"resolved_from": cleaned, "discovered": True, "checked": checked}

    max_depth = _bounded_int_env("JAKATA_PATH_DISCOVERY_MAX_DEPTH", _DISCOVERY_MAX_DEPTH, 1, 20)
    max_visits = _bounded_int_env("JAKATA_PATH_DISCOVERY_MAX_VISITS", _DISCOVERY_MAX_VISITS, 500, 500_000)
    exclude_dirs = _discovery_excludes()
    visits = 0
    best: tuple[float, Path] | None = None

    for root in _path_search_roots(cwd):
        queue: deque[tuple[Path, int]] = deque([(root, 0)])
        best_in_root: tuple[float, Path] | None = None
        while queue and visits < max_visits:
            current, depth = queue.popleft()
            visits += 1
            try:
                exists = current.exists()
            except OSError:
                continue
            if not exists:
                continue
            if _kind_matches(current, want):
                score = _path_match_score(cleaned, current)
                if score >= 0.995:
                    return current.resolve(), {
                        "resolved_from": cleaned,
                        "discovered": True,
                        "checked": checked,
                        "visits": visits,
                        "score": score,
                        "search_root": str(root),
                    }
                if score >= _DISCOVERY_MIN_SCORE and (best is None or score > best[0]):
                    resolved = current.resolve()
                    best = (score, resolved)
                    if best_in_root is None or score > best_in_root[0]:
                        best_in_root = (score, resolved)
            if depth >= max_depth or not current.is_dir():
                continue
            try:
                children = sorted(current.iterdir(), key=lambda item: item.name.casefold())
            except (OSError, PermissionError):
                continue
            for child in children:
                if child.is_symlink():
                    continue
                if child.name in exclude_dirs:
                    continue
                if child.is_dir() or want != "dir":
                    queue.append((child, depth + 1))
        if best_in_root is not None:
            score, path = best_in_root
            return path, {
                "resolved_from": cleaned,
                "discovered": True,
                "checked": checked,
                "visits": visits,
                "score": score,
                "search_root": str(root),
            }

    if best is not None:
        score, path = best
        return path, {
            "resolved_from": cleaned,
            "discovered": True,
            "checked": checked,
            "visits": visits,
            "score": score,
            "search_root": "",
        }
    return None, {"resolved_from": cleaned, "discovered": False, "checked": checked, "visits": visits}


def _resolve_existing_path(cwd: _CwdState, raw_path: str, *, want: str = "any", raw_cwd: str = "") -> tuple[Path, dict[str, Any]]:
    direct = _resolve_path(cwd, raw_path, raw_cwd)
    if _kind_matches(direct, want):
        return direct, {"resolved_from": _clean_path_text(raw_path), "discovered": False, "checked": [str(direct)]}
    discovered, meta = _discover_existing_path(cwd, raw_path, want=want, raw_cwd=raw_cwd)
    if discovered is not None:
        return discovered, meta
    return direct, meta


def _resolve_write_target(cwd: _CwdState, raw_path: str, raw_cwd: str = "") -> tuple[Path, dict[str, Any]]:
    direct = _resolve_path(cwd, raw_path, raw_cwd)
    if direct.parent.exists():
        return direct, {"resolved_from": _clean_path_text(raw_path), "discovered": False, "checked": [str(direct.parent)]}
    raw_parent = Path(_clean_path_text(raw_path)).parent
    if str(raw_parent) not in {"", "."}:
        parent, meta = _resolve_existing_path(cwd, str(raw_parent), want="dir", raw_cwd=raw_cwd)
        if parent.exists() and parent.is_dir():
            return (parent / Path(raw_path).name).resolve(), meta
    return direct, {"resolved_from": _clean_path_text(raw_path), "discovered": False, "checked": [str(direct.parent)]}


def _run_cmd(
    cmd: str,
    cwd: Path,
    *,
    timeout: int = _TIMEOUT,
    shell_name: str = "auto",
    env_extra: dict[str, str] | None = None,
) -> tuple[str, str, int]:
    """Run a shell command, return (stdout, stderr, returncode)."""
    env = {**os.environ, "TERM": "dumb", "NO_COLOR": "1", **(env_extra or {})}
    shell_name = shell_name.strip().lower() or "auto"
    if PLATFORM == "Windows":
        if shell_name in {"auto", "powershell", "pwsh"}:
            executable = "pwsh" if shell_name == "pwsh" else "powershell"
            command: str | list[str] = [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd]
            use_shell = False
        elif shell_name == "cmd":
            command = ["cmd", "/d", "/s", "/c", cmd]
            use_shell = False
        elif shell_name == "bash":
            command = ["bash", "-lc", cmd]
            use_shell = False
        else:
            command = cmd
            use_shell = True
    elif shell_name == "bash":
        command = ["bash", "-lc", cmd]
        use_shell = False
    else:
        command = cmd
        use_shell = True
    try:
        proc = subprocess.run(
            command,
            shell=use_shell,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
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
    public = True
    description = (
        "Run real terminal commands with persistent cwd, per-command cwd/env, shell selection, longer timeouts, "
        "network-capable commands, and no command blacklist. Use for compiling, installing packages, tests, git, scripts, "
        "repo inspection, whole-PC search, and commands not covered by a dedicated tool."
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
                "description": "Max seconds to wait. Default 60, max 1800.",
            },
            "cwd": {
                "type": "string",
                "description": "Optional working directory for this command. Relative paths resolve from the shared terminal cwd.",
            },
            "shell": {
                "type": "string",
                "enum": ["auto", "powershell", "pwsh", "cmd", "bash"],
                "description": "Shell flavor. On Windows, auto uses PowerShell.",
            },
            "env": {
                "type": "object",
                "description": "Optional environment variable overrides for this command.",
            },
            "max_output": {
                "type": "integer",
                "description": "Maximum stdout/stderr characters to return. Default 24000, max 200000.",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def __init__(self, cwd: _CwdState) -> None:
        self.cwd = cwd

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("timeout", _TIMEOUT)
        args.setdefault("cwd", "")
        args.setdefault("shell", "auto")
        args.setdefault("env", {})
        args.setdefault("max_output", _MAX_OUTPUT)
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        cmd = str(args["command"]).strip()
        timeout = _bounded_timeout(args.get("timeout", _TIMEOUT))
        output_limit = _bounded_output_limit(args.get("max_output", _MAX_OUTPUT))
        raw_cwd = str(args.get("cwd", "")).strip()
        run_cwd = _resolve_base(self.cwd, raw_cwd)
        if raw_cwd and (not run_cwd.exists() or not run_cwd.is_dir()):
            run_cwd, _ = _resolve_existing_path(self.cwd, raw_cwd, want="dir")
        shell_name = str(args.get("shell", "auto")).strip().lower() or "auto"
        env_extra = _coerce_env(args.get("env", {}))

        if not run_cwd.exists() or not run_cwd.is_dir():
            return ToolResult(ok=False, summary=f"Working directory not found: {run_cwd}", data={}, error="cwd_not_found")

        # Handle `cd` specially so follow-up terminal and file tools share the new cwd.
        if cmd == "cd" or cmd.startswith("cd "):
            target = cmd[2:].strip().strip("'\"") or str(Path.home())
            if args.get("cwd"):
                self.cwd.path = run_cwd
            self.cwd.chdir(target)
            return ToolResult(
                ok=True,
                summary=f"Changed directory to {self.cwd}",
                data={"cwd": str(self.cwd), "stdout": "", "stderr": "", "returncode": 0, "shell": shell_name},
            )

        stdout, stderr, returncode = _run_cmd(cmd, run_cwd, timeout=timeout, shell_name=shell_name, env_extra=env_extra)
        out, stdout_truncated = _truncate(stdout, output_limit)
        err, stderr_truncated = _truncate(stderr, min(output_limit, 20_000))
        if stdout_truncated:
            out += f"\n\n[... stdout truncated at {output_limit} chars ...]"
        if stderr_truncated:
            err += f"\n\n[... stderr truncated at {min(output_limit, 20_000)} chars ...]"

        ok = returncode == 0
        summary = out.strip() or err.strip() or ("Done." if ok else f"Exit code {returncode}.")
        return ToolResult(
            ok=ok,
            summary=summary[:300],
            data={
                "command": cmd,
                "stdout": out,
                "stderr": err,
                "returncode": returncode,
                "cwd": str(run_cwd),
                "shell": shell_name,
                "timeout": timeout,
                "truncated": stdout_truncated or stderr_truncated,
            },
            error=None if ok else f"exit_{returncode}",
        )

    def render(self, data: dict[str, Any]) -> str:
        cmd = data.get("command", "")
        stdout = str(data.get("stdout", "")).strip()
        stderr = str(data.get("stderr", "")).strip()
        rc = data.get("returncode", 0)
        cwd = data.get("cwd", "")
        shell = data.get("shell", "auto")
        parts = [f"$ {cmd}  (cwd: {cwd}, shell: {shell})"]
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
    skip_planning_memory = True
    semantic_direct_min_score = 0.30
    semantic_direct_min_margin = 0.05
    description = (
        "Read a named local file path such as README.md, markdown, config, txt, source code, or docs. "
        "Use this to summarize setup sections, inspect, quote, or answer using current file contents. "
        "Supports line range (start_line, end_line). "
        "Handles text and binary files gracefully. If a relative path does not exist, searches likely PC roots and verifies the match."
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
            "cwd": {
                "type": "string",
                "description": "Optional base directory for relative paths.",
            },
        },
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, cwd: _CwdState) -> None:
        self.cwd = cwd

    def semantic_direct_args(self, user_message: str) -> dict[str, Any] | None:
        matches = FILE_REFERENCE_RE.findall(user_message)
        if not matches:
            return None
        path = max((item.strip("`\"'.,;:()[]{}") for item in matches), key=len, default="")
        if path and not re.search(r"[\\/]", path) and " " in path:
            path = path.split()[-1]
        return {"path": path} if path else None

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("cwd", "")
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        raw_path = str(args["path"]).strip()
        target, path_meta = _resolve_existing_path(self.cwd, raw_path, want="file", raw_cwd=str(args.get("cwd", "")).strip())

        if not target.exists():
            return ToolResult(ok=False, summary=f"File not found: {raw_path}", data=path_meta, error="file_not_found")
        if not target.is_file():
            return ToolResult(ok=False, summary=f"Not a file: {raw_path}", data=path_meta, error="not_a_file")

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
                    data={"path": str(target), "binary": True, "size_bytes": len(raw), "content": "", **path_meta},
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
                **path_meta,
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
    skip_planning_memory = True
    description = (
        "List files and directories. Shows names, sizes, types, and modification times. "
        "Optionally recursive. If a relative path does not exist, searches likely PC roots and verifies the matching directory."
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
            "cwd": {
                "type": "string",
                "description": "Optional base directory for relative paths.",
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
        args.setdefault("cwd", "")
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        raw_path = str(args.get("path", ".")).strip()
        target, path_meta = _resolve_existing_path(self.cwd, raw_path, want="dir", raw_cwd=str(args.get("cwd", "")).strip())
        recursive = bool(args.get("recursive", False))
        pattern = str(args.get("pattern", "*"))

        if not target.exists():
            return ToolResult(ok=False, summary=f"Path not found: {raw_path}", data=path_meta, error="not_found")
        if not target.is_dir():
            return ToolResult(ok=False, summary=f"Not a directory: {raw_path}", data=path_meta, error="not_a_dir")

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
                **path_meta,
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
    skip_planning_memory = True
    description = (
        "Find files by name pattern OR search file contents with a text/regex query. "
        "Like find + grep. Use for exploring codebases, locating configs, searching logs, and whole-PC file discovery."
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
            "exclude_dirs": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Directory names to skip during recursive search.",
            },
            "max_files": {
                "type": "integer",
                "description": "Maximum files to inspect before returning partial results. Default 20000.",
            },
            "max_seconds": {
                "type": "number",
                "description": "Maximum seconds to search before returning partial results. Default 8.",
            },
            "cwd": {
                "type": "string",
                "description": "Optional base directory for relative paths.",
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
        args.setdefault("exclude_dirs", sorted(_DEFAULT_EXCLUDES))
        args.setdefault("max_files", _SEARCH_MAX_FILES)
        args.setdefault("max_seconds", _SEARCH_MAX_SECONDS)
        args.setdefault("cwd", "")
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        file_pattern = str(args.get("file_pattern", "*"))
        raw_path = str(args.get("path", ".")).strip()
        case_sensitive = bool(args.get("case_sensitive", False))
        max_results = int(args.get("max_results", 50))
        max_files = max(1, min(int(args.get("max_files", _SEARCH_MAX_FILES)), 200_000))
        max_seconds = max(1.0, min(float(args.get("max_seconds", _SEARCH_MAX_SECONDS)), 60.0))
        exclude_dirs = {str(item) for item in args.get("exclude_dirs", sorted(_DEFAULT_EXCLUDES)) if str(item).strip()}

        root, path_meta = _resolve_existing_path(self.cwd, raw_path, want="dir", raw_cwd=str(args.get("cwd", "")).strip())
        if not root.exists():
            return ToolResult(ok=False, summary=f"Path not found: {raw_path}", data=path_meta, error="not_found")

        started = time.monotonic()
        deadline = started + max_seconds
        scanned = 0
        timed_out = False
        scan_capped = False

        def iter_files():
            nonlocal scanned, timed_out, scan_capped
            try:
                iterator = root.rglob(file_pattern)
                for p in iterator:
                    if time.monotonic() >= deadline:
                        timed_out = True
                        break
                    if scanned >= max_files:
                        scan_capped = True
                        break
                    try:
                        if not p.is_file():
                            continue
                        relative_parts = p.relative_to(root).parts[:-1]
                    except Exception:
                        continue
                    if any(part in exclude_dirs for part in relative_parts):
                        continue
                    scanned += 1
                    yield p
            except Exception:
                return

        # Name-only mode: no query
        if not query:
            results = []
            for p in iter_files():
                results.append({"file": str(p.relative_to(root)), "line": None, "text": None})
                if len(results) >= max_results:
                    break
            return ToolResult(
                ok=True,
                summary=f"Found {len(results)} file(s) matching '{file_pattern}' in {root}",
                data={
                    "mode": "name",
                    "root": str(root),
                    "results": results,
                    "total": len(results),
                    "scanned_files": scanned,
                    "capped": scan_capped or timed_out,
                    "timed_out": timed_out,
                    **path_meta,
                },
            )

        # Content grep mode
        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            pattern = re.compile(query, flags)
        except re.error as exc:
            return ToolResult(ok=False, summary="Invalid regex pattern.", data={}, error=str(exc))

        matches: list[dict[str, Any]] = []
        for file_path in iter_files():
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
                "scanned_files": scanned,
                "capped": len(matches) >= max_results or scan_capped or timed_out,
                "timed_out": timed_out,
                **path_meta,
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
    skip_planning_memory = True
    description = (
        "Write, overwrite, or append content to a named local file. Use this when the user asks to save text, "
        "create a note, create a simple file, update file contents, or write content to a path. "
        "Creates parent directories automatically. If a relative parent path does not exist, searches likely PC roots and verifies it."
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
            "cwd": {
                "type": "string",
                "description": "Optional base directory for relative paths.",
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def __init__(self, cwd: _CwdState) -> None:
        self.cwd = cwd

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("mode", "overwrite")
        args.setdefault("cwd", "")
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        raw_path = str(args["path"]).strip()
        content = str(args["content"])
        mode = str(args.get("mode", "overwrite"))

        target, path_meta = _resolve_write_target(self.cwd, raw_path, str(args.get("cwd", "")).strip())

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
            data={"path": str(target), "size_bytes": size, "mode": mode, "lines": content.count("\n") + 1, **path_meta},
        )

    def render(self, data: dict[str, Any]) -> str:
        path = data.get("path", "")
        size = data.get("size_bytes", 0)
        mode = data.get("mode", "overwrite")
        lines = data.get("lines", "?")
        action = {"overwrite": "Written", "append": "Appended", "create_only": "Created"}.get(mode, "Written")
        return f"{action}: {path}  ({lines} lines, {size} bytes)"


# ---------------------------------------------------------------------------
# 6. OpenPathTool
# ---------------------------------------------------------------------------

class OpenPathTool(Tool):
    name = "open_path"
    description = (
        "Open a named local file path such as README.md in the default Windows app. Launch files, folders, "
        "directories, generated artifacts, and URLs for viewing, then report whether the OS returned launch/window evidence."
    )
    safety = "write"
    semantic_direct_min_score = 0.35
    semantic_direct_min_margin = 0.05
    input_schema = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "File path, folder path, or URL to open.",
            },
            "cwd": {
                "type": "string",
                "description": "Optional base directory for relative paths.",
            },
            "wait_seconds": {
                "type": "number",
                "description": "Seconds to wait while checking for a launched app/window. Default 1.5.",
            },
        },
        "required": ["target"],
        "additionalProperties": False,
    }

    def __init__(self, cwd: _CwdState) -> None:
        self.cwd = cwd

    def semantic_direct_args(self, user_message: str) -> dict[str, Any] | None:
        url_match = re.search(r"https?://\S+", user_message)
        if url_match:
            return {"target": url_match.group(0).strip("`\"'.,;:()[]{}")}
        matches = FILE_REFERENCE_RE.findall(user_message)
        if not matches:
            return None
        target = max((item.strip("`\"'.,;:()[]{}") for item in matches), key=len, default="")
        if target and not re.search(r"[\\/]", target) and " " in target:
            target = target.split()[-1]
        return {"target": target} if target else None

    def normalize_args(self, args: dict[str, Any]) -> dict[str, Any]:
        args.setdefault("cwd", "")
        args.setdefault("wait_seconds", 1.5)
        return args

    def run(self, args: dict[str, Any]) -> ToolResult:
        raw_target = str(args["target"]).strip()
        wait_seconds = float(args.get("wait_seconds", 1.5))
        path_meta: dict[str, Any] = {}
        if not raw_target:
            return ToolResult(ok=False, summary="Open target is required.", data={}, error="missing_target")

        if is_url_target(raw_target):
            target = raw_target
            kind = "url"
        else:
            resolved, path_meta = _resolve_existing_path(self.cwd, raw_target, want="any", raw_cwd=str(args.get("cwd", "")).strip())
            if not resolved.exists():
                return ToolResult(ok=False, summary=f"Path not found: {raw_target}", data=path_meta, error="not_found")
            target = str(resolved)
            kind = "dir" if resolved.is_dir() else "file"

        opened = open_target(target, wait_seconds=wait_seconds)
        data = {
            "target": target,
            "kind": kind,
            "opened": opened.opened,
            "verified": opened.verified,
            "method": opened.method,
            "process": opened.process,
            "matching_windows": opened.matching_windows or [],
            "open_error": opened.error,
            **path_meta,
        }
        if opened.ok:
            if opened.verified:
                summary = f"Opened {kind}: {target}"
            else:
                summary = f"Open request sent for {kind}: {target}"
            return ToolResult(ok=True, summary=summary, data=data)
        return ToolResult(ok=False, summary=f"Failed to open {kind}: {target}", data=data, error=opened.error or "open_failed")

    def render(self, data: dict[str, Any]) -> str:
        target = data.get("target", "")
        kind = data.get("kind", "target")
        method = data.get("method", "")
        verified = bool(data.get("verified"))
        status = "opened and verified" if verified else "open request sent"
        lines = [f"{status}: {target}"]
        if method:
            lines.append(f"method: {method}")
        windows = data.get("matching_windows") or []
        if windows:
            lines.append("matching windows:")
            for window in windows[:5]:
                lines.append(f"- {window.get('ProcessName', window.get('process_name', 'process'))} [{window.get('Id', window.get('id', '?'))}] {window.get('MainWindowTitle', window.get('main_window_title', ''))}")
        error = str(data.get("open_error", "")).strip()
        if error:
            lines.append(f"open error: {error}")
        if kind:
            lines.append(f"kind: {kind}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Factory: register all six terminal tools
# ---------------------------------------------------------------------------

def register_terminal_tools(registry: ToolRegistry, initial_cwd: str | Path | None = None) -> _CwdState:
    """
    Register all six terminal tools sharing one cwd state.
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
    registry.register(OpenPathTool(cwd))
    return cwd
