from __future__ import annotations

from typing import Any

from jakata_agent.tools.base import Tool, ToolResult


class MemoryTool(Tool):
    name = "memory"
    description = "Recall stored user facts and archived chat context."
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
