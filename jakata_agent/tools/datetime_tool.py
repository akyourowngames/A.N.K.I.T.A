from __future__ import annotations

from datetime import datetime, timezone

from jakata_agent.tools.base import Tool, ToolResult


class DateTimeTool(Tool):
    name = "datetime"
    description = "Get the current local and UTC date/time."
    input_schema = {
        "type": "object",
        "properties": {
            "include_utc": {"type": "boolean", "description": "Whether to include UTC time."}
        },
        "required": [],
        "additionalProperties": False,
    }

    def run(self, args: dict[str, object]) -> ToolResult:
        now_local = datetime.now().astimezone()
        now_utc = datetime.now(timezone.utc)
        include_utc = bool(args.get("include_utc", True))
        data = {
            "local_iso": now_local.isoformat(),
            "local_human": now_local.strftime("%Y-%m-%d %H:%M:%S %Z"),
        }
        if include_utc:
            data["utc_iso"] = now_utc.isoformat()
            data["utc_human"] = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
        return ToolResult(ok=True, summary=f"Local time is {data['local_human']}.", data=data)

