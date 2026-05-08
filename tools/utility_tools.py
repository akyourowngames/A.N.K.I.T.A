from __future__ import annotations

import base64
import json
from difflib import unified_diff
from typing import Any
from urllib.parse import quote, unquote

from .registry import ToolInputError, optional_text, require_text


def transform_text(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation").lower()
    text = require_text(params, "text")
    if operation == "json_format":
        result = json.dumps(json.loads(text), ensure_ascii=False, indent=bounded_int(params.get("indent"), 2, 0, 8))
    elif operation == "json_minify":
        result = json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))
    elif operation == "base64_encode":
        result = base64.b64encode(text.encode("utf-8")).decode("ascii")
    elif operation == "base64_decode":
        result = base64.b64decode(text.encode("ascii"), validate=True).decode("utf-8")
    elif operation == "url_encode":
        result = quote(text, safe="")
    elif operation == "url_decode":
        result = unquote(text)
    elif operation == "slug":
        result = slug_text(text)
    else:
        raise ToolInputError(f"unsupported transform operation: {operation}")
    return {
        "operation": operation,
        "result": result,
        "summary": result,
    }


def compare_text(params: dict[str, Any]) -> dict[str, Any]:
    left = require_text(params, "left")
    right = require_text(params, "right")
    from_label = optional_text(params, "from_label", "left")
    to_label = optional_text(params, "to_label", "right")
    max_chars = bounded_int(params.get("max_chars"), 12000, 100, 100000)
    diff = "\n".join(
        unified_diff(
            left.splitlines(),
            right.splitlines(),
            fromfile=from_label,
            tofile=to_label,
            lineterm="",
        )
    )
    summary = diff[:max_chars] if diff else "No text differences found."
    return {
        "from_label": from_label,
        "to_label": to_label,
        "changed": bool(diff),
        "truncated": len(diff) > max_chars,
        "diff": summary,
        "summary": summary,
    }


def slug_text(text: str) -> str:
    parts: list[str] = []
    previous_separator = False
    for char in text.lower():
        if char.isalnum():
            parts.append(char)
            previous_separator = False
            continue
        if not previous_separator:
            parts.append("-")
            previous_separator = True
    return "".join(parts).strip("-")


def bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip():
        try:
            number = int(value.strip())
        except ValueError:
            number = fallback
    else:
        number = fallback
    return max(minimum, min(maximum, number))
