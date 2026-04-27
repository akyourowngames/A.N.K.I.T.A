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
    categories = ("tooling", "self_awareness")
    aliases = ("tools", "what can you do", "capability map")
    daily_uses = ("Discover available tools.", "Choose the right tool chain for a grounded task.")
    grounding = "Reports the live registered tool manifest."
    output_capabilities = ("tool_catalog", "tool_chains")
    input_schema = {"type": "object", "properties": {}, "required": []}
    safety = "read_only"

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def run(self, args: dict) -> ToolResult:
        del args
        public_tools = [tool for tool in self.registry.manifest(public_only=True) if tool.get("name") != self.name]
        tool_lines = []
        chains: list[str] = []
        for tool in public_tools:
            name = str(tool.get("name", ""))
            tool_lines.append(f"- {name}: {tool.get('description', '')}")
            use_with = [item for item in tool.get("use_with", []) if item]
            if use_with:
                chains.append(f"- {name} + {', '.join(use_with[:4])}")
        summary = "I can chat normally and use these connected tools when needed:\n" + "\n".join(tool_lines)
        if chains:
            summary += "\n\nGood tool chains:\n" + "\n".join(chains[:10])
        return ToolResult(ok=True, summary=summary, data={"summary": summary, "tools": public_tools, "chains": chains})

    def render(self, data: dict) -> str:
        return str(data.get("summary", "")).strip()


def register_capabilities_tool(registry: ToolRegistry) -> None:
    registry.register(CapabilitiesTool(registry))
