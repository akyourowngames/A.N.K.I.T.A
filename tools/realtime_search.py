import os
from html.parser import HTMLParser
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlencode, urlparse
import xml.etree.ElementTree as ET

import requests


class _DuckResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._capture = False
        self._current_href = ""
        self._current_text_parts: List[str] = []
        self.results: List[Dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {k: (v or "") for k, v in attrs}
        cls = attr_map.get("class", "")
        href = attr_map.get("href", "")
        if "result__a" in cls and href:
            self._capture = True
            self._current_href = href
            self._current_text_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._current_text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._capture:
            return
        title = " ".join("".join(self._current_text_parts).split()).strip()
        link = _normalize_duck_link(self._current_href)
        if title and link:
            self.results.append({"title": title, "url": link})
        self._capture = False
        self._current_href = ""
        self._current_text_parts = []


def _normalize_duck_link(url: str) -> str:
    parsed = urlparse(url)
    if parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        unwrapped = qs.get("uddg", [])
        if unwrapped and unwrapped[0]:
            return unwrapped[0]
    if parsed.scheme and parsed.netloc:
        return url
    return ""


def _domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def _base_result(title: str, url: str, snippet: str = "") -> Dict[str, str]:
    row: Dict[str, str] = {"title": title, "domain": _domain(url), "snippet": snippet}
    return row


def search_web(query: str, max_results: int = 8, include_urls: bool = False) -> Dict[str, Any]:
    q = str(query or "").strip()
    if not q:
        raise ValueError("query is required")
    limit = max(1, min(int(max_results), 20))

    google_key = os.getenv("GOOGLE_SEARCH_API_KEY", "").strip()
    google_cx = os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip()
    if google_key and google_cx:
        try:
            resp = requests.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "q": q,
                    "key": google_key,
                    "cx": google_cx,
                    "num": min(limit, 10),
                    "safe": "off",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", []) if isinstance(data, dict) else []
            out: List[Dict[str, str]] = []
            for item in items[:limit]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", "")).strip()
                url = str(item.get("link", "")).strip()
                desc = str(item.get("snippet", "")).strip()
                if not title or not url:
                    continue
                row = _base_result(title=title, url=url, snippet=desc)
                if include_urls:
                    row["url"] = url
                out.append(row)
            if out:
                return {
                    "kind": "web_search",
                    "engine": "google-custom-search",
                    "query": q,
                    "include_urls": bool(include_urls),
                    "results": out,
                }
        except Exception:
            # Fallback below
            pass

    # Fallback: DuckDuckGo HTML results (no key)
    url = f"https://duckduckgo.com/html/?{urlencode({'q': q})}"
    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    parser = _DuckResultParser()
    parser.feed(resp.text)
    out = []
    for row in parser.results[:limit]:
        item = _base_result(title=row["title"], url=row["url"], snippet="")
        if include_urls:
            item["url"] = row["url"]
        out.append(item)
    return {
        "kind": "web_search",
        "engine": "duckduckgo-html",
        "query": q,
        "include_urls": bool(include_urls),
        "results": out,
    }


def search_news(query: str, max_results: int = 8, include_urls: bool = False) -> Dict[str, Any]:
    q = str(query or "").strip()
    if not q:
        raise ValueError("query is required")
    limit = max(1, min(int(max_results), 20))

    params = {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"}
    url = f"https://news.google.com/rss/search?{urlencode(params)}"
    resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    channel = root.find("channel")
    items = channel.findall("item") if channel is not None else []
    out: List[Dict[str, str]] = []
    for item in items[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub_date = (item.findtext("pubDate") or "").strip()
        source = ""
        src_node = item.find("source")
        if src_node is not None and src_node.text:
            source = src_node.text.strip()
        if title and link:
            row: Dict[str, str] = {
                "title": title,
                "domain": _domain(link),
                "published": pub_date,
                "source": source,
            }
            if include_urls:
                row["url"] = link
            out.append(row)
    return {
        "kind": "news_search",
        "engine": "google-news-rss",
        "query": q,
        "include_urls": bool(include_urls),
        "results": out,
    }
