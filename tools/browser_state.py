from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from tools.path_resolver import resolve_local_path


DEFAULT_CONFIG_PATH = Path("config/browser_agent.json")


def config_path() -> Path:
    value = os.environ.get("JARVIS_BROWSER_CONFIG", "").strip()
    return Path(value) if value else DEFAULT_CONFIG_PATH


def default_config() -> dict[str, Any]:
    return {
        "agent_name": "Codex Browser Agent",
        "profiles_dir": "media/browser/profiles",
        "sessions_dir": "media/browser/sessions",
        "screenshots_dir": "media/browser/screenshots",
        "downloads_dir": "media/browser/downloads",
        "recordings_dir": "media/browser/recordings",
        "cache_dir": "media/browser/cache",
        "default_profile": "default",
        "headless": False,
        "default_viewport": {"width": 1280, "height": 900},
        "default_timeout_ms": 15000,
        "network_idle_timeout_ms": 2000,
        "slow_mo_ms": 0,
        "search_url_template": "https://www.google.com/search?q={query}",
        "human_simulation": {
            "enabled": False,
            "typing_delay_ms_min": 40,
            "typing_delay_ms_max": 120,
            "click_delay_ms_min": 80,
            "click_delay_ms_max": 200,
            "scroll_step_px": 300,
            "scroll_delay_ms": 150,
        },
        "anti_detection": {
            "enabled": False,
            "stealth_mode": True,
            "randomize_user_agent": False,
            "user_agents": [],
        },
        "network_interception": {
            "enabled": True,
            "capture_patterns": [],
            "max_captured_responses": 50,
            "max_response_body_chars": 10000,
        },
        "dom_snapshot": {
            "max_elements_per_type": 50,
            "include_hidden_inputs": True,
            "include_accessibility_tree": True,
            "max_text_per_element": 200,
            "auto_snapshot_on_navigate": True,
        },
        "workflow": {
            "max_steps_per_workflow": 40,
            "step_timeout_seconds": 30,
            "retry_attempts": 2,
            "checkpoint_every_n_steps": 5,
            "resume_on_restart": True,
        },
        "captcha": {
            "auto_solve_checkbox": True,
            "auto_solve_audio": False,
            "escalate_to_user": True,
        },
        "browser_executables": {
            "chrome": "{localappdata}/Google/Chrome/Application/chrome.exe",
            "edge": "{programfiles}/Microsoft/Edge/Application/msedge.exe",
            "firefox": "{programfiles}/Mozilla Firefox/firefox.exe",
            "playwright_chromium": "{playwright_chromium}",
        },
        "browser_executable_candidates": ["{playwright_chromium}"],
        "launch_args": ["--disable-blink-features=AutomationControlled"],
        "proxy": {"enabled": False, "server": "", "username_env": "", "password_env": ""},
        "workflow_defaults": {},
        "sites": {},
    }


def load_config() -> dict[str, Any]:
    path = config_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            return ensure_config_shape(data)
    config = default_config()
    save_config(config)
    return config


def save_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ensure_config_shape(config), indent=2, ensure_ascii=False), encoding="utf-8")


def ensure_config_shape(config: dict[str, Any]) -> dict[str, Any]:
    merged = merge_defaults(config, default_config())
    for key in [
        "browser_executable_candidates",
        "launch_args",
    ]:
        if not isinstance(merged.get(key), list):
            merged[key] = default_config()[key]
    if not isinstance(merged.get("browser_executables"), dict):
        merged["browser_executables"] = default_config()["browser_executables"]
    if not isinstance(merged.get("sites"), dict):
        merged["sites"] = {}
    ensure_media_dirs(merged)
    return merged


def merge_defaults(data: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    result = dict(data)
    for key, value in fallback.items():
        if key not in result:
            result[key] = value
            continue
        if isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_defaults(result[key], value)
    return result


def ensure_media_dirs(config: dict[str, Any]) -> None:
    for key in ["profiles_dir", "sessions_dir", "screenshots_dir", "downloads_dir", "recordings_dir", "cache_dir"]:
        path_value = config.get(key)
        if isinstance(path_value, str) and path_value.strip():
            resolve_local_path(path_value).mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def new_session_id() -> str:
    return uuid.uuid4().hex


def safe_path_segment(value: str, fallback: str) -> str:
    text = value.strip() or fallback
    chars: list[str] = []
    for char in text:
        if char.isalnum() or char in {"-", "_", "."}:
            chars.append(char)
        else:
            chars.append("_")
    cleaned = "".join(chars).strip("._")
    return cleaned or fallback


def configured_path(config: dict[str, Any], key: str) -> Path:
    value = config.get(key)
    if not isinstance(value, str) or not value.strip():
        value = str(default_config()[key])
    return resolve_local_path(value)


def profile_dir(config: dict[str, Any], profile_name: str) -> Path:
    return configured_path(config, "profiles_dir") / safe_path_segment(profile_name, "default")


def session_file(config: dict[str, Any], session_id: str) -> Path:
    return configured_path(config, "sessions_dir") / f"{safe_path_segment(session_id, 'session')}.json"


def cache_file(config: dict[str, Any], session_id: str, label: str) -> Path:
    directory = configured_path(config, "cache_dir") / safe_path_segment(session_id, "session")
    directory.mkdir(parents=True, exist_ok=True)
    stamp = str(int(time.time() * 1000))
    return directory / f"{safe_path_segment(label, 'snapshot')}-{stamp}.json"


def screenshot_file(config: dict[str, Any], label: str = "browser") -> Path:
    directory = configured_path(config, "screenshots_dir")
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{safe_path_segment(label, 'browser')}-{int(time.time())}.png"


def create_session_state(session_id: str, profile_name: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "profile_name": profile_name,
        "started_at": now_iso(),
        "updated_at": now_iso(),
        "current_url": "",
        "current_title": "",
        "page_load_state": "unknown",
        "navigation_history": [],
        "active_frames": [],
        "dialog_pending": None,
        "download_in_progress": False,
        "network_idle": True,
        "intercepted_requests": [],
        "cookies": [],
        "local_storage_keys": [],
        "dom_snapshot_path": "",
        "last_screenshot_path": "",
        "workflow_state": None,
        "current_frame": None,
        "last_error": "",
    }


def read_session_state(config: dict[str, Any], session_id: str) -> dict[str, Any]:
    path = session_file(config, session_id)
    if not path.exists():
        return create_session_state(session_id, "default")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        return data
    return create_session_state(session_id, "default")


def write_session_state(config: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    state["updated_at"] = now_iso()
    path = session_file(config, str(state.get("session_id") or "session"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    return state


def update_session_state(config: dict[str, Any], state: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(state)
    merged.update(updates)
    return write_session_state(config, merged)


def append_history(state: dict[str, Any], url: str, title: str) -> None:
    if not url:
        return
    history = state.get("navigation_history")
    if not isinstance(history, list):
        history = []
    latest = {"url": url, "title": title, "timestamp": now_iso()}
    if not history or history[-1].get("url") != url:
        history.append(latest)
    state["navigation_history"] = history[-25:]


def cookie_metadata(cookies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    safe: list[dict[str, Any]] = []
    for cookie in cookies:
        if not isinstance(cookie, dict):
            continue
        safe.append(
            {
                "name": cookie.get("name", ""),
                "domain": cookie.get("domain", ""),
                "path": cookie.get("path", ""),
                "expires": cookie.get("expires", -1),
                "httpOnly": cookie.get("httpOnly", False),
                "secure": cookie.get("secure", False),
                "sameSite": cookie.get("sameSite", ""),
            }
        )
    return safe
