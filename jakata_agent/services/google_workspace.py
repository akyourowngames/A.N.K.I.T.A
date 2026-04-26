from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from jakata_agent.services.sync_store import ServiceItem


GOOGLE_WORKSPACE_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


@dataclass(slots=True)
class GoogleServiceStatus:
    configured: bool
    authorized: bool
    credentials_path: str
    token_path: str
    message: str


class GoogleWorkspaceConnector:
    def __init__(self, *, credentials_path: Path, token_path: Path, scopes: list[str] | None = None) -> None:
        self.credentials_path = credentials_path
        self.token_path = token_path
        self.scopes = scopes or GOOGLE_WORKSPACE_SCOPES

    def status(self) -> GoogleServiceStatus:
        if not self.credentials_path.exists():
            return GoogleServiceStatus(
                configured=False,
                authorized=False,
                credentials_path=str(self.credentials_path),
                token_path=str(self.token_path),
                message="Google credentials file is missing.",
            )
        if not self.token_path.exists():
            return GoogleServiceStatus(
                configured=True,
                authorized=False,
                credentials_path=str(self.credentials_path),
                token_path=str(self.token_path),
                message="Google credentials are present, but OAuth authorization has not been completed.",
            )
        return GoogleServiceStatus(
            configured=True,
            authorized=True,
            credentials_path=str(self.credentials_path),
            token_path=str(self.token_path),
            message="Google Workspace token is available.",
        )

    def authorize(self, *, interactive: bool = False) -> GoogleServiceStatus:
        try:
            self._credentials(interactive=interactive)
        except Exception as exc:  # noqa: BLE001
            status = self.status()
            return GoogleServiceStatus(
                configured=status.configured,
                authorized=False,
                credentials_path=status.credentials_path,
                token_path=status.token_path,
                message=str(exc),
            )
        return self.status()

    def list_calendar_events(
        self,
        *,
        time_min: datetime,
        time_max: datetime,
        max_results: int = 10,
        calendar_id: str = "primary",
    ) -> list[ServiceItem]:
        service = self._build("calendar", "v3")
        response = (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min.astimezone(timezone.utc).isoformat(),
                timeMax=time_max.astimezone(timezone.utc).isoformat(),
                maxResults=max(1, min(int(max_results), 50)),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return [self._event_to_item(item) for item in response.get("items", [])]

    def search_gmail(self, *, query: str, max_results: int = 10) -> list[ServiceItem]:
        service = self._build("gmail", "v1")
        listed = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max(1, min(int(max_results), 25)))
            .execute()
        )
        messages = []
        for item in listed.get("messages", []):
            message_id = item.get("id")
            if not message_id:
                continue
            message = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="metadata", metadataHeaders=["From", "To", "Subject", "Date"])
                .execute()
            )
            messages.append(self._message_to_item(message))
        return messages

    def unread_gmail(self, *, max_results: int = 10) -> list[ServiceItem]:
        return self.search_gmail(query="is:unread", max_results=max_results)

    def create_gmail_draft(
        self,
        *,
        to: str,
        subject: str,
        body: str,
        thread_id: str = "",
    ) -> dict[str, Any]:
        service = self._build("gmail", "v1")
        message = EmailMessage()
        message.set_content(body)
        message["To"] = to
        message["Subject"] = subject
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
        payload: dict[str, Any] = {"message": {"raw": encoded}}
        if thread_id:
            payload["message"]["threadId"] = thread_id
        return service.users().drafts().create(userId="me", body=payload).execute()

    def upcoming_range(self, *, days: int) -> tuple[datetime, datetime]:
        start = datetime.now().astimezone()
        return start, start + timedelta(days=max(1, min(int(days), 60)))

    def today_range(self) -> tuple[datetime, datetime]:
        now = datetime.now().astimezone()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)

    def _credentials(self, *, interactive: bool = False):
        if not self.credentials_path.exists():
            raise RuntimeError(f"Missing Google OAuth credentials: {self.credentials_path}")
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise RuntimeError(
                "Google API libraries are not installed. Run `pip install -r requirements.txt`."
            ) from exc

        creds = None
        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), self.scopes)
        if creds and creds.valid:
            return creds
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif interactive:
            flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), self.scopes)
            creds = flow.run_local_server(port=0)
        else:
            raise RuntimeError("Google OAuth token is missing or expired. Run google_workspace_connect with authorize=true.")
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def _build(self, api: str, version: str):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Google API libraries are not installed. Run `pip install -r requirements.txt`."
            ) from exc
        return build(api, version, credentials=self._credentials(interactive=False), cache_discovery=False)

    @staticmethod
    def _event_to_item(event: dict[str, Any]) -> ServiceItem:
        start = event.get("start", {})
        end = event.get("end", {})
        start_at = str(start.get("dateTime") or start.get("date") or "")
        end_at = str(end.get("dateTime") or end.get("date") or "")
        title = str(event.get("summary") or "(untitled event)")
        text = str(event.get("description") or event.get("location") or "")
        return ServiceItem(
            provider="google",
            item_type="calendar_event",
            external_id=str(event.get("id") or event.get("iCalUID") or title),
            title=title,
            text=text,
            start_at=start_at,
            end_at=end_at,
            url=str(event.get("htmlLink") or ""),
            labels=[str(item.get("email", "")) for item in event.get("attendees", []) if item.get("email")],
            raw=event,
        )

    @staticmethod
    def _message_to_item(message: dict[str, Any]) -> ServiceItem:
        headers = {
            str(item.get("name", "")).lower(): str(item.get("value", ""))
            for item in (message.get("payload", {}) or {}).get("headers", [])
        }
        labels = [str(label) for label in message.get("labelIds", [])]
        subject = headers.get("subject") or "(no subject)"
        sender = headers.get("from", "")
        snippet = str(message.get("snippet") or "")
        title = f"{subject} - {sender}" if sender else subject
        return ServiceItem(
            provider="google",
            item_type="gmail_message",
            external_id=str(message.get("id") or ""),
            title=title,
            text=snippet,
            start_at=headers.get("date", ""),
            end_at="",
            url=f"https://mail.google.com/mail/u/0/#all/{message.get('id', '')}",
            labels=labels,
            raw=message,
        )

