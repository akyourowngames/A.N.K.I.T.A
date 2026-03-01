"""
Auth Manager for A.N.K.I.T.A — Passport Control 🛂

Central store for OAuth2 tokens and API keys.
Handles:
  - First-time CLI OAuth2 flow (prints URL, user pastes code)
  - Refresh token persistence in ~/.ankita/tokens.json
  - Auto-refresh of expired Google tokens
  - Figma Personal Access Token storage
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Token vault path
# ---------------------------------------------------------------------------
_VAULT_DIR  = Path.home() / ".ankita"
_VAULT_FILE = _VAULT_DIR / "tokens.json"

# ---------------------------------------------------------------------------
# Google OAuth2 scopes
# ---------------------------------------------------------------------------
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/youtube",
]


def _load_vault() -> Dict[str, Any]:
    """Load the token vault from disk (returns empty dict if missing)."""
    if _VAULT_FILE.exists():
        try:
            return json.loads(_VAULT_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_vault(data: Dict[str, Any]) -> None:
    """Persist the token vault to disk."""
    _VAULT_DIR.mkdir(parents=True, exist_ok=True)
    _VAULT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Google OAuth2 helpers
# ---------------------------------------------------------------------------

def _get_google_client_config() -> Optional[Dict[str, Any]]:
    """
    Return the Google OAuth2 client config from env vars or a JSON file.
    Users can set:
      GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET  (minimal)
    or:
      GOOGLE_CLIENT_SECRET_FILE=/path/to/client_secret.json
    """
    secret_file = os.environ.get("GOOGLE_CLIENT_SECRET_FILE")
    if secret_file and Path(secret_file).exists():
        raw = json.loads(Path(secret_file).read_text(encoding="utf-8"))
        # Support both 'installed' and 'web' app types
        cfg = raw.get("installed") or raw.get("web")
        if cfg:
            return cfg

    client_id     = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    if client_id and client_secret:
        return {
            "client_id":     client_id,
            "client_secret": client_secret,
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     "https://oauth2.googleapis.com/token",
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
        }
    return None


def get_google_credentials():
    """
    Return a valid google.oauth2.credentials.Credentials object.

    Flow:
      1. Load refresh_token from vault — if found, build Credentials and refresh.
      2. If not found, run CLI OAuth2 flow (print URL, ask user for code).
      3. Save refresh_token to vault for future use.

    Raises RuntimeError if client config is missing.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise RuntimeError(
            "Google auth libraries not installed. "
            "Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        )

    vault = _load_vault()
    google_data = vault.get("google", {})

    # Try to restore from saved refresh token
    if google_data.get("refresh_token"):
        cfg = _get_google_client_config()
        if cfg:
            creds = Credentials(
                token=google_data.get("access_token"),
                refresh_token=google_data["refresh_token"],
                token_uri=cfg["token_uri"],
                client_id=cfg["client_id"],
                client_secret=cfg["client_secret"],
                scopes=GOOGLE_SCOPES,
            )
            # Auto-refresh if expired
            if not creds.valid:
                creds.refresh(Request())
                vault["google"]["access_token"] = creds.token
                _save_vault(vault)
            return creds

    # First-time flow — need client config
    cfg = _get_google_client_config()
    if not cfg:
        raise RuntimeError(
            "Google client config not found.\n"
            "Set GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET in your .env, "
            "or set GOOGLE_CLIENT_SECRET_FILE=/path/to/client_secret.json"
        )

    client_config = {
        "installed": {
            **cfg,
            "redirect_uris": cfg.get("redirect_uris", ["urn:ietf:wg:oauth:2.0:oob"]),
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=GOOGLE_SCOPES)

    # CLI-friendly: print URL, ask user to paste the auth code
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")
    print("\n🔐 ANKITA needs Google permission (one-time setup).")
    print(f"   👉 Open this URL in your browser:\n\n   {auth_url}\n")
    code = input("   Paste the authorisation code here: ").strip()

    flow.fetch_token(code=code)
    creds = flow.credentials

    # Persist refresh token
    vault["google"] = {
        "access_token":  creds.token,
        "refresh_token": creds.refresh_token,
    }
    _save_vault(vault)
    print("✅ Google authorised! Token saved — you won't need to do this again.")
    return creds


# ---------------------------------------------------------------------------
# Figma PAT helper
# ---------------------------------------------------------------------------

def get_figma_token() -> str:
    """
    Return the Figma Personal Access Token.

    Priority:
      1. FIGMA_ACCESS_TOKEN env var
      2. Vault (previously saved)
      3. Ask user to paste it (saved to vault)
    """
    token = os.environ.get("FIGMA_ACCESS_TOKEN")
    if token:
        return token

    vault = _load_vault()
    token = vault.get("figma", {}).get("access_token")
    if token:
        return token

    print("\n🔐 ANKITA needs your Figma Personal Access Token (one-time setup).")
    print("   Generate one at: https://www.figma.com/settings → Personal access tokens")
    token = input("   Paste your Figma token here: ").strip()

    vault.setdefault("figma", {})["access_token"] = token
    _save_vault(vault)
    print("✅ Figma token saved!")
    return token


# ---------------------------------------------------------------------------
# Vault utilities (for future services)
# ---------------------------------------------------------------------------

def save_token(service: str, key: str, value: str) -> None:
    """Generic helper to persist any token to the vault."""
    vault = _load_vault()
    vault.setdefault(service, {})[key] = value
    _save_vault(vault)


def load_token(service: str, key: str) -> Optional[str]:
    """Generic helper to read a token from the vault."""
    return _load_vault().get(service, {}).get(key)


def revoke_token(service: str) -> None:
    """Remove all tokens for a given service from the vault."""
    vault = _load_vault()
    vault.pop(service, None)
    _save_vault(vault)
    print(f"🗑️  Tokens for '{service}' removed from vault.")
