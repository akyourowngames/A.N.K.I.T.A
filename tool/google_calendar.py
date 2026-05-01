from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from tool.google_auth import google_service


CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]


@dataclass(frozen=True)
class GoogleCalendarTool:
    name: str = "google_calendar"
    description: str = "List, create, and delete Google Calendar events."

    def run(
        self,
        action: str,
        calendar_id: str = "primary",
        query: str = "",
        summary: str = "",
        start: str = "",
        end: str = "",
        timezone_name: str = "Asia/Kolkata",
        location: str = "",
        description: str = "",
        event_id: str = "",
        max_results: int = 10,
    ) -> str:
        service, error = google_service("calendar", "v3", CALENDAR_SCOPES)
        if error:
            return error

        action = action.strip().lower()
        try:
            if action in {"list", "upcoming", "search"}:
                return self._list(service, calendar_id, query, max_results)
            if action in {"create", "add"}:
                return self._create(service, calendar_id, summary, start, end, timezone_name, location, description)
            if action in {"delete", "remove"}:
                return self._delete(service, calendar_id, event_id)
        except Exception as error:
            return f"FAILED: Google Calendar {action or 'action'} error: {error}"

        return f"FAILED: unsupported Google Calendar action '{action}'. Use list, create, or delete."

    def _list(self, service: Any, calendar_id: str, query: str, max_results: int) -> str:
        now = datetime.now(timezone.utc).isoformat()
        events_result = service.events().list(
            calendarId=calendar_id or "primary",
            timeMin=now,
            maxResults=max(1, min(int(max_results or 10), 50)),
            singleEvents=True,
            orderBy="startTime",
            q=query or None,
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return "No upcoming Google Calendar events found."

        lines = ["Upcoming Google Calendar events:"]
        for event in events:
            start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
            lines.append(f"- id={event.get('id')} | {start} | {event.get('summary', '(no title)')}")
        return "\n".join(lines)

    def _create(
        self,
        service: Any,
        calendar_id: str,
        summary: str,
        start: str,
        end: str,
        timezone_name: str,
        location: str,
        description: str,
    ) -> str:
        if not summary or not start:
            return "FAILED: summary and start are required to create a calendar event."
        start_dt = self._parse_datetime(start)
        end_dt = self._parse_datetime(end) if end else start_dt + timedelta(hours=1)
        event = {
            "summary": summary,
            "location": location or None,
            "description": description or None,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": timezone_name or "Asia/Kolkata"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": timezone_name or "Asia/Kolkata"},
        }
        created = service.events().insert(calendarId=calendar_id or "primary", body=event).execute()
        return f"VERIFIED: Calendar event created. id={created.get('id')} link={created.get('htmlLink', '')}"

    def _delete(self, service: Any, calendar_id: str, event_id: str) -> str:
        if not event_id:
            return "FAILED: event_id is required to delete a calendar event."
        service.events().delete(calendarId=calendar_id or "primary", eventId=event_id).execute()
        return f"VERIFIED: Calendar event deleted. id={event_id}"

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.astimezone()
        return parsed
