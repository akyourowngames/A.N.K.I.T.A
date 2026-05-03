from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

from tool.google_auth import google_service


GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

LABEL_ACTIONS = {
    "mark_read": ([], ["UNREAD"]),
    "read_status_read": ([], ["UNREAD"]),
    "mark_unread": (["UNREAD"], []),
    "read_status_unread": (["UNREAD"], []),
    "archive": ([], ["INBOX"]),
    "move_to_inbox": (["INBOX"], []),
    "star": (["STARRED"], []),
    "unstar": ([], ["STARRED"]),
}


@dataclass(frozen=True)
class GmailTool:
    name: str = "gmail"
    description: str = "Search, read, draft, send, label, and manage Gmail messages through the user's Google account."

    def run(
        self,
        action: str,
        query: str = "",
        to: str = "",
        subject: str = "",
        body: str = "",
        message_id: str = "",
        max_results: int = 5,
        cc: str = "",
        bcc: str = "",
        thread_id: str = "",
        label_ids: str | list[str] | None = None,
        include_spam_trash: bool | None = None,
        add_labels: str | list[str] | None = None,
        remove_labels: str | list[str] | None = None,
    ) -> str:
        service, error = google_service("gmail", "v1", GMAIL_SCOPES)
        if error:
            return error

        action = self._action(action)
        try:
            if action in {"search", "list"}:
                return self._search(
                    service,
                    query=query,
                    max_results=max_results,
                    label_ids=self._list_value(label_ids),
                    include_spam_trash=self._bool(include_spam_trash),
                )
            if action in {"read", "get"}:
                return self._read(service, message_id=message_id)
            if action in {"thread", "read_thread"}:
                return self._thread(service, thread_id=thread_id or message_id)
            if action == "send":
                return self._send(service, to=to, subject=subject, body=body, cc=cc, bcc=bcc, thread_id=thread_id)
            if action == "draft":
                return self._draft(service, to=to, subject=subject, body=body, cc=cc, bcc=bcc, thread_id=thread_id)
            if action in {"reply", "draft_reply"}:
                return self._reply(
                    service,
                    message_id=message_id,
                    body=body,
                    cc=cc,
                    bcc=bcc,
                    to=to,
                    subject=subject,
                    send_now=False,
                )
            if action == "send_reply":
                return self._reply(
                    service,
                    message_id=message_id,
                    body=body,
                    cc=cc,
                    bcc=bcc,
                    to=to,
                    subject=subject,
                    send_now=True,
                )
            if action == "labels":
                return self._labels(service)
            if action == "profile":
                return self._profile(service)
            if action in LABEL_ACTIONS:
                add, remove = LABEL_ACTIONS[action]
                return self._modify_labels(service, message_id=message_id, add_labels=add, remove_labels=remove)
            if action == "modify_labels":
                return self._modify_labels(
                    service,
                    message_id=message_id,
                    add_labels=self._list_value(add_labels),
                    remove_labels=self._list_value(remove_labels),
                )
            if action == "trash":
                return self._trash(service, message_id=message_id)
            if action == "untrash":
                return self._untrash(service, message_id=message_id)
        except Exception as error:
            return f"FAILED: Gmail {action or 'action'} error: {error}"

        return (
            f"FAILED: unsupported Gmail action '{action}'. "
            "Use search, read, thread, draft, send, draft_reply, send_reply, labels, profile, mark_read, "
            "mark_unread, archive, trash, untrash, star, unstar, or modify_labels."
        )

    def _search(
        self,
        service: Any,
        query: str,
        max_results: int,
        label_ids: list[str] | None = None,
        include_spam_trash: bool = False,
    ) -> str:
        request: dict[str, Any] = {
            "userId": "me",
            "q": query or "",
            "maxResults": self._clamp_int(max_results, default=5, minimum=1, maximum=50),
            "includeSpamTrash": include_spam_trash,
        }
        if label_ids:
            request["labelIds"] = label_ids

        result = service.users().messages().list(**request).execute()
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
            labels = ", ".join(metadata.get("labelIds", []) or [])
            snippet = self._clean_text(metadata.get("snippet", ""))
            lines.append(
                f"- id={metadata.get('id')} | thread={metadata.get('threadId', '')} | "
                f"from={headers.get('from', '')} | subject={headers.get('subject', '')} | "
                f"date={headers.get('date', '')} | labels={labels or '<none>'} | snippet={snippet}"
            )
        return "\n".join(lines)

    def _read(self, service: Any, message_id: str) -> str:
        if not message_id:
            return "FAILED: message_id is required to read a Gmail message."
        message = service.users().messages().get(userId="me", id=message_id, format="full").execute()
        headers = self._headers(message)
        body = self._message_body(message.get("payload", {}))
        labels = ", ".join(message.get("labelIds", []) or [])
        return (
            "Gmail message:\n"
            f"id: {message.get('id')}\n"
            f"thread: {message.get('threadId', '')}\n"
            f"from: {headers.get('from', '')}\n"
            f"to: {headers.get('to', '')}\n"
            f"cc: {headers.get('cc', '')}\n"
            f"subject: {headers.get('subject', '')}\n"
            f"date: {headers.get('date', '')}\n"
            f"labels: {labels or '<none>'}\n"
            f"snippet: {self._clean_text(message.get('snippet', ''))}\n\n"
            f"{body[:6000] or message.get('snippet', '')}"
        )

    def _thread(self, service: Any, thread_id: str) -> str:
        if not thread_id:
            return "FAILED: thread_id or message_id is required to read a Gmail thread."
        thread = service.users().threads().get(userId="me", id=thread_id, format="full").execute()
        messages = thread.get("messages", []) or []
        if not messages:
            return f"Gmail thread is empty. id={thread.get('id', thread_id)}"

        lines = [f"Gmail thread: id={thread.get('id', thread_id)} messages={len(messages)}"]
        for message in messages:
            headers = self._headers(message)
            snippet = self._clean_text(message.get("snippet", ""))
            lines.append(
                f"- id={message.get('id')} | from={headers.get('from', '')} | "
                f"date={headers.get('date', '')} | subject={headers.get('subject', '')} | snippet={snippet}"
            )
        return "\n".join(lines)

    def _send(
        self,
        service: Any,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        thread_id: str = "",
    ) -> str:
        if not to or not subject or not body:
            return "FAILED: to, subject, and body are required to send Gmail."
        message: dict[str, Any] = {"raw": self._raw_email(to, subject, body, cc=cc, bcc=bcc)}
        if thread_id:
            message["threadId"] = thread_id
        sent = service.users().messages().send(userId="me", body=message).execute()
        return f"VERIFIED: Gmail sent. id={sent.get('id')} thread={sent.get('threadId', thread_id)}"

    def _draft(
        self,
        service: Any,
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        thread_id: str = "",
    ) -> str:
        if not to or not subject or not body:
            return "FAILED: to, subject, and body are required to create a Gmail draft."
        message: dict[str, Any] = {"raw": self._raw_email(to, subject, body, cc=cc, bcc=bcc)}
        if thread_id:
            message["threadId"] = thread_id
        draft = {"message": message}
        created = service.users().drafts().create(userId="me", body=draft).execute()
        created_message = created.get("message", {}) or {}
        return f"VERIFIED: Gmail draft created. id={created.get('id')} message_id={created_message.get('id', '')}"

    def _reply(
        self,
        service: Any,
        message_id: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        to: str = "",
        subject: str = "",
        send_now: bool = False,
    ) -> str:
        if not message_id or not body:
            return "FAILED: message_id and body are required to reply to Gmail."
        original = service.users().messages().get(
            userId="me",
            id=message_id,
            format="metadata",
            metadataHeaders=["From", "Reply-To", "Subject", "Message-ID", "References"],
        ).execute()
        headers = self._headers(original)
        reply_to = to or headers.get("reply-to") or headers.get("from", "")
        reply_subject = subject or self._reply_subject(headers.get("subject", ""))
        message_headers = {}
        if headers.get("message-id"):
            message_headers["In-Reply-To"] = headers["message-id"]
        references = " ".join(item for item in (headers.get("references", ""), headers.get("message-id", "")) if item)
        if references:
            message_headers["References"] = references
        message: dict[str, Any] = {
            "raw": self._raw_email(reply_to, reply_subject, body, cc=cc, bcc=bcc, headers=message_headers),
            "threadId": original.get("threadId", ""),
        }
        if send_now:
            sent = service.users().messages().send(userId="me", body=message).execute()
            return f"VERIFIED: Gmail reply sent. id={sent.get('id')} thread={sent.get('threadId', original.get('threadId', ''))}"
        created = service.users().drafts().create(userId="me", body={"message": message}).execute()
        created_message = created.get("message", {}) or {}
        return f"VERIFIED: Gmail reply draft created. id={created.get('id')} message_id={created_message.get('id', '')}"

    def _labels(self, service: Any) -> str:
        result = service.users().labels().list(userId="me").execute()
        labels = result.get("labels", []) or []
        if not labels:
            return "No Gmail labels found."
        lines = ["Gmail labels:"]
        for label in sorted(labels, key=lambda item: str(item.get("name", "")).lower()):
            lines.append(f"- id={label.get('id')} | name={label.get('name')} | type={label.get('type', '')}")
        return "\n".join(lines)

    def _profile(self, service: Any) -> str:
        profile = service.users().getProfile(userId="me").execute()
        return (
            "Gmail profile:\n"
            f"email: {profile.get('emailAddress', '')}\n"
            f"messages_total: {profile.get('messagesTotal', '')}\n"
            f"threads_total: {profile.get('threadsTotal', '')}\n"
            f"history_id: {profile.get('historyId', '')}"
        )

    def _modify_labels(
        self,
        service: Any,
        message_id: str,
        add_labels: list[str],
        remove_labels: list[str],
    ) -> str:
        if not message_id:
            return "FAILED: message_id is required to modify Gmail labels."
        if not add_labels and not remove_labels:
            return "FAILED: add_labels or remove_labels is required."
        body = {"addLabelIds": add_labels, "removeLabelIds": remove_labels}
        updated = service.users().messages().modify(userId="me", id=message_id, body=body).execute()
        labels = ", ".join(updated.get("labelIds", []) or [])
        return f"VERIFIED: Gmail labels updated. id={updated.get('id', message_id)} labels={labels or '<none>'}"

    def _trash(self, service: Any, message_id: str) -> str:
        if not message_id:
            return "FAILED: message_id is required to trash Gmail."
        trashed = service.users().messages().trash(userId="me", id=message_id).execute()
        return f"VERIFIED: Gmail message moved to trash. id={trashed.get('id', message_id)}"

    def _untrash(self, service: Any, message_id: str) -> str:
        if not message_id:
            return "FAILED: message_id is required to untrash Gmail."
        restored = service.users().messages().untrash(userId="me", id=message_id).execute()
        return f"VERIFIED: Gmail message restored from trash. id={restored.get('id', message_id)}"

    @staticmethod
    def _raw_email(
        to: str,
        subject: str,
        body: str,
        cc: str = "",
        bcc: str = "",
        headers: dict[str, str] | None = None,
    ) -> str:
        message = EmailMessage()
        message["To"] = to
        if cc:
            message["Cc"] = cc
        if bcc:
            message["Bcc"] = bcc
        message["Subject"] = subject
        for name, value in (headers or {}).items():
            if name and value:
                message[name] = value
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
        html_parts = [part for part in parts if part.get("mimeType") == "text/html"]
        for part in plain_parts or html_parts or parts:
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

    @staticmethod
    def _list_value(value: str | list[str] | None) -> list[str]:
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
    def _clean_text(text: str) -> str:
        return " ".join(str(text or "").split())

    @staticmethod
    def _reply_subject(subject: str) -> str:
        cleaned = str(subject or "").strip()
        if cleaned.lower().startswith("re:"):
            return cleaned
        return f"Re: {cleaned}" if cleaned else "Re:"

    @staticmethod
    def _bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if value in (None, ""):
            return False
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _action(action: str) -> str:
        return str(action or "search").strip().lower().replace("-", "_").replace(" ", "_")

    @staticmethod
    def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))
