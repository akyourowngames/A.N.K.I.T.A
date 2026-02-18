import json
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import cron_ops
from . import fs_ops
from . import music_ops
from . import realtime_search
from . import system_ops
from . import terminal_ops


TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "cron",
            "description": "Manage ANKITA cron jobs (status/list/add/update/remove/run/runs/run_due).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "job": {"type": "object"},
                    "job_id": {"type": "string"},
                    "patch": {"type": "object"},
                    "include_disabled": {"type": "boolean"},
                    "mode": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_web",
            "description": "Search the public web for real-time information.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "include_urls": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_music",
            "description": "Search music candidates on the web and rank best match to user request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "play_music",
            "description": "Play music in headless/background mode after validating best match from web search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "headless": {"type": "boolean"},
                    "stop_current": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stop_music",
            "description": "Stop currently playing headless music process.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "system_control",
            "description": "Control system-level actions like volume, media keys, and show desktop.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "amount": {"type": "integer"},
                    "path": {"type": "string"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_music",
            "description": "Get currently playing music details.",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_news",
            "description": "Search latest news headlines in real time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "max_results": {"type": "integer"},
                    "include_urls": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminate_app",
            "description": "Close/terminate a running desktop application by name.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app": {"type": "string"},
                    "force": {"type": "boolean"},
                },
                "required": ["app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "launch_app",
            "description": "Launch a desktop application or command on the local machine.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}},
                    "cwd": {"type": "string"},
                },
                "required": ["app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a terminal command in workspace and return stdout/stderr/exit code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "args": {"type": "array", "items": {"type": "string"}},
                    "cwd": {"type": "string"},
                    "timeout_ms": {"type": "integer"},
                    "use_shell": {"type": "boolean"},
                    "env": {"type": "object"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files/directories in workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "max_entries": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read UTF-8 text file.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search text in workspace files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "path": {"type": "string"},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite UTF-8 text file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace text in UTF-8 file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "replace_all": {"type": "boolean"},
                },
                "required": ["path", "old_text", "new_text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_path",
            "description": "Rename file/dir in same parent folder.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "new_name": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["path", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_path",
            "description": "Delete file/dir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "recursive": {"type": "boolean"},
                    "missing_ok": {"type": "boolean"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_path",
            "description": "Move/rename to new destination path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string"},
                    "dst": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                },
                "required": ["src", "dst"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "copy_path",
            "description": "Copy file/dir to destination path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "src": {"type": "string"},
                    "dst": {"type": "string"},
                    "overwrite": {"type": "boolean"},
                    "recursive": {"type": "boolean"},
                },
                "required": ["src", "dst"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_dir",
            "description": "Create directory path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "parents": {"type": "boolean"},
                    "exist_ok": {"type": "boolean"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_info",
            "description": "Get metadata for file/dir.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "Apply multi-file patch using *** Begin Patch / *** End Patch format.",
            "parameters": {
                "type": "object",
                "properties": {"patch": {"type": "string"}},
                "required": ["patch"],
            },
        },
    },
]


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _match(token: str, choices: List[str], threshold: float = 0.78) -> bool:
    t = token.strip().lower()
    if not t:
        return False
    return any(t == c.lower() or _sim(t, c.lower()) >= threshold for c in choices)


def _tokenize(text: str) -> List[str]:
    cleaned = text
    for ch in ",.;:!?()[]{}<>|/\\\t\r\n":
        cleaned = cleaned.replace(ch, " ")
    return [t for t in cleaned.lower().split(" ") if t]


def _extract_quoted_text(text: str) -> Optional[str]:
    for q in ('"', "'"):
        start = text.find(q)
        if start == -1:
            continue
        end = text.find(q, start + 1)
        if end == -1:
            continue
        val = text[start + 1 : end].strip()
        if val:
            return val
    return None


def _normalize_human_path(raw: str) -> str:
    value = raw.strip().strip("\"'").lower()
    aliases = ["", ".", "this project", "project", "workspace", "this workspace", "here"]
    if any(_sim(value, alias) >= 0.76 for alias in aliases):
        return "."
    return raw.strip().strip("\"'")


def _call(name: str, args: Dict[str, Any], workspace_root: Path) -> Dict[str, Any]:
    if name == "cron":
        return cron_ops.cron_action(
            workspace_root=workspace_root,
            action=str(args.get("action", "")),
            job=args.get("job") if isinstance(args.get("job"), dict) else None,
            job_id=str(args.get("job_id", "")) if args.get("job_id") is not None else None,
            patch=args.get("patch") if isinstance(args.get("patch"), dict) else None,
            include_disabled=bool(args.get("include_disabled", False)),
            mode=str(args.get("mode", "due")),
            limit=int(args.get("limit", 20)),
        )
    if name == "search_web":
        return realtime_search.search_web(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 8)),
            include_urls=bool(args.get("include_urls", False)),
        )
    if name == "search_music":
        return music_ops.search_music(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 8)),
        )
    if name == "play_music":
        return music_ops.play_music(
            workspace_root=workspace_root,
            query=str(args.get("query", "")),
            headless=bool(args.get("headless", True)),
            stop_current=bool(args.get("stop_current", True)),
        )
    if name == "stop_music":
        return music_ops.stop_music(workspace_root=workspace_root)
    if name == "current_music":
        return music_ops.current_music(workspace_root=workspace_root)
    if name == "system_control":
        return system_ops.system_control(
            action=str(args.get("action", "")),
            amount=int(args.get("amount", 1)),
            path=str(args.get("path")) if args.get("path") is not None else None,
            workspace_root=workspace_root,
        )
    if name == "search_news":
        return realtime_search.search_news(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 8)),
            include_urls=bool(args.get("include_urls", False)),
        )
    if name == "terminate_app":
        return terminal_ops.terminate_app(
            app=str(args.get("app", "")),
            force=bool(args.get("force", False)),
        )
    if name == "launch_app":
        return terminal_ops.launch_app(
            workspace_root,
            app=str(args.get("app", "")),
            args=[str(v) for v in (args.get("args") or [])] if isinstance(args.get("args"), list) else None,
            cwd=str(args.get("cwd")) if args.get("cwd") is not None else None,
        )
    if name == "run_command":
        env = args.get("env")
        env_obj = env if isinstance(env, dict) else None
        return terminal_ops.run_command(
            workspace_root,
            command=str(args.get("command", "")),
            args=[str(v) for v in (args.get("args") or [])] if isinstance(args.get("args"), list) else None,
            cwd=str(args.get("cwd")) if args.get("cwd") is not None else None,
            timeout_ms=int(args.get("timeout_ms", 20000)),
            use_shell=bool(args.get("use_shell", False)),
            env={str(k): str(v) for k, v in env_obj.items()} if env_obj is not None else None,
        )
    if name == "list_files":
        return fs_ops.list_files(workspace_root, path=str(args.get("path", ".")), max_entries=int(args.get("max_entries", 200)))
    if name == "read_file":
        return fs_ops.read_file(workspace_root, path=str(args.get("path", "")))
    if name == "search_text":
        return fs_ops.search_text(
            workspace_root,
            query=str(args.get("query", "")),
            path=str(args.get("path", ".")),
            max_results=int(args.get("max_results", 100)),
        )
    if name == "write_file":
        return fs_ops.write_file(
            workspace_root,
            path=str(args.get("path", "")),
            content=str(args.get("content", "")),
            overwrite=bool(args.get("overwrite", True)),
        )
    if name == "edit_file":
        return fs_ops.edit_file(
            workspace_root,
            path=str(args.get("path", "")),
            old_text=str(args.get("old_text", "")),
            new_text=str(args.get("new_text", "")),
            replace_all=bool(args.get("replace_all", False)),
        )
    if name == "rename_path":
        return fs_ops.rename_path(
            workspace_root,
            path=str(args.get("path", "")),
            new_name=str(args.get("new_name", "")),
            overwrite=bool(args.get("overwrite", False)),
        )
    if name == "delete_path":
        return fs_ops.delete_path(
            workspace_root,
            path=str(args.get("path", "")),
            recursive=bool(args.get("recursive", False)),
            missing_ok=bool(args.get("missing_ok", False)),
        )
    if name == "move_path":
        return fs_ops.move_path(
            workspace_root,
            src=str(args.get("src", "")),
            dst=str(args.get("dst", "")),
            overwrite=bool(args.get("overwrite", False)),
        )
    if name == "copy_path":
        return fs_ops.copy_path(
            workspace_root,
            src=str(args.get("src", "")),
            dst=str(args.get("dst", "")),
            overwrite=bool(args.get("overwrite", False)),
            recursive=bool(args.get("recursive", False)),
        )
    if name == "make_dir":
        return fs_ops.make_dir(
            workspace_root,
            path=str(args.get("path", "")),
            parents=bool(args.get("parents", True)),
            exist_ok=bool(args.get("exist_ok", True)),
        )
    if name == "file_info":
        return fs_ops.file_info(workspace_root, path=str(args.get("path", "")))
    if name == "apply_patch":
        return fs_ops.apply_patch(workspace_root, patch=str(args.get("patch", "")))
    raise ValueError(f"Unknown tool: {name}")


def execute_tool_call(tool_call: Dict[str, Any], workspace_root: Path) -> Dict[str, Any]:
    fn = tool_call.get("function", {})
    name = str(fn.get("name", ""))
    raw_args = fn.get("arguments", "{}")

    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
    except json.JSONDecodeError as err:
        raise ValueError(f"Invalid JSON args for {name}: {err}") from err

    if not isinstance(args, dict):
        raise ValueError(f"Tool args must be an object for {name}")

    result = _call(name, args, workspace_root)
    return {"ok": True, "tool": name, "result": result}


def select_tools_for_user_text(user_text: str) -> List[Dict[str, Any]]:
    tokens = _tokenize(user_text)
    chosen: List[str] = []

    has_list = any(_match(t, ["list", "show", "display", "ls"], 0.74) for t in tokens)
    has_files = any(_match(t, ["file", "files", "dir", "directory", "folder"], 0.72) for t in tokens)
    has_read = any(_match(t, ["read", "open", "cat", "summarize"], 0.72) for t in tokens)
    has_search = any(_match(t, ["search", "find", "grep", "contains"], 0.72) for t in tokens)
    has_write = any(_match(t, ["write", "create", "save"], 0.72) for t in tokens)
    has_edit = any(_match(t, ["edit", "replace", "update", "modify"], 0.72) for t in tokens)
    has_rename = any(_match(t, ["rename"], 0.72) for t in tokens)
    has_delete = any(_match(t, ["delete", "remove", "rm"], 0.72) for t in tokens)
    has_move = any(_match(t, ["move", "mv"], 0.72) for t in tokens)
    has_copy = any(_match(t, ["copy", "cp", "duplicate"], 0.72) for t in tokens)
    has_mkdir = any(_match(t, ["mkdir", "folder", "directory"], 0.72) for t in tokens) and any(
        _match(t, ["create", "make", "new"], 0.72) for t in tokens
    )
    has_info = any(_match(t, ["info", "metadata", "stat", "details"], 0.72) for t in tokens)
    has_patch = any(_match(t, ["patch", "diff", "apply", "hunk"], 0.72) for t in tokens)
    has_exec = any(_match(t, ["run", "exec", "execute", "terminal", "cmd", "command", "powershell"], 0.72) for t in tokens)
    has_launch = any(_match(t, ["open", "launch", "start"], 0.72) for t in tokens)
    has_close = any(_match(t, ["close", "kill", "stop", "terminate", "quit"], 0.72) for t in tokens)
    has_web_search = any(_match(t, ["web", "internet", "online", "google"], 0.72) for t in tokens)
    has_news_search = any(_match(t, ["news", "headline", "headlines", "latest"], 0.72) for t in tokens)
    has_search_word = any(_match(t, ["search", "find", "lookup"], 0.72) for t in tokens)
    has_cron = any(_match(t, ["cron", "schedule", "reminder", "reminders"], 0.72) for t in tokens)
    has_manage = any(_match(t, ["add", "create", "update", "remove", "run", "list", "status"], 0.72) for t in tokens)
    has_music = any(_match(t, ["music", "song", "songs", "track", "audio"], 0.72) for t in tokens)
    has_play = any(_match(t, ["play", "listen", "start"], 0.72) for t in tokens)
    has_stop = any(_match(t, ["stop", "pause", "end"], 0.72) for t in tokens)
    has_now = any(_match(t, ["current", "now", "what", "which", "name"], 0.72) for t in tokens)
    has_system = any(
        _match(
            t,
            [
                "volume",
                "mute",
                "desktop",
                "media",
                "system",
                "sound",
                "brightness",
                "wifi",
                "wireless",
                "bluetooth",
                "screenshot",
                "screen",
                "window",
            ],
            0.72,
        )
        for t in tokens
    )

    if has_cron and has_manage:
        chosen.append("cron")
    if has_music and has_play:
        chosen.append("play_music")
    if has_music and has_stop:
        chosen.append("stop_music")
    if has_music and has_now:
        chosen.append("current_music")
    if has_system:
        chosen.append("system_control")
    if has_news_search:
        chosen.append("search_news")
    if has_web_search and has_search_word:
        chosen.append("search_web")
    if has_close:
        chosen.append("terminate_app")
    if has_launch:
        chosen.append("launch_app")
    if has_exec:
        chosen.append("run_command")
    if has_list and has_files:
        chosen.append("list_files")
    if has_read:
        chosen.append("read_file")
    if has_search:
        chosen.append("search_text")
    if has_write:
        chosen.append("write_file")
    if has_edit:
        chosen.append("edit_file")
    if has_rename:
        chosen.append("rename_path")
    if has_delete:
        chosen.append("delete_path")
    if has_move:
        chosen.append("move_path")
    if has_copy:
        chosen.append("copy_path")
    if has_mkdir:
        chosen.append("make_dir")
    if has_info:
        chosen.append("file_info")
    if has_patch:
        chosen.append("apply_patch")

    if not chosen and any(_match(t, ["workspace", "project", "code", "file"], 0.72) for t in tokens):
        return TOOL_SPECS

    allow = set(chosen)
    return [spec for spec in TOOL_SPECS if spec["function"]["name"] in allow]


def _format_result(result: Dict[str, Any]) -> str:
    if isinstance(result, dict) and result.get("kind") == "music_search":
        rows = result.get("results", [])
        if not isinstance(rows, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [f"Music search for '{result.get('query', '')}'", "Top matches:"]
        for i, row in enumerate(rows[:8], 1):
            if not isinstance(row, dict):
                continue
            lines.append(f"{i}. {row.get('title', '')} (score={row.get('score', 0)})")
            lines.append(f"   {row.get('domain', '')}")
        best = result.get("best_match")
        if isinstance(best, dict):
            lines.append(f"Best match: {best.get('title', '')} (score={best.get('score', 0)})")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("kind") == "music_play":
        return (
            f"[MUSIC PLAYING]\n"
            f"title: {result.get('title', '')}\n"
            f"pid: {result.get('pid', '')}\n"
            f"score: {result.get('score', 0)}\n"
            f"headless: {bool(result.get('headless', True))}"
        )

    if isinstance(result, dict) and result.get("kind") == "music_stop":
        if bool(result.get("stopped")):
            return f"[MUSIC STOPPED] pid={result.get('pid', '')}"
        return f"[MUSIC STOP] no active player ({result.get('reason', 'unknown')})"

    if isinstance(result, dict) and result.get("kind") == "music_current":
        if not bool(result.get("playing")):
            return "No music is currently playing."
        return (
            f"[MUSIC CURRENT]\n"
            f"title: {result.get('title', '')}\n"
            f"pid: {result.get('pid', '')}\n"
            f"engine: {result.get('engine', '')}\n"
            f"launcher: {result.get('launcher', '')}"
        )

    if isinstance(result, dict) and result.get("kind") == "system_control":
        lines = [
            f"[SYSTEM] action={result.get('action', '')} ok={bool(result.get('ok'))} amount={result.get('amount', 1)}"
        ]
        if result.get("path"):
            lines.append(f"path: {result.get('path', '')}")
        lines.append(f"stdout: {result.get('stdout', '')}")
        lines.append(f"stderr: {result.get('stderr', '')}")
        return "\n".join(lines).strip()

    if isinstance(result, dict) and result.get("kind") == "cron_status":
        return (
            f"Cron status\n"
            f"- jobs_total: {result.get('jobs_total', 0)}\n"
            f"- jobs_enabled: {result.get('jobs_enabled', 0)}\n"
            f"- jobs_due_now: {result.get('jobs_due_now', 0)}"
        )

    if isinstance(result, dict) and result.get("kind") == "cron_list":
        jobs = result.get("jobs", [])
        if not isinstance(jobs, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [f"Cron jobs: {len(jobs)}"]
        for row in jobs[:40]:
            if not isinstance(row, dict):
                continue
            jid = row.get("id", "")
            name = row.get("name", "")
            enabled = bool(row.get("enabled", True))
            next_at = row.get("state", {}).get("next_run_at_ms") if isinstance(row.get("state"), dict) else None
            lines.append(f"- {jid} | {name} | enabled={enabled} | next={next_at}")
        if len(jobs) > 40:
            lines.append("... [truncated in display]")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("kind") == "cron_job":
        action = str(result.get("action", ""))
        job = result.get("job", {})
        if not isinstance(job, dict):
            return json.dumps(result, ensure_ascii=False, indent=2)
        return (
            f"Cron {action} complete\n"
            f"- id: {job.get('id', '')}\n"
            f"- name: {job.get('name', '')}\n"
            f"- enabled: {bool(job.get('enabled', True))}\n"
            f"- next_run_at_ms: {job.get('state', {}).get('next_run_at_ms') if isinstance(job.get('state'), dict) else None}"
        )

    if isinstance(result, dict) and result.get("kind") in {"cron_run", "cron_run_due", "cron_runs"}:
        if result.get("kind") == "cron_run":
            return (
                f"Cron run\n"
                f"- job_id: {result.get('job_id', '')}\n"
                f"- status: {result.get('status', '')}\n"
                f"- duration_ms: {result.get('duration_ms', '')}\n"
                f"- error: {result.get('error', '')}"
            )
        if result.get("kind") == "cron_run_due":
            ran = result.get("ran", [])
            if not isinstance(ran, list):
                return json.dumps(result, ensure_ascii=False, indent=2)
            lines = [f"Cron run_due executed: {len(ran)}"]
            for row in ran[:40]:
                if not isinstance(row, dict):
                    continue
                lines.append(f"- {row.get('job_id', '')}: {row.get('status', '')} ({row.get('duration_ms', '')} ms)")
            return "\n".join(lines)
        rows = result.get("runs", [])
        if not isinstance(rows, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [f"Cron runs for {result.get('job_id', '')}: {len(rows)}"]
        for row in rows[:40]:
            if not isinstance(row, dict):
                continue
            lines.append(f"- {row.get('ts_ms', '')}: {row.get('status', '')} {row.get('error', '')}")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("kind") in {"web_search", "news_search"}:
        rows = result.get("results", [])
        if not isinstance(rows, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        kind = str(result.get("kind"))
        engine = str(result.get("engine", ""))
        query = str(result.get("query", ""))
        include_urls = bool(result.get("include_urls", False))
        label = "News Brief" if kind == "news_search" else "Web Brief"
        lines = [f"{label} ({engine}) on '{query}'", "Key pointers:"]
        for i, row in enumerate(rows[:12], 1):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title", "")).strip()
            url = str(row.get("url", "")).strip()
            source = str(row.get("source", "")).strip()
            published = str(row.get("published", "")).strip()
            snippet = str(row.get("snippet", "")).strip()
            meta = " | ".join(x for x in [source or row.get("domain", ""), published] if x)
            lines.append(f"{i}. {title}".strip())
            if meta:
                lines.append(f"   {meta}")
            if snippet:
                lines.append(f"   {snippet}")
            if include_urls and url:
                lines.append(f"   {url}")
        if len(rows) > 12:
            lines.append("... [truncated in display]")
        if not include_urls:
            lines.append("Ask 'with links' if you want source URLs.")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("terminated") is True:
        proc = result.get("process", "")
        requested = result.get("requested", "")
        return f"[CLOSED] requested={requested} process={proc}".strip()

    if isinstance(result, dict) and result.get("launched") is True:
        app = result.get("app", "")
        pid = result.get("pid", "")
        cwd = result.get("cwd", ".")
        args = result.get("args", [])
        args_text = " ".join(str(a) for a in args) if isinstance(args, list) else ""
        return f"[LAUNCHED] {app} {args_text}\npid: {pid}\ncwd: {cwd}".strip()

    if isinstance(result, dict) and "argv" in result and "exit_code" in result:
        ok = bool(result.get("ok"))
        status = "OK" if ok else "FAILED"
        exit_code = result.get("exit_code")
        timed_out = bool(result.get("timed_out"))
        duration = result.get("duration_ms")
        cwd = result.get("cwd", ".")
        argv = result.get("argv", [])
        stdout = str(result.get("stdout", "") or "")
        stderr = str(result.get("stderr", "") or "")
        lines = [
            f"[{status}] exit={exit_code} timeout={timed_out} duration_ms={duration}",
            f"cwd: {cwd}",
            f"cmd: {' '.join(str(x) for x in argv)}",
        ]
        if stdout.strip():
            lines.append("stdout:")
            lines.append(stdout.rstrip())
        if stderr.strip():
            lines.append("stderr:")
            lines.append(stderr.rstrip())
        return "\n".join(lines)

    if isinstance(result, dict) and "path" in result and "content" in result:
        content = str(result.get("content", ""))
        head = content[:3000]
        truncated = len(content) > len(head)
        suffix = "\n... [truncated]" if truncated else ""
        return f"file: {result.get('path')}\n{head}{suffix}"

    if isinstance(result, dict) and "entries" in result:
        entries = result.get("entries", [])
        if not isinstance(entries, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [f"entries: {len(entries)} (truncated={bool(result.get('truncated'))})"]
        for item in entries[:120]:
            if not isinstance(item, dict):
                continue
            p = item.get("path", "")
            t = item.get("type", "")
            if t == "file":
                lines.append(f"FILE {p}")
            else:
                lines.append(f"DIR  {p}")
        if len(entries) > 120:
            lines.append("... [truncated in display]")
        return "\n".join(lines)

    if isinstance(result, dict) and "matches" in result:
        matches = result.get("matches", [])
        if not isinstance(matches, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [
            f"matches: {len(matches)} (truncated={bool(result.get('truncated'))}, engine={result.get('engine')})"
        ]
        lines.extend(str(m) for m in matches[:120])
        if len(matches) > 120:
            lines.append("... [truncated in display]")
        return "\n".join(lines)

    return json.dumps(result, ensure_ascii=False, indent=2)


def _first_path_after_prep(words: List[str]) -> str:
    preps = ["in", "inside", "from", "at", "on", "within", "under"]
    for i, w in enumerate(words):
        if _match(w.strip("\"'"), preps, 0.7):
            if i + 1 < len(words):
                return _normalize_human_path(" ".join(words[i + 1 :]))
            return "."
    return "."


def _looks_like_python_snippet(text: str) -> bool:
    raw = text.strip()
    lower = raw.lower()
    python_prefixes = (
        "print(",
        "import ",
        "from ",
        "def ",
        "class ",
        "for ",
        "while ",
        "if ",
        "with ",
        "x =",
        "y =",
        "z =",
    )
    if lower.startswith("python ") or lower.startswith("py "):
        return False
    if any(lower.startswith(p) for p in python_prefixes):
        return True
    if raw.endswith(")") and "(" in raw and " " not in raw.split("(", 1)[0]:
        return True
    return False


def _parse_local_intent(user_text: str, workspace_root: Path) -> Optional[Tuple[str, Dict[str, Any]]]:
    text = user_text.strip()
    tokens = _tokenize(text)
    words = text.split()
    lower_words = [w.lower().strip("\"'") for w in words]

    if not tokens:
        return None

    if tokens[0] in {"stop", "pause"} and len(tokens) == 1:
        return ("stop_music", {})

    if tokens[0] in {"stop", "pause"} and any(t in {"music", "song", "audio"} for t in tokens[1:]):
        return ("stop_music", {})

    if tokens[0] in {"play", "listen"}:
        if len(words) == 1:
            return ("__run_help", {"message": "Usage: play <song name>"})
        query = text.split(maxsplit=1)[1].strip().strip("\"'")
        if query:
            return ("play_music", {"query": query, "headless": True, "stop_current": True})

    if any(t in {"song", "music", "track"} for t in tokens) and any(
        t in {"what", "which", "name", "current", "now", "playing"} for t in tokens
    ):
        return ("current_music", {})

    has_volume = any(_match(t, ["volume", "sound", "audio", "loudness"], 0.72) for t in tokens)
    has_up = any(_match(t, ["up", "increase", "higher", "raise", "boost", "louder"], 0.72) for t in tokens)
    has_down = any(_match(t, ["down", "decrease", "lower", "reduce", "softer", "quieter"], 0.72) for t in tokens)
    has_desktop = any(_match(t, ["desktop"], 0.75) for t in tokens)
    has_show = any(_match(t, ["show", "minimize", "hide"], 0.74) for t in tokens)
    has_lock = any(_match(t, ["lock"], 0.75) for t in tokens)
    has_screen = any(_match(t, ["screen", "pc", "computer", "system"], 0.72) for t in tokens)
    has_mute = any(_match(t, ["mute", "unmute", "silent"], 0.72) for t in tokens)
    has_next = any(_match(t, ["next", "skip"], 0.72) for t in tokens)
    has_prev = any(_match(t, ["previous", "prev", "back"], 0.72) for t in tokens)
    has_media = any(_match(t, ["song", "track", "music", "audio", "media"], 0.72) for t in tokens)
    has_play_pause = any(_match(t, ["playpause", "pause", "resume", "play"], 0.72) for t in tokens) and has_media
    has_brightness = any(_match(t, ["brightness", "backlight"], 0.74) for t in tokens)
    has_wifi = any(_match(t, ["wifi", "wi-fi", "wlan", "wireless"], 0.72) for t in tokens)
    has_bluetooth = any(_match(t, ["bluetooth", "bt"], 0.72) for t in tokens)
    has_screenshot = any(_match(t, ["screenshot", "snapshot", "capture"], 0.72) for t in tokens) and any(
        _match(t, ["screen", "desktop"], 0.72) for t in tokens
    ) or any(_match(t, ["screenshot"], 0.72) for t in tokens)
    has_window = any(_match(t, ["window", "windows"], 0.72) for t in tokens)
    has_restore = any(_match(t, ["restore", "undo"], 0.72) for t in tokens)
    has_disable = any(_match(t, ["disable", "off", "turnoff", "disconnect"], 0.72) for t in tokens)
    has_enable = any(_match(t, ["enable", "on", "turnon", "connect"], 0.72) for t in tokens)

    if has_show and has_desktop:
        return ("system_control", {"action": "show_desktop", "amount": 1})
    if has_lock and has_screen:
        return ("system_control", {"action": "lock_screen", "amount": 1})
    if has_volume and has_up:
        return ("system_control", {"action": "volume_up", "amount": 6})
    if has_volume and has_down:
        return ("system_control", {"action": "volume_down", "amount": 6})
    if has_mute:
        return ("system_control", {"action": "mute_toggle", "amount": 1})
    if has_next and has_media:
        return ("system_control", {"action": "media_next", "amount": 1})
    if has_prev and has_media:
        return ("system_control", {"action": "media_prev", "amount": 1})
    if has_play_pause:
        return ("system_control", {"action": "media_play_pause", "amount": 1})
    if has_brightness and has_up:
        return ("system_control", {"action": "brightness_up", "amount": 10})
    if has_brightness and has_down:
        return ("system_control", {"action": "brightness_down", "amount": 10})
    if has_brightness:
        nums = [int(t) for t in tokens if t.isdigit()]
        if nums:
            return ("system_control", {"action": "brightness_set", "amount": max(1, min(nums[0], 100))})
    if has_wifi and has_disable:
        return ("system_control", {"action": "wifi_off", "amount": 1})
    if has_wifi and has_enable:
        return ("system_control", {"action": "wifi_on", "amount": 1})
    if has_bluetooth and has_disable:
        return ("system_control", {"action": "bluetooth_off", "amount": 1})
    if has_bluetooth and has_enable:
        return ("system_control", {"action": "bluetooth_on", "amount": 1})
    if has_screenshot:
        return ("system_control", {"action": "screenshot", "amount": 1})
    if has_window and has_show and not has_desktop:
        return ("system_control", {"action": "window_minimize_all", "amount": 1})
    if has_window and has_restore:
        return ("system_control", {"action": "window_restore_all", "amount": 1})

    if tokens[0] == "cron":
        if len(tokens) == 1:
            return ("cron", {"action": "status"})
        action = tokens[1]
        if action in {"status", "list"}:
            return ("cron", {"action": action})
        if action in {"run", "remove", "runs"}:
            if len(words) < 3:
                return ("__run_help", {"message": f"Usage: cron {action} <job_id>"})
            return ("cron", {"action": action, "job_id": words[2].strip()})
        if action == "due":
            return ("cron", {"action": "run_due"})

    if tokens[0] in {"close", "kill", "stop", "terminate", "quit"}:
        if len(words) == 1:
            return (
                "__run_help",
                {"message": "Usage: close <app>. Examples: close notepad | kill chrome"},
            )
        target_text = text.split(maxsplit=1)[1].strip().strip("\"'")
        if target_text:
            return ("terminate_app", {"app": target_text, "force": True})

    # Realtime web/news search (separate from workspace file search)
    news_tokens = {"news", "headline", "headlines", "latest"}
    web_tokens = {"web", "internet", "online", "google"}
    search_tokens = {"search", "find", "lookup"}
    link_tokens = {"link", "links", "url", "urls", "source", "sources"}
    has_news = any(t in news_tokens for t in tokens)
    has_web = any(t in web_tokens for t in tokens)
    has_search = any(t in search_tokens for t in tokens)
    wants_links = any(t in link_tokens for t in tokens)
    if has_news:
        query = _extract_quoted_text(text)
        if not query:
            filtered = [w for w in words if w.lower().strip("\"'") not in news_tokens | search_tokens | {"for", "about"}]
            query = " ".join(filtered).strip()
        query = query or "latest technology news"
        return ("search_news", {"query": query, "max_results": 8, "include_urls": wants_links})
    if has_web and has_search:
        query = _extract_quoted_text(text)
        if not query:
            filtered = [w for w in words if w.lower().strip("\"'") not in web_tokens | search_tokens | {"for", "about"}]
            query = " ".join(filtered).strip()
        if query:
            return ("search_web", {"query": query, "max_results": 8, "include_urls": wants_links})

    if tokens[0] in {"open", "launch", "start"}:
        if len(words) == 1:
            return (
                "__run_help",
                {"message": "Usage: open <app|file>. Examples: open notepad | open README.md"},
            )
        target_text = text.split(maxsplit=1)[1].strip().strip("\"'")
        if target_text:
            normalized_path = _normalize_human_path(target_text)
            try:
                resolved = fs_ops.resolve_safe_path(workspace_root, normalized_path)
                if resolved.exists() and resolved.is_file():
                    return ("read_file", {"path": normalized_path})
            except Exception:
                pass
            # If user mentions an extension-like token, prefer file read attempt.
            if "." in Path(normalized_path).name and " " not in Path(normalized_path).name:
                return ("read_file", {"path": normalized_path})
            return ("launch_app", {"app": target_text, "args": []})

    if tokens[0] in {"run", "exec", "execute", "cmd"}:
        if len(words) == 1:
            return (
                "__run_help",
                {
                    "message": "Usage: run <command>. Examples: run dir | run python -c \"print('hi')\" | run Get-ChildItem -Force",
                },
            )
        command_text = text.split(maxsplit=1)[1].strip()
        if command_text:
            if _looks_like_python_snippet(command_text):
                return (
                    "run_command",
                    {
                        "command": sys.executable,
                        "args": ["-c", command_text],
                        "use_shell": False,
                        "timeout_ms": 20000,
                    },
                )
            return ("run_command", {"command": command_text, "use_shell": True, "timeout_ms": 20000})

    has_list = any(_match(t, ["list", "show", "display", "ls"], 0.74) for t in tokens)
    has_files = any(_match(t, ["file", "files", "dir", "directory", "folder", "workspace", "project"], 0.72) for t in tokens)
    if has_list and has_files:
        return ("list_files", {"path": _first_path_after_prep(words), "max_entries": 300})

    if tokens[0] in {"read", "open", "cat"} and len(words) > 1:
        return ("read_file", {"path": _normalize_human_path(" ".join(words[1:]))})

    has_search = any(_match(t, ["search", "find", "grep", "contains", "lookup"], 0.72) for t in tokens)
    if has_search:
        query = _extract_quoted_text(text)
        path = _first_path_after_prep(words)
        if not query:
            idx = 0
            for i, w in enumerate(lower_words):
                if _match(w, ["search", "find", "grep", "contains", "lookup"], 0.72):
                    idx = i
                    break
            end = len(words)
            for i, w in enumerate(lower_words):
                if i <= idx:
                    continue
                if _match(w, ["in", "inside", "within", "under"], 0.7):
                    end = i
                    break
            query = " ".join(words[idx + 1 : end]).strip().strip("\"'")
        if query:
            if query.lower().startswith("for "):
                query = query[4:].strip()
            scope_tokens = {
                "workspace",
                "project",
                "repo",
                "repository",
                "codebase",
                "file",
                "files",
                "folder",
                "directory",
                "path",
                "here",
            }
            has_local_scope = any(t in scope_tokens for t in tokens)
            if has_local_scope:
                return ("search_text", {"query": query, "path": path, "max_results": 100})
            wants_links = any(t in {"link", "links", "url", "urls", "source", "sources"} for t in tokens)
            return ("search_web", {"query": query, "max_results": 8, "include_urls": wants_links})

    return None


def try_direct_local_command(user_text: str, workspace_root: Path) -> Optional[str]:
    parsed = _parse_local_intent(user_text, workspace_root)
    if not parsed:
        return None
    name, args = parsed
    if name == "__run_help":
        return str(args.get("message", "Usage: run <command>"))
    return _format_result(_call(name, args, workspace_root))


def compact_messages(messages: List[Dict[str, Any]], keep_tail: int = 8) -> List[Dict[str, Any]]:
    if len(messages) <= keep_tail + 1:
        return messages
    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    tail = messages[-keep_tail:]
    return ([system_msg] if system_msg else []) + tail
