from __future__ import annotations

import os
from pathlib import Path
from typing import Any


DEFAULT_TOKEN_FILE = "memory/store/google-token.json"
DEFAULT_CLIENT_SECRET_FILE = "secrets/google-client-secret.json"


def google_service(api_name: str, api_version: str, scopes: list[str]) -> tuple[Any | None, str | None]:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as error:
        return None, (
            "FAILED: Google API libraries are not installed.\n"
            "Install with: pip install google-api-python-client google-auth google-auth-oauthlib google-auth-httplib2\n"
            f"Import error: {error}"
        )

    token_path = Path(os.getenv("GOOGLE_TOKEN_FILE", DEFAULT_TOKEN_FILE))
    client_secret_path = Path(os.getenv("GOOGLE_CLIENT_SECRET_FILE", DEFAULT_CLIENT_SECRET_FILE))
    token_path.parent.mkdir(parents=True, exist_ok=True)

    credentials = None
    if token_path.exists():
        try:
            credentials = Credentials.from_authorized_user_file(str(token_path), scopes)
        except Exception:
            credentials = None

    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_path.write_text(credentials.to_json(), encoding="utf-8")

    if not credentials or not credentials.valid:
        if not client_secret_path.exists():
            return None, (
                "FAILED: Google OAuth client secret file is missing.\n"
                f"Expected: {client_secret_path}\n"
                "Next step: place the Desktop OAuth JSON there or set GOOGLE_CLIENT_SECRET_FILE."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), scopes)
        credentials = flow.run_local_server(port=0)
        token_path.write_text(credentials.to_json(), encoding="utf-8")

    return build(api_name, api_version, credentials=credentials), None
