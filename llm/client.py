import json
import os
import re
import sys
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_COPILOT_API_BASE_URL = "https://api.individual.githubcopilot.com"
COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_DEVICE_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"

DEFAULT_GROQ_MODEL = "llama-3.1-8b-instant"
DEFAULT_COPILOT_MODEL = "gpt-4o"
DEFAULT_MAX_TOKENS = 2048  # 120 was far too low — tool call JSON alone can exceed 300 tokens
_HTTP = requests.Session()


@dataclass
class LLMRuntime:
    provider: str
    model: str
    api_key: str
    base_url: str
    max_tokens: Optional[int]


def _parse_int(value: str, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except ValueError:
        return fallback
    return max(minimum, min(parsed, maximum))


def _parse_max_tokens(value: str) -> Optional[int]:
    raw = str(value or "").strip().lower()
    if raw in {"auto", "none", "off", "model", "provider", "llm"}:
        return None
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_MAX_TOKENS
    if parsed <= 0:
        return None
    return max(64, min(parsed, 8192))  # Raised cap: 2048 was too low for long tool-call chains


def _env_first(*names: str) -> str:
    for name in names:
        v = os.getenv(name, "").strip()
        if v:
            return v
    return ""


def _cache_path() -> Path:
    return Path(".ankita") / "credentials" / "github-copilot.token.json"


def _github_auth_cache_path() -> Path:
    return Path(".ankita") / "credentials" / "github.device.token.json"


def _load_cached_copilot_token(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    token = str(payload.get("token", "")).strip()
    expires_at = payload.get("expires_at")
    if not token:
        return None
    try:
        expires_num = int(expires_at)
    except (TypeError, ValueError):
        return None
    now = int(time.time())
    if expires_num - now <= 300:
        return None
    return {"token": token, "expires_at": expires_num}


def _load_cached_github_token(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    token = str(payload.get("token", "")).strip()
    return token or None


def _save_cached_github_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"token": token, "updated_at": int(time.time())}, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )


def _github_device_login() -> str:
    body = {
        "client_id": GITHUB_COPILOT_CLIENT_ID,
        "scope": "read:user",
    }
    res = _HTTP.post(
        GITHUB_DEVICE_CODE_URL,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data=body,
        timeout=30,
    )
    res.raise_for_status()
    data = res.json()
    device_code = str(data.get("device_code", "")).strip()
    user_code = str(data.get("user_code", "")).strip()
    verification_uri = str(data.get("verification_uri", "")).strip()
    interval = int(data.get("interval", 5))
    expires_in = int(data.get("expires_in", 900))
    if not device_code or not user_code or not verification_uri:
        raise RuntimeError("GitHub device flow returned invalid response")

    print("\nGitHub Device Login required for Copilot.")
    print(f"Open: {verification_uri}")
    print(f"Code: {user_code}\n")
    try:
        webbrowser.open(verification_uri)
    except Exception:
        pass

    deadline = time.time() + expires_in
    while time.time() < deadline:
        token_res = _HTTP.post(
            GITHUB_DEVICE_TOKEN_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "client_id": GITHUB_COPILOT_CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=30,
        )
        token_res.raise_for_status()
        payload = token_res.json()
        access_token = str(payload.get("access_token", "")).strip()
        if access_token:
            return access_token

        err = str(payload.get("error", "")).strip()
        if err == "authorization_pending":
            time.sleep(max(1, interval))
            continue
        if err == "slow_down":
            time.sleep(max(2, interval + 2))
            continue
        if err == "expired_token":
            break
        if err == "access_denied":
            raise RuntimeError("GitHub device login was denied")
        raise RuntimeError(f"GitHub device login failed: {err or 'unknown_error'}")

    raise RuntimeError("GitHub device code expired. Run again.")


def _derive_copilot_base_url(token: str) -> str:
    m = re.search(r"(?:^|;)\s*proxy-ep=([^;\s]+)", token, flags=re.IGNORECASE)
    if not m:
        return DEFAULT_COPILOT_API_BASE_URL
    host = m.group(1).strip()
    host = re.sub(r"^https?://", "", host, flags=re.IGNORECASE)
    host = re.sub(r"^proxy\.", "api.", host, flags=re.IGNORECASE)
    if not host:
        return DEFAULT_COPILOT_API_BASE_URL
    return f"https://{host}"


def _exchange_github_to_copilot_token(github_token: str, cache_file: Path) -> Dict[str, Any]:
    cached = _load_cached_copilot_token(cache_file)
    if cached:
        return cached

    res = _HTTP.get(
        COPILOT_TOKEN_URL,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {github_token}",
            "User-Agent": "GitHubCopilotChat/0.26.7",
        },
        timeout=30,
    )
    if not res.ok:
        if res.status_code == 404:
            raise RuntimeError(
                "Copilot token exchange failed (HTTP 404). "
                "Your GitHub account likely has no active Copilot access for this token/account."
            )
        raise RuntimeError(f"Copilot token exchange failed: HTTP {res.status_code}")
    data = res.json()
    token = str(data.get("token", "")).strip()
    expires_at_raw = data.get("expires_at")
    if not token:
        raise RuntimeError("Copilot token exchange missing token")
    if expires_at_raw is None:
        raise RuntimeError("Copilot token exchange missing expires_at")
    try:
        expires_at = int(expires_at_raw)
    except (TypeError, ValueError) as err:
        raise RuntimeError("Copilot token exchange has invalid expires_at") from err

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps(
            {
                "token": token,
                "expires_at": expires_at,
            },
            ensure_ascii=True,
            indent=2,
        ),
        encoding="utf-8",
    )
    return {"token": token, "expires_at": expires_at}


def build_runtime_from_env() -> LLMRuntime:
    provider = os.getenv("LLM_PROVIDER", "groq").strip().lower() or "groq"
    max_tokens_raw = _env_first("LLM_MAX_TOKENS", "GROQ_MAX_TOKENS", "COPILOT_MAX_TOKENS")
    max_tokens = _parse_max_tokens(max_tokens_raw or "auto")

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "").strip()
        if not api_key:
            print("Error: GROQ_API_KEY is not set.")
            print("Set it in .env or shell env.")
            sys.exit(1)
        model = os.getenv("GROQ_MODEL", DEFAULT_GROQ_MODEL).strip() or DEFAULT_GROQ_MODEL
        base_url = os.getenv("GROQ_BASE_URL", GROQ_BASE_URL).strip() or GROQ_BASE_URL
        return LLMRuntime(
            provider="groq",
            model=model,
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            max_tokens=max_tokens,
        )

    if provider == "copilot":
        try:
            copilot_api_key = os.getenv("COPILOT_API_KEY", "").strip()
            if copilot_api_key:
                token = copilot_api_key
            else:
                github_token = _env_first("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
                if not github_token:
                    github_token = _load_cached_github_token(_github_auth_cache_path()) or ""
                if not github_token:
                    # Only do interactive device login as last resort
                    github_token = _github_device_login()
                    _save_cached_github_token(_github_auth_cache_path(), github_token)
                # Always delete stale copilot token so _exchange re-fetches if needed
                cache = _cache_path()
                existing = _load_cached_copilot_token(cache)
                if existing is None and cache.exists():
                    # Token file exists but is expired — delete it so exchange runs fresh
                    try:
                        cache.unlink()
                    except Exception:
                        pass
                token_payload = _exchange_github_to_copilot_token(github_token, cache)
                token = str(token_payload["token"])
        except Exception as err:
            print(f"Error: {err}")
            print("Tip: ensure the signed-in GitHub account has active Copilot access.")
            sys.exit(1)

        derived_base = _derive_copilot_base_url(token)
        base_url = os.getenv("COPILOT_BASE_URL", "").strip() or derived_base
        model = os.getenv("COPILOT_MODEL", DEFAULT_COPILOT_MODEL).strip() or DEFAULT_COPILOT_MODEL
        return LLMRuntime(
            provider="copilot",
            model=model,
            api_key=token,
            base_url=base_url.rstrip("/"),
            max_tokens=max_tokens,
        )

    print(f"Error: unsupported LLM_PROVIDER '{provider}'. Use 'groq' or 'copilot'.")
    sys.exit(1)


def call_chat_with_image(
    runtime: LLMRuntime,
    prompt: str,
    image_b64: str,
    max_tokens: Optional[int] = None,
    temperature: float = 0.0,
) -> str:
    """Send a single vision request to GPT-4o with an inline base64 image.

    This is used internally by the ScreenAgent tools (capture_screen / visual_click)
    to let the model *look* at a screenshot and return a text answer.

    Args:
        runtime:    The active LLMRuntime (must be a model that supports vision, e.g. gpt-4o).
        prompt:     The text instruction to accompany the image.
        image_b64:  Base64-encoded PNG/JPEG image string (no data URI prefix needed).
        max_tokens: Optional token cap. Falls back to runtime.max_tokens.

    Returns:
        The model's text reply (string).
    """
    url = f"{runtime.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {runtime.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if runtime.provider == "copilot":
        headers["Editor-Version"] = "vscode/1.96.2"
        headers["User-Agent"] = "GitHubCopilotChat/0.26.7"
        headers["Editor-Plugin-Version"] = "copilot-chat/0.26.7"
        headers["Copilot-Integration-Id"] = "vscode-chat"
        headers["OpenAI-Intent"] = "conversation-panel"

    vision_message = {
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_b64}",
                    "detail": "high",
                },
            },
        ],
    }

    tokens = max_tokens if isinstance(max_tokens, int) and max_tokens > 0 else runtime.max_tokens
    payload: Dict[str, Any] = {
        "model": runtime.model,
        "messages": [vision_message],
        "temperature": temperature,  # 0.0 for coordinate tasks (deterministic), 0.7 for descriptive
    }
    if isinstance(tokens, int) and tokens > 0:
        if runtime.provider == "copilot":
            payload["max_completion_tokens"] = tokens
        else:
            payload["max_tokens"] = tokens

    response = _HTTP.post(url, headers=headers, json=payload, timeout=60)
    response.raise_for_status()
    data = response.json()
    content = data["choices"][0]["message"].get("content") or ""
    return content.strip()


def call_chat_once(
    runtime: LLMRuntime,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    max_tokens: Optional[int],
) -> Dict[str, Any]:
    url = f"{runtime.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {runtime.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if runtime.provider == "copilot":
        headers["Editor-Version"] = "vscode/1.96.2"
        headers["User-Agent"] = "GitHubCopilotChat/0.26.7"
        headers["Editor-Plugin-Version"] = "copilot-chat/0.26.7"
        headers["Copilot-Integration-Id"] = "vscode-chat"
        headers["OpenAI-Intent"] = "conversation-panel"

    payload: Dict[str, Any] = {
        "model": runtime.model,
        "messages": messages,
        "temperature": 0.2,
    }
    if isinstance(max_tokens, int) and max_tokens > 0:
        if runtime.provider == "copilot":
            payload["max_completion_tokens"] = max_tokens
        else:
            payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    # Configurable per-request timeout
    request_timeout = int(os.getenv("LLM_REQUEST_TIMEOUT_SEC", "45"))

    # Exponential backoff with jitter for transient errors (429, 502, 503, 504)
    _RETRYABLE = {429, 502, 503, 504}
    max_retries = 3
    for attempt in range(max_retries + 1):
        try:
            response = _HTTP.post(url, headers=headers, json=payload, timeout=request_timeout)
            if response.status_code in _RETRYABLE and attempt < max_retries:
                # Exponential backoff: 1s, 2s, 4s + jitter
                delay = (2 ** attempt) + (hash(str(time.time())) % 100) / 100.0
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        pass
                time.sleep(delay)
                continue
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]
        except requests.exceptions.Timeout:
            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            raise
        except requests.HTTPError:
            raise  # Don't retry non-retryable HTTP errors
    # Should never reach here, but satisfy type checker
    raise RuntimeError("call_chat_once: exhausted retries")
