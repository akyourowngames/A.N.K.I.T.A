from __future__ import annotations

import json
import os
import time
import urllib.parse
from pathlib import Path
from typing import Any

from tools.path_resolver import resolve_local_path
from tools.registry import ToolInputError, optional_text, require_text


DEFAULT_CONFIG_PATH = Path("config/browser_agent.json")
_PLAYWRIGHT: Any | None = None
_CONTEXT: Any | None = None
_PAGE: Any | None = None


def browser_status(_params: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_config()
    executable = resolve_browser_executable(config)
    page = current_page()
    return {
        "summary": f"{config.get('agent_name', 'Browser Agent')} ready.",
        "config_path": str(config_path()),
        "playwright_available": playwright_available(),
        "browser_executable": str(executable) if executable else "",
        "connected": page is not None,
        "current_url": page.url if page is not None else "",
        "current_title": safe_page_title(page) if page is not None else "",
    }


def browser_manage(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    if operation == "open_url":
        url = normalize_url(require_text(params, "url"))
        page = ensure_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms(params))
        return page_result("Opened URL.", page)
    if operation == "search":
        query = require_text(params, "query")
        config = load_config()
        url = build_url(str(config.get("search_url_template") or ""), {"query": query})
        page = ensure_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms(params))
        return page_result("Opened browser search.", page, {"query": query})
    if operation == "snapshot":
        page = ensure_existing_page()
        return page_result("Browser snapshot.", page, {"text": page_text(page, bounded_int(params.get("max_chars"), 4000, 1, 50000))})
    if operation == "click_text":
        text = require_text(params, "text")
        page = ensure_existing_page()
        locator = page.get_by_text(text).first
        locator.click(timeout=timeout_ms(params))
        return page_result("Clicked matching text.", page, {"target_text": text})
    if operation == "type_text":
        text = require_text(params, "text")
        page = ensure_existing_page()
        selector = optional_text(params, "selector")
        clear = bool(params.get("clear", False))
        target = page.locator(selector).first if selector else page.locator("input, textarea, [contenteditable='true']").first
        if clear:
            target.fill("", timeout=timeout_ms(params))
        target.fill(text, timeout=timeout_ms(params))
        return page_result("Typed text.", page, {"typed_chars": len(text)})
    if operation == "press_key":
        key = require_text(params, "key")
        page = ensure_existing_page()
        page.keyboard.press(key)
        return page_result("Pressed key.", page, {"key": key})
    if operation == "screenshot":
        page = ensure_existing_page()
        path = screenshot_path(optional_text(params, "path"))
        full_page = bool(params.get("full_page", True))
        page.screenshot(path=str(path), full_page=full_page)
        return page_result("Saved screenshot.", page, {"path": str(path)})
    if operation == "close":
        close_browser()
        return {"summary": "Browser session closed.", "closed": True}
    raise ToolInputError(f"Unsupported browser operation: {operation}")


def config_path() -> Path:
    value = os.environ.get("JARVIS_BROWSER_CONFIG", "").strip()
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
        "agent_name": "Codex Browser Agent",
        "headless": False,
        "user_data_dir": "media/browser-profile",
        "default_timeout_ms": 15000,
        "screenshot_dir": "media/browser-screenshots",
        "search_url_template": "https://www.google.com/search?q={query}",
        "browser_executable_candidates": ["{playwright_chromium}"],
        "launch_args": ["--disable-blink-features=AutomationControlled"],
    }


def ensure_config_shape(config: dict[str, Any]) -> None:
    fallback = default_config()
    for key, value in fallback.items():
        config.setdefault(key, value)
    if not isinstance(config.get("browser_executable_candidates"), list):
        config["browser_executable_candidates"] = fallback["browser_executable_candidates"]
    if not isinstance(config.get("launch_args"), list):
        config["launch_args"] = fallback["launch_args"]


def ensure_page() -> Any:
    global _PAGE
    context = ensure_context()
    if _PAGE is not None and not _PAGE.is_closed():
        return _PAGE
    pages = context.pages
    _PAGE = pages[0] if pages else context.new_page()
    return _PAGE


def ensure_existing_page() -> Any:
    page = current_page()
    if page is None:
        return ensure_page()
    return page


def current_page() -> Any | None:
    global _PAGE
    if _PAGE is not None and not _PAGE.is_closed():
        return _PAGE
    if _CONTEXT is None:
        return None
    pages = _CONTEXT.pages
    _PAGE = pages[0] if pages else None
    return _PAGE


def ensure_context() -> Any:
    global _PLAYWRIGHT, _CONTEXT
    if _CONTEXT is not None:
        return _CONTEXT
    if not playwright_available():
        raise ToolInputError("Python package playwright is not installed")
    from playwright.sync_api import sync_playwright

    config = load_config()
    _PLAYWRIGHT = sync_playwright().start()
    executable = resolve_browser_executable(config)
    user_data_dir = resolve_local_path(str(config.get("user_data_dir") or "media/browser-profile"))
    user_data_dir.mkdir(parents=True, exist_ok=True)
    launch_args = [str(item) for item in config.get("launch_args", []) if isinstance(item, str)]
    kwargs: dict[str, Any] = {
        "headless": env_bool("JARVIS_BROWSER_HEADLESS", bool(config.get("headless", False))),
        "args": launch_args,
    }
    if executable is not None:
        kwargs["executable_path"] = str(executable)
    _CONTEXT = _PLAYWRIGHT.chromium.launch_persistent_context(str(user_data_dir), **kwargs)
    return _CONTEXT


def close_browser() -> None:
    global _PLAYWRIGHT, _CONTEXT, _PAGE
    if _CONTEXT is not None:
        _CONTEXT.close()
    if _PLAYWRIGHT is not None:
        _PLAYWRIGHT.stop()
    _PLAYWRIGHT = None
    _CONTEXT = None
    _PAGE = None


def playwright_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("playwright") is not None
    except Exception:
        return False


def resolve_browser_executable(config: dict[str, Any]) -> Path | None:
    values = template_values()
    for candidate in config.get("browser_executable_candidates", []):
        if not isinstance(candidate, str) or not candidate.strip():
            continue
        expanded = candidate
        for key, value in values.items():
            expanded = expanded.replace("{" + key + "}", value)
        path = Path(os.path.expandvars(expanded))
        if path.exists():
            return path.resolve()
    return None


def template_values() -> dict[str, str]:
    values = {
        "programfiles": os.environ.get("ProgramFiles", ""),
        "programfilesx86": os.environ.get("ProgramFiles(x86)", ""),
        "localappdata": os.environ.get("LOCALAPPDATA", ""),
        "home": str(Path.home()),
        "cwd": str(Path.cwd()),
        "playwright_chromium": "",
    }
    if playwright_available():
        try:
            from playwright.sync_api import sync_playwright

            playwright = sync_playwright().start()
            try:
                values["playwright_chromium"] = playwright.chromium.executable_path
            finally:
                playwright.stop()
        except Exception:
            values["playwright_chromium"] = ""
    return values


def page_result(summary: str, page: Any, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "summary": summary,
        "url": page.url,
        "title": safe_page_title(page),
    }
    if extra:
        result.update(extra)
    return result


def safe_page_title(page: Any) -> str:
    try:
        return page.title()
    except Exception:
        return ""


def page_text(page: Any, max_chars: int) -> str:
    try:
        text = page.locator("body").inner_text(timeout=2000)
    except Exception:
        text = ""
    return text[:max_chars]


def screenshot_path(value: str) -> Path:
    if value:
        path = resolve_local_path(value)
    else:
        config = load_config()
        directory = resolve_local_path(str(config.get("screenshot_dir") or "media/browser-screenshots"))
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"browser-{int(time.time())}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def build_url(template: str, values: dict[str, str]) -> str:
    if not template:
        raise ToolInputError("Browser URL template is not configured")
    url = template
    for key, value in values.items():
        url = url.replace("{" + key + "}", urllib.parse.quote(value, safe=""))
    return url


def normalize_url(value: str) -> str:
    text = value.strip()
    lowered = text.lower()
    if "://" in text or lowered.startswith("data:") or lowered.startswith("about:") or lowered.startswith("file:"):
        return text
    return "https://" + text


def timeout_ms(params: dict[str, Any]) -> int:
    config = load_config()
    return bounded_int(params.get("timeout_ms"), bounded_int(config.get("default_timeout_ms"), 15000, 1000, 120000), 1000, 120000)


def env_bool(name: str, fallback: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return fallback
    return value in {"1", "true", "yes", "on"}


def bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))
