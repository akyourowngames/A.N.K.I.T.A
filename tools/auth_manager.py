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
    "https://www.googleapis.com/auth/spreadsheets",   # Read + write cells in any sheet
    "https://www.googleapis.com/auth/drive.file",      # Access files the app created (required for logging data)
    "https://www.googleapis.com/auth/drive.readonly",  # Read any Drive file (for opening existing sheets by name)
    "https://www.googleapis.com/auth/youtube",         # YouTube read/write
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

def _get_google_client_secret_file() -> Optional[Path]:
    """
    Locate the Google OAuth2 client_secret JSON file.

    Search order:
      1. GOOGLE_CLIENT_SECRET_FILE env var
      2. Any client_secret_*.json file in the project root (same dir as this file's parent)
      3. Any client_secret_*.json file in the current working directory
    """
    # 1. Explicit env var
    env_path = os.environ.get("GOOGLE_CLIENT_SECRET_FILE", "").strip()
    if env_path and Path(env_path).exists():
        return Path(env_path)

    # 2. Project root (parent of tools/)
    project_root = Path(__file__).parent.parent
    candidates = sorted(project_root.glob("client_secret*.json"))
    if candidates:
        return candidates[0]

    # 3. CWD
    candidates = sorted(Path.cwd().glob("client_secret*.json"))
    if candidates:
        return candidates[0]

    return None


def _get_google_client_config() -> Optional[Dict[str, Any]]:
    """
    Return the Google OAuth2 client config from env vars or a JSON file.
    Users can set:
      GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET  (minimal)
    or:
      GOOGLE_CLIENT_SECRET_FILE=/path/to/client_secret.json
    or just drop a client_secret_*.json file in the project root.
    """
    secret_file = _get_google_client_secret_file()
    if secret_file:
        raw = json.loads(secret_file.read_text(encoding="utf-8"))
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
            "redirect_uris": ["http://localhost"],
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
        secret_file = _get_google_client_secret_file()
        raise RuntimeError(
            "Google client config not found.\n"
            f"Searched for client_secret*.json in project root — not found.\n"
            "Options:\n"
            "  1. Drop your client_secret_*.json file into the A.N.K.I.T.A folder\n"
            "  2. Set GOOGLE_CLIENT_SECRET_FILE=/path/to/file in your .env\n"
            "  3. Set GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET in your .env"
        )

    secret_file = _get_google_client_secret_file()

    print("\n🔐 ANKITA needs Google permission (one-time setup).")
    print("   A browser window will open — sign in and allow access.")
    print("   (This only happens once — tokens are saved for future use)\n")

    if secret_file:
        # Preferred: use the actual JSON file — most reliable
        flow = InstalledAppFlow.from_client_secrets_file(
            str(secret_file), scopes=GOOGLE_SCOPES
        )
    else:
        client_config = {
            "installed": {
                **cfg,
                "redirect_uris": cfg.get("redirect_uris", ["http://localhost"]),
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, scopes=GOOGLE_SCOPES)

    # run_local_server(port=0) picks a random free port on localhost.
    # Google allows any port on http://localhost for "Desktop app" / installed OAuth clients.
    # This opens the browser automatically — no manual code pasting needed.
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        access_type="offline",
        success_message=(
            "✅ ANKITA authorised! You can close this tab and return to ANKITA."
        ),
        open_browser=True,
    )

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


# ---------------------------------------------------------------------------
# GitHub OAuth — Device Authorization Grant (RFC 8628)
# ---------------------------------------------------------------------------

# Scopes needed for GitWatcher API calls (repos, PRs, issues)
_GITHUB_SCOPES = "repo read:user"

# GitHub OAuth App client ID for the device flow
# Uses the same client ID as Copilot device login (public, registered by GitHub)
_GITHUB_CLIENT_ID = "Iv1.b507a08c87ecfe98"

_GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
_GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"

# Cache file for the GitHub personal access token obtained via device flow
_GITHUB_TOKEN_CACHE = _VAULT_DIR / "credentials" / "github.api.token.json"


def _load_github_token_cache() -> Optional[str]:
    """Load the cached GitHub API token from disk."""
    if not _GITHUB_TOKEN_CACHE.exists():
        return None
    try:
        data = json.loads(_GITHUB_TOKEN_CACHE.read_text(encoding="utf-8"))
        token = str(data.get("token", "")).strip()
        return token or None
    except Exception:
        return None


def _save_github_token_cache(token: str) -> None:
    """Persist the GitHub API token to disk."""
    _GITHUB_TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _GITHUB_TOKEN_CACHE.write_text(
        json.dumps({"token": token, "updated_at": __import__("time").time()}, indent=2),
        encoding="utf-8",
    )


def get_github_token(force_reauth: bool = False) -> str:
    """
    Return a valid GitHub personal access token.

    Priority:
      1. GITHUB_TOKEN / GH_TOKEN env var (plain token, no expiry check)
      2. Cached token from ~/.ankita/credentials/github.api.token.json
      3. Interactive GitHub Device Flow (opens browser, user enters code)

    Pass force_reauth=True to skip cache and run Device Flow again
    (useful when the cached token has expired).

    Saves the new token to the cache file so future calls are instant.
    """
    import time
    import webbrowser

    if not force_reauth:
        # 1. Env var
        for env_name in ("GITHUB_TOKEN", "GH_TOKEN"):
            token = os.environ.get(env_name, "").strip()
            if token:
                return token

        # 2. Cache
        cached = _load_github_token_cache()
        if cached:
            return cached

    # 3. GitHub Device Authorization Grant
    try:
        import urllib.request
        import urllib.parse

        body = urllib.parse.urlencode({
            "client_id": _GITHUB_CLIENT_ID,
            "scope": _GITHUB_SCOPES,
        }).encode()

        req = urllib.request.Request(
            _GITHUB_DEVICE_CODE_URL,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())

    except Exception as exc:
        raise RuntimeError(f"GitHub device flow initiation failed: {exc}") from exc

    device_code = str(data.get("device_code", "")).strip()
    user_code = str(data.get("user_code", "")).strip()
    verification_uri = str(data.get("verification_uri", "https://github.com/login/device")).strip()
    interval = int(data.get("interval", 5))
    expires_in = int(data.get("expires_in", 900))

    if not device_code or not user_code:
        raise RuntimeError(f"GitHub device flow returned invalid response: {data}")

    # Inform the user
    print("\n🔐 GitHub Re-Authorization Required")
    print("─" * 40)
    print(f"  1. Open:  {verification_uri}")
    print(f"  2. Enter: {user_code}")
    print("─" * 40)
    try:
        webbrowser.open(verification_uri)
        print("  (Browser opened automatically — paste the code above if prompted)")
    except Exception:
        print("  (Could not open browser — please open the URL manually)")
    print()

    # Poll until authorized or expired
    import time as _time
    deadline = _time.time() + expires_in
    while _time.time() < deadline:
        _time.sleep(max(1, interval))
        try:
            import urllib.request as _req
            poll_body = urllib.parse.urlencode({
                "client_id": _GITHUB_CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            }).encode()
            poll_req = _req.Request(
                _GITHUB_TOKEN_URL,
                data=poll_body,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            with _req.urlopen(poll_req, timeout=30) as poll_resp:
                poll_data = json.loads(poll_resp.read())
        except Exception:
            continue

        access_token = str(poll_data.get("access_token", "")).strip()
        if access_token:
            _save_github_token_cache(access_token)
            # Also update the vault for backward compat
            vault = _load_vault()
            vault.setdefault("github", {})["access_token"] = access_token
            _save_vault(vault)
            # Also update llm/client.py's device token cache so Copilot LLM re-auth
            # works with the same token (both GitWatcher API + Copilot exchange use it)
            try:
                import json as _json
                import time as _time
                _llm_cache = Path(".ankita") / "credentials" / "github.device.token.json"
                _llm_cache.parent.mkdir(parents=True, exist_ok=True)
                _llm_cache.write_text(
                    _json.dumps({"token": access_token, "updated_at": int(_time.time())}, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                pass  # Non-fatal — llm cache update is best-effort
            print("✅ GitHub authorized! Token saved for both GitWatcher and Copilot LLM.")
            return access_token

        err = str(poll_data.get("error", "")).strip()
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err == "expired_token":
            break
        if err == "access_denied":
            raise RuntimeError("GitHub authorization was denied by the user.")
        raise RuntimeError(f"GitHub device flow error: {err or poll_data}")

    raise RuntimeError("GitHub device code expired. Please try again.")


def revoke_github_token() -> None:
    """
    Clear the cached GitHub token so the next call triggers a fresh Device Flow.
    Does NOT actually revoke the token on GitHub's side
    (use github.com/settings/tokens for that).
    """
    if _GITHUB_TOKEN_CACHE.exists():
        try:
            _GITHUB_TOKEN_CACHE.unlink()
        except Exception:
            pass
    vault = _load_vault()
    vault.pop("github", None)
    _save_vault(vault)
    print("🗑️  GitHub token cleared. Next use will trigger re-authorization.")


def github_token_status() -> str:
    """Return a human-readable string showing the current GitHub token state."""
    # Check env var
    for env_name in ("GITHUB_TOKEN", "GH_TOKEN"):
        token = os.environ.get(env_name, "").strip()
        if token:
            return f"✅ GitHub token active (from env var {env_name}, {len(token)} chars)"

    # Check cache
    cached = _load_github_token_cache()
    if cached:
        # Show last 4 chars for identification
        return f"✅ GitHub token cached ({len(cached)} chars, ends …{cached[-4:]})"

    # Check vault fallback
    vault_token = _load_vault().get("github", {}).get("access_token", "")
    if vault_token:
        return f"✅ GitHub token in vault ({len(vault_token)} chars, ends …{vault_token[-4:]})"

    return "❌ No GitHub token found — run /reauth github to authorize."
