"""
CalendarWatcher — Meeting & Deadline Guardian for A.N.K.I.T.A.

Polls Google Calendar for upcoming events and alerts before meetings start.
Also tracks overdue tasks from a local tasks.json file.

Config (calendar_config.json):
    {
        "enabled": true,
        "poll_interval_sec": 120,
        "alert_minutes_before": [10, 2],
        "calendar_ids": ["primary"],
        "credentials_file": "client_secret_....json",
        "token_file": ".ankita/calendar_token.json",
        "local_tasks_file": ".ankita/tasks.json",
        "cooldown_sec": 60
    }

Requires: google-auth, google-auth-oauthlib, google-api-python-client
    pip install google-auth google-auth-oauthlib google-api-python-client
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from pathlib import Path

from watchdog_manager import BaseWatcher
from proactive import ProactiveEngine


class CalendarWatcher(BaseWatcher):
    """
    Monitors Google Calendar for upcoming meetings and local task deadlines.

    - Alerts N minutes before each meeting (configurable, e.g. 10min + 2min)
    - Includes meeting join link (Google Meet / Zoom) if present in event
    - Tracks local tasks.json for overdue items
    - Handles OAuth2 token refresh automatically
    """

    def __init__(
        self,
        config: Dict[str, Any],
        proactive: ProactiveEngine,
        workspace_root: Path,
    ) -> None:
        super().__init__(
            name="CalendarWatcher",
            config=config,
            proactive=proactive,
            workspace_root=workspace_root,
        )
        self.poll_interval = float(config.get("poll_interval_sec", 120))
        self.alert_minutes = sorted(config.get("alert_minutes_before", [10, 2]), reverse=True)
        self.calendar_ids = config.get("calendar_ids", ["primary"])
        self.cooldown_sec = float(config.get("cooldown_sec", 60))

        # Resolve credentials paths
        creds_name = config.get("credentials_file", "")
        if creds_name:
            self.credentials_file = workspace_root / creds_name
        else:
            # Auto-discover client_secret_*.json in workspace root
            matches = list(workspace_root.glob("client_secret_*.json"))
            self.credentials_file = matches[0] if matches else None

        token_rel = config.get("token_file", ".ankita/calendar_token.json")
        self.token_file = workspace_root / token_rel

        local_tasks_rel = config.get("local_tasks_file", ".ankita/tasks.json")
        self.local_tasks_file = workspace_root / local_tasks_rel

        # State: track which event+alert_window combos we've already fired
        self.state.setdefault("alerted_events", {})   # {event_id_window: epoch}
        self.state.setdefault("alerted_tasks", [])    # [task_id]
        self.state.setdefault("last_alert_time", {})

        self._service = None  # lazy-init Google Calendar service

    # ------------------------------------------------------------------
    # Main check
    # ------------------------------------------------------------------

    def _check(self) -> Optional[str]:
        alerts: List[str] = []

        # Google Calendar events
        cal_alerts = self._check_calendar_events()
        alerts.extend(cal_alerts)

        # Local task deadlines
        task_alerts = self._check_local_tasks()
        alerts.extend(task_alerts)

        self._save_state()

        if alerts:
            return "\n".join(alerts)
        return None

    # ------------------------------------------------------------------
    # Google Calendar
    # ------------------------------------------------------------------

    def _get_service(self):
        """Lazy-init and return the Google Calendar API service object."""
        if self._service is not None:
            return self._service
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build  # type: ignore

            SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
            creds = None

            if self.token_file.exists():
                creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)

            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                elif self.credentials_file and Path(self.credentials_file).exists():
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self.credentials_file), SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                else:
                    print("[CalendarWatcher] No credentials file found — skipping Google Calendar.", flush=True)
                    return None

                self.token_file.parent.mkdir(parents=True, exist_ok=True)
                self.token_file.write_text(creds.to_json())

            self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
            return self._service

        except ImportError:
            print(
                "[CalendarWatcher] google-api-python-client not installed. "
                "Run: pip install google-auth google-auth-oauthlib google-api-python-client",
                flush=True,
            )
            return None
        except Exception as exc:
            print(f"[CalendarWatcher] Failed to init Google Calendar service: {exc}", flush=True)
            return None

    def _check_calendar_events(self) -> List[str]:
        """Fetch upcoming events and fire pre-meeting alerts."""
        service = self._get_service()
        if service is None:
            return []

        now = datetime.now(timezone.utc)
        # Look ahead up to max alert window + 5 min buffer
        max_lookahead_min = (max(self.alert_minutes) + 5) if self.alert_minutes else 15
        time_max = now + timedelta(minutes=max_lookahead_min)

        alerts: List[str] = []

        for cal_id in self.calendar_ids:
            try:
                events_result = service.events().list(
                    calendarId=cal_id,
                    timeMin=now.isoformat(),
                    timeMax=time_max.isoformat(),
                    maxResults=10,
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()
                events = events_result.get("items", [])
            except Exception as exc:
                print(f"[CalendarWatcher] Failed to fetch events from {cal_id}: {exc}", flush=True)
                continue

            for event in events:
                event_alerts = self._process_event(event, now)
                alerts.extend(event_alerts)

        return alerts

    def _process_event(self, event: Dict, now: datetime) -> List[str]:
        """Generate pre-meeting alerts for a single calendar event."""
        event_id = event.get("id", "")
        summary = event.get("summary", "Unnamed Event")
        location = event.get("location", "")
        description = event.get("description", "")

        # Parse start time
        start_info = event.get("start", {})
        start_str = start_info.get("dateTime") or start_info.get("date")
        if not start_str:
            return []

        try:
            if "T" in start_str:
                start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            else:
                # All-day event — skip time-based alerts
                return []
        except Exception:
            return []

        # Ensure timezone-aware
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)

        minutes_until = (start_dt - now).total_seconds() / 60
        alerts: List[str] = []

        for alert_min in self.alert_minutes:
            # Window: fire if we're within [alert_min - poll_interval/60, alert_min] minutes
            window_key = f"{event_id}_{alert_min}"
            if window_key in self.state["alerted_events"]:
                continue  # Already alerted for this window

            if 0 <= minutes_until <= alert_min:
                # Extract join link (Google Meet / Zoom)
                join_link = ""
                entry_points = event.get("conferenceData", {}).get("entryPoints", [])
                for ep in entry_points:
                    if ep.get("entryPointType") == "video":
                        join_link = ep.get("uri", "")
                        break
                if not join_link and location and location.startswith("http"):
                    join_link = location

                mins_int = int(minutes_until)
                time_str = f"in {mins_int} minute{'s' if mins_int != 1 else ''}" if mins_int > 0 else "NOW"
                alert = f"📅 Meeting {time_str}: **{summary}**"
                if join_link:
                    alert += f"\n   🔗 Join: {join_link}"
                elif location:
                    alert += f"\n   📍 Location: {location}"

                alerts.append(alert)
                self.state["alerted_events"][window_key] = time.time()

        # Clean up old fired alerts (> 2 hours old)
        cutoff = time.time() - 7200
        self.state["alerted_events"] = {
            k: v for k, v in self.state["alerted_events"].items()
            if v > cutoff
        }

        return alerts

    # ------------------------------------------------------------------
    # Local tasks
    # ------------------------------------------------------------------

    def _check_local_tasks(self) -> List[str]:
        """Check local tasks.json for overdue or due-soon items."""
        if not self.local_tasks_file.exists():
            return []

        try:
            tasks = json.loads(self.local_tasks_file.read_text(encoding="utf-8"))
        except Exception:
            return []

        if not isinstance(tasks, list):
            return []

        now = time.time()
        alerts: List[str] = []
        alerted = set(self.state.get("alerted_tasks", []))

        for task in tasks:
            if not isinstance(task, dict):
                continue
            task_id = task.get("id", task.get("title", ""))
            if not task_id or task_id in alerted:
                continue
            if task.get("done") or task.get("completed"):
                continue

            due_str = task.get("due") or task.get("deadline") or task.get("due_date")
            if not due_str:
                continue

            try:
                # Support epoch or ISO string
                if isinstance(due_str, (int, float)):
                    due_ts = float(due_str)
                else:
                    due_dt = datetime.fromisoformat(str(due_str).replace("Z", "+00:00"))
                    due_ts = due_dt.timestamp()
            except Exception:
                continue

            overdue_sec = now - due_ts
            if overdue_sec >= 0:
                title = task.get("title", task.get("name", "Unknown task"))
                mins_overdue = int(overdue_sec / 60)
                if mins_overdue < 60:
                    overdue_label = f"{mins_overdue}m overdue"
                elif mins_overdue < 1440:
                    overdue_label = f"{mins_overdue // 60}h overdue"
                else:
                    overdue_label = f"{mins_overdue // 1440}d overdue"

                alerts.append(f"⏰ Task overdue ({overdue_label}): **{title}**")
                alerted.add(task_id)

        self.state["alerted_tasks"] = list(alerted)[-200:]  # cap size
        return alerts

    def get_todays_agenda(self) -> str:
        """Return today's calendar agenda (callable by WatchdogAgent)."""
        service = self._get_service()
        if service is None:
            return "Google Calendar not configured. Set up credentials first."

        now = datetime.now(timezone.utc)
        end_of_day = now.replace(hour=23, minute=59, second=59)

        try:
            events_result = service.events().list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=end_of_day.isoformat(),
                maxResults=20,
                singleEvents=True,
                orderBy="startTime",
            ).execute()
            events = events_result.get("items", [])
        except Exception as exc:
            return f"Failed to fetch agenda: {exc}"

        if not events:
            return "📅 No more events today — you're free!"

        lines = [f"📅 Today's remaining agenda ({len(events)} events):"]
        for event in events:
            start_info = event.get("start", {})
            start_str = start_info.get("dateTime") or start_info.get("date", "")
            summary = event.get("summary", "Unnamed")
            try:
                if "T" in start_str:
                    dt = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                    time_str = dt.strftime("%I:%M %p")
                else:
                    time_str = "All day"
            except Exception:
                time_str = start_str[:10]
            lines.append(f"  {time_str}  —  {summary}")

        return "\n".join(lines)
