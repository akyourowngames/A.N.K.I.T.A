from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from tool.date_time import DateTimeTool
from tool.tavily_search import TavilySearchTool


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args: dict[str, str]


class ToolRegistry:
    def __init__(self) -> None:
        self.date_time = DateTimeTool()
        self.tavily_search = TavilySearchTool()

    def specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                name="date_time",
                description="Get the current date/time for a timezone.",
                args={"timezone": "Optional IANA timezone. Default: Asia/Kolkata."},
            ),
            ToolSpec(
                name="tavily_search",
                description="Search the live web for current or external information.",
                args={"query": "Search query.", "max_results": "Optional integer, default 5."},
            ),
        ]

    def planner_text(self) -> str:
        lines = []
        for spec in self.specs():
            lines.append(
                json.dumps(
                    {
                        "name": spec.name,
                        "description": spec.description,
                        "args": spec.args,
                    },
                    ensure_ascii=False,
                )
            )
        return "\n".join(lines)

    def run(self, name: str, args: dict[str, Any] | None = None) -> str:
        args = args or {}
        try:
            if name == "date_time":
                timezone = str(args.get("timezone") or "Asia/Kolkata")
                return self.date_time.run(timezone=timezone)
            if name == "tavily_search":
                query = str(args.get("query") or "").strip()
                max_results = int(args.get("max_results") or 5)
                return self.tavily_search.run(query=query, max_results=max_results)
        except Exception as error:
            return f"Tool error: {error}"

        return f"Unknown tool: {name}"
