"""
EmailWatcher — Gmail Sentinel for A.N.K.I.T.A.

Polls Gmail for new important emails and alerts on priority senders,
urgent subjects, and keyword matches. Summarises email content.

Config (email_config.json):
    {
        "enabled": true,
        "poll_interval_sec": 120,
        "max_results": 10,
        "vip_senders": ["boss@company.com", "mom"],
        "urgent_keywords": ["urgent", "asap", "deadline", "action required", "important"],
        "label_filter": "INBOX",
        "credentials_file": "client_secret_....json",
        "token_file": ".ankita/gmail_token.json",
        "cooldown_sec": 60,
        "summarise_with_llm": false
    }

Requires: google-auth, google-auth-oauthlib, google-api-python-client
    pip install google-auth google-auth-oauthlib google-api-python-client
"""
from __future__ import annotations

import base64
import json
import re
import time
from typing import Any, Dict, List, Optional, Set
from pathlib import Path

from watchdog_manager import BaseWatcher
from proactive import ProactiveEngine


class EmailWatcher(BaseWatcher):
    """
    Monitors Gmail inbox for new priority emails.

    - Detects emails from VIP senders
    - Scans subject lines for urgent keywords
    - Deduplicates across restarts using message IDs
    - Optionally summarises email body with LLM
    """

    def __init__(
        self,
        config: Dict[str, Any],
        proactive: ProactiveEngine,
        workspace_root: Path,
    ) -> None:
        super().__init__(
            name="EmailWatcher",
            config=config,
            proactive=proactive,
            workspace_root=workspace_root,
        )
        self.poll_interval = float(config.get("poll_interval_sec", 120))
        self.max_results = int(config.get("max_results", 10))
        self.vip_senders = [s.lower() for s in config.get("vip_senders", [])]
        self.urgent_keywords = [
            kw.lower() for kw in config.get("urgent_keywords", [
                "urgent", "asap", "deadline", "action required",
                "important", "critical", "immediately", "emergency",
            ])
        ]
        self.label_filter = config.get("label_filter", "INBOX")
        self.cooldown_sec = float(config.get("cooldown_sec", 60))
        self.summarise = config.get("summarise_with_llm", False)

        # Resolve credentials
        creds_name = config.get("credentials_file", "")
        if creds_name:
            self.credentials_file = workspace_root / creds_name
        else:
            matches = list(workspace_root.glob("client_secret_*.json"))
            self.credentials_file = matches[0] if matches else None

        token_rel = config.get("token_file", ".ankita/gmail_token.json")
        self.token_file = workspace_root / token_rel

        # State
        self.state.setdefault("seen_message_ids", [])   # list of str (capped at 2000)
        self.state.setdefault("last_alert_time", {})

        self._seen_ids: Set[str] = set(self.state.get("seen_message_ids", []))
        self._service = None

    # ------------------------------------------------------------------
    # Main check
    # ------------------------------------------------------------------

    def _check(self) -> Optional[str]:
        service = self._get_service()
        if service is None:
            return None

        try:
            results = service.users().messages().list(
                userId="me",
                labelIds=[self.label_filter],
                maxResults=self.max_results,
                q="is:unread",
            ).execute()
        except Exception as exc:
            print(f"[EmailWatcher] Failed to list messages: {exc}", flush=True)
            return None

        messages = results.get("messages", [])
        if not messages:
            self._save_state()
            return None

        alerts: List[str] = []

        for msg_stub in messages:
            msg_id = msg_stub.get("id", "")
            if msg_id in self._seen_ids:
                continue

            # Fetch message details
            try:
                msg = service.users().messages().get(
                    userId="me", id=msg_id, format="metadata",
                    metadataHeaders=["From", "Subject", "Date"],
                ).execute()
            except Exception as exc:
                print(f"[EmailWatcher] Failed to fetch message {msg_id}: {exc}", flush=True)
                continue

            self._seen_ids.add(msg_id)

            # Parse headers
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            from_raw = headers.get("from", "")
            subject = headers.get("subject", "(no subject)")
            date_str = headers.get("date", "")
            snippet = msg.get("snippet", "")

            # Clean up sender
            sender_name, sender_email = self._parse_sender(from_raw)

            # Determine priority
            is_vip = self._is_vip(sender_name, sender_email)
            is_urgent = self._is_urgent(subject, snippet)

            if not (is_vip or is_urgent):
                # Not interesting enough to alert on
                continue

            # Build alert
            priority_tag = "🔴 VIP" if is_vip else ("🟡 URGENT" if is_urgent else "📧")
            alert_lines = [
                f"📧 {priority_tag} New email from **{sender_name or sender_email}**",
                f"   Subject: {subject}",
            ]
            if snippet:
                clean_snippet = snippet[:150].replace("\n", " ").strip()
                alert_lines.append(f"   Preview: {clean_snippet}…")

            alerts.append("\n".join(alert_lines))

        # Update state
        seen_list = list(self._seen_ids)
        self.state["seen_message_ids"] = seen_list[-2000:]  # cap at 2000
        self._save_state()

        if not alerts:
            return None

        count = len(alerts)
        header = f"📬 {count} new priority email{'s' if count > 1 else ''}!\n"
        return header + "\n\n".join(alerts[:5])  # cap at 5 per cycle

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_service(self):
        """Lazy-init Gmail API service with OAuth2."""
        if self._service is not None:
            return self._service
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build  # type: ignore

            SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
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
                    print(
                        "[EmailWatcher] No Gmail credentials found — skipping. "
                        "Add client_secret_*.json to workspace root.",
                        flush=True,
                    )
                    return None

                self.token_file.parent.mkdir(parents=True, exist_ok=True)
                self.token_file.write_text(creds.to_json())

            self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
            print("[EmailWatcher] ✅ Gmail API connected.", flush=True)
            return self._service

        except ImportError:
            print(
                "[EmailWatcher] google-api-python-client not installed. "
                "Run: pip install google-auth google-auth-oauthlib google-api-python-client",
                flush=True,
            )
            return None
        except Exception as exc:
            print(f"[EmailWatcher] Auth failed: {exc}", flush=True)
            return None

    def _parse_sender(self, from_raw: str):
        """Parse 'Name <email@domain.com>' into (name, email)."""
        match = re.match(r'^"?([^"<]+)"?\s*<([^>]+)>', from_raw)
        if match:
            return match.group(1).strip(), match.group(2).strip().lower()
        if "@" in from_raw:
            return "", from_raw.strip().lower()
        return from_raw.strip(), ""

    def _is_vip(self, name: str, email: str) -> bool:
        """Check if sender matches any VIP pattern."""
        if not self.vip_senders:
            return False
        name_lower = name.lower()
        email_lower = email.lower()
        return any(
            vip in name_lower or vip in email_lower
            for vip in self.vip_senders
        )

    def _is_urgent(self, subject: str, snippet: str) -> bool:
        """Check if subject or snippet contains urgent keywords."""
        text = (subject + " " + snippet).lower()
        return any(kw in text for kw in self.urgent_keywords)

    def get_unread_count(self) -> str:
        """Return unread email count (callable by WatchdogAgent)."""
        service = self._get_service()
        if service is None:
            return "Gmail not configured."
        try:
            result = service.users().labels().get(userId="me", id="INBOX").execute()
            unread = result.get("messagesUnread", 0)
            total = result.get("messagesTotal", 0)
            return f"📬 Inbox: {unread} unread / {total} total"
        except Exception as e:
            return f"Failed to get inbox stats: {e}"
