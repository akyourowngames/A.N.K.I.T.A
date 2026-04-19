from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from jakata_agent.tools.base import Tool, ToolResult


class TavilySearchTool(Tool):
    name = "search_web"
    description = "Search the web for current information using Tavily."
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query."},
            "topic": {"type": "string", "enum": ["general", "news", "finance"]},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def run(self, args: dict[str, Any]) -> ToolResult:
        if not self.api_key:
            return ToolResult(ok=False, summary="Tavily API key is missing.", data={}, error="missing_api_key")

        payload = {
            "query": str(args["query"]),
            "topic": str(args.get("topic", "general")),
            "search_depth": "fast",
            "max_results": int(args.get("max_results", 5)),
            "include_answer": True,
            "include_raw_content": False,
        }
        request = urllib.request.Request(
            "https://api.tavily.com/search",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            return ToolResult(ok=False, summary="Tavily search failed.", data={}, error=f"http_{exc.code}: {detail}")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary="Tavily search failed.", data={}, error=str(exc))

        results = data.get("results", [])
        compact_results = [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
            }
            for item in results
        ]
        summary = data.get("answer") or (compact_results[0]["content"] if compact_results else "No results found.")
        return ToolResult(
            ok=True,
            summary=summary,
            data={"answer": data.get("answer", ""), "results": compact_results},
        )

