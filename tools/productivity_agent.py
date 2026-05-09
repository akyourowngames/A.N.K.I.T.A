from __future__ import annotations

import json
import os
import subprocess
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any

from tools.registry import ToolInputError, optional_text, require_text


DEFAULT_CONFIG_PATH = Path("config/productivity_agent.json")


def productivity_status(_params: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_config()
    gh = github_status(config)
    google = google_status(config)
    return {
        "summary": f"{config.get('agent_name', 'Productivity Agent')} ready.",
        "config_path": str(config_path()),
        "github": gh,
        "google": google,
    }


def productivity_config(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    if operation == "get":
        return {"summary": f"Productivity config: {config_path()}", "config": config}
    if operation == "update":
        values = params.get("values", {})
        if not isinstance(values, dict):
            raise ToolInputError("values must be an object")
        merge_config(config, values)
        save_config(config)
        return {"summary": f"Updated productivity config: {config_path()}", "config": config}
    raise ToolInputError(f"Unsupported productivity config operation: {operation}")


def github_manage(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    repo = optional_text(params, "repo") or optional_nested_text(config, ["github", "default_repo"])
    limit = bounded_int(params.get("limit"), 1, 100, bounded_int(nested_value(config, ["github", "default_limit"]), 1, 100, 20))
    state = optional_text(params, "state") or "open"
    gh = optional_nested_text(config, ["github", "gh_executable"]) or "gh"

    args: list[str]
    if operation == "auth_status":
        args = [gh, "auth", "status"]
    elif operation == "repo_view":
        args = [gh, "repo", "view"]
        append_repo(args, repo)
        args.extend(["--json", "nameWithOwner,description,url,visibility,defaultBranchRef,isPrivate"])
    elif operation == "issue_list":
        args = [gh, "issue", "list", "--state", state, "--limit", str(limit), "--json", "number,title,state,url,updatedAt,author"]
        append_repo(args, repo)
    elif operation == "pr_list":
        args = [gh, "pr", "list", "--state", state, "--limit", str(limit), "--json", "number,title,state,url,updatedAt,author,headRefName,baseRefName"]
        append_repo(args, repo)
    elif operation == "workflow_runs":
        args = [gh, "run", "list", "--limit", str(limit), "--json", "databaseId,displayTitle,status,conclusion,createdAt,url"]
        append_repo(args, repo)
    elif operation == "notifications":
        args = [gh, "api", f"notifications?per_page={limit}"]
    elif operation == "create_issue":
        title = require_text(params, "title")
        body = optional_text(params, "body")
        args = [gh, "issue", "create", "--title", title]
        if body:
            args.extend(["--body", body])
        append_repo(args, repo)
    else:
        raise ToolInputError(f"Unsupported GitHub operation: {operation}")

    result = run_command(args, bounded_int(params.get("timeout_seconds"), 5, 120, 30), config)
    parsed = parse_json_output(result["stdout"])
    return {
        "summary": f"GitHub operation {operation} finished with exit code {result['exit_code']}.",
        "operation": operation,
        "repo": repo,
        "command": safe_command(args),
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "data": parsed,
    }


def gmail_manage(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    gmail = nested_dict(config, ["gmail"])
    open_browser = bool(params.get("open_browser", False))
    dry_run = dry_run_enabled(config)
    url = ""
    if operation == "open_inbox":
        url = optional_nested_text(gmail, ["inbox_url"]) or optional_nested_text(gmail, ["base_url"])
    elif operation == "search":
        query = require_text(params, "query")
        url = build_url(optional_nested_text(gmail, ["search_url_template"]), {"query": query})
    elif operation == "compose":
        values = {
            "to": optional_text(params, "to"),
            "subject": optional_text(params, "subject"),
            "body": optional_text(params, "body"),
        }
        url = build_url(optional_nested_text(gmail, ["compose_url_template"]), values)
    else:
        raise ToolInputError(f"Unsupported Gmail operation: {operation}")
    opened = open_url_if_requested(url, open_browser, dry_run)
    return {
        "summary": f"Gmail operation {operation} prepared.",
        "operation": operation,
        "url": url,
        "opened": opened,
        "dry_run": dry_run,
    }


def calendar_manage(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    calendar = nested_dict(config, ["calendar"])
    open_browser = bool(params.get("open_browser", False))
    dry_run = dry_run_enabled(config)
    url = ""
    if operation == "open":
        url = optional_nested_text(calendar, ["base_url"])
    elif operation == "create_event":
        values = {
            "title": optional_text(params, "title"),
            "details": optional_text(params, "details"),
            "location": optional_text(params, "location"),
            "dates": event_dates(params),
        }
        url = build_url(optional_nested_text(calendar, ["event_url_template"]), values)
    else:
        raise ToolInputError(f"Unsupported Calendar operation: {operation}")
    opened = open_url_if_requested(url, open_browser, dry_run)
    return {
        "summary": f"Calendar operation {operation} prepared.",
        "operation": operation,
        "url": url,
        "opened": opened,
        "dry_run": dry_run,
    }


def config_path() -> Path:
    value = os.environ.get("JARVIS_PRODUCTIVITY_CONFIG", "").strip()
    return Path(value) if value else DEFAULT_CONFIG_PATH


def load_config() -> dict[str, Any]:
    path = config_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            ensure_config_shape(data)
            return data
    data = default_config()
    save_config(data)
    return data


def save_config(config: dict[str, Any]) -> None:
    ensure_config_shape(config)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def default_config() -> dict[str, Any]:
    return {
        "agent_name": "Codex Productivity Agent",
        "dry_run": False,
        "max_output_chars": 6000,
        "github": {
            "gh_executable": "gh",
            "default_repo": "",
            "default_limit": 20,
        },
        "gmail": {
            "base_url": "https://mail.google.com/mail/u/0/",
            "inbox_url": "https://mail.google.com/mail/u/0/#inbox",
            "search_url_template": "https://mail.google.com/mail/u/0/#search/{query}",
            "compose_url_template": "https://mail.google.com/mail/?view=cm&fs=1&to={to}&su={subject}&body={body}",
        },
        "calendar": {
            "base_url": "https://calendar.google.com/calendar/u/0/r",
            "event_url_template": "https://calendar.google.com/calendar/render?action=TEMPLATE&text={title}&dates={dates}&details={details}&location={location}",
        },
    }


def ensure_config_shape(config: dict[str, Any]) -> None:
    fallback = default_config()
    for key, value in fallback.items():
        if key not in config:
            config[key] = value
    for section in ("github", "gmail", "calendar"):
        if not isinstance(config.get(section), dict):
            config[section] = fallback[section]
        else:
            for key, value in fallback[section].items():
                config[section].setdefault(key, value)


def merge_config(config: dict[str, Any], values: dict[str, Any]) -> None:
    allowed_sections = {"github", "gmail", "calendar"}
    for key, value in values.items():
        if key in {"agent_name", "dry_run", "max_output_chars"}:
            config[key] = value
            continue
        if key in allowed_sections and isinstance(value, dict):
            target = config.setdefault(key, {})
            if isinstance(target, dict):
                for child_key, child_value in value.items():
                    if isinstance(child_key, str):
                        target[child_key] = child_value
    ensure_config_shape(config)


def github_status(config: dict[str, Any]) -> dict[str, Any]:
    gh = optional_nested_text(config, ["github", "gh_executable"]) or "gh"
    version = run_command([gh, "--version"], 10, config, allow_missing=True)
    auth = run_command([gh, "auth", "status"], 20, config, allow_missing=True)
    return {
        "available": version["exit_code"] == 0,
        "authenticated": auth["exit_code"] == 0,
        "version_output": version["stdout"],
        "auth_output": auth["stdout"] or auth["stderr"],
    }


def google_status(config: dict[str, Any]) -> dict[str, Any]:
    env_names = ["GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_OAUTH_CLIENT_SECRETS", "GMAIL_TOKEN_FILE", "GOOGLE_CALENDAR_TOKEN_FILE"]
    configured_env = {name: bool(os.environ.get(name, "").strip()) for name in env_names}
    return {
        "gmail_url": optional_nested_text(config, ["gmail", "base_url"]),
        "calendar_url": optional_nested_text(config, ["calendar", "base_url"]),
        "credential_env": configured_env,
    }


def run_command(args: list[str], timeout_seconds: int, config: dict[str, Any], allow_missing: bool = False) -> dict[str, Any]:
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout_seconds)
    except FileNotFoundError as error:
        if allow_missing:
            return {"exit_code": 127, "stdout": "", "stderr": str(error)}
        raise ToolInputError(f"Command not found: {args[0]}") from error
    except subprocess.TimeoutExpired as error:
        raise ToolInputError(f"Command timed out: {safe_command(args)}") from error
    return {
        "exit_code": completed.returncode,
        "stdout": clip_output(redact_output(completed.stdout), config),
        "stderr": clip_output(redact_output(completed.stderr), config),
    }


def append_repo(args: list[str], repo: str) -> None:
    if repo:
        args.extend(["--repo", repo])


def safe_command(args: list[str]) -> list[str]:
    return [redact_argument(arg) for arg in args]


def redact_argument(value: str) -> str:
    lowered = value.lower()
    if "token" in lowered or "authorization" in lowered:
        return "<redacted>"
    return value


def redact_output(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith("- token:") or stripped.startswith("token:"):
            head = line.split(":", 1)[0]
            lines.append(f"{head}: <redacted>")
        else:
            lines.append(line)
    return "\n".join(lines).strip()


def clip_output(text: str, config: dict[str, Any]) -> str:
    limit = bounded_int(config.get("max_output_chars"), 500, 50000, 6000)
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def parse_json_output(text: str) -> Any:
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def event_dates(params: dict[str, Any]) -> str:
    dates = optional_text(params, "dates")
    if dates:
        return dates
    start = optional_text(params, "start")
    end = optional_text(params, "end")
    if start and end:
        return f"{compact_calendar_time(start)}/{compact_calendar_time(end)}"
    return ""


def compact_calendar_time(value: str) -> str:
    keep = []
    for char in value:
        if char.isalnum():
            keep.append(char)
    return "".join(keep)


def build_url(template: str, values: dict[str, str]) -> str:
    if not template:
        raise ToolInputError("URL template is not configured")
    url = template
    for key, value in values.items():
        url = url.replace("{" + key + "}", urllib.parse.quote(value, safe=""))
    return url


def open_url_if_requested(url: str, open_browser: bool, dry_run: bool) -> bool:
    if not open_browser or dry_run:
        return False
    return bool(webbrowser.open(url))


def dry_run_enabled(config: dict[str, Any]) -> bool:
    env_value = os.environ.get("JARVIS_PRODUCTIVITY_DRY_RUN", "").strip().lower()
    if env_value:
        return env_value in {"1", "true", "yes", "on"}
    return bool(config.get("dry_run", False))


def nested_value(data: dict[str, Any], keys: list[str]) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def nested_dict(data: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    value = nested_value(data, keys)
    return value if isinstance(value, dict) else {}


def optional_nested_text(data: dict[str, Any], keys: list[str]) -> str:
    value = nested_value(data, keys)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def bounded_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))
