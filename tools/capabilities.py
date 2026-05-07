from __future__ import annotations

from typing import Any

from .registry import discover_tools


def list_registered_tools(params: dict[str, Any]) -> dict[str, Any]:
    registry = discover_tools()
    return {
        "tools": [
            {"name": tool.name, "description": tool.description}
            for tool in registry.visible_tools()
            if tool.name != "list_registered_tools"
        ]
    }
