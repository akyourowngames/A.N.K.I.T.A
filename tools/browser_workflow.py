from __future__ import annotations

import uuid
from typing import Any

from tools.browser_state import now_iso


WORKFLOW_TYPES = {
    "flight_search",
    "flight_book",
    "hotel_search",
    "hotel_book",
    "video_watch",
    "form_fill",
    "product_search",
    "product_buy",
    "login",
    "custom",
}


def start_workflow(workflow_type: str, parameters: dict[str, Any], config: dict[str, Any], custom_steps: list[Any] | None = None) -> dict[str, Any]:
    clean_type = workflow_type.strip()
    if clean_type not in WORKFLOW_TYPES:
        clean_type = "custom"
    steps = build_steps(clean_type, parameters, config, custom_steps)
    return {
        "workflow_id": uuid.uuid4().hex,
        "name": clean_type,
        "parameters": parameters,
        "started_at": now_iso(),
        "updated_at": now_iso(),
        "current_step": 0,
        "total_steps": len(steps),
        "steps": steps,
        "last_result": None,
        "errors": [],
        "blocked": False,
        "blocked_reason": "",
        "checkpoints": {},
        "status": "running",
    }


def build_steps(workflow_type: str, parameters: dict[str, Any], config: dict[str, Any], custom_steps: list[Any] | None) -> list[dict[str, Any]]:
    if workflow_type == "custom":
        return normalize_custom_steps(custom_steps or parameters.get("steps"))

    site = workflow_site(workflow_type, parameters, config)
    steps: list[dict[str, Any]] = []
    if site:
        steps.append({"action": "navigate_site", "site": site, "label": "Open workflow site"})
    steps.extend(
        [
            {"action": "snapshot", "label": "Capture structured DOM"},
            {"action": "detect_state", "label": "Detect page state"},
            {"action": "checkpoint", "name": "initial-page", "label": "Save initial checkpoint"},
            {"action": "model_action", "label": "Continue with page-specific operation"},
        ]
    )
    if workflow_type in {"flight_search", "hotel_search", "product_search"}:
        steps.append({"action": "network_log", "label": "Review network data after search"})
    if workflow_type in {"flight_book", "hotel_book", "product_buy"}:
        steps.extend(
            [
                {"action": "frame_list", "label": "Inspect embedded checkout frames"},
                {"action": "checkpoint", "name": "before-sensitive-submit", "label": "Save sensitive action checkpoint"},
                {"action": "model_action", "label": "Ask before irreversible submit"},
            ]
        )
    if workflow_type == "video_watch":
        steps.extend(
            [
                {"action": "media_extract", "label": "Extract media metadata"},
                {"action": "media_state", "label": "Verify media state"},
            ]
        )
    if workflow_type == "form_fill":
        steps.append({"action": "model_action", "label": "Fill requested form fields from snapshot"})
    if workflow_type == "login":
        steps.append({"action": "model_action", "label": "Fill login fields from provided secret sources"})
    return steps


def normalize_custom_steps(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return [{"action": "model_action", "label": "No custom steps supplied"}]
    steps: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            action = item.get("action") or item.get("tool") or "model_action"
            step = dict(item)
            step["action"] = str(action)
            steps.append(step)
        elif isinstance(item, str) and item.strip():
            steps.append({"action": "model_action", "label": item.strip()})
    return steps or [{"action": "model_action", "label": "No custom steps supplied"}]


def workflow_site(workflow_type: str, parameters: dict[str, Any], config: dict[str, Any]) -> str:
    site = parameters.get("site")
    if isinstance(site, str) and site.strip():
        return site.strip()
    defaults = config.get("workflow_defaults")
    if isinstance(defaults, dict):
        item = defaults.get(workflow_type)
        if isinstance(item, dict):
            configured = item.get("site")
            if isinstance(configured, str) and configured.strip():
                return configured.strip()
    return ""


def current_step(workflow: dict[str, Any]) -> dict[str, Any] | None:
    steps = workflow.get("steps")
    index = workflow.get("current_step")
    if not isinstance(steps, list) or not isinstance(index, int):
        return None
    if index < 0 or index >= len(steps):
        return None
    step = steps[index]
    return step if isinstance(step, dict) else None


def complete_step(workflow: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    updated = dict(workflow)
    updated["last_result"] = result
    updated["updated_at"] = now_iso()
    updated["current_step"] = int(updated.get("current_step", 0)) + 1
    if updated["current_step"] >= int(updated.get("total_steps", 0)):
        updated["status"] = "completed"
    return updated


def fail_step(workflow: dict[str, Any], error: str) -> dict[str, Any]:
    updated = dict(workflow)
    errors = updated.get("errors")
    if not isinstance(errors, list):
        errors = []
    errors.append({"step": updated.get("current_step", 0), "error": error, "timestamp": now_iso()})
    updated["errors"] = errors
    updated["last_result"] = {"ok": False, "error": error}
    updated["updated_at"] = now_iso()
    return updated


def checkpoint(workflow: dict[str, Any], name: str, state: dict[str, Any]) -> dict[str, Any]:
    updated = dict(workflow)
    checkpoints = updated.get("checkpoints")
    if not isinstance(checkpoints, dict):
        checkpoints = {}
    checkpoint_name = name.strip() if name.strip() else f"step-{updated.get('current_step', 0)}"
    checkpoints[checkpoint_name] = {
        "saved_at": now_iso(),
        "current_step": updated.get("current_step", 0),
        "current_url": state.get("current_url", ""),
        "current_title": state.get("current_title", ""),
        "dom_snapshot_path": state.get("dom_snapshot_path", ""),
        "last_screenshot_path": state.get("last_screenshot_path", ""),
    }
    updated["checkpoints"] = checkpoints
    updated["updated_at"] = now_iso()
    return updated


def abort(workflow: dict[str, Any]) -> dict[str, Any]:
    updated = dict(workflow)
    updated["status"] = "aborted"
    updated["updated_at"] = now_iso()
    return updated


def recover(workflow: dict[str, Any], strategy: str) -> dict[str, Any]:
    updated = dict(workflow)
    chosen = strategy.strip() or "retry"
    if chosen == "retry":
        updated["blocked"] = False
        updated["blocked_reason"] = ""
    elif chosen == "back":
        updated["current_step"] = max(0, int(updated.get("current_step", 0)) - 1)
    elif chosen == "checkpoint":
        checkpoints = updated.get("checkpoints")
        if isinstance(checkpoints, dict) and checkpoints:
            latest = list(checkpoints.values())[-1]
            if isinstance(latest, dict):
                updated["current_step"] = int(latest.get("current_step", updated.get("current_step", 0)))
    elif chosen == "restart":
        updated["current_step"] = 0
        updated["blocked"] = False
        updated["blocked_reason"] = ""
    elif chosen == "escalate":
        updated["blocked"] = True
        updated["blocked_reason"] = "Workflow needs user input or approval."
    updated["updated_at"] = now_iso()
    updated["last_result"] = {"summary": "Workflow recovery applied.", "strategy": chosen}
    return updated
