from __future__ import annotations

from typing import Any

from .registry import active_or_discovered_registry


def list_registered_tools(params: dict[str, Any]) -> dict[str, Any]:
    registry = active_or_discovered_registry()
    return {
        "tools": [
            {"name": tool.name, "description": tool.description}
            for tool in registry.visible_tools()
            if tool.name != "list_registered_tools"
        ]
    }
