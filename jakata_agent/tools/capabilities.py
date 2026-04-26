from __future__ import annotations

from jakata_agent.tools.base import Tool, ToolResult
from jakata_agent.tools.registry import ToolRegistry


class CapabilitiesTool(Tool):
    name = "capabilities"
    semantic_direct = True
    semantic_direct_min_score = 0.21
    description = (
        "List JAKATA connected tools, tool names, tool catalog, integrations, and available tool inventory."
    )
    input_schema = {"type": "object", "properties": {}, "required": []}
    safety = "read_only"

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def run(self, args: dict) -> ToolResult:
        del args
        public_tools = [tool for tool in self.registry.manifest(public_only=True) if tool.get("name") != self.name]
        tool_lines = [f"- {tool['name']}: {tool['description']}" for tool in public_tools]
        summary = "I can chat normally and use these connected tools when needed:\n" + "\n".join(tool_lines)
        return ToolResult(ok=True, summary=summary, data={"summary": summary, "tools": public_tools})

    def render(self, data: dict) -> str:
        return str(data.get("summary", "")).strip()


def register_capabilities_tool(registry: ToolRegistry) -> None:
    registry.register(CapabilitiesTool(registry))
