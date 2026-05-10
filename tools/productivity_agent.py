from __future__ import annotations

import json
import os
import subprocess
import unicodedata
import urllib.parse
import webbrowser
from base64 import urlsafe_b64decode, urlsafe_b64encode
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from tools.google_auth import env_or_config, google_service, token_status
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
    if operation == "auth_status":
        return gmail_auth_status(config)
    if operation == "auth_login":
        service = gmail_service(config, allow_interactive=True)
        profile = service.users().getProfile(userId="me").execute()
        return {"summary": "Gmail OAuth is ready.", "operation": operation, "profile": profile}
    if operation == "list_messages":
        readiness = gmail_auth_status(config)
        if not readiness.get("ready") and not bool(params.get("allow_interactive_auth", False)):
            return google_not_connected_result("Gmail", readiness, operation, "messages")
        service = gmail_service(config, allow_interactive=bool(params.get("allow_interactive_auth", False)))
        query = optional_text(params, "query")
        limit = bounded_int(params.get("limit"), 1, 50, bounded_int(nested_value(gmail, ["default_limit"]), 1, 50, 10))
        response = service.users().messages().list(userId="me", q=query, maxResults=limit).execute()
        messages = []
        for item in response.get("messages", []) if isinstance(response, dict) else []:
            message_id = item.get("id") if isinstance(item, dict) else ""
            if not message_id:
                continue
            messages.append(gmail_message_metadata(service, message_id))
        return {
            "summary": f"Gmail returned {len(messages)} message(s).",
            "operation": operation,
            "query": query,
            "messages": messages,
            "result_size_estimate": response.get("resultSizeEstimate") if isinstance(response, dict) else None,
        }
    if operation == "read_message":
        message_id = require_text(params, "message_id")
        readiness = gmail_auth_status(config)
        if not readiness.get("ready") and not bool(params.get("allow_interactive_auth", False)):
            result = google_not_connected_result("Gmail", readiness, operation, "messages")
            result["message_id"] = message_id
            return result
        service = gmail_service(config, allow_interactive=bool(params.get("allow_interactive_auth", False)))
        message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        return {
            "summary": "Gmail message read.",
            "operation": operation,
            "message": gmail_message_detail(message),
        }
    if operation in {"send", "draft"}:
        message = build_email_message(params)
        raw = urlsafe_b64encode(message.as_bytes()).decode("ascii")
        if dry_run_enabled(config):
            summary = "No Gmail message was sent; dry-run prepared the email only."
            if operation == "draft":
                summary = "No Gmail draft was created; dry-run prepared the draft content only."
            return {
                "summary": summary,
                "safe_user_output": f"No external action happened. Prepared only: to {optional_text(params, 'to')}, subject {optional_text(params, 'subject')}.",
                "operation": operation,
                "dry_run": True,
                "action_completed": False,
                "external_state_changed": False,
                "dry_run_note": "No Gmail message or draft exists in Gmail from this dry-run result.",
                "to": optional_text(params, "to"),
                "subject": optional_text(params, "subject"),
                "body": optional_text(params, "body"),
            }
        readiness = gmail_auth_status(config)
        if not readiness.get("ready") and not bool(params.get("allow_interactive_auth", False)):
            result = google_not_connected_result("Gmail", readiness, operation, "messages")
            result["action_completed"] = False
            result["external_state_changed"] = False
            return result
        service = gmail_service(config, allow_interactive=bool(params.get("allow_interactive_auth", False)))
        if operation == "send":
            result = service.users().messages().send(userId="me", body={"raw": raw}).execute()
        else:
            result = service.users().drafts().create(userId="me", body={"message": {"raw": raw}}).execute()
        return {
            "summary": f"Gmail {operation} completed.",
            "operation": operation,
            "dry_run": False,
            "result": result,
        }
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
        "action_completed": False,
        "external_state_changed": False,
    }


def gmail_api(params: dict[str, Any]) -> dict[str, Any]:
    return gmail_manage(params)


def calendar_manage(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    calendar = nested_dict(config, ["calendar"])
    if operation == "auth_status":
        return calendar_auth_status(config)
    if operation == "auth_login":
        service = calendar_service(config, allow_interactive=True)
        calendar_id = optional_text(params, "calendar_id") or optional_nested_text(calendar, ["default_calendar_id"]) or "primary"
        result = service.calendars().get(calendarId=calendar_id).execute()
        return {"summary": "Google Calendar OAuth is ready.", "operation": operation, "calendar": result}
    if operation == "list_events":
        readiness = calendar_auth_status(config)
        if not readiness.get("ready") and not bool(params.get("allow_interactive_auth", False)):
            return google_not_connected_result("Google Calendar", readiness, operation, "events")
        service = calendar_service(config, allow_interactive=bool(params.get("allow_interactive_auth", False)))
        calendar_id = optional_text(params, "calendar_id") or optional_nested_text(calendar, ["default_calendar_id"]) or "primary"
        limit = bounded_int(params.get("limit"), 1, 50, bounded_int(nested_value(calendar, ["default_limit"]), 1, 50, 10))
        request = service.events().list(
            calendarId=calendar_id,
            maxResults=limit,
            singleEvents=True,
            orderBy="startTime",
            timeMin=optional_text(params, "time_min") or None,
            timeMax=optional_text(params, "time_max") or None,
        )
        result = request.execute()
        events = [calendar_event_summary(item) for item in result.get("items", [])] if isinstance(result, dict) else []
        return {
            "summary": f"Google Calendar returned {len(events)} event(s).",
            "operation": operation,
            "calendar_id": calendar_id,
            "events": events,
        }
    if operation == "get_event":
        event_id = require_text(params, "event_id")
        readiness = calendar_auth_status(config)
        if not readiness.get("ready") and not bool(params.get("allow_interactive_auth", False)):
            result = google_not_connected_result("Google Calendar", readiness, operation, "events")
            result["event_id"] = event_id
            return result
        service = calendar_service(config, allow_interactive=bool(params.get("allow_interactive_auth", False)))
        calendar_id = optional_text(params, "calendar_id") or optional_nested_text(calendar, ["default_calendar_id"]) or "primary"
        result = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        return {
            "summary": "Google Calendar event read.",
            "operation": operation,
            "calendar_id": calendar_id,
            "event": calendar_event_summary(result),
        }
    if operation == "api_create_event":
        if dry_run_enabled(config):
            return {
                "summary": "No Google Calendar event was created; dry-run prepared the event only.",
                "safe_user_output": f"No external action happened. Prepared only: {require_text(params, 'title')} from {require_text(params, 'start')} to {require_text(params, 'end')}.",
                "operation": operation,
                "dry_run": True,
                "action_completed": False,
                "external_state_changed": False,
                "dry_run_note": "No Google Calendar event exists from this dry-run result.",
                "event": calendar_event_body(params, config),
            }
        readiness = calendar_auth_status(config)
        if not readiness.get("ready") and not bool(params.get("allow_interactive_auth", False)):
            result = google_not_connected_result("Google Calendar", readiness, operation, "events")
            result["action_completed"] = False
            result["external_state_changed"] = False
            return result
        service = calendar_service(config, allow_interactive=bool(params.get("allow_interactive_auth", False)))
        calendar_id = optional_text(params, "calendar_id") or optional_nested_text(calendar, ["default_calendar_id"]) or "primary"
        result = service.events().insert(calendarId=calendar_id, body=calendar_event_body(params, config)).execute()
        return {
            "summary": "Google Calendar event created.",
            "operation": operation,
            "dry_run": False,
            "calendar_id": calendar_id,
            "event": calendar_event_summary(result),
        }
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
        "action_completed": False,
        "external_state_changed": False,
    }


def calendar_api(params: dict[str, Any]) -> dict[str, Any]:
    return calendar_manage(params)


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
            "client_secrets_file": "config/google/client_secret.json",
            "token_file": "media/google/gmail_token.json",
            "scopes": [
                "https://www.googleapis.com/auth/gmail.readonly",
                "https://www.googleapis.com/auth/gmail.send",
                "https://www.googleapis.com/auth/gmail.compose"
            ],
            "default_limit": 10,
        },
        "calendar": {
            "base_url": "https://calendar.google.com/calendar/u/0/r",
            "event_url_template": "https://calendar.google.com/calendar/render?action=TEMPLATE&text={title}&dates={dates}&details={details}&location={location}",
            "client_secrets_file": "config/google/client_secret.json",
            "token_file": "media/google/calendar_token.json",
            "scopes": [
                "https://www.googleapis.com/auth/calendar.events",
                "https://www.googleapis.com/auth/calendar.readonly"
            ],
            "default_calendar_id": "primary",
            "default_limit": 10,
            "timezone": "Asia/Kolkata",
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
        "credential_env": configured_env,
        "gmail_api": gmail_auth_status(config),
        "calendar_api": calendar_auth_status(config),
    }


def gmail_auth_status(config: dict[str, Any]) -> dict[str, Any]:
    gmail = nested_dict(config, ["gmail"])
    status = token_status(gmail_token_file(gmail), google_client_secrets_file(gmail))
    ready = bool(status.get("token_exists")) and bool(status.get("client_secrets_exists"))
    status["ready"] = ready
    status["status_text"] = google_auth_status_text("Gmail", status)
    status["summary"] = status["status_text"]
    return status


def calendar_auth_status(config: dict[str, Any]) -> dict[str, Any]:
    calendar = nested_dict(config, ["calendar"])
    status = token_status(calendar_token_file(calendar), google_client_secrets_file(calendar))
    ready = bool(status.get("token_exists")) and bool(status.get("client_secrets_exists"))
    status["ready"] = ready
    status["status_text"] = google_auth_status_text("Google Calendar", status)
    status["summary"] = status["status_text"]
    return status


def google_auth_status_text(label: str, status: dict[str, Any]) -> str:
    deps = status.get("dependencies") if isinstance(status.get("dependencies"), dict) else {}
    missing_deps = [name for name, available in deps.items() if not available]
    if missing_deps:
        return f"{label} is not ready. Missing Google API libraries: {', '.join(missing_deps)}."
    if status.get("ready"):
        return f"{label} is connected and ready for API calls."
    missing = []
    if not status.get("client_secrets_exists"):
        missing.append("client secrets file")
    if not status.get("token_exists"):
        missing.append("OAuth token")
    missing_text = ", ".join(missing) if missing else "OAuth readiness"
    return f"{label} is not connected yet. Missing: {missing_text}."


def google_not_connected_result(label: str, readiness: dict[str, Any], operation: str, empty_key: str) -> dict[str, Any]:
    status_text = str(readiness.get("status_text") or readiness.get("summary") or f"{label} is not connected yet.")
    return {
        "summary": status_text,
        "status_text": status_text,
        "safe_user_output": status_text,
        "ready": False,
        "operation": operation,
        empty_key: [],
    }


def gmail_service(config: dict[str, Any], allow_interactive: bool = False) -> Any:
    gmail = nested_dict(config, ["gmail"])
    return google_service(
        "gmail",
        "v1",
        text_list(gmail.get("scopes")),
        gmail_token_file(gmail),
        google_client_secrets_file(gmail),
        allow_interactive,
    )


def calendar_service(config: dict[str, Any], allow_interactive: bool = False) -> Any:
    calendar = nested_dict(config, ["calendar"])
    return google_service(
        "calendar",
        "v3",
        text_list(calendar.get("scopes")),
        calendar_token_file(calendar),
        google_client_secrets_file(calendar),
        allow_interactive,
    )


def google_client_secrets_file(section: dict[str, Any]) -> str:
    return env_or_config("GOOGLE_OAUTH_CLIENT_SECRETS", optional_nested_text(section, ["client_secrets_file"]), "config/google/client_secret.json")


def gmail_token_file(gmail: dict[str, Any]) -> str:
    return env_or_config("GMAIL_TOKEN_FILE", optional_nested_text(gmail, ["token_file"]), "media/google/gmail_token.json")


def calendar_token_file(calendar: dict[str, Any]) -> str:
    return env_or_config("GOOGLE_CALENDAR_TOKEN_FILE", optional_nested_text(calendar, ["token_file"]), "media/google/calendar_token.json")


def gmail_message_metadata(service: Any, message_id: str) -> dict[str, Any]:
    message = service.users().messages().get(userId="me", id=message_id, format="metadata", metadataHeaders=["From", "To", "Subject", "Date"]).execute()
    return {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "snippet": display_text(message.get("snippet")),
        "headers": message_headers(message),
    }


def gmail_message_detail(message: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "snippet": display_text(message.get("snippet")),
        "headers": message_headers(message),
        "body_text": display_text(gmail_body_text(message)),
    }


def message_headers(message: dict[str, Any]) -> dict[str, str]:
    payload = message.get("payload", {}) if isinstance(message, dict) else {}
    headers = payload.get("headers", []) if isinstance(payload, dict) else []
    result: dict[str, str] = {}
    for item in headers:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if isinstance(name, str) and isinstance(value, str):
            result[name] = display_text(value)
    return result


def display_text(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = urllib.parse.unquote(html_unescape(value))
    cleaned: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category in {"Cc", "Cf", "Cs", "So"}:
            cleaned.append(" ")
            continue
        cleaned.append(char)
    return " ".join("".join(cleaned).split())


def html_unescape(value: str) -> str:
    import html

    return html.unescape(value)


def gmail_body_text(message: dict[str, Any]) -> str:
    payload = message.get("payload", {}) if isinstance(message, dict) else {}
    chunks: list[str] = []
    collect_gmail_text(payload, chunks)
    return "\n".join(chunk for chunk in chunks if chunk.strip()).strip()


def collect_gmail_text(part: Any, chunks: list[str]) -> None:
    if not isinstance(part, dict):
        return
    mime_type = str(part.get("mimeType", ""))
    body = part.get("body", {})
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, str) and (mime_type.startswith("text/plain") or not part.get("parts")):
        chunks.append(decode_urlsafe_text(data))
    parts = part.get("parts", [])
    if isinstance(parts, list):
        for child in parts:
            collect_gmail_text(child, chunks)


def decode_urlsafe_text(value: str) -> str:
    padded = value + ("=" * ((4 - len(value) % 4) % 4))
    try:
        return urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="replace")
    except Exception:
        return ""


def build_email_message(params: dict[str, Any]) -> EmailMessage:
    message = EmailMessage()
    message["To"] = require_text(params, "to")
    subject = optional_text(params, "subject")
    if subject:
        message["Subject"] = subject
    cc = optional_text(params, "cc")
    if cc:
        message["Cc"] = cc
    bcc = optional_text(params, "bcc")
    if bcc:
        message["Bcc"] = bcc
    message.set_content(optional_text(params, "body"))
    return message


def calendar_event_body(params: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    calendar = nested_dict(config, ["calendar"])
    timezone = optional_text(params, "timezone") or optional_nested_text(calendar, ["timezone"]) or "UTC"
    body: dict[str, Any] = {
        "summary": require_text(params, "title"),
    }
    details = optional_text(params, "details")
    if details:
        body["description"] = details
    location = optional_text(params, "location")
    if location:
        body["location"] = location
    start = require_text(params, "start")
    end = require_text(params, "end")
    body["start"] = calendar_time_value(start, timezone)
    body["end"] = calendar_time_value(end, timezone)
    return body


def calendar_time_value(value: str, timezone: str) -> dict[str, str]:
    if len(value) == 10 and value.count("-") == 2:
        return {"date": value}
    return {"dateTime": value, "timeZone": timezone}


def calendar_event_summary(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": event.get("id"),
        "summary": event.get("summary"),
        "status": event.get("status"),
        "html_link": event.get("htmlLink"),
        "start": event.get("start"),
        "end": event.get("end"),
        "location": event.get("location"),
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


def text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def bounded_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))
