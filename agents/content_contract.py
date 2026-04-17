from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_START = "CONTENT_PAYLOAD_V1"
_END = "CONTENT_PAYLOAD_V1_END"
_FORMATS = {"markdown", "plain_text"}
_TASK_TYPE_RE = re.compile(r"^[a-z][a-z0-9_ -]{1,63}$")


def parse_content_payload(text: str) -> Optional[Dict[str, Any]]:
    """
    Parse CONTENT_PAYLOAD_V1 envelope from model text.
    Returns a payload dict or None if envelope markers are missing.
    """
    raw = text or ""
    m = re.search(rf"{_START}\s*(.*?)\s*{_END}", raw, re.DOTALL)
    if not m:
        return None

    block = m.group(1)
    before = raw[: m.start()].strip()
    after = raw[m.end() :].strip()

    body_m = re.search(r"BODY_START\s*(.*?)\s*BODY_END", block, re.DOTALL)
    notes_m = re.search(r"NOTES_START\s*(.*?)\s*NOTES_END", block, re.DOTALL)

    header_section = block
    if body_m:
        header_section = block[: body_m.start()]

    headers: Dict[str, str] = {}
    for line in header_section.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        headers[key.strip().upper()] = val.strip()

    payload: Dict[str, Any] = {
        "task_type": headers.get("TASK_TYPE", ""),
        "title": headers.get("TITLE", ""),
        "format": headers.get("FORMAT", ""),
        "audience": headers.get("AUDIENCE", ""),
        "tone": headers.get("TONE", ""),
        "word_target": headers.get("WORD_TARGET", ""),
        "body": (body_m.group(1).strip() if body_m else ""),
        "notes": (notes_m.group(1).strip() if notes_m else ""),
        "_outside_text": "\n".join([x for x in (before, after) if x]).strip(),
    }
    return payload


def validate_content_payload(payload: Optional[Dict[str, Any]]) -> Tuple[bool, List[str]]:
    """Validate parsed payload shape and field constraints."""
    errors: List[str] = []
    if payload is None:
        return False, ["Missing CONTENT_PAYLOAD_V1 envelope"]

    if payload.get("_outside_text"):
        errors.append("Extra text exists outside CONTENT_PAYLOAD_V1 envelope")

    task_type = str(payload.get("task_type", "")).strip().lower()
    if not task_type or not _TASK_TYPE_RE.fullmatch(task_type):
        errors.append(f"Invalid TASK_TYPE: {task_type!r}")

    fmt = str(payload.get("format", "")).strip().lower()
    if fmt not in _FORMATS:
        errors.append(f"Invalid FORMAT: {fmt!r}")

    for field in ("title", "audience", "tone"):
        if not str(payload.get(field, "")).strip():
            errors.append(f"Missing/empty {field.upper()}")

    wt_raw = str(payload.get("word_target", "")).strip()
    try:
        wt = int(wt_raw)
        if wt <= 0:
            errors.append("WORD_TARGET must be > 0")
    except Exception:
        errors.append("WORD_TARGET must be an integer")

    if not str(payload.get("body", "")).strip():
        errors.append("BODY is empty or missing")

    return len(errors) == 0, errors


def extract_body(payload: Optional[Dict[str, Any]]) -> str:
    """Extract the BODY section from a parsed payload."""
    if not payload:
        return ""
    return str(payload.get("body", "")).strip()

