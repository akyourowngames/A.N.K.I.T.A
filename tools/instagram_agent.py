from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from tools.path_resolver import resolve_local_path
from tools.registry import ToolInputError, optional_text, require_text


DEFAULT_CONFIG_PATH = Path("config/instagram_agent.json")


def instagram_status(_params: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_config()
    session_file = session_path(config)
    available = instagrapi_available()
    username_ready = bool(instagram_username(config))
    session_ready = session_file.exists()
    ready = available and username_ready and session_ready
    status_text = instagram_status_text(ready, available, username_ready, session_ready, dry_run_enabled(config))
    return {
        "summary": status_text,
        "status_text": status_text,
        "ready": ready,
        "config_path": str(config_path()),
        "instagrapi_available": available,
        "username_configured": username_ready,
        "session_file": str(session_file),
        "session_exists": session_ready,
        "dry_run": dry_run_enabled(config),
        "monitored_profiles": text_list(config.get("monitored_profiles")),
    }


def instagram_status_text(ready: bool, available: bool, username_ready: bool, session_ready: bool, dry_run: bool) -> str:
    if ready:
        mode = "dry-run mode is on" if dry_run else "live account actions are enabled"
        return f"Instagram is connected; {mode}."
    missing = []
    if not available:
        missing.append("instagrapi package")
    if not username_ready:
        missing.append("username")
    if not session_ready:
        missing.append("saved session")
    missing_text = ", ".join(missing) if missing else "connection readiness"
    return f"Instagram is not connected yet. Missing: {missing_text}. Dry-run mode is {'on' if dry_run else 'off'}."


def instagram_config(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    if operation == "get":
        return {"summary": f"Instagram config: {config_path()}", "config": public_config(config)}
    if operation == "update":
        values = params.get("values", {})
        if not isinstance(values, dict):
            raise ToolInputError("values must be an object")
        merge_config(config, values)
        save_config(config)
        return {"summary": f"Updated Instagram config: {config_path()}", "config": public_config(config)}
    raise ToolInputError(f"Unsupported Instagram config operation: {operation}")


def instagram_manage(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    if operation == "auth_login":
        client = instagram_client(config, login=True, two_factor_code=optional_text(params, "two_factor_code"))
        return {"summary": "Instagram session saved.", "operation": operation, "account": account_summary(client)}
    if operation == "own_summary":
        client = instagram_client(config)
        username = instagram_username(config)
        return {"summary": "Instagram account summary read.", "operation": operation, "profile": profile_summary(client, username)}
    if operation == "profile":
        client = instagram_client(config)
        username = require_text(params, "username")
        return {"summary": f"Instagram profile read: {username}", "operation": operation, "profile": profile_summary(client, username)}
    if operation == "recent_posts":
        client = instagram_client(config)
        username = require_text(params, "username")
        amount = bounded_int(params.get("amount"), 1, 50, bounded_int(config.get("default_post_limit"), 1, 50, 5))
        return {
            "summary": f"Instagram recent posts read: {username}",
            "operation": operation,
            "username": username,
            "posts": recent_posts(client, username, amount),
        }
    if operation == "monitor_profiles":
        client = instagram_client(config)
        usernames = request_usernames(params, config)
        amount = bounded_int(params.get("amount"), 1, 20, bounded_int(config.get("default_post_limit"), 1, 20, 3))
        profiles = []
        for username in usernames:
            profiles.append({"username": username, "profile": profile_summary(client, username), "recent_posts": recent_posts(client, username, amount)})
        return {"summary": f"Instagram monitor checked {len(profiles)} profile(s).", "operation": operation, "profiles": profiles}
    if operation == "post_photo":
        path = resolve_local_path(require_text(params, "path"))
        caption = optional_text(params, "caption")
        if dry_run_enabled(config):
            return {"summary": "No Instagram photo was posted; dry-run prepared the post only.", "safe_user_output": f"No external action happened. Prepared only: Instagram photo post from {path.name}.", "operation": operation, "dry_run": True, "action_completed": False, "external_state_changed": False, "path": str(path), "caption": caption}
        client = instagram_client(config)
        sleep_for_rate_limit(config)
        result = client.photo_upload(str(path), caption)
        return {"summary": "Instagram photo posted.", "operation": operation, "dry_run": False, "media": model_summary(result)}
    if operation == "like_media":
        media_id = require_text(params, "media_id")
        if dry_run_enabled(config):
            return {"summary": "No Instagram media was liked; dry-run prepared the like only.", "safe_user_output": f"No external action happened. Prepared only: Instagram like for media {media_id}.", "operation": operation, "dry_run": True, "action_completed": False, "external_state_changed": False, "media_id": media_id}
        client = instagram_client(config)
        sleep_for_rate_limit(config)
        result = client.media_like(media_id)
        return {"summary": "Instagram media liked.", "operation": operation, "dry_run": False, "result": bool(result)}
    if operation == "comment_media":
        media_id = require_text(params, "media_id")
        text = require_text(params, "text")
        if dry_run_enabled(config):
            return {"summary": "No Instagram comment was posted; dry-run prepared the comment only.", "safe_user_output": f"No external action happened. Prepared only: Instagram comment for media {media_id}.", "operation": operation, "dry_run": True, "action_completed": False, "external_state_changed": False, "media_id": media_id, "text": text}
        client = instagram_client(config)
        sleep_for_rate_limit(config)
        result = client.media_comment(media_id, text)
        return {"summary": "Instagram comment posted.", "operation": operation, "dry_run": False, "comment": model_summary(result)}
    if operation == "dm":
        text = require_text(params, "text")
        user_ids = text_list(params.get("user_ids"))
        if not user_ids:
            raise ToolInputError("user_ids must contain at least one Instagram user id")
        if dry_run_enabled(config):
            return {"summary": "No Instagram DM was sent; dry-run prepared the message only.", "safe_user_output": "No external action happened. Prepared only: Instagram DM.", "operation": operation, "dry_run": True, "action_completed": False, "external_state_changed": False, "user_ids": user_ids, "text": text}
        client = instagram_client(config)
        sleep_for_rate_limit(config)
        result = client.direct_send(text, user_ids)
        return {"summary": "Instagram DM sent.", "operation": operation, "dry_run": False, "result": model_summary(result)}
    raise ToolInputError(f"Unsupported Instagram operation: {operation}")


def config_path() -> Path:
    value = os.environ.get("JARVIS_INSTAGRAM_CONFIG", "").strip()
    return Path(value) if value else DEFAULT_CONFIG_PATH


def load_config() -> dict[str, Any]:
    path = config_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            ensure_config_shape(data)
            return data
    data = default_config()
    save_config(data)
    return data


def save_config(config: dict[str, Any]) -> None:
    ensure_config_shape(config)
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


def default_config() -> dict[str, Any]:
    return {
        "agent_name": "Codex Instagram Agent",
        "dry_run": True,
        "session_file": "media/instagram/session.json",
        "default_post_limit": 5,
        "rate_limit_seconds": 2.0,
        "monitored_profiles": [],
        "notes": [
            "Use official Meta APIs where available for production accounts.",
            "Session-based automation can violate platform rules; keep dry-run on until the user intentionally enables live actions.",
        ],
    }


def ensure_config_shape(config: dict[str, Any]) -> None:
    fallback = default_config()
    for key, value in fallback.items():
        config.setdefault(key, value)
    if not isinstance(config.get("monitored_profiles"), list):
        config["monitored_profiles"] = []
    if not isinstance(config.get("notes"), list):
        config["notes"] = fallback["notes"]


def merge_config(config: dict[str, Any], values: dict[str, Any]) -> None:
    allowed = {"agent_name", "dry_run", "session_file", "default_post_limit", "rate_limit_seconds", "monitored_profiles", "notes"}
    for key, value in values.items():
        if key in allowed:
            config[key] = value
    ensure_config_shape(config)


def public_config(config: dict[str, Any]) -> dict[str, Any]:
    result = dict(config)
    result["username_configured"] = bool(instagram_username(config))
    return result


def instagram_client(config: dict[str, Any], login: bool = False, two_factor_code: str = "") -> Any:
    if not instagrapi_available():
        raise ToolInputError("Python package instagrapi is not installed")
    from instagrapi import Client

    client = Client()
    session_file = session_path(config)
    if session_file.exists():
        client.load_settings(str(session_file))
    if login or not session_file.exists():
        username = instagram_username(config)
        password = instagram_password()
        if not username or not password:
            raise ToolInputError("Instagram username and password are not configured in environment")
        if two_factor_code:
            client.login(username, password, verification_code=two_factor_code)
        else:
            client.login(username, password)
        session_file.parent.mkdir(parents=True, exist_ok=True)
        client.dump_settings(str(session_file))
    return client


def instagrapi_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("instagrapi") is not None
    except Exception:
        return False


def instagram_username(config: dict[str, Any]) -> str:
    return os.environ.get("INSTAGRAM_USERNAME", "").strip() or str(config.get("username", "")).strip()


def instagram_password() -> str:
    return os.environ.get("INSTAGRAM_PASSWORD", "").strip()


def session_path(config: dict[str, Any]) -> Path:
    return resolve_local_path(os.environ.get("INSTAGRAM_SESSION_FILE", "").strip() or str(config.get("session_file", "media/instagram/session.json")))


def dry_run_enabled(config: dict[str, Any]) -> bool:
    value = os.environ.get("INSTAGRAM_DRY_RUN", "").strip().lower()
    if value:
        return value in {"1", "true", "yes", "on"}
    return bool(config.get("dry_run", True))


def request_usernames(params: dict[str, Any], config: dict[str, Any]) -> list[str]:
    usernames = text_list(params.get("usernames"))
    if usernames:
        return usernames
    username = optional_text(params, "username")
    if username:
        return [username]
    return text_list(config.get("monitored_profiles"))


def profile_summary(client: Any, username: str) -> dict[str, Any]:
    info = client.user_info_by_username(username)
    data = model_summary(info)
    return {
        "pk": data.get("pk"),
        "username": data.get("username"),
        "full_name": data.get("full_name"),
        "biography": data.get("biography"),
        "follower_count": data.get("follower_count"),
        "following_count": data.get("following_count"),
        "media_count": data.get("media_count"),
        "is_private": data.get("is_private"),
        "is_verified": data.get("is_verified"),
    }


def recent_posts(client: Any, username: str, amount: int) -> list[dict[str, Any]]:
    user_id = client.user_id_from_username(username)
    medias = client.user_medias(user_id, amount)
    return [media_summary(media) for media in medias]


def media_summary(media: Any) -> dict[str, Any]:
    data = model_summary(media)
    return {
        "id": data.get("id"),
        "pk": data.get("pk"),
        "code": data.get("code"),
        "caption_text": data.get("caption_text"),
        "taken_at": str(data.get("taken_at", "")),
        "like_count": data.get("like_count"),
        "comment_count": data.get("comment_count"),
        "media_type": data.get("media_type"),
        "thumbnail_url": str(data.get("thumbnail_url", "")),
    }


def account_summary(client: Any) -> dict[str, Any]:
    account = client.account_info()
    return model_summary(account)


def model_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(key): serializable(child) for key, child in value.items()}
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        data = model_dump()
        return {str(key): serializable(child) for key, child in data.items()} if isinstance(data, dict) else {}
    dict_method = getattr(value, "dict", None)
    if callable(dict_method):
        data = dict_method()
        return {str(key): serializable(child) for key, child in data.items()} if isinstance(data, dict) else {}
    return {}


def serializable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [serializable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): serializable(child) for key, child in value.items()}
    return str(value)


def sleep_for_rate_limit(config: dict[str, Any]) -> None:
    delay = float_value(config.get("rate_limit_seconds"), 2.0)
    if delay > 0:
        time.sleep(delay)


def text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def bounded_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def float_value(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback
