from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    content: str


@dataclass(frozen=True)
class TavilySearchTool:
    api_key: str | None = None
    endpoint: str = "https://api.tavily.com/search"
    name: str = "tavily_search"
    description: str = "Searches the live web using Tavily."

    def run(self, query: str, max_results: int = 5) -> str:
        if not query.strip():
            return "No search query provided."

        body = self._request(query=query, max_results=max_results)
        return self._format_results(body)

    def _request(self, query: str, max_results: int) -> dict[str, Any]:
        key = self.api_key or os.getenv("TAVILY_API_KEY", "").strip()
        if not key:
            raise ValueError("Missing TAVILY_API_KEY. Add it to .env before using web search.")

        payload = {
            "query": query,
            "max_results": max_results,
            "include_answer": True,
            "include_raw_content": False,
        }
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Tavily search failed: {error.code} {details}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Could not reach Tavily: {error.reason}") from error

    @staticmethod
    def _format_results(body: dict[str, Any]) -> str:
        lines: list[str] = []
        answer = TavilySearchTool._clean_text(str(body.get("answer") or ""))
        if answer:
            lines.append(f"Answer: {answer}")

        results = body.get("results") or []
        for index, item in enumerate(results, start=1):
            if not isinstance(item, dict):
                continue
            result = SearchResult(
                title=TavilySearchTool._clean_text(str(item.get("title") or "Untitled")),
                url=TavilySearchTool._clean_text(str(item.get("url") or "")),
                content=TavilySearchTool._clean_text(str(item.get("content") or "")),
            )
            lines.append(f"{index}. {result.title}\nURL: {result.url}\nSummary: {result.content}")

        return "\n\n".join(lines) if lines else "No Tavily results found."

    @staticmethod
    def _clean_text(text: str) -> str:
        return (
            text.replace("\u200b", "")
            .replace("\u200c", "")
            .replace("\u200d", "")
            .replace("\ufeff", "")
            .strip()
        )
