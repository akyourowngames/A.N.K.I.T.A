from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from jakata_agent.tools.base import Tool, ToolResult


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture_title = False
        self._capture_snippet = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        classes = set(attrs_dict.get("class", "").split())
        if tag == "a" and "result__a" in classes:
            href = attrs_dict.get("href", "")
            parsed = urllib.parse.urlparse(href)
            query = urllib.parse.parse_qs(parsed.query)
            href = query.get("uddg", [href])[0]
            self._current = {"title": "", "url": urllib.parse.unquote(href), "content": ""}
            self._capture_title = True
        elif self._current is not None and tag in {"a", "div"} and "result__snippet" in classes:
            self._capture_snippet = True

    def handle_data(self, data: str) -> None:
        if self._current is None:
            return
        text = " ".join(unescape(data).split())
        if not text:
            return
        if self._capture_title:
            self._current["title"] = (self._current["title"] + " " + text).strip()
        elif self._capture_snippet:
            self._current["content"] = (self._current["content"] + " " + text).strip()

    def handle_endtag(self, tag: str) -> None:
        if self._current is None:
            return
        if tag == "a" and self._capture_title:
            self._capture_title = False
            if self._current.get("title") and self._current.get("url"):
                self.results.append(self._current)
        elif tag in {"a", "div"} and self._capture_snippet:
            self._capture_snippet = False
            self._current = None


class TavilySearchTool(Tool):
    name = "search_web"
    description = "Search the web for current information. Uses Tavily when configured, with a keyless DuckDuckGo HTML fallback."
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
            return self._run_duckduckgo(args)

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

    def _run_duckduckgo(self, args: dict[str, Any]) -> ToolResult:
        query = str(args["query"]).strip()
        max_results = max(1, min(int(args.get("max_results", 5)), 10))
        url = "https://duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 JAKATA local assistant"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                html = response.read().decode("utf-8", errors="replace")
        except Exception as exc:  # noqa: BLE001
            return ToolResult(ok=False, summary="Web search failed.", data={}, error=str(exc))

        parser = _DuckDuckGoHTMLParser()
        parser.feed(html)
        results = parser.results[:max_results]
        summary = results[0]["content"] or results[0]["title"] if results else "No results found."
        return ToolResult(
            ok=bool(results),
            summary=summary,
            data={"answer": "", "results": results, "backend": "duckduckgo_html"},
            error=None if results else "no_results",
        )

