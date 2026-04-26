from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from jakata_agent.services.google_workspace import GoogleServiceStatus, GoogleWorkspaceConnector
from jakata_agent.services.sync_store import ExternalServiceStore, ServiceItem
from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.registry import ToolRegistry


class GoogleConnectorLike(Protocol):
    def status(self) -> GoogleServiceStatus: ...
    def authorize(self, *, interactive: bool = False) -> GoogleServiceStatus: ...
    def upcoming_range(self, *, days: int): ...
    def today_range(self): ...
    def list_calendar_events(self, *, time_min, time_max, max_results: int = 10, calendar_id: str = "primary") -> list[ServiceItem]: ...
    def search_gmail(self, *, query: str, max_results: int = 10) -> list[ServiceItem]: ...
    def unread_gmail(self, *, max_results: int = 10) -> list[ServiceItem]: ...
    def create_gmail_draft(self, *, to: str, subject: str, body: str, thread_id: str = "") -> dict[str, Any]: ...


def _status_dict(status: GoogleServiceStatus) -> dict[str, Any]:
    return {
        "configured": status.configured,
        "authorized": status.authorized,
        "credentials_path": status.credentials_path,
        "token_path": status.token_path,
        "message": status.message,
    }


def _items_to_dicts(items: list[ServiceItem]) -> list[dict[str, Any]]:
    return [
        {
            "provider": item.provider,
            "item_type": item.item_type,
            "external_id": item.external_id,
            "title": item.title,
            "text": item.text,
            "start_at": item.start_at,
            "end_at": item.end_at,
            "url": item.url,
            "labels": item.labels or [],
            "raw": item.raw or {},
        }
        for item in items
    ]


def _render_items(items: list[dict[str, Any]], *, empty: str) -> str:
    if not items:
        return empty
    lines: list[str] = []
    for item in items:
        when = str(item.get("start_at", "")).strip()
        title = str(item.get("title", "")).strip()
        text = str(item.get("text", "")).strip()
        prefix = f"{when}: " if when else ""
        suffix = f" - {text[:160]}" if text else ""
        lines.append(f"- {prefix}{title}{suffix}")
    return "\n".join(lines)


class ExternalServicesStatusTool(Tool):
    name = "external_services_status"
    semantic_direct = True
    semantic_direct_min_score = 0.42
    semantic_direct_min_margin = 0.05
    description = "Check Google Workspace integration health for Calendar, Gmail, OAuth authorization, and the local external-service sync cache."
    input_schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    safety = "read_only"

    def __init__(self, *, google: GoogleConnectorLike, store: ExternalServiceStore) -> None:
        self.google = google
        self.store = store

    def run(self, args: dict[str, Any]) -> ToolResult:
        del args
        google_status = self.google.status()
        counts = self.store.counts()
        summary = (
            f"Google Workspace: {google_status.message} "
            f"Cache: {counts or 'empty'}."
        )
        return ToolResult(
            ok=True,
            summary=summary,
            data={"summary": summary, "google": _status_dict(google_status), "cache_counts": counts},
        )

    def render(self, data: dict[str, Any]) -> str:
        return str(data.get("summary", "")).strip()


class GoogleWorkspaceConnectTool(Tool):
    name = "google_workspace_connect"
    description = "Check or start Google Workspace OAuth for Calendar and Gmail on this local machine."
    input_schema = {
        "type": "object",
        "properties": {
            "authorize": {
                "type": "boolean",
                "description": "When true, open the local OAuth browser flow and save a local token.",
            }
        },
        "required": [],
        "additionalProperties": False,
    }
    safety = "external_auth"

    def __init__(self, *, google: GoogleConnectorLike) -> None:
        self.google = google

    def run(self, args: dict[str, Any]) -> ToolResult:
        authorize = bool(args.get("authorize", False))
        status = self.google.authorize(interactive=authorize) if authorize else self.google.status()
        return ToolResult(ok=True, summary=status.message, data={"google": _status_dict(status)})


class CalendarUpcomingTool(Tool):
    name = "calendar_upcoming"
    description = (
        "Read real upcoming Google Calendar events and cache them locally for assistant context. "
        "Use only when the user asks to check, list, show, search, or summarize actual calendar meetings, appointments, or events."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "days": {"type": "integer", "description": "How many days ahead to inspect."},
            "max_results": {"type": "integer", "description": "Maximum events to return."},
            "calendar_id": {"type": "string", "description": "Google calendar id, defaults to primary."},
            "use_cache": {"type": "boolean", "description": "Return cached events if live Google access is unavailable."},
        },
        "required": [],
        "additionalProperties": False,
    }
    safety = "read_only"

    def __init__(self, *, google: GoogleConnectorLike, store: ExternalServiceStore) -> None:
        self.google = google
        self.store = store

    def run(self, args: dict[str, Any]) -> ToolResult:
        days = max(1, min(int(args.get("days", 7) or 7), 60))
        max_results = max(1, min(int(args.get("max_results", 10) or 10), 50))
        use_cache = bool(args.get("use_cache", True))
        start, end = self.google.upcoming_range(days=days)
        try:
            items = self.google.list_calendar_events(
                time_min=start,
                time_max=end,
                max_results=max_results,
                calendar_id=str(args.get("calendar_id", "primary") or "primary"),
            )
            self.store.upsert_many(items)
            data_items = _items_to_dicts(items)
            summary = _render_items(data_items, empty=f"No Google Calendar events found in the next {days} day(s).")
            return ToolResult(ok=True, summary=summary, data={"source": "live", "events": data_items, "summary": summary})
        except Exception as exc:  # noqa: BLE001
            if not use_cache:
                return ToolResult(ok=False, summary="Google Calendar lookup failed.", data={}, error=str(exc))
            cached = self.store.query(
                provider="google",
                item_type="calendar_event",
                start_at=start.isoformat(),
                end_at=end.isoformat(),
                limit=max_results,
            )
            if cached:
                summary = _render_items(cached, empty="")
                return ToolResult(ok=True, summary=f"Using cached calendar data:\n{summary}", data={"source": "cache", "events": cached})
            return ToolResult(ok=False, summary=f"Google Calendar is not connected: {exc}", data={}, error="google_calendar_unavailable")


class CalendarTodayTool(Tool):
    name = "calendar_today"
    description = (
        "Read real Google Calendar events for today and cache them locally for assistant context. "
        "Use only when the user asks to check, list, show, search, or summarize actual calendar meetings, appointments, or events."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "max_results": {"type": "integer", "description": "Maximum events to return."},
            "calendar_id": {"type": "string", "description": "Google calendar id, defaults to primary."},
            "use_cache": {"type": "boolean"},
        },
        "required": [],
        "additionalProperties": False,
    }
    safety = "read_only"

    def __init__(self, *, google: GoogleConnectorLike, store: ExternalServiceStore) -> None:
        self.google = google
        self.store = store

    def run(self, args: dict[str, Any]) -> ToolResult:
        start, end = self.google.today_range()
        max_results = max(1, min(int(args.get("max_results", 10) or 10), 50))
        use_cache = bool(args.get("use_cache", True))
        try:
            items = self.google.list_calendar_events(
                time_min=start,
                time_max=end,
                max_results=max_results,
                calendar_id=str(args.get("calendar_id", "primary") or "primary"),
            )
            self.store.upsert_many(items)
            data_items = _items_to_dicts(items)
            summary = _render_items(data_items, empty="No Google Calendar events found for today.")
            return ToolResult(ok=True, summary=summary, data={"source": "live", "events": data_items, "summary": summary})
        except Exception as exc:  # noqa: BLE001
            if not use_cache:
                return ToolResult(ok=False, summary="Google Calendar lookup failed.", data={}, error=str(exc))
            cached = self.store.query(
                provider="google",
                item_type="calendar_event",
                start_at=start.isoformat(),
                end_at=end.isoformat(),
                limit=max_results,
            )
            if cached:
                summary = _render_items(cached, empty="")
                return ToolResult(ok=True, summary=f"Using cached calendar data:\n{summary}", data={"source": "cache", "events": cached})
            return ToolResult(ok=False, summary=f"Google Calendar is not connected: {exc}", data={}, error="google_calendar_unavailable")


class GmailSearchTool(Tool):
    name = "gmail_search"
    description = "Search Gmail messages by Gmail query syntax, summarize matches, and cache metadata locally."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Gmail search query, such as from:teacher newer_than:7d."},
            "max_results": {"type": "integer", "description": "Maximum messages to return."},
            "use_cache": {"type": "boolean", "description": "Search cached Gmail metadata if live access is unavailable."},
        },
        "required": ["query"],
        "additionalProperties": False,
    }
    safety = "read_only"

    def __init__(self, *, google: GoogleConnectorLike, store: ExternalServiceStore) -> None:
        self.google = google
        self.store = store

    def run(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(ok=False, summary="Gmail search query is required.", data={}, error="missing_query")
        max_results = max(1, min(int(args.get("max_results", 10) or 10), 25))
        try:
            items = self.google.search_gmail(query=query, max_results=max_results)
            self.store.upsert_many(items)
            data_items = _items_to_dicts(items)
            summary = _render_items(data_items, empty=f"No Gmail messages matched `{query}`.")
            return ToolResult(ok=True, summary=summary, data={"source": "live", "messages": data_items, "summary": summary})
        except Exception as exc:  # noqa: BLE001
            if not bool(args.get("use_cache", True)):
                return ToolResult(ok=False, summary="Gmail search failed.", data={}, error=str(exc))
            cached = self.store.query(provider="google", item_type="gmail_message", text_query=query, limit=max_results)
            if cached:
                summary = _render_items(cached, empty="")
                return ToolResult(ok=True, summary=f"Using cached Gmail data:\n{summary}", data={"source": "cache", "messages": cached})
            return ToolResult(ok=False, summary=f"Gmail is not connected: {exc}", data={}, error="gmail_unavailable")


class GmailUnreadTool(Tool):
    name = "gmail_unread"
    description = "Read unread Gmail message metadata and cache it locally."
    input_schema = {
        "type": "object",
        "properties": {
            "max_results": {"type": "integer", "description": "Maximum unread messages to return."},
            "use_cache": {"type": "boolean"},
        },
        "required": [],
        "additionalProperties": False,
    }
    safety = "read_only"

    def __init__(self, *, google: GoogleConnectorLike, store: ExternalServiceStore) -> None:
        self.google = google
        self.store = store

    def run(self, args: dict[str, Any]) -> ToolResult:
        max_results = max(1, min(int(args.get("max_results", 10) or 10), 25))
        try:
            items = self.google.unread_gmail(max_results=max_results)
            self.store.upsert_many(items)
            data_items = _items_to_dicts(items)
            summary = _render_items(data_items, empty="No unread Gmail messages found.")
            return ToolResult(ok=True, summary=summary, data={"source": "live", "messages": data_items, "summary": summary})
        except Exception as exc:  # noqa: BLE001
            cached = self.store.query(provider="google", item_type="gmail_message", text_query="UNREAD", limit=max_results)
            if bool(args.get("use_cache", True)) and cached:
                summary = _render_items(cached, empty="")
                return ToolResult(ok=True, summary=f"Using cached Gmail data:\n{summary}", data={"source": "cache", "messages": cached})
            return ToolResult(ok=False, summary=f"Gmail is not connected: {exc}", data={}, error="gmail_unavailable")


class GmailCreateDraftTool(Tool):
    name = "gmail_create_draft"
    description = "Create a Gmail draft only when the user explicitly asks to draft an email; this never sends mail."
    input_schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "thread_id": {"type": "string"},
            "confirm_create": {"type": "boolean", "description": "Must be true after the user explicitly asks to create a draft."},
        },
        "required": ["to", "subject", "body"],
        "additionalProperties": False,
    }
    safety = "external_write"

    def __init__(self, *, google: GoogleConnectorLike) -> None:
        self.google = google

    def run(self, args: dict[str, Any]) -> ToolResult:
        if not bool(args.get("confirm_create", False)):
            preview = f"Draft preview for {args.get('to', '')}: {args.get('subject', '')}\n{args.get('body', '')}"
            return ToolResult(
                ok=False,
                summary="Draft creation needs explicit confirm_create=true. No Gmail draft was created.",
                data={"preview": preview},
                error="confirmation_required",
            )
        try:
            result = self.google.create_gmail_draft(
                to=str(args["to"]),
                subject=str(args["subject"]),
                body=str(args["body"]),
                thread_id=str(args.get("thread_id", "") or ""),
            )
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"Gmail draft creation failed: {exc}", data={}, error="gmail_draft_failed")
        draft_id = str(result.get("id", ""))
        return ToolResult(ok=True, summary=f"Gmail draft created: {draft_id}", data={"draft": result})


def register_external_service_tools(
    registry: ToolRegistry,
    *,
    data_dir: Path,
    google_credentials_path: Path,
    google_token_path: Path,
) -> None:
    store = ExternalServiceStore(data_dir / "integrations" / "external_services.db")
    google = GoogleWorkspaceConnector(credentials_path=google_credentials_path, token_path=google_token_path)
    for tool in [
        ExternalServicesStatusTool(google=google, store=store),
        GoogleWorkspaceConnectTool(google=google),
        CalendarTodayTool(google=google, store=store),
        CalendarUpcomingTool(google=google, store=store),
        GmailUnreadTool(google=google, store=store),
        GmailSearchTool(google=google, store=store),
        GmailCreateDraftTool(google=google),
    ]:
        registry.register(tool)
