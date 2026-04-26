from __future__ import annotations

from typing import Any

from jakata_agent.tools.base import Tool, ToolResult


class MemoryTool(Tool):
    name = "memory"
    description = "Recall stored user identity, profile facts, preferences, knowledge files, semantic memory matches, graph facts, and archived chat context."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "User memory query."},
        },
        "required": [],
        "additionalProperties": False,
    }

    def run(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, summary="Memory handled by agent.", data=args)

    def render(self, data: dict[str, Any]) -> str:
        summary = str(data.get("summary", "")).strip()
        if summary:
            return summary
        facts = data.get("facts")
        if isinstance(facts, list) and facts:
            return "; ".join(str(item.get("content", "")).strip() for item in facts[:5] if isinstance(item, dict))
        return "No personal memory found."
