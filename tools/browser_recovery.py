from __future__ import annotations

from typing import Any


STATE_ORDER = [
    "captcha",
    "login_wall",
    "rate_limited",
    "error_page",
    "loading",
    "checkout",
    "product",
    "results",
    "form",
    "success",
    "unknown",
]


def detect_state(snapshot: dict[str, Any], session_state: dict[str, Any], status_code: int | None = None) -> dict[str, Any]:
    signals = structural_signals(snapshot, session_state, status_code)
    primary = "unknown"
    for state_name in STATE_ORDER:
        if signals.get(state_name):
            primary = state_name
            break
    return {"summary": f"Detected browser state: {primary}.", "state": primary, "signals": signals}


def structural_signals(snapshot: dict[str, Any], session_state: dict[str, Any], status_code: int | None) -> dict[str, Any]:
    interactive = snapshot.get("interactive_elements") if isinstance(snapshot, dict) else {}
    structure = snapshot.get("page_structure") if isinstance(snapshot, dict) else {}
    if not isinstance(interactive, dict):
        interactive = {}
    if not isinstance(structure, dict):
        structure = {}
    inputs = [*list_values(interactive.get("inputs")), *list_values(interactive.get("editable_elements")), *list_values(interactive.get("comboboxes"))]
    iframes = list_values(interactive.get("iframes"))
    buttons = list_values(interactive.get("buttons"))
    links = list_values(interactive.get("links"))
    forms = list_values(structure.get("forms"))
    loading = list_values(structure.get("loading_indicators"))
    alerts = list_values(structure.get("alerts"))
    modals = list_values(structure.get("modals"))
    headings = list_values(structure.get("headings"))
    request_entries = list_values(session_state.get("intercepted_requests"))

    password_inputs = [item for item in inputs if item.get("type") == "password"]
    captcha_elements = captcha_candidates(snapshot)
    checkout_fields = [item for item in inputs if str(item.get("autocomplete", "")).startswith("cc-")]
    visible_controls = [item for item in [*buttons, *links] if item.get("visible")]
    result_like_density = len(visible_controls) >= 8 and (len(headings) >= 1 or len(links) >= 8)
    product_structured = has_json_ld_type(snapshot, "Product")
    success = bool(session_state.get("workflow_state") and session_state.get("workflow_state", {}).get("status") == "completed")
    latest_status = status_code or latest_response_status(request_entries)

    return {
        "login_wall": bool(password_inputs),
        "captcha": bool(captcha_elements),
        "rate_limited": latest_status == 429,
        "error_page": bool(latest_status and latest_status >= 400 and latest_status != 429),
        "loading": bool(loading) or not bool(session_state.get("network_idle", True)),
        "form": bool(forms or inputs),
        "results": result_like_density,
        "product": product_structured,
        "checkout": bool(checkout_fields),
        "success": success,
        "unknown": False,
        "counts": {
            "inputs": len(inputs),
            "forms": len(forms),
            "buttons": len(buttons),
            "links": len(links),
            "alerts": len(alerts),
            "modals": len(modals),
            "iframes": len(iframes),
            "captcha_candidates": len(captcha_elements),
        },
    }


def find_element(snapshot: dict[str, Any], description: str, element_type: str = "") -> dict[str, Any]:
    target_terms = meaningful_terms(description)
    typed = normalize_group_name(element_type)
    candidates = snapshot_candidates(snapshot)
    scored: list[tuple[float, dict[str, Any]]] = []
    for candidate in candidates:
        if typed and candidate.get("group") != typed:
            continue
        score = element_score(candidate, target_terms)
        if score > 0:
            scored.append((score, candidate))
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return {"summary": "No matching element found.", "selector": "", "confidence": 0.0, "candidate": None}
    score, candidate = scored[0]
    confidence = min(1.0, score / max(1, len(target_terms)))
    return {
        "summary": "Best matching element found.",
        "selector": candidate.get("selector", ""),
        "confidence": round(confidence, 3),
        "candidate": candidate,
    }


def normalize_group_name(value: str) -> str:
    text = value.strip().casefold()
    aliases = {
        "button": "buttons",
        "input": "inputs",
        "field": "inputs",
        "textbox": "editable_elements",
        "editable": "editable_elements",
        "combobox": "comboboxes",
        "dropdown": "comboboxes",
        "select": "selects",
        "listbox": "listboxes",
        "option": "options",
        "suggestion": "options",
        "link": "links",
        "checkbox": "checkboxes",
        "radio": "checkboxes",
        "textarea": "textareas",
    }
    return aliases.get(text, text)


def captcha_candidates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    interactive = snapshot.get("interactive_elements") if isinstance(snapshot, dict) else {}
    if not isinstance(interactive, dict):
        return []
    candidates: list[dict[str, Any]] = []
    for item in list_values(interactive.get("inputs")):
        if item.get("name") == "g-recaptcha-response":
            candidates.append(item)
    for item in list_values(interactive.get("iframes")):
        src = str(item.get("src", ""))
        title = str(item.get("title", ""))
        if "captcha" in src.casefold() or "captcha" in title.casefold():
            candidates.append(item)
    return candidates


def solve_captcha(snapshot: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    candidates = captcha_candidates(snapshot)
    if not candidates:
        return {"summary": "No CAPTCHA evidence found in the current snapshot.", "detected": False, "attempted": False}
    captcha_config = config.get("captcha")
    if not isinstance(captcha_config, dict):
        captcha_config = {}
    return {
        "summary": "CAPTCHA evidence found; user input may be required.",
        "detected": True,
        "attempted": False,
        "auto_solve_checkbox": bool(captcha_config.get("auto_solve_checkbox", True)),
        "auto_solve_audio": bool(captcha_config.get("auto_solve_audio", False)),
        "escalate_to_user": bool(captcha_config.get("escalate_to_user", True)),
        "candidates": candidates,
    }


def anti_detect_script() -> str:
    return """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    """


def snapshot_candidates(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    interactive = snapshot.get("interactive_elements") if isinstance(snapshot, dict) else {}
    if not isinstance(interactive, dict):
        return []
    result: list[dict[str, Any]] = []
    for group in ["buttons", "inputs", "editable_elements", "comboboxes", "selects", "listboxes", "options", "links", "checkboxes", "textareas"]:
        for item in list_values(interactive.get(group)):
            if not isinstance(item, dict):
                continue
            candidate = dict(item)
            candidate["group"] = group
            result.append(candidate)
    return result


def element_score(candidate: dict[str, Any], terms: list[str]) -> float:
    if not terms:
        return 0.0
    haystack = " ".join(
        str(candidate.get(key, ""))
        for key in ["text", "label", "placeholder", "name", "aria_label", "role", "type", "href", "value", "current_value", "controls", "owns"]
    ).casefold()
    score = 0.0
    for term in terms:
        if term and term in haystack:
            score += 1.0
    group = str(candidate.get("group", ""))
    if any(term in {"field", "input", "type", "enter"} for term in terms) and group in {"inputs", "editable_elements", "comboboxes", "textareas"}:
        score += 0.75
    if any(term in {"option", "suggestion", "list", "result", "item"} for term in terms) and group in {"options", "listboxes", "links"}:
        score += 0.75
    if any(term in {"from", "origin", "source", "departure"} for term in terms) and "from" in haystack:
        score += 0.5
    if any(term in {"to", "destination", "arrival"} for term in terms) and "to" in haystack:
        score += 0.5
    if candidate.get("visible"):
        score += 0.25
    if candidate.get("enabled", True):
        score += 0.25
    return score


def meaningful_terms(text: str) -> list[str]:
    cleaned_chars: list[str] = []
    for char in text.casefold():
        if char.isalnum():
            cleaned_chars.append(char)
        else:
            cleaned_chars.append(" ")
    seen: set[str] = set()
    terms: list[str] = []
    for item in "".join(cleaned_chars).split():
        if len(item) < 2 or item in seen:
            continue
        seen.add(item)
        terms.append(item)
    return terms


def latest_response_status(entries: list[dict[str, Any]]) -> int | None:
    for item in reversed(entries):
        if item.get("kind") != "response":
            continue
        status = item.get("status")
        if isinstance(status, int):
            return status
    return None


def has_json_ld_type(snapshot: dict[str, Any], type_name: str) -> bool:
    typed = snapshot.get("schema_types")
    if not isinstance(typed, list):
        return False
    return type_name in typed


def list_values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
