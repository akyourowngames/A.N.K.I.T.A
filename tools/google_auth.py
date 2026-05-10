from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from tools.registry import ToolInputError


def dependency_status() -> dict[str, bool]:
    return {
        "googleapiclient": module_available("googleapiclient.discovery"),
        "google_auth_oauthlib": module_available("google_auth_oauthlib.flow"),
        "google_auth_transport": module_available("google.auth.transport.requests"),
        "google_oauth_credentials": module_available("google.oauth2.credentials"),
    }


def google_service(
    api_name: str,
    api_version: str,
    scopes: list[str],
    token_file: str,
    client_secrets_file: str,
    allow_interactive: bool = False,
) -> Any:
    missing = [name for name, available in dependency_status().items() if not available]
    if missing:
        raise ToolInputError("Google API libraries are missing: " + ", ".join(missing))

    from googleapiclient.discovery import build

    credentials = credentials_for(scopes, token_file, client_secrets_file, allow_interactive)
    return build(api_name, api_version, credentials=credentials, cache_discovery=False)


def credentials_for(
    scopes: list[str],
    token_file: str,
    client_secrets_file: str,
    allow_interactive: bool = False,
) -> Any:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = Path(token_file).expanduser()
    client_path = Path(client_secrets_file).expanduser()
    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), scopes)
    if credentials and credentials.valid:
        return credentials
    if credentials and credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        save_token(token_path, credentials)
        return credentials
    if not allow_interactive:
        raise ToolInputError(
            "Google OAuth token is not ready. Connect Google once with a valid client secrets file, then ask again."
        )
    if not client_path.exists():
        raise ToolInputError(f"Google OAuth client secrets file does not exist: {client_path}")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), scopes)
    credentials = flow.run_local_server(port=0)
    save_token(token_path, credentials)
    return credentials


def save_token(path: Path, credentials: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(credentials.to_json(), encoding="utf-8")


def token_status(token_file: str, client_secrets_file: str) -> dict[str, Any]:
    token_path = Path(token_file).expanduser()
    client_path = Path(client_secrets_file).expanduser()
    return {
        "token_file": str(token_path),
        "token_exists": token_path.exists(),
        "client_secrets_file": str(client_path),
        "client_secrets_exists": client_path.exists(),
        "dependencies": dependency_status(),
    }


def module_available(name: str) -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def env_or_config(env_name: str, configured: str, fallback: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    if configured:
        return configured
    return fallback
