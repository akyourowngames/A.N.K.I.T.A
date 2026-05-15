from __future__ import annotations

import os
import random
import subprocess
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools import browser_dom, browser_media, browser_network, browser_recovery, browser_workflow
from tools.browser_state import (
    append_history,
    cache_file,
    config_path,
    configured_path,
    cookie_metadata,
    create_session_state,
    load_config,
    new_session_id,
    profile_dir,
    read_session_state,
    safe_path_segment,
    screenshot_file,
    update_session_state,
    write_session_state,
)
from tools.path_resolver import resolve_local_path
from tools.registry import ToolInputError, optional_text, require_text


_PLAYWRIGHT: Any | None = None
_PLAYWRIGHT_CHROMIUM_EXECUTABLE = ""
_SESSIONS: dict[str, "BrowserRuntimeSession"] = {}
_ACTIVE_SESSION_ID: str = ""
_PENDING_DIALOGS: dict[str, Any] = {}
_POPUPS: dict[str, list[Any]] = {}
_ATTACHED_PAGE_EVENTS: set[int] = set()


@dataclass
class BrowserRuntimeSession:
    session_id: str
    profile_name: str
    browser_name: str
    context: Any
    page: Any
    state: dict[str, Any]
    current_frame: Any | None = None
    page_load_state: str = "unknown"


def browser_status(_params: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_config()
    executable = resolve_browser_executable(config, playwright=_PLAYWRIGHT)
    session = active_session()
    page = session.page if session else None
    warning = browser_engine_warning("", executable, _PLAYWRIGHT)
    return {
        "summary": f"{config.get('agent_name', 'Browser Agent')} ready.",
        "config_path": str(config_path()),
        "playwright_available": playwright_available(),
        "browser_executable": str(executable) if executable else "",
        "browser_engine_warning": warning,
        "connected": page is not None and not page.is_closed(),
        "active_session_id": session.session_id if session else "",
        "current_url": page.url if page is not None and not page.is_closed() else "",
        "current_title": safe_page_title(page) if page is not None and not page.is_closed() else "",
        "registered_sessions": list(_SESSIONS.keys()),
    }


def browser(params: dict[str, Any]) -> dict[str, Any]:
    action = require_text(params, "action")
    if action == "status":
        return browser_status({})
    if action == "start":
        return browser_launch({"profile_name": optional_text(params, "profile_name", optional_text(params, "profile")), "headless": params.get("headless")})
    if action == "stop":
        return browser_close({"session_id": optional_text(params, "targetId", optional_text(params, "session_id"))})
    if action == "tabs":
        return browser_tabs(params)
    if action == "open":
        label = optional_text(params, "label")
        launched = ensure_session_for_browser_tool(params)
        result = browser_navigate(
            {
                "session_id": launched.session_id,
                "url": read_target_url(params),
                "capture_snapshot": bool(params.get("capture_snapshot", True)),
                "timeout_ms": params.get("timeoutMs", params.get("timeout_ms")),
            }
        )
        if label:
            labels = dict(launched.state.get("tab_labels") if isinstance(launched.state.get("tab_labels"), dict) else {})
            labels[label] = launched.session_id
            sync_state(launched, {"tab_labels": labels})
            result["label"] = label
        result["targetId"] = launched.session_id
        return result
    if action == "navigate":
        target = ensure_session_for_browser_tool(params)
        result = browser_navigate(
            {
                "session_id": target.session_id,
                "url": read_target_url(params),
                "capture_snapshot": bool(params.get("capture_snapshot", True)),
                "timeout_ms": params.get("timeoutMs", params.get("timeout_ms")),
            }
        )
        result["targetId"] = target.session_id
        return result
    if action == "snapshot":
        target = ensure_session_for_browser_tool(params)
        snapshot = browser_snapshot(
            {
                "session_id": target.session_id,
                "max_elements_per_type": params.get("limit"),
                "include_accessibility_tree": params.get("include_accessibility_tree", True),
            }
        )
        compact = bool(params.get("compact", True) or params.get("interactive", False))
        refs = snapshot_refs(snapshot)
        sync_state(target, {"ref_map": refs})
        return {
            "summary": "Browser ref snapshot.",
            "targetId": target.session_id,
            "url": snapshot.get("url", ""),
            "title": snapshot.get("title", ""),
            "snapshot": format_ref_snapshot(snapshot, compact=compact, urls=bool(params.get("urls", False))),
            "refs": refs,
            "stats": {"refs": len(refs), "counts": snapshot.get("counts", {})},
            "snapshot_path": snapshot.get("snapshot_path", ""),
        }
    if action == "screenshot":
        target = ensure_session_for_browser_tool(params)
        result = browser_screenshot(
            {
                "session_id": target.session_id,
                "path": optional_text(params, "path"),
                "full_page": bool(params.get("fullPage", params.get("full_page", True))),
            }
        )
        result["targetId"] = target.session_id
        return result
    if action == "act":
        return browser_act(params)
    raise ToolInputError(f"Unsupported browser action: {action}")


def browser_launch(params: dict[str, Any] | None = None) -> dict[str, Any]:
    global _ACTIVE_SESSION_ID, _PLAYWRIGHT
    params = params or {}
    config = load_config()
    profile_name = optional_text(params, "profile_name", str(config.get("default_profile") or "default"))
    browser_name = optional_text(params, "browser", "playwright_chromium")
    for session in _SESSIONS.values():
        if session.profile_name == profile_name and not session.page.is_closed():
            _ACTIVE_SESSION_ID = session.session_id
            sync_state(session)
            return {"summary": "Browser session already active.", "session_id": session.session_id, "state": public_state(session.state)}

    if not playwright_available():
        raise ToolInputError("Python package playwright is not installed")
    from playwright.sync_api import sync_playwright

    if _PLAYWRIGHT is None:
        _PLAYWRIGHT = sync_playwright().start()
    remember_playwright_chromium_executable(_PLAYWRIGHT)

    profile_path = profile_dir(config, profile_name)
    profile_path.mkdir(parents=True, exist_ok=True)
    removed_locks = cleanup_profile_locks(profile_path)
    launch_args = [str(item) for item in config.get("launch_args", []) if isinstance(item, str)]
    kwargs: dict[str, Any] = {
        "headless": browser_headless(params, config),
        "args": launch_args,
        "accept_downloads": True,
        "downloads_path": str(configured_path(config, "downloads_dir")),
        "slow_mo": bounded_int(config.get("slow_mo_ms"), 0, 0, 10000),
    }
    viewport = viewport_from_params(params.get("viewport"), config)
    proxy = proxy_options(config)
    if proxy:
        kwargs["proxy"] = proxy
    executable = resolve_browser_executable(config, browser_name, _PLAYWRIGHT)
    if executable is not None:
        kwargs["executable_path"] = str(executable)

    engine = browser_engine(browser_name, _PLAYWRIGHT)
    context = engine.launch_persistent_context(str(profile_path), **kwargs)
    pages = context.pages
    page = pages[0] if pages else context.new_page()
    viewport_applied = apply_page_viewport(page, viewport)
    session_id = new_session_id()
    state = create_session_state(session_id, profile_name)
    session = BrowserRuntimeSession(
        session_id=session_id,
        profile_name=profile_name,
        browser_name=browser_name,
        context=context,
        page=page,
        state=state,
    )
    _SESSIONS[session_id] = session
    _ACTIVE_SESSION_ID = session_id
    attach_context_events(session)
    sync_state(session, {"page_load_state": "launched"})
    warning = browser_engine_warning(browser_name, executable, _PLAYWRIGHT)
    result = {
        "summary": "Browser session launched.",
        "session_id": session_id,
        "profile_name": profile_name,
        "state": public_state(session.state),
        "profile_locks_removed": removed_locks,
        "viewport_applied": viewport_applied,
    }
    if warning:
        result["browser_engine_warning"] = warning
    return result


def browser_navigate(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    url = normalize_url(require_text(params, "url"))
    wait_until = optional_text(params, "wait_until", "domcontentloaded")
    before_url = session.page.url
    start = time.perf_counter()
    response = session.page.goto(url, wait_until=wait_until, timeout=timeout_ms(params))
    session.page_load_state = wait_until
    wait_for_stability(session, params)
    load_time_ms = int((time.perf_counter() - start) * 1000)
    result: dict[str, Any] = {
        "summary": "Navigation completed.",
        "session_id": session.session_id,
        "url": session.page.url,
        "title": safe_page_title(session.page),
        "load_time_ms": load_time_ms,
        "redirected": before_url not in {"", "about:blank"} and session.page.url != url,
        "status": response.status if response is not None else None,
    }
    if bool(params.get("capture_snapshot", auto_snapshot_enabled())):
        snapshot = snapshot_for_session(session)
        result["snapshot_path"] = snapshot.get("snapshot_path", "")
        detection = browser_recovery.detect_state(snapshot, session.state, result.get("status"))
        result["detected_state"] = detection["state"]
    sync_state(session)
    return result


def browser_back(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    response = session.page.go_back(timeout=timeout_ms(params))
    wait_for_stability(session, params)
    sync_state(session, {"page_load_state": "history"})
    return {"summary": "Navigated back.", "session_id": session.session_id, "status": response.status if response else None, "state": public_state(session.state)}


def browser_forward(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    response = session.page.go_forward(timeout=timeout_ms(params))
    wait_for_stability(session, params)
    sync_state(session, {"page_load_state": "history"})
    return {"summary": "Navigated forward.", "session_id": session.session_id, "status": response.status if response else None, "state": public_state(session.state)}


def browser_refresh(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    wait_until = optional_text(params, "wait_until", "domcontentloaded")
    response = session.page.reload(wait_until=wait_until, timeout=timeout_ms(params))
    session.page_load_state = wait_until
    wait_for_stability(session, params)
    sync_state(session)
    return {"summary": "Page refreshed.", "session_id": session.session_id, "status": response.status if response else None, "state": public_state(session.state)}


def browser_close(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = session_from_params(params, allow_missing=True)
    if session is None:
        close_browser()
        return {"summary": "No active browser session was open.", "closed": False}
    close_session(session.session_id)
    return {"summary": "Browser session closed.", "session_id": session.session_id, "closed": True}


def browser_snapshot(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    snapshot = snapshot_for_session(session, params)
    sync_state(session, {"dom_snapshot_path": snapshot.get("snapshot_path", "")})
    return snapshot


def browser_state(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = session_from_params(params, allow_missing=True)
    if session is None:
        config = load_config()
        session_id = optional_text(params, "session_id")
        if session_id:
            return read_session_state(config, session_id)
        return {"summary": "No active browser session.", "active_session_id": "", "sessions": []}
    sync_state(session)
    state = public_state(session.state)
    state["summary"] = "Browser state read."
    return state


def browser_screenshot(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    path_text = optional_text(params, "path")
    path = resolve_local_path(path_text) if path_text else screenshot_file(load_config())
    path.parent.mkdir(parents=True, exist_ok=True)
    session.page.screenshot(path=str(path), full_page=bool(params.get("full_page", True)))
    sync_state(session, {"last_screenshot_path": str(path)})
    return {"summary": "Saved screenshot.", "session_id": session.session_id, "path": str(path), "state": public_state(session.state)}


def browser_get_text(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    target = interaction_target(session)
    selector = optional_text(params, "selector")
    max_chars = bounded_int(params.get("max_chars"), 4000, 1, 50000)
    if selector:
        text = target.locator(selector).first.inner_text(timeout=timeout_ms(params))
    else:
        text = target.locator("main, [role='main'], body").first.inner_text(timeout=timeout_ms(params))
    return {"summary": "Extracted visible text.", "session_id": session.session_id, "text": text[:max_chars], "truncated": len(text) > max_chars}


def browser_get_attribute(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    target = interaction_target(session)
    selector = require_text(params, "selector")
    attribute = require_text(params, "attribute")
    value = target.locator(selector).first.get_attribute(attribute, timeout=timeout_ms(params))
    return {"summary": "Read element attribute.", "session_id": session.session_id, "selector": selector, "attribute": attribute, "value": value or ""}


def browser_network_log(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    result = browser_network.network_log(session.session_id, bounded_int(params.get("limit"), 50, 1, 500), bool(params.get("include_bodies", False)))
    sync_state(session, {"intercepted_requests": browser_network.recent_request_summaries(session.session_id)})
    result["summary"] = "Network log read."
    return result


def browser_click(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    target = interaction_target(session)
    before = state_signature(session)
    if "x" in params and "y" in params:
        session.page.mouse.click(float(params["x"]), float(params["y"]))
    else:
        locator = locator_from_params(target, params)
        human_delay(load_config(), "click")
        locator.click(timeout=timeout_ms(params))
    wait_for_stability(session, params)
    sync_state(session)
    return {"summary": "Click completed.", "session_id": session.session_id, "changed": compare_state(before, state_signature(session)), "state": public_state(session.state)}


def browser_type(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    target = interaction_target(session)
    text = require_text(params, "text")
    selector = optional_text(params, "selector")
    locator = field_locator(target, selector)
    strategy = fill_field(locator, text, params)
    wait_for_stability(session, params)
    suggestions = autocomplete_suggestions(target)
    sync_state(session)
    return {"summary": "Typed text.", "session_id": session.session_id, "typed_chars": len(text), "strategy": strategy, "suggestions": suggestions, "state": public_state(session.state)}


def browser_select(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    target = interaction_target(session)
    selector = require_text(params, "selector")
    locator = target.locator(selector).first
    tag = locator.evaluate("(element) => element.tagName.toLowerCase()")
    if tag == "select":
        option: dict[str, Any] = {}
        value = optional_text(params, "value")
        label = optional_text(params, "label")
        index = params.get("index")
        if value:
            option["value"] = value
        elif label:
            option["label"] = label
        elif isinstance(index, int):
            option["index"] = index
        else:
            raise ToolInputError("value, label, or index is required")
        selected = locator.select_option(**option, timeout=timeout_ms(params))
    else:
        locator.click(timeout=timeout_ms(params))
        label = optional_text(params, "label", optional_text(params, "value"))
        if label:
            click_option_by_text(target, label, timeout_ms(params))
            selected = [label]
        elif isinstance(params.get("index"), int):
            target.locator("[role='option'], option").nth(int(params["index"])).click(timeout=timeout_ms(params))
            selected = [str(params["index"])]
        else:
            raise ToolInputError("label, value, or index is required for custom dropdown")
    wait_for_stability(session, params)
    sync_state(session)
    return {"summary": "Selection completed.", "session_id": session.session_id, "selected": selected, "state": public_state(session.state)}


def browser_check(params: dict[str, Any]) -> dict[str, Any]:
    return set_checked(params, True)


def browser_uncheck(params: dict[str, Any]) -> dict[str, Any]:
    return set_checked(params, False)


def browser_upload(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    target = interaction_target(session)
    selector = require_text(params, "selector")
    path = resolve_local_path(require_text(params, "path"))
    if not path.exists():
        raise ToolInputError(f"Upload file does not exist: {path}")
    target.locator(selector).first.set_input_files(str(path), timeout=timeout_ms(params))
    wait_for_stability(session, params)
    sync_state(session)
    return {"summary": "File uploaded to input.", "session_id": session.session_id, "path": str(path), "state": public_state(session.state)}


def browser_drag(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    page = session.page
    source = optional_text(params, "from_selector")
    target_selector = optional_text(params, "to_selector")
    if source and target_selector:
        interaction_target(session).locator(source).first.drag_to(interaction_target(session).locator(target_selector).first, timeout=timeout_ms(params))
    else:
        if not all(key in params for key in ["from_x", "from_y", "to_x", "to_y"]):
            raise ToolInputError("Provide from_selector/to_selector or from_x/from_y/to_x/to_y")
        page.mouse.move(float(params["from_x"]), float(params["from_y"]))
        page.mouse.down()
        page.mouse.move(float(params["to_x"]), float(params["to_y"]))
        page.mouse.up()
    wait_for_stability(session, params)
    sync_state(session)
    return {"summary": "Drag completed.", "session_id": session.session_id, "state": public_state(session.state)}


def browser_hover(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    target = interaction_target(session)
    locator_from_params(target, params).hover(timeout=timeout_ms(params))
    wait_for_stability(session, params)
    snapshot = snapshot_for_session(session, {"max_elements_per_type": 10})
    sync_state(session)
    return {"summary": "Hover completed.", "session_id": session.session_id, "snapshot_path": snapshot.get("snapshot_path", ""), "state": public_state(session.state)}


def browser_scroll(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    target = interaction_target(session)
    selector = optional_text(params, "selector")
    direction = optional_text(params, "to")
    amount = bounded_int(params.get("amount"), 600, -100000, 100000)
    before = target.evaluate("() => ({height: document.body.scrollHeight, y: window.scrollY})")
    if direction == "element":
        target_selector = require_text(params, "target_selector")
        target.locator(target_selector).first.scroll_into_view_if_needed(timeout=timeout_ms(params))
    elif direction == "bottom":
        scroll_script(target, selector, "bottom", amount)
    elif direction == "top":
        scroll_script(target, selector, "top", amount)
    else:
        scroll_script(target, selector, "amount", amount)
    wait_for_stability(session, params)
    after = target.evaluate("() => ({height: document.body.scrollHeight, y: window.scrollY})")
    sync_state(session)
    return {"summary": "Scroll completed.", "session_id": session.session_id, "new_content_loaded": after.get("height") != before.get("height"), "state": public_state(session.state)}


def browser_press_key(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    key = require_text(params, "key")
    session.page.keyboard.press(key)
    wait_for_stability(session, params)
    sync_state(session)
    return {"summary": "Pressed key.", "session_id": session.session_id, "key": key, "state": public_state(session.state)}


def browser_handle_dialog(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    dialog = _PENDING_DIALOGS.get(session.session_id)
    if dialog is None:
        sync_state(session, {"dialog_pending": None})
        return {"summary": "No pending dialog.", "session_id": session.session_id, "handled": False}
    action = require_text(params, "action")
    text = optional_text(params, "text")
    if action == "accept":
        dialog.accept(text if text else None)
    elif action == "dismiss":
        dialog.dismiss()
    else:
        raise ToolInputError("action must be accept or dismiss")
    _PENDING_DIALOGS.pop(session.session_id, None)
    sync_state(session, {"dialog_pending": None})
    return {"summary": "Dialog handled.", "session_id": session.session_id, "action": action}


def browser_handle_popup(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    popups = [page for page in _POPUPS.get(session.session_id, []) if not page.is_closed()]
    if not popups:
        return {"summary": "No popup is available.", "session_id": session.session_id, "handled": False}
    index = bounded_int(params.get("index"), len(popups) - 1, 0, len(popups) - 1)
    popup = popups[index]
    session.page = popup
    session.current_frame = None
    attach_page_events(session, popup)
    wait_for_stability(session, params)
    sync_state(session)
    result = {"summary": "Popup focused.", "session_id": session.session_id, "url": popup.url, "title": safe_page_title(popup), "state": public_state(session.state)}
    if bool(params.get("close_after", False)):
        popup.close()
        remaining = [page for page in session.context.pages if not page.is_closed()]
        session.page = remaining[0] if remaining else session.context.new_page()
        sync_state(session)
        result["closed_after"] = True
    return result


def browser_wait_for(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    target = interaction_target(session)
    condition = require_text(params, "condition")
    timeout = timeout_ms(params)
    start_url = session.page.url
    if condition == "element_appears":
        target.locator(require_text(params, "selector")).first.wait_for(state="visible", timeout=timeout)
    elif condition == "element_disappears":
        target.locator(require_text(params, "selector")).first.wait_for(state="hidden", timeout=timeout)
    elif condition == "text_appears":
        target.get_by_text(require_text(params, "text")).first.wait_for(state="visible", timeout=timeout)
    elif condition == "url_changes":
        wait_until(lambda: session.page.url != start_url and url_condition_ok(session.page.url, optional_text(params, "url_pattern")), timeout)
    elif condition == "network_idle":
        session.page.wait_for_load_state("networkidle", timeout=timeout)
    elif condition == "response_received":
        pattern = require_text(params, "response_pattern")
        wait_until(lambda: any(browser_network.pattern_matches(str(item.get("url", "")), pattern) for item in browser_network.network_log(session.session_id, 100, False)["entries"]), timeout)
    else:
        raise ToolInputError(f"Unsupported wait condition: {condition}")
    sync_state(session)
    return {"summary": "Wait condition satisfied.", "session_id": session.session_id, "condition": condition, "state": public_state(session.state)}


def browser_frame_list(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    frames = frame_summaries(session.page)
    sync_state(session, {"active_frames": frames})
    return {"summary": "Frames listed.", "session_id": session.session_id, "frames": frames}


def browser_frame_switch(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    if bool(params.get("main", False)):
        session.current_frame = None
        sync_state(session, {"current_frame": None})
        return {"summary": "Switched to main frame.", "session_id": session.session_id, "current_frame": None}
    frames = session.page.frames
    chosen = None
    if isinstance(params.get("index"), int):
        index = int(params["index"])
        if 0 <= index < len(frames):
            chosen = frames[index]
    name = optional_text(params, "name")
    if chosen is None and name:
        for frame in frames:
            if frame.name == name:
                chosen = frame
                break
    pattern = optional_text(params, "url_pattern")
    if chosen is None and pattern:
        for frame in frames:
            if browser_network.pattern_matches(frame.url, pattern):
                chosen = frame
                break
    if chosen is None:
        raise ToolInputError("No matching frame found")
    session.current_frame = chosen
    current = frame_summary(chosen, frames.index(chosen))
    sync_state(session, {"current_frame": current})
    return {"summary": "Switched frame context.", "session_id": session.session_id, "current_frame": current}


def browser_frame_snapshot(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    if session.current_frame is None:
        raise ToolInputError("No frame is selected. Use browser_frame_switch first or pass main=true to return to the main frame.")
    snapshot = browser_dom.snapshot_target(session.current_frame, load_config(), session.session_id, "frame-dom")
    sync_state(session, {"dom_snapshot_path": snapshot.get("snapshot_path", "")})
    return snapshot


def browser_media_play(params: dict[str, Any] | None = None) -> dict[str, Any]:
    session = ensure_session(params or {})
    result = browser_media.media_play(interaction_target(session))
    sync_state(session)
    result["session_id"] = session.session_id
    return result


def browser_media_control(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    result = browser_media.media_control(interaction_target(session), params)
    sync_state(session)
    result["session_id"] = session.session_id
    return result


def browser_media_state(params: dict[str, Any] | None = None) -> dict[str, Any]:
    session = ensure_session(params or {})
    result = browser_media.media_state(interaction_target(session))
    sync_state(session)
    result["session_id"] = session.session_id
    return result


def browser_media_extract(params: dict[str, Any] | None = None) -> dict[str, Any]:
    session = ensure_session(params or {})
    result = browser_media.media_extract(interaction_target(session))
    sync_state(session)
    result["session_id"] = session.session_id
    return result


def browser_intercept_start(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    patterns = text_list(params.get("patterns"))
    result = browser_network.start_capture(session.session_id, load_config(), patterns if patterns else None, bool(params.get("capture_bodies", False)))
    sync_state(session, {"intercepted_requests": browser_network.recent_request_summaries(session.session_id)})
    return result


def browser_intercept_stop(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    result = browser_network.stop_capture(session.session_id, True)
    sync_state(session, {"intercepted_requests": browser_network.recent_request_summaries(session.session_id)})
    return result


def browser_intercept_mock(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    result = browser_network.install_mock(
        session.page,
        session.session_id,
        require_text(params, "url_pattern"),
        bounded_int(params.get("status"), 200, 100, 599),
        optional_text(params, "content_type", "application/json"),
        require_text(params, "body"),
    )
    sync_state(session)
    result["session_id"] = session.session_id
    return result


def browser_workflow_start(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    workflow_type = require_text(params, "type")
    workflow_params = params.get("parameters") if isinstance(params.get("parameters"), dict) else {}
    custom_steps = params.get("steps") if isinstance(params.get("steps"), list) else None
    workflow = browser_workflow.start_workflow(workflow_type, workflow_params, load_config(), custom_steps)
    sync_state(session, {"workflow_state": workflow})
    return {"summary": "Browser workflow started.", "session_id": session.session_id, "workflow": workflow_public(workflow)}


def browser_workflow_step(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    workflow = active_workflow(session)
    step = browser_workflow.current_step(workflow)
    if step is None:
        return {"summary": "No workflow step remains.", "session_id": session.session_id, "workflow": workflow_public(workflow)}
    try:
        result = execute_workflow_step(session, step)
        workflow = browser_workflow.complete_step(result.pop("_workflow_state", workflow), result)
    except Exception as error:
        workflow = browser_workflow.fail_step(workflow, f"{type(error).__name__}: {error}")
        sync_state(session, {"workflow_state": workflow})
        return {"summary": "Workflow step failed.", "session_id": session.session_id, "workflow": workflow_public(workflow), "error": str(error)}
    sync_state(session, {"workflow_state": workflow})
    return {"summary": "Workflow step executed.", "session_id": session.session_id, "step": step, "result": result, "workflow": workflow_public(workflow)}


def browser_workflow_status(params: dict[str, Any] | None = None) -> dict[str, Any]:
    session = ensure_session(params or {})
    workflow = session.state.get("workflow_state")
    return {"summary": "Workflow status read.", "session_id": session.session_id, "workflow": workflow_public(workflow) if isinstance(workflow, dict) else None}


def browser_workflow_recover(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    workflow = active_workflow(session)
    strategy = optional_text(params, "strategy", "retry")
    if strategy == "back":
        try:
            session.page.go_back(timeout=timeout_ms(params))
        except Exception:
            pass
    workflow = browser_workflow.recover(workflow, strategy)
    sync_state(session, {"workflow_state": workflow})
    return {"summary": "Workflow recovery attempted.", "session_id": session.session_id, "strategy": strategy, "workflow": workflow_public(workflow)}


def browser_workflow_checkpoint(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = ensure_session(params)
    workflow = active_workflow(session)
    name = optional_text(params, "name", f"step-{workflow.get('current_step', 0)}")
    workflow = browser_workflow.checkpoint(workflow, name, session.state)
    sync_state(session, {"workflow_state": workflow})
    return {"summary": "Workflow checkpoint saved.", "session_id": session.session_id, "name": name, "workflow": workflow_public(workflow)}


def browser_workflow_abort(params: dict[str, Any] | None = None) -> dict[str, Any]:
    session = ensure_session(params or {})
    workflow = active_workflow(session)
    workflow = browser_workflow.abort(workflow)
    sync_state(session, {"workflow_state": workflow})
    return {"summary": "Workflow aborted.", "session_id": session.session_id, "workflow": workflow_public(workflow)}


def browser_detect_state(params: dict[str, Any] | None = None) -> dict[str, Any]:
    session = ensure_session(params or {})
    snapshot = snapshot_for_session(session)
    result = browser_recovery.detect_state(snapshot, session.state)
    sync_state(session, {"dom_snapshot_path": snapshot.get("snapshot_path", "")})
    result["session_id"] = session.session_id
    result["snapshot_path"] = snapshot.get("snapshot_path", "")
    return result


def browser_find_element(params: dict[str, Any]) -> dict[str, Any]:
    session = ensure_session(params)
    snapshot = snapshot_for_session(session)
    result = browser_recovery.find_element(snapshot, require_text(params, "description"), optional_text(params, "element_type"))
    sync_state(session, {"dom_snapshot_path": snapshot.get("snapshot_path", "")})
    result["session_id"] = session.session_id
    result["snapshot_path"] = snapshot.get("snapshot_path", "")
    return result


def browser_solve_captcha(params: dict[str, Any] | None = None) -> dict[str, Any]:
    session = ensure_session(params or {})
    snapshot = snapshot_for_session(session)
    result = browser_recovery.solve_captcha(snapshot, load_config())
    sync_state(session, {"dom_snapshot_path": snapshot.get("snapshot_path", "")})
    result["session_id"] = session.session_id
    return result


def browser_anti_detect(params: dict[str, Any] | None = None) -> dict[str, Any]:
    session = ensure_session(params or {})
    config = load_config()
    anti_config = config.get("anti_detection")
    if not isinstance(anti_config, dict) or not bool(anti_config.get("stealth_mode", True)):
        return {"summary": "Anti-detection settings are disabled in config.", "session_id": session.session_id, "applied": False}
    session.context.add_init_script(browser_recovery.anti_detect_script())
    sync_state(session)
    return {"summary": "Configured anti-detection script applied for future page loads.", "session_id": session.session_id, "applied": True}


def browser_tabs(params: dict[str, Any] | None = None) -> dict[str, Any]:
    params = params or {}
    session = session_from_browser_target(params, allow_missing=True)
    sessions = []
    for item in _SESSIONS.values():
        sync_state(item)
        sessions.append(
            {
                "suggestedTargetId": label_for_session(item) or item.session_id,
                "targetId": item.session_id,
                "tabId": item.session_id,
                "label": label_for_session(item),
                "title": item.state.get("current_title", ""),
                "url": item.state.get("current_url", ""),
                "profile": item.profile_name,
            }
        )
    return {"summary": "Browser tabs listed.", "targetId": session.session_id if session else "", "tabs": sessions}


def browser_act(params: dict[str, Any]) -> dict[str, Any]:
    target = ensure_session_for_browser_tool(params)
    request = params.get("request") if isinstance(params.get("request"), dict) else params
    kind = require_text(request, "kind")
    ref = optional_text(request, "ref")
    selector = ref_selector(target, ref) if ref else optional_text(request, "selector")
    timeout = request.get("timeoutMs", request.get("timeout_ms", params.get("timeoutMs", params.get("timeout_ms"))))
    tool_params: dict[str, Any] = {"session_id": target.session_id, "timeout_ms": timeout}
    if kind == "click":
        if selector:
            tool_params["selector"] = selector
        else:
            tool_params["x"] = request.get("x")
            tool_params["y"] = request.get("y")
        result = browser_click(tool_params)
    elif kind == "clickCoords":
        result = browser_click({"session_id": target.session_id, "x": request.get("x"), "y": request.get("y"), "timeout_ms": timeout})
    elif kind == "type":
        text = require_text(request, "text")
        result = browser_type({"session_id": target.session_id, "selector": selector, "text": text, "clear": True, "timeout_ms": timeout, "human_like": bool(request.get("slowly", False))})
        if bool(request.get("submit", False)):
            result["submit"] = browser_press_key({"session_id": target.session_id, "key": "Enter"})
    elif kind == "press":
        result = browser_press_key({"session_id": target.session_id, "key": require_text(request, "key")})
    elif kind == "hover":
        result = browser_hover({"session_id": target.session_id, "selector": selector, "timeout_ms": timeout})
    elif kind == "select":
        values = request.get("values")
        label = ""
        if isinstance(values, list) and values:
            label = str(values[0])
        result = browser_select({"session_id": target.session_id, "selector": selector, "label": label, "timeout_ms": timeout})
    elif kind == "wait":
        result = browser_wait_for(browser_wait_request(target.session_id, request, timeout))
    elif kind == "close":
        result = browser_close({"session_id": target.session_id})
    elif kind == "fill":
        fields = request.get("fields")
        if not isinstance(fields, list):
            raise ToolInputError("fields is required for fill")
        results = []
        for field in fields:
            if not isinstance(field, dict):
                continue
            field_ref = optional_text(field, "ref")
            field_selector = ref_selector(target, field_ref) if field_ref else optional_text(field, "selector")
            value = str(field.get("value", ""))
            results.append(browser_type({"session_id": target.session_id, "selector": field_selector, "text": value, "clear": True, "timeout_ms": timeout}))
        result = {"summary": "Filled browser form fields.", "results": results}
    else:
        raise ToolInputError(f"Unsupported browser act kind: {kind}")
    sync_state(target)
    return {"summary": "Browser act completed.", "targetId": target.session_id, "kind": kind, "result": result, "url": target.state.get("current_url", ""), "title": target.state.get("current_title", "")}


def ensure_session(params: dict[str, Any] | None = None) -> BrowserRuntimeSession:
    session = session_from_params(params or {}, allow_missing=True)
    if session is not None:
        attach_page_events(session, session.page)
        return session
    launched = browser_launch({})
    session_id = str(launched.get("session_id") or "")
    session = _SESSIONS.get(session_id)
    if session is None:
        raise ToolInputError("Browser session could not be launched")
    return session


def session_from_params(params: dict[str, Any], allow_missing: bool = False) -> BrowserRuntimeSession | None:
    session_id = optional_text(params, "session_id")
    if not session_id:
        session_id = _ACTIVE_SESSION_ID
    session = _SESSIONS.get(session_id)
    if session is None:
        if allow_missing:
            return None
        raise ToolInputError("No active browser session")
    if session.page.is_closed():
        if allow_missing:
            return None
        raise ToolInputError("Browser session page is closed")
    return session


def active_session() -> BrowserRuntimeSession | None:
    return _SESSIONS.get(_ACTIVE_SESSION_ID)


def ensure_session_for_browser_tool(params: dict[str, Any]) -> BrowserRuntimeSession:
    session = session_from_browser_target(params, allow_missing=True)
    if session is not None:
        return session
    launched = browser_launch({"profile_name": optional_text(params, "profile_name", optional_text(params, "profile")), "headless": params.get("headless")})
    session = _SESSIONS.get(str(launched.get("session_id") or ""))
    if session is None:
        raise ToolInputError("Browser session could not be launched")
    return session


def session_from_browser_target(params: dict[str, Any], allow_missing: bool = False) -> BrowserRuntimeSession | None:
    target_id = optional_text(params, "targetId", optional_text(params, "session_id"))
    if target_id:
        for session in _SESSIONS.values():
            labels = session.state.get("tab_labels")
            if isinstance(labels, dict) and labels.get(target_id) == session.session_id:
                return session
        session = _SESSIONS.get(target_id)
        if session is not None:
            return session
    return session_from_params({}, allow_missing=allow_missing)


def label_for_session(session: BrowserRuntimeSession) -> str:
    labels = session.state.get("tab_labels")
    if not isinstance(labels, dict):
        return ""
    for label, session_id in labels.items():
        if session_id == session.session_id and isinstance(label, str):
            return label
    return ""


def close_session(session_id: str) -> None:
    global _ACTIVE_SESSION_ID
    session = _SESSIONS.pop(session_id, None)
    if session is None:
        return
    try:
        sync_state(session, {"page_load_state": "closing"})
    except Exception:
        pass
    try:
        for page in session.context.pages:
            _ATTACHED_PAGE_EVENTS.discard(id(page))
    except Exception:
        _ATTACHED_PAGE_EVENTS.discard(id(session.page))
    try:
        session.context.close()
    finally:
        config = load_config()
        state = dict(session.state)
        state["page_load_state"] = "closed"
        write_session_state(config, state)
    if _ACTIVE_SESSION_ID == session_id:
        _ACTIVE_SESSION_ID = next(iter(_SESSIONS), "")


def close_browser() -> None:
    global _PLAYWRIGHT, _ACTIVE_SESSION_ID
    for session_id in list(_SESSIONS.keys()):
        close_session(session_id)
    if _PLAYWRIGHT is not None:
        _PLAYWRIGHT.stop()
    _PLAYWRIGHT = None
    _ACTIVE_SESSION_ID = ""
    _ATTACHED_PAGE_EVENTS.clear()


def attach_context_events(session: BrowserRuntimeSession) -> None:
    attach_page_events(session, session.page)

    def on_page(page: Any) -> None:
        _POPUPS.setdefault(session.session_id, []).append(page)
        browser_network.attach_network_listeners(page, session.session_id, load_config())
        attach_page_events(session, page)

    session.context.on("page", on_page)


def attach_page_events(session: BrowserRuntimeSession, page: Any) -> None:
    browser_network.attach_network_listeners(page, session.session_id, load_config())
    page_key = id(page)
    if page_key in _ATTACHED_PAGE_EVENTS:
        return
    _ATTACHED_PAGE_EVENTS.add(page_key)

    def on_dialog(dialog: Any) -> None:
        _PENDING_DIALOGS[session.session_id] = dialog
        update_session_state(load_config(), session.state, {"dialog_pending": dialog_summary(dialog)})

    def on_download(download: Any) -> None:
        update_session_state(
            load_config(),
            session.state,
            {"download_in_progress": True, "download": {"suggested_filename": download.suggested_filename}},
        )

    try:
        page.on("dialog", on_dialog)
        page.on("download", on_download)
    except Exception:
        pass


def sync_state(session: BrowserRuntimeSession, updates: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_config()
    page = session.page
    title = safe_page_title(page)
    url = page.url if page is not None and not page.is_closed() else ""
    state = dict(session.state)
    append_history(state, url, title)
    state.update(
        {
            "session_id": session.session_id,
            "profile_name": session.profile_name,
            "current_url": url,
            "current_title": title,
            "page_load_state": session.page_load_state,
            "active_frames": frame_summaries(page) if page is not None and not page.is_closed() else [],
            "dialog_pending": dialog_summary(_PENDING_DIALOGS.get(session.session_id)) if _PENDING_DIALOGS.get(session.session_id) is not None else None,
            "network_idle": browser_network.network_idle(session.session_id),
            "intercepted_requests": browser_network.recent_request_summaries(session.session_id),
            "cookies": safe_cookies(session),
            "local_storage_keys": local_storage_keys(page),
            "current_frame": current_frame_summary(session),
        }
    )
    if updates:
        state.update(updates)
    session.state = write_session_state(config, state)
    return session.state


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "session_id",
        "profile_name",
        "started_at",
        "updated_at",
        "current_url",
        "current_title",
        "page_load_state",
        "navigation_history",
        "active_frames",
        "dialog_pending",
        "download_in_progress",
        "network_idle",
        "intercepted_requests",
        "cookies",
        "local_storage_keys",
        "dom_snapshot_path",
        "last_screenshot_path",
        "workflow_state",
        "current_frame",
        "last_error",
    ]
    return {key: state.get(key) for key in keys}


def snapshot_for_session(session: BrowserRuntimeSession, params: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_config()
    params = params or {}
    if params.get("max_elements_per_type") is not None:
        dom_config = dict(config.get("dom_snapshot") if isinstance(config.get("dom_snapshot"), dict) else {})
        dom_config["max_elements_per_type"] = params.get("max_elements_per_type")
        if params.get("include_accessibility_tree") is not None:
            dom_config["include_accessibility_tree"] = bool(params.get("include_accessibility_tree"))
        config = dict(config)
        config["dom_snapshot"] = dom_config
    target = interaction_target(session)
    label = "frame-dom" if session.current_frame is not None else "dom"
    snapshot = browser_dom.snapshot_target(target, config, session.session_id, label)
    session.state = update_session_state(load_config(), session.state, {"dom_snapshot_path": snapshot.get("snapshot_path", "")})
    return snapshot


def snapshot_refs(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    interactive = snapshot.get("interactive_elements")
    if not isinstance(interactive, dict):
        return refs
    for group, values in interactive.items():
        if not isinstance(values, list):
            continue
        for item in values:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("ref") or "").strip()
            selector = str(item.get("selector") or "").strip()
            if not ref or not selector:
                continue
            refs[ref] = {
                "ref": ref,
                "selector": selector,
                "group": group,
                "role": item.get("role", ""),
                "text": item.get("text", ""),
                "label": item.get("label", ""),
                "placeholder": item.get("placeholder", ""),
                "value": item.get("value", item.get("current_value", "")),
                "visible": item.get("visible", False),
                "enabled": item.get("enabled", True),
            }
    return refs


def format_ref_snapshot(snapshot: dict[str, Any], compact: bool, urls: bool) -> str:
    interactive = snapshot.get("interactive_elements")
    structure = snapshot.get("page_structure")
    if not isinstance(interactive, dict):
        interactive = {}
    if not isinstance(structure, dict):
        structure = {}
    lines = [f'Title: {snapshot.get("title", "")}', f'URL: {snapshot.get("url", "")}']
    headings = structure.get("headings")
    if isinstance(headings, list) and headings:
        lines.append("Headings:")
        for item in headings[:8]:
            if isinstance(item, dict):
                lines.append(f'- h{item.get("level", "")} "{item.get("text", "")}"')
    groups = ["comboboxes", "inputs", "editable_elements", "textareas", "selects", "listboxes", "options", "buttons", "links", "checkboxes"]
    for group in groups:
        values = interactive.get(group)
        if not isinstance(values, list) or not values:
            continue
        lines.append(group + ":")
        for item in values[:40]:
            if not isinstance(item, dict):
                continue
            ref = item.get("ref", "")
            name = first_non_empty(item.get("label"), item.get("text"), item.get("placeholder"), item.get("name"), item.get("value"), item.get("current_value"))
            descriptor = f'- [{ref}] {group[:-1]}'
            if name:
                descriptor += f' "{name}"'
            role = item.get("role")
            if role:
                descriptor += f" role={role}"
            if item.get("visible") is False:
                descriptor += " hidden"
            if item.get("enabled") is False:
                descriptor += " disabled"
            if urls and item.get("href"):
                descriptor += f' href={item.get("href")}'
            lines.append(descriptor)
            if compact and len(lines) > 160:
                lines.append("(snapshot truncated)")
                return "\n".join(lines)
    alerts = structure.get("alerts")
    if isinstance(alerts, list) and alerts:
        lines.append("Alerts:")
        for item in alerts[:8]:
            if isinstance(item, dict):
                lines.append(f'- "{item.get("text", "")}"')
    return "\n".join(lines)


def first_non_empty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def ref_selector(session: BrowserRuntimeSession, ref: str) -> str:
    refs = session.state.get("ref_map")
    if not isinstance(refs, dict):
        raise ToolInputError("No ref map is available. Run browser action=snapshot first.")
    item = refs.get(ref)
    if not isinstance(item, dict):
        raise ToolInputError(f"Unknown or stale browser ref: {ref}. Run browser action=snapshot again.")
    selector = item.get("selector")
    if not isinstance(selector, str) or not selector.strip():
        raise ToolInputError(f"Browser ref has no actionable selector: {ref}")
    return selector


def read_target_url(params: dict[str, Any]) -> str:
    return require_text({"url": optional_text(params, "targetUrl", optional_text(params, "url"))}, "url")


def browser_wait_request(session_id: str, request: dict[str, Any], timeout: Any) -> dict[str, Any]:
    if request.get("textGone"):
        return {"session_id": session_id, "condition": "element_disappears", "selector": f"text={request.get('textGone')}", "timeout_ms": timeout}
    if request.get("text"):
        return {"session_id": session_id, "condition": "text_appears", "text": str(request.get("text")), "timeout_ms": timeout}
    if request.get("selector"):
        return {"session_id": session_id, "condition": "element_appears", "selector": str(request.get("selector")), "timeout_ms": timeout}
    if request.get("url"):
        return {"session_id": session_id, "condition": "url_changes", "url_pattern": str(request.get("url")), "timeout_ms": timeout}
    if request.get("loadState"):
        return {"session_id": session_id, "condition": "network_idle" if request.get("loadState") == "networkidle" else "element_appears", "selector": "body", "timeout_ms": timeout}
    time_ms = bounded_int(request.get("timeMs"), 250, 0, 120000)
    if time_ms:
        time.sleep(time_ms / 1000)
    return {"session_id": session_id, "condition": "element_appears", "selector": "body", "timeout_ms": timeout}


def interaction_target(session: BrowserRuntimeSession) -> Any:
    if session.current_frame is not None:
        return session.current_frame
    return session.page


def locator_from_params(target: Any, params: dict[str, Any]) -> Any:
    selector = optional_text(params, "selector")
    if selector:
        return target.locator(selector).first
    text = optional_text(params, "text")
    if text:
        return target.get_by_text(text).first
    aria = optional_text(params, "aria_label")
    if aria:
        return target.get_by_label(aria).first
    raise ToolInputError("selector, text, aria_label, or coordinates are required")


def field_locator(target: Any, selector: str) -> Any:
    if selector:
        return target.locator(selector).first
    return target.locator("input:visible, textarea:visible, [contenteditable='true']:visible, [contenteditable='plaintext-only']:visible, [role='textbox']:visible, [role='combobox']:visible").first


def fill_field(locator: Any, text: str, params: dict[str, Any]) -> str:
    timeout = timeout_ms(params)
    clear = bool(params.get("clear", False))
    human_like = bool(params.get("human_like", False)) or human_simulation_enabled()
    try:
        if clear:
            locator.fill("", timeout=timeout)
        if human_like:
            for char in text:
                locator.type(char, delay=typing_delay_ms(), timeout=timeout)
            return "typed_with_element"
        locator.fill(text, timeout=timeout)
        return "filled_element"
    except Exception as first_error:
        try:
            locator.click(timeout=timeout)
            if clear:
                locator.press("Control+A", timeout=timeout)
                locator.press("Backspace", timeout=timeout)
            if human_like:
                for char in text:
                    locator.type(char, delay=typing_delay_ms(), timeout=timeout)
                return "clicked_and_typed"
            locator.type(text, timeout=timeout)
            return "clicked_and_typed"
        except Exception:
            try:
                locator.evaluate(
                    """
                    (element, value) => {
                      if ("value" in element) {
                        element.value = value;
                      } else {
                        element.textContent = value;
                      }
                      element.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: value}));
                      element.dispatchEvent(new Event("change", {bubbles: true}));
                    }
                    """,
                    text,
                    timeout=timeout,
                )
                return "dom_input_event"
            except Exception as final_error:
                raise ToolInputError(f"Unable to type into field. fill failed: {first_error}; fallback failed: {final_error}") from final_error


def click_option_by_text(target: Any, label: str, timeout: int) -> None:
    option_selectors = [
        "[role='option']",
        "[role='menuitem']",
        "option",
        "li",
        "[data-value]",
    ]
    lowered = label.casefold()
    for selector in option_selectors:
        locator = target.locator(selector).filter(has_text=label).first
        try:
            locator.click(timeout=min(timeout, 3000))
            return
        except Exception:
            continue
    try:
        target.get_by_text(label, exact=True).first.click(timeout=min(timeout, 3000))
        return
    except Exception:
        pass
    try:
        target.get_by_text(label).first.click(timeout=timeout)
        return
    except Exception as error:
        raise ToolInputError(f"Unable to click option containing {lowered}") from error


def wait_for_stability(session: BrowserRuntimeSession, params: dict[str, Any] | None = None) -> None:
    params = params or {}
    timeout = timeout_ms(params)
    try:
        session.page.wait_for_load_state("domcontentloaded", timeout=min(timeout, 5000))
        session.page_load_state = "domcontentloaded"
    except Exception:
        pass


def set_checked(params: dict[str, Any], checked: bool) -> dict[str, Any]:
    session = ensure_session(params)
    target = interaction_target(session)
    selector = require_text(params, "selector")
    locator = target.locator(selector).first
    locator.set_checked(checked, timeout=timeout_ms(params))
    state = locator.is_checked(timeout=timeout_ms(params))
    wait_for_stability(session, params)
    sync_state(session)
    return {"summary": "Control state updated.", "session_id": session.session_id, "checked": state, "state": public_state(session.state)}


def scroll_script(target: Any, selector: str, mode: str, amount: int) -> None:
    target.evaluate(
        """
        ({selector, mode, amount}) => {
          const element = selector ? document.querySelector(selector) : document.scrollingElement || document.documentElement;
          if (!element) {
            return;
          }
          if (mode === "bottom") {
            element.scrollTo({top: element.scrollHeight, behavior: "instant"});
          } else if (mode === "top") {
            element.scrollTo({top: 0, behavior: "instant"});
          } else {
            element.scrollBy({top: amount, behavior: "instant"});
          }
        }
        """,
        {"selector": selector, "mode": mode, "amount": amount},
    )


def autocomplete_suggestions(target: Any) -> list[dict[str, Any]]:
    try:
        return target.evaluate(
            """
            () => Array.from(document.querySelectorAll("[role='option'], option, datalist option")).slice(0, 20).map((item) => ({
              text: (item.innerText || item.textContent || item.getAttribute("label") || "").trim(),
              value: item.getAttribute("value") || "",
              visible: Boolean(item.offsetWidth || item.offsetHeight || item.getClientRects().length)
            }))
            """
        )
    except Exception:
        return []


def execute_workflow_step(session: BrowserRuntimeSession, step: dict[str, Any]) -> dict[str, Any]:
    action = str(step.get("action") or "model_action")
    if action == "navigate_site":
        site = str(step.get("site") or "")
        url = site_url(site, load_config())
        if not url:
            return {"summary": "Workflow site has no configured base URL.", "requires_model_action": True, "site": site}
        return browser_navigate({"session_id": session.session_id, "url": url, "capture_snapshot": True})
    if action == "snapshot":
        snapshot = browser_snapshot({"session_id": session.session_id})
        return {"summary": "Workflow snapshot captured.", "snapshot_path": snapshot.get("snapshot_path", "")}
    if action == "detect_state":
        return browser_detect_state({"session_id": session.session_id})
    if action == "checkpoint":
        workflow = browser_workflow.checkpoint(active_workflow(session), str(step.get("name") or ""), session.state)
        return {"summary": "Workflow checkpoint saved.", "name": str(step.get("name") or ""), "_workflow_state": workflow}
    if action == "network_log":
        return browser_network_log({"session_id": session.session_id, "limit": 50})
    if action == "frame_list":
        return browser_frame_list({"session_id": session.session_id})
    if action == "media_extract":
        return browser_media_extract({"session_id": session.session_id})
    if action == "media_state":
        return browser_media_state({"session_id": session.session_id})
    if action == "wait_for":
        params = dict(step.get("params") if isinstance(step.get("params"), dict) else {})
        params["session_id"] = session.session_id
        return browser_wait_for(params)
    return {"summary": str(step.get("label") or "Workflow needs model action."), "requires_model_action": True, "step": step}


def active_workflow(session: BrowserRuntimeSession) -> dict[str, Any]:
    workflow = session.state.get("workflow_state")
    if not isinstance(workflow, dict):
        raise ToolInputError("No active browser workflow")
    return workflow


def workflow_public(workflow: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(workflow, dict):
        return None
    return {
        "workflow_id": workflow.get("workflow_id"),
        "name": workflow.get("name"),
        "current_step": workflow.get("current_step"),
        "total_steps": workflow.get("total_steps"),
        "last_result": workflow.get("last_result"),
        "errors": workflow.get("errors", []),
        "blocked": workflow.get("blocked", False),
        "blocked_reason": workflow.get("blocked_reason", ""),
        "status": workflow.get("status", ""),
        "checkpoints": workflow.get("checkpoints", {}),
    }


def site_url(site: str, config: dict[str, Any]) -> str:
    sites = config.get("sites")
    if not isinstance(sites, dict):
        return ""
    item = sites.get(site)
    if not isinstance(item, dict):
        return ""
    url = item.get("base_url")
    return url.strip() if isinstance(url, str) else ""


def current_frame_summary(session: BrowserRuntimeSession) -> dict[str, Any] | None:
    if session.current_frame is None:
        return None
    frames = session.page.frames
    try:
        index = frames.index(session.current_frame)
    except ValueError:
        index = -1
    return frame_summary(session.current_frame, index)


def frame_summaries(page: Any) -> list[dict[str, Any]]:
    if page is None or page.is_closed():
        return []
    return [frame_summary(frame, index) for index, frame in enumerate(page.frames)]


def frame_summary(frame: Any, index: int) -> dict[str, Any]:
    return {"index": index, "name": frame.name, "url": frame.url, "main": frame.parent_frame is None, "accessible": True}


def state_signature(session: BrowserRuntimeSession) -> dict[str, str]:
    return {"url": session.page.url, "title": safe_page_title(session.page)}


def compare_state(before: dict[str, str], after: dict[str, str]) -> dict[str, bool]:
    return {key: before.get(key) != after.get(key) for key in sorted(set(before) | set(after))}


def safe_cookies(session: BrowserRuntimeSession) -> list[dict[str, Any]]:
    try:
        return cookie_metadata(session.context.cookies())
    except Exception:
        return []


def local_storage_keys(page: Any) -> list[str]:
    try:
        value = page.evaluate("() => Object.keys(window.localStorage || {})")
        return [item for item in value if isinstance(item, str)]
    except Exception:
        return []


def dialog_summary(dialog: Any) -> dict[str, Any]:
    return {"type": dialog.type, "message": dialog.message, "default_value": dialog.default_value}


def safe_page_title(page: Any) -> str:
    if page is None:
        return ""
    try:
        return page.title()
    except Exception:
        return ""


def remember_playwright_chromium_executable(playwright: Any | None) -> str:
    global _PLAYWRIGHT_CHROMIUM_EXECUTABLE
    if playwright is None:
        return _PLAYWRIGHT_CHROMIUM_EXECUTABLE
    try:
        executable = str(playwright.chromium.executable_path or "")
    except Exception:
        executable = ""
    if executable:
        _PLAYWRIGHT_CHROMIUM_EXECUTABLE = executable
    return _PLAYWRIGHT_CHROMIUM_EXECUTABLE


def apply_page_viewport(page: Any, viewport: dict[str, int] | None) -> bool:
    if not viewport:
        return False
    try:
        page.set_viewport_size(viewport)
        return True
    except Exception:
        return False


def cleanup_profile_locks(profile_path: Path) -> list[str]:
    removed: list[str] = []
    for lock_path in profile_lock_paths(profile_path):
        if not lock_path.exists() and not lock_path.is_symlink():
            continue
        pid = lock_pid(lock_path)
        if pid is not None and process_is_running(pid):
            continue
        if lock_path.is_dir() and not lock_path.is_symlink():
            continue
        try:
            lock_path.unlink()
            removed.append(str(lock_path))
        except Exception:
            continue
    return removed


def profile_lock_paths(profile_path: Path) -> list[Path]:
    return [profile_path / "SingletonLock", profile_path / "Default" / "LOCK"]


def lock_pid(path: Path) -> int | None:
    texts: list[str] = []
    try:
        if path.is_symlink():
            texts.append(os.readlink(path))
    except Exception:
        pass
    try:
        texts.append(path.read_text(encoding="utf-8-sig", errors="ignore"))
    except Exception:
        pass
    for text in texts:
        pid = last_positive_int(text)
        if pid is not None:
            return pid
    return None


def last_positive_int(text: str) -> int | None:
    current = ""
    numbers: list[int] = []
    for char in text:
        if char.isdigit():
            current += char
        elif current:
            numbers.append(int(current))
            current = ""
    if current:
        numbers.append(int(current))
    for number in reversed(numbers):
        if number > 0:
            return number
    return None


def process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:
            return True
        return str(pid) in completed.stdout
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def playwright_available() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("playwright") is not None
    except Exception:
        return False


def resolve_browser_executable(config: dict[str, Any], browser_name: str = "", playwright: Any | None = None) -> Path | None:
    values = template_values(playwright)
    executables = config.get("browser_executables")
    candidates: list[str] = []
    if browser_name and isinstance(executables, dict):
        value = executables.get(browser_name)
        if isinstance(value, str) and value.strip():
            candidates.append(value)
    candidates.extend([item for item in config.get("browser_executable_candidates", []) if isinstance(item, str)])
    for candidate in candidates:
        expanded = expand_template(candidate, values)
        path = Path(os.path.expandvars(expanded))
        if path.exists():
            return path.resolve()
    return None


def template_values(playwright: Any | None = None) -> dict[str, str]:
    values = {
        "programfiles": os.environ.get("ProgramFiles", ""),
        "programfilesx86": os.environ.get("ProgramFiles(x86)", ""),
        "localappdata": os.environ.get("LOCALAPPDATA", ""),
        "home": str(Path.home()),
        "cwd": str(Path.cwd()),
        "playwright_chromium": "",
    }
    if playwright is not None:
        values["playwright_chromium"] = remember_playwright_chromium_executable(playwright)
    else:
        values["playwright_chromium"] = _PLAYWRIGHT_CHROMIUM_EXECUTABLE
    return values


def expand_template(value: str, values: dict[str, str]) -> str:
    expanded = value
    for key, replacement in values.items():
        expanded = expanded.replace("{" + key + "}", replacement)
    return expanded


def browser_engine(browser_name: str, playwright: Any) -> Any:
    key = browser_name.casefold()
    if key == "firefox":
        return playwright.firefox
    return playwright.chromium


def browser_engine_warning(browser_name: str, executable: Path | None, playwright: Any | None) -> str:
    if executable is None or playwright is None:
        return ""
    bundled = remember_playwright_chromium_executable(playwright)
    if not bundled:
        return ""
    try:
        if executable.resolve() == Path(bundled).resolve():
            return ""
    except Exception:
        return ""
    key = browser_name.casefold().strip()
    label = key or executable.stem
    if key == "firefox":
        return ""
    return f"Using Playwright chromium driver with external {label} executable at {executable}."


def browser_headless(params: dict[str, Any], config: dict[str, Any]) -> bool:
    if isinstance(params.get("headless"), bool):
        return bool(params["headless"])
    return env_bool("JARVIS_BROWSER_HEADLESS", bool(config.get("headless", False)))


def viewport_from_params(value: Any, config: dict[str, Any]) -> dict[str, int] | None:
    raw = value if isinstance(value, dict) else config.get("default_viewport")
    if not isinstance(raw, dict):
        return None
    width = bounded_int(raw.get("width"), 1280, 320, 7680)
    height = bounded_int(raw.get("height"), 900, 320, 4320)
    return {"width": width, "height": height}


def proxy_options(config: dict[str, Any]) -> dict[str, str] | None:
    proxy = config.get("proxy")
    if not isinstance(proxy, dict) or not bool(proxy.get("enabled", False)):
        return None
    server = str(proxy.get("server") or "").strip()
    if not server:
        return None
    result = {"server": server}
    username_env = str(proxy.get("username_env") or "").strip()
    password_env = str(proxy.get("password_env") or "").strip()
    username = os.environ.get(username_env, "") if username_env else ""
    password = os.environ.get(password_env, "") if password_env else ""
    if username:
        result["username"] = username
    if password:
        result["password"] = password
    return result


def auto_snapshot_enabled() -> bool:
    dom_config = load_config().get("dom_snapshot")
    return bool(isinstance(dom_config, dict) and dom_config.get("auto_snapshot_on_navigate", True))


def timeout_ms(params: dict[str, Any] | None = None) -> int:
    params = params or {}
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


def normalize_url(value: str) -> str:
    text = value.strip()
    lowered = text.lower()
    if "://" in text or lowered.startswith("data:") or lowered.startswith("about:") or lowered.startswith("file:"):
        return text
    return "https://" + text


def build_url(template: str, values: dict[str, str]) -> str:
    if not template:
        raise ToolInputError("Browser URL template is not configured")
    url = template
    for key, value in values.items():
        url = url.replace("{" + key + "}", urllib.parse.quote(value, safe=""))
    return url


def human_simulation_enabled() -> bool:
    config = load_config()
    human = config.get("human_simulation")
    return bool(isinstance(human, dict) and human.get("enabled", False))


def human_delay(config: dict[str, Any], kind: str) -> None:
    human = config.get("human_simulation")
    if not isinstance(human, dict) or not bool(human.get("enabled", False)):
        return
    if kind == "click":
        minimum = bounded_int(human.get("click_delay_ms_min"), 80, 0, 10000)
        maximum = bounded_int(human.get("click_delay_ms_max"), 200, minimum, 10000)
    else:
        minimum = bounded_int(human.get("scroll_delay_ms"), 150, 0, 10000)
        maximum = minimum
    time.sleep(random.randint(minimum, maximum) / 1000)


def typing_delay_ms() -> int:
    human = load_config().get("human_simulation")
    if not isinstance(human, dict):
        return 0
    minimum = bounded_int(human.get("typing_delay_ms_min"), 40, 0, 10000)
    maximum = bounded_int(human.get("typing_delay_ms_max"), 120, minimum, 10000)
    return random.randint(minimum, maximum)


def wait_until(predicate: Any, timeout: int) -> None:
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.1)
    raise ToolInputError("Timed out waiting for browser condition")


def url_condition_ok(url: str, pattern: str) -> bool:
    if not pattern:
        return True
    return browser_network.pattern_matches(url, pattern)


def text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
