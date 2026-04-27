from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Iterable


@dataclass(slots=True)
class RouterFormatError(ValueError):
    reason: str
    raw_output: str

    def __str__(self) -> str:
        return self.reason


def format_tool_array(tools: Iterable[str]) -> str:
    return json.dumps(list(tools), ensure_ascii=False, separators=(",", ":"))


def parse_tool_array(raw_output: str, allowed_tools: Iterable[str]) -> list[str]:
    allowed = set(allowed_tools)
    raw = raw_output.strip()
    if not raw:
        raise RouterFormatError("empty model output", raw_output)

    decoder = json.JSONDecoder()
    try:
        parsed, end = decoder.raw_decode(raw)
    except json.JSONDecodeError as exc:
        raise RouterFormatError(f"invalid JSON: {exc.msg}", raw_output) from exc

    if raw[end:].strip():
        raise RouterFormatError("extra text after JSON array", raw_output)
    if not isinstance(parsed, list):
        raise RouterFormatError("output is not a JSON array", raw_output)
    if not parsed:
        raise RouterFormatError("tool array is empty", raw_output)

    tools: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(parsed):
        if not isinstance(item, str):
            raise RouterFormatError(f"array item {index} is not a string", raw_output)
        if item not in allowed:
            raise RouterFormatError(f"unknown tool label: {item}", raw_output)
        if item in seen:
            raise RouterFormatError(f"duplicate tool label: {item}", raw_output)
        seen.add(item)
        tools.append(item)

    return tools
