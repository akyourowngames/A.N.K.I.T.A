from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    content: str
    score: float | None = None
    published_date: str = ""


@dataclass(frozen=True)
class TavilySearchTool:
    api_key: str | None = None
    endpoint: str = "https://api.tavily.com/search"
    name: str = "tavily_search"
    description: str = "Searches the live web using Tavily with source filters and current-info formatting."

    def run(
        self,
        query: str,
        max_results: Any = 5,
        search_depth: str = "advanced",
        topic: str = "general",
        include_domains: str | list[str] | None = None,
        exclude_domains: str | list[str] | None = None,
        include_answer: Any = True,
        include_raw_content: Any = False,
        days: Any = None,
    ) -> str:
        query = query.strip()
        if not query:
            return "FAILED: No search query provided."

        max_results_int = self._clamp_int(max_results, default=5, minimum=1, maximum=10)
        if not self._api_key() and self._free_fallback_enabled():
            body = self._free_search(query=query, max_results=max_results_int)
            return self._format_results(body, query=query)

        body = self._request(
            query=query,
            max_results=max_results_int,
            search_depth=self._search_depth(search_depth),
            topic=self._topic(topic),
            include_domains=self._list_value(include_domains),
            exclude_domains=self._list_value(exclude_domains),
            include_answer=self._bool(include_answer),
            include_raw_content=self._bool(include_raw_content),
            days=self._optional_int(days),
        )
        return self._format_results(body, query=query)

    def _request(
        self,
        query: str,
        max_results: int,
        search_depth: str,
        topic: str,
        include_domains: list[str],
        exclude_domains: list[str],
        include_answer: bool,
        include_raw_content: bool,
        days: int | None,
    ) -> dict[str, Any]:
        key = self._api_key()
        if not key:
            raise ValueError("Missing TAVILY_API_KEY. Add it to .env or enable TAVILY_FREE_FALLBACK=true.")

        payload: dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "topic": topic,
            "include_answer": include_answer,
            "include_raw_content": include_raw_content,
        }
        if include_domains:
            payload["include_domains"] = include_domains
        if exclude_domains:
            payload["exclude_domains"] = exclude_domains
        if days is not None:
            payload["days"] = days

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
            with urllib.request.urlopen(request, timeout=int(os.getenv("TAVILY_TIMEOUT_SECONDS", "45"))) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Tavily search failed: {error.code} {details}") from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"Could not reach Tavily: {error.reason}") from error

    def _free_search(self, query: str, max_results: int) -> dict[str, Any]:
        endpoint = os.getenv("FREE_WEB_SEARCH_ENDPOINT", "https://html.duckduckgo.com/html/").strip()
        params = urllib.parse.urlencode({"q": query})
        separator = "&" if "?" in endpoint else "?"
        request = urllib.request.Request(
            endpoint + separator + params,
            headers={
                "User-Agent": os.getenv(
                    "FREE_WEB_SEARCH_USER_AGENT",
                    "Mozilla/5.0 compatible personal assistant search",
                )
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=int(os.getenv("FREE_WEB_SEARCH_TIMEOUT_SECONDS", "20"))) as response:
                html = response.read().decode("utf-8", errors="replace")
        except urllib.error.URLError as error:
            raise RuntimeError(f"Could not reach free web search: {error.reason}") from error

        parser = FreeSearchHTMLParser(max_results=max_results)
        parser.feed(html)
        return {
            "answer": "",
            "results": [
                {
                    "title": result.title,
                    "url": result.url,
                    "content": result.content,
                    "score": None,
                    "published_date": "",
                }
                for result in parser.results
            ],
        }

    @staticmethod
    def _format_results(body: dict[str, Any], query: str = "") -> str:
        lines: list[str] = []
        if query:
            lines.append(f"Search query: {query}")

        answer = TavilySearchTool._clean_text(str(body.get("answer") or ""))
        if answer:
            lines.append(f"Answer: {answer}")

        results = body.get("results") or []
        source_count = 0
        for item in results:
            if not isinstance(item, dict):
                continue
            source_count += 1
            result = SearchResult(
                title=TavilySearchTool._clean_text(str(item.get("title") or "Untitled")),
                url=TavilySearchTool._clean_text(str(item.get("url") or "")),
                content=TavilySearchTool._clean_text(str(item.get("content") or "")),
                score=TavilySearchTool._score(item.get("score")),
                published_date=TavilySearchTool._clean_text(str(item.get("published_date") or "")),
            )
            metadata = []
            if result.published_date:
                metadata.append(f"published {result.published_date}")
            if result.score is not None:
                metadata.append(f"score {result.score:.3f}")
            metadata_text = f"\nMetadata: {', '.join(metadata)}" if metadata else ""
            lines.append(
                f"{source_count}. {result.title}\n"
                f"URL: {result.url}{metadata_text}\n"
                f"Summary: {result.content or '<empty>'}"
            )

        if source_count:
            lines.append(f"Sources returned: {source_count}")
            return "\n\n".join(lines)
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

    @staticmethod
    def _list_value(value: str | list[str] | None) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        parts: list[str] = []
        current: list[str] = []
        for char in str(value):
            if char in {",", ";", "\n", "\t", " "}:
                if current:
                    parts.append("".join(current).strip())
                    current = []
                continue
            current.append(char)
        if current:
            parts.append("".join(current).strip())
        return [part for part in parts if part]

    @staticmethod
    def _search_depth(value: str) -> str:
        normalized = str(value or "advanced").strip().casefold()
        return "basic" if normalized == "basic" else "advanced"

    @staticmethod
    def _topic(value: str) -> str:
        normalized = str(value or "general").strip().casefold()
        return "news" if normalized == "news" else "general"

    @staticmethod
    def _bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return max(1, min(30, parsed))

    @staticmethod
    def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _score(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _api_key(self) -> str:
        return self.api_key or os.getenv("TAVILY_API_KEY", "").strip()

    @staticmethod
    def _free_fallback_enabled() -> bool:
        value = os.getenv("TAVILY_FREE_FALLBACK", "true").strip().lower()
        return value in {"1", "true", "yes", "on"}


class FreeSearchHTMLParser(HTMLParser):
    def __init__(self, max_results: int):
        super().__init__(convert_charrefs=True)
        self.max_results = max_results
        self.results: list[SearchResult] = []
        self._current_link: dict[str, str] | None = None
        self._current_snippet_index: int | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {name: value or "" for name, value in attrs}
        class_text = attrs_map.get("class", "")
        if tag == "a" and "result__a" in class_text and len(self.results) < self.max_results:
            self._current_link = {"title": "", "url": self._result_url(attrs_map.get("href", ""))}
            return
        if "result__snippet" in class_text and self.results:
            self._current_snippet_index = len(self.results) - 1

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._current_link is not None:
            current_title = self._current_link.get("title", "")
            self._current_link["title"] = (current_title + " " + text).strip()
            return
        if self._current_snippet_index is not None:
            result = self.results[self._current_snippet_index]
            content = (result.content + " " + text).strip()
            self.results[self._current_snippet_index] = SearchResult(
                title=result.title,
                url=result.url,
                content=content,
                score=result.score,
                published_date=result.published_date,
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_link is not None:
            title = self._current_link.get("title", "").strip()
            url = self._current_link.get("url", "").strip()
            if title and url and len(self.results) < self.max_results:
                self.results.append(SearchResult(title=title, url=url, content=""))
            self._current_link = None
        elif self._current_snippet_index is not None:
            self._current_snippet_index = None

    @staticmethod
    def _result_url(href: str) -> str:
        value = href.strip()
        if value.startswith("//"):
            value = "https:" + value
        parsed = urllib.parse.urlparse(value)
        query = urllib.parse.parse_qs(parsed.query)
        uddg = query.get("uddg", [])
        if uddg:
            return str(uddg[0])
        return value
