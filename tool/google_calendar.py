from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from tool.google_auth import google_service


CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar"]


@dataclass(frozen=True)
class GoogleCalendarTool:
    name: str = "google_calendar"
    description: str = "List, search, create, update, delete, inspect, and free/busy-check Google Calendar events."

    def run(
        self,
        action: str,
        calendar_id: str = "primary",
        query: str = "",
        summary: str = "",
        start: str = "",
        end: str = "",
        timezone_name: str = "",
        location: str = "",
        description: str = "",
        event_id: str = "",
        max_results: int = 10,
        time_min: str = "",
        time_max: str = "",
        attendees: str | list[str] | None = None,
        all_day: bool | str = False,
        recurrence: str | list[str] | None = None,
        reminders: Any = None,
        reminders_minutes: Any = None,
    ) -> str:
        service, error = google_service("calendar", "v3", CALENDAR_SCOPES)
        if error:
            return error

        action = self._action(action)
        timezone_name = self._timezone_name(timezone_name)
        reminder_values = self._list_value(reminders_minutes if reminders_minutes not in (None, "") else reminders)
        recurrence_values = self._list_value(recurrence)
        try:
            if action in {"list", "upcoming", "search"}:
                return self._list(service, calendar_id, query, max_results, time_min=time_min, time_max=time_max)
            if action in {"get", "read"}:
                return self._get(service, calendar_id, event_id)
            if action in {"create", "add"}:
                return self._create(
                    service,
                    calendar_id,
                    summary,
                    start,
                    end,
                    timezone_name,
                    location,
                    description,
                    attendees=self._list_value(attendees),
                    all_day=self._bool(all_day),
                    recurrence=recurrence_values,
                    reminders=reminder_values,
                )
            if action in {"update", "patch", "edit"}:
                return self._update(
                    service,
                    calendar_id,
                    event_id,
                    summary=summary,
                    start=start,
                    end=end,
                    timezone_name=timezone_name,
                    location=location,
                    description=description,
                    attendees=self._list_value(attendees),
                    all_day=self._bool(all_day),
                    recurrence=recurrence_values,
                    reminders=reminder_values,
                )
            if action in {"delete", "remove"}:
                return self._delete(service, calendar_id, event_id)
            if action in {"freebusy", "availability", "busy"}:
                return self._freebusy(service, calendar_id, time_min, time_max, timezone_name)
            if action in {"calendars", "list_calendars"}:
                return self._calendars(service)
        except Exception as error:
            return f"FAILED: Google Calendar {action or 'action'} error: {error}"

        return (
            f"FAILED: unsupported Google Calendar action '{action}'. "
            "Use list, get, create, update, delete, freebusy, or calendars."
        )

    def _list(
        self,
        service: Any,
        calendar_id: str,
        query: str,
        max_results: int,
        time_min: str = "",
        time_max: str = "",
    ) -> str:
        start = self._time_bound(time_min) or datetime.now(timezone.utc).isoformat()
        request: dict[str, Any] = {
            "calendarId": calendar_id or "primary",
            "timeMin": start,
            "maxResults": self._clamp_int(max_results, default=10, minimum=1, maximum=100),
            "singleEvents": True,
            "orderBy": "startTime",
            "q": query or None,
        }
        end = self._time_bound(time_max)
        if end:
            request["timeMax"] = end
        events_result = service.events().list(**request).execute()
        events = events_result.get("items", [])
        if not events:
            return "No upcoming Google Calendar events found."

        lines = ["Google Calendar events:"]
        for event in events:
            lines.append("- " + self._event_line(event))
        return "\n".join(lines)

    def _get(self, service: Any, calendar_id: str, event_id: str) -> str:
        if not event_id:
            return "FAILED: event_id is required to read a calendar event."
        event = service.events().get(calendarId=calendar_id or "primary", eventId=event_id).execute()
        return "Google Calendar event:\n" + self._event_detail(event)

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
        attendees: list[str],
        all_day: bool,
        recurrence: list[str],
        reminders: list[str],
    ) -> str:
        if not summary or not start:
            return "FAILED: summary and start are required to create a calendar event."
        event = self._event_body(
            summary,
            start,
            end,
            timezone_name,
            location,
            description,
            attendees,
            all_day,
            recurrence,
            reminders,
        )
        created = service.events().insert(calendarId=calendar_id or "primary", body=event).execute()
        return f"VERIFIED: Calendar event created. id={created.get('id')} link={created.get('htmlLink', '')}"

    def _update(
        self,
        service: Any,
        calendar_id: str,
        event_id: str,
        summary: str = "",
        start: str = "",
        end: str = "",
        timezone_name: str = "Asia/Kolkata",
        location: str = "",
        description: str = "",
        attendees: list[str] | None = None,
        all_day: bool = False,
        recurrence: list[str] | None = None,
        reminders: list[str] | None = None,
    ) -> str:
        if not event_id:
            return "FAILED: event_id is required to update a calendar event."
        body: dict[str, Any] = {}
        if summary:
            body["summary"] = summary
        if location:
            body["location"] = location
        if description:
            body["description"] = description
        if start:
            times = self._event_times(start, end, timezone_name, all_day)
            body["start"] = times["start"]
            body["end"] = times["end"]
        if attendees:
            body["attendees"] = [{"email": email} for email in attendees]
        if recurrence:
            body["recurrence"] = recurrence
        if reminders:
            body["reminders"] = self._reminders_body(reminders)
        if not body:
            return "FAILED: at least one field is required to update a calendar event."
        updated = service.events().patch(calendarId=calendar_id or "primary", eventId=event_id, body=body).execute()
        return f"VERIFIED: Calendar event updated. id={updated.get('id', event_id)} link={updated.get('htmlLink', '')}"

    def _delete(self, service: Any, calendar_id: str, event_id: str) -> str:
        if not event_id:
            return "FAILED: event_id is required to delete a calendar event."
        service.events().delete(calendarId=calendar_id or "primary", eventId=event_id).execute()
        return f"VERIFIED: Calendar event deleted. id={event_id}"

    def _freebusy(self, service: Any, calendar_id: str, time_min: str, time_max: str, timezone_name: str) -> str:
        start_dt = self._parse_datetime(time_min) if str(time_min or "").strip() else datetime.now(timezone.utc)
        end_dt = self._parse_datetime(time_max) if str(time_max or "").strip() else start_dt + timedelta(days=1)
        body = {
            "timeMin": start_dt.isoformat(),
            "timeMax": end_dt.isoformat(),
            "timeZone": self._timezone_name(timezone_name),
            "items": [{"id": calendar_id or "primary"}],
        }
        result = service.freebusy().query(body=body).execute()
        calendars = result.get("calendars", {}) or {}
        busy = calendars.get(calendar_id or "primary", {}).get("busy", []) or []
        if not busy:
            return "Calendar availability: free for the requested window."
        lines = ["Calendar busy windows:"]
        for item in busy:
            lines.append(f"- {item.get('start')} to {item.get('end')}")
        return "\n".join(lines)

    def _calendars(self, service: Any) -> str:
        result = service.calendarList().list().execute()
        calendars = result.get("items", []) or []
        if not calendars:
            return "No Google calendars found."
        lines = ["Google calendars:"]
        for calendar in calendars:
            primary = " primary" if calendar.get("primary") else ""
            lines.append(
                f"- id={calendar.get('id')} | summary={calendar.get('summary', '')}{primary} | "
                f"timezone={calendar.get('timeZone', '')} | access={calendar.get('accessRole', '')}"
            )
        return "\n".join(lines)

    @classmethod
    def _event_body(
        cls,
        summary: str,
        start: str,
        end: str,
        timezone_name: str,
        location: str,
        description: str,
        attendees: list[str],
        all_day: bool,
        recurrence: list[str],
        reminders: list[str],
    ) -> dict[str, Any]:
        times = cls._event_times(start, end, timezone_name, all_day)
        event: dict[str, Any] = {
            "summary": summary,
            "start": times["start"],
            "end": times["end"],
        }
        if location:
            event["location"] = location
        if description:
            event["description"] = description
        if attendees:
            event["attendees"] = [{"email": email} for email in attendees]
        if recurrence:
            event["recurrence"] = recurrence
        if reminders:
            event["reminders"] = cls._reminders_body(reminders)
        return event

    @classmethod
    def _event_times(cls, start: str, end: str, timezone_name: str, all_day: bool) -> dict[str, dict[str, str]]:
        start_dt = cls._parse_datetime(start)
        if all_day:
            end_dt = cls._parse_datetime(end) if end else start_dt + timedelta(days=1)
            return {
                "start": {"date": start_dt.date().isoformat()},
                "end": {"date": end_dt.date().isoformat()},
            }
        end_dt = cls._parse_datetime(end) if end else start_dt + timedelta(hours=1)
        return {
            "start": {"dateTime": start_dt.isoformat(), "timeZone": cls._timezone_name(timezone_name)},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": cls._timezone_name(timezone_name)},
        }

    @staticmethod
    def _reminders_body(reminders: list[str]) -> dict[str, Any]:
        overrides = []
        for reminder in reminders:
            minutes = GoogleCalendarTool._reminder_minutes(reminder)
            if minutes is not None:
                overrides.append({"method": "popup", "minutes": minutes})
        if not overrides:
            return {"useDefault": True}
        return {"useDefault": False, "overrides": overrides}

    @staticmethod
    def _reminder_minutes(value: str) -> int | None:
        try:
            return max(0, min(40320, int(str(value).strip())))
        except ValueError:
            return None

    @staticmethod
    def _event_line(event: dict[str, Any]) -> str:
        start = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
        end = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
        attendees = event.get("attendees", []) or []
        attendee_text = f" | attendees={len(attendees)}" if attendees else ""
        location = f" | location={event.get('location')}" if event.get("location") else ""
        status = f" | status={event.get('status')}" if event.get("status") else ""
        return f"id={event.get('id')} | {start} to {end} | {event.get('summary', '(no title)')}{location}{status}{attendee_text}"

    @classmethod
    def _event_detail(cls, event: dict[str, Any]) -> str:
        attendees = event.get("attendees", []) or []
        attendee_text = ", ".join(item.get("email", "") for item in attendees if item.get("email"))
        return "\n".join(
            [
                f"id: {event.get('id')}",
                f"summary: {event.get('summary', '(no title)')}",
                f"start: {event.get('start', {}).get('dateTime') or event.get('start', {}).get('date')}",
                f"end: {event.get('end', {}).get('dateTime') or event.get('end', {}).get('date')}",
                f"status: {event.get('status', '')}",
                f"location: {event.get('location', '')}",
                f"attendees: {attendee_text}",
                f"recurrence: {', '.join(event.get('recurrence', []) or [])}",
                f"link: {event.get('htmlLink', '')}",
                f"description: {event.get('description', '')}",
            ]
        )

    @staticmethod
    def _time_bound(value: str) -> str:
        return GoogleCalendarTool._parse_datetime(value).isoformat() if str(value or "").strip() else ""

    @staticmethod
    def _parse_datetime(value: str) -> datetime:
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.astimezone()
        return parsed

    @staticmethod
    def _list_value(value: Any) -> list[str]:
        if not value:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        pieces: list[str] = []
        current: list[str] = []
        for char in str(value):
            if char in {",", ";", "\n", "\t"}:
                if current:
                    pieces.append("".join(current).strip())
                    current = []
                continue
            current.append(char)
        if current:
            pieces.append("".join(current).strip())
        return [piece for piece in pieces if piece]

    @staticmethod
    def _bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _timezone_name(value: str) -> str:
        return str(value or os.getenv("DEFAULT_TIMEZONE") or "Asia/Kolkata").strip() or "Asia/Kolkata"

    @staticmethod
    def _action(action: str) -> str:
        return str(action or "list").strip().lower().replace("-", "_").replace(" ", "_")

    @staticmethod
    def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))
