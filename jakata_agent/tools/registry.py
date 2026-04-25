from __future__ import annotations

import json
from dataclasses import dataclass

from jakata_agent.tools.base import Tool, ToolResult


@dataclass(slots=True)
class ToolCall:
    tool: str
    args: dict


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def execute(self, name: str, args: dict) -> ToolResult:
        tool = self.get(name)
        if not tool:
            return ToolResult(ok=False, summary=f"Unknown tool: {name}", data={}, error="unknown_tool")
        return tool.run(args)

    def describe(self, public_only: bool = True) -> str:
        tools = list(self._iter_tools(public_only=public_only))
        if not tools:
            return "No tools connected yet."
        return "\n".join(f"- {tool.name}: {tool.description}" for tool in tools)

    def manifest(self, public_only: bool = True) -> list[dict]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "args": tool.input_schema.get("properties", {}),
                "required": tool.input_schema.get("required", []),
                "safety": getattr(tool, "safety", "read_only"),
            }
            for tool in self._iter_tools(public_only=public_only)
        ]

    def planner_prompt(self) -> str:
        specs = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._iter_tools(public_only=True)
        ]
        return json.dumps(specs, indent=2)

    def _iter_tools(self, public_only: bool) -> list[Tool]:
        if not public_only:
            return list(self._tools.values())
        return [tool for tool in self._tools.values() if getattr(tool, "public", True)]
