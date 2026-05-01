from __future__ import annotations

import base64
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any

from tool.google_auth import google_service


GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


@dataclass(frozen=True)
class GmailTool:
    name: str = "gmail"
    description: str = "Search, read, draft, and send Gmail messages through the user's Google account."

    def run(
        self,
        action: str,
        query: str = "",
        to: str = "",
        subject: str = "",
        body: str = "",
        message_id: str = "",
        max_results: int = 5,
    ) -> str:
        service, error = google_service("gmail", "v1", GMAIL_SCOPES)
        if error:
            return error

        action = action.strip().lower()
        try:
            if action in {"search", "list"}:
                return self._search(service, query=query, max_results=max_results)
            if action in {"read", "get"}:
                return self._read(service, message_id=message_id)
            if action == "send":
                return self._send(service, to=to, subject=subject, body=body)
            if action == "draft":
                return self._draft(service, to=to, subject=subject, body=body)
        except Exception as error:
            return f"FAILED: Gmail {action or 'action'} error: {error}"

        return f"FAILED: unsupported Gmail action '{action}'. Use search, read, draft, or send."

    def _search(self, service: Any, query: str, max_results: int) -> str:
        result = service.users().messages().list(
            userId="me",
            q=query or "",
            maxResults=max(1, min(int(max_results or 5), 20)),
        ).execute()
        messages = result.get("messages", [])
        if not messages:
            return "No Gmail messages found."

        lines = ["Gmail search results:"]
        for message in messages:
            metadata = service.users().messages().get(
                userId="me",
                id=message["id"],
                format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()
            headers = self._headers(metadata)
            lines.append(
                f"- id={metadata.get('id')} | from={headers.get('from', '')} | "
                f"subject={headers.get('subject', '')} | date={headers.get('date', '')}"
            )
        return "\n".join(lines)

    def _read(self, service: Any, message_id: str) -> str:
        if not message_id:
            return "FAILED: message_id is required to read a Gmail message."
        message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = self._headers(message)
        body = self._message_body(message.get("payload", {}))
        return (
            "Gmail message:\n"
            f"id: {message.get('id')}\n"
            f"from: {headers.get('from', '')}\n"
            f"to: {headers.get('to', '')}\n"
            f"subject: {headers.get('subject', '')}\n"
            f"date: {headers.get('date', '')}\n\n"
            f"{body[:6000] or message.get('snippet', '')}"
        )

    def _send(self, service: Any, to: str, subject: str, body: str) -> str:
        if not to or not subject or not body:
            return "FAILED: to, subject, and body are required to send Gmail."
        message = {"raw": self._raw_email(to, subject, body)}
        sent = service.users().messages().send(userId="me", body=message).execute()
        return f"VERIFIED: Gmail sent. id={sent.get('id')}"

    def _draft(self, service: Any, to: str, subject: str, body: str) -> str:
        if not to or not subject or not body:
            return "FAILED: to, subject, and body are required to create a Gmail draft."
        draft = {"message": {"raw": self._raw_email(to, subject, body)}}
        created = service.users().drafts().create(userId="me", body=draft).execute()
        return f"VERIFIED: Gmail draft created. id={created.get('id')}"

    @staticmethod
    def _raw_email(to: str, subject: str, body: str) -> str:
        message = EmailMessage()
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        return base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    @staticmethod
    def _headers(message: dict[str, Any]) -> dict[str, str]:
        headers = {}
        for header in message.get("payload", {}).get("headers", []):
            headers[header.get("name", "").lower()] = header.get("value", "")
        return headers

    @classmethod
    def _message_body(cls, payload: dict[str, Any]) -> str:
        if "data" in payload.get("body", {}):
            return cls._decode_body(payload["body"]["data"])
        parts = payload.get("parts", []) or []
        plain_parts = [part for part in parts if part.get("mimeType") == "text/plain"]
        for part in plain_parts or parts:
            body = part.get("body", {})
            if "data" in body:
                return cls._decode_body(body["data"])
            nested = cls._message_body(part)
            if nested:
                return nested
        return ""

    @staticmethod
    def _decode_body(data: str) -> str:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
