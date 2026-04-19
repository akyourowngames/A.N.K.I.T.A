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

    def describe(self) -> str:
        if not self._tools:
            return "No tools connected yet."
        return "\n".join(f"- {tool.name}: {tool.description}" for tool in self._tools.values())

    def planner_prompt(self) -> str:
        specs = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]
        return json.dumps(specs, indent=2)
