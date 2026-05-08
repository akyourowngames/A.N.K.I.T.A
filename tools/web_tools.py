from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any

from .registry import ToolInputError, require_text


def fetch_url_text(params: dict[str, Any]) -> dict[str, Any]:
    url = require_text(params, "url")
    max_chars = bounded_int(params.get("max_chars"), 4000, 100, 50000)
    timeout = bounded_int(params.get("timeout_seconds"), 15, 1, 120)
    summary_read_chars = max(max_chars, 4000)
    request = urllib.request.Request(url, headers={"User-Agent": "Jarvis-NIM-Assistant"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(summary_read_chars + 1)
            text = body.decode("utf-8", errors="replace")
            readable = readable_text(text, response.headers.get("content-type", ""))
            return {
                "url": url,
                "status": getattr(response, "status", None),
                "content_type": response.headers.get("content-type", ""),
                "truncated": len(readable) > max_chars,
                "text": readable[:max_chars],
                "summary": summarize_readable_text(readable, url),
            }
    except urllib.error.HTTPError as error:
        raise ToolInputError(f"url fetch failed: {error.code} {error.reason}") from error
    except urllib.error.URLError as error:
        raise ToolInputError(f"url fetch failed: {error.reason}") from error
    except TimeoutError as error:
        raise ToolInputError("url fetch timed out") from error


def extract_url_content(params: dict[str, Any]) -> dict[str, Any]:
    result = fetch_url_text(params)
    return {
        "url": result["url"],
        "status": result["status"],
        "content_type": result["content_type"],
        "truncated": result["truncated"],
        "content": result["text"],
        "summary": result["summary"],
    }


def web_search(params: dict[str, Any]) -> dict[str, Any]:
    query = require_text(params, "query")
    count = bounded_int(params.get("count"), 5, 1, 10)
    timeout = bounded_int(params.get("timeout_seconds"), 15, 1, 120)
    url = search_url(query)
    request = urllib.request.Request(url, headers={"User-Agent": "Jarvis-NIM-Assistant"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            html = response.read(500000).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        raise ToolInputError(f"web search failed: {error.code} {error.reason}") from error
    except urllib.error.URLError as error:
        raise ToolInputError(f"web search failed: {error.reason}") from error
    except TimeoutError as error:
        raise ToolInputError("web search timed out") from error

    results = parse_duckduckgo_results(html, count)
    return {
        "query": query,
        "count": len(results),
        "results": results,
        "summary": search_summary(query, results),
    }


def document_extract_text(params: dict[str, Any]) -> dict[str, Any]:
    path = resolve_document_path(require_text(params, "path"))
    max_chars = bounded_int(params.get("max_chars"), 12000, 100, 200000)
    if not path.is_file():
        raise ToolInputError(f"path is not a file: {path}")

    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".csv", ".json", ".log", ".py", ".js", ".ts", ".html", ".css"}:
        content = path.read_text(encoding="utf-8-sig", errors="replace")
    elif suffix == ".pdf":
        content = extract_pdf_text(path)
    else:
        try:
            content = path.read_text(encoding="utf-8-sig", errors="replace")
        except UnicodeDecodeError as error:
            raise ToolInputError(f"document type is not readable as text: {path.suffix}") from error

    return {
        "path": str(path),
        "name": path.name,
        "chars": len(content),
        "truncated": len(content) > max_chars,
        "content": content[:max_chars],
        "summary": document_summary(path, content),
    }


def bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip():
        try:
            number = int(value.strip())
        except ValueError:
            number = fallback
    else:
        number = fallback
    return max(minimum, min(maximum, number))


class ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self.skip_depth > 0:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def readable_text(text: str, content_type: str) -> str:
    if "html" not in content_type.lower():
        return text
    parser = ReadableHtmlParser()
    parser.feed(text)
    parsed = "\n".join(parser.parts).strip()
    return parsed if parsed else text


def summarize_readable_text(text: str, url: str) -> str:
    lines = []
    seen = set()
    for raw_line in text.splitlines():
        line = " ".join(raw_line.split())
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
        if len(lines) >= 3:
            break
    if lines:
        return " ".join(lines)
    return f"Fetched {url} but no readable text was extracted."


class DuckDuckGoResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._capture_title = False
        self._current_href = ""
        self._current_title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attrs_map = {key: value or "" for key, value in attrs}
        class_value = attrs_map.get("class", "")
        href = attrs_map.get("href", "")
        if "result__a" in class_value and href:
            self._capture_title = True
            self._current_href = href
            self._current_title_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._capture_title:
            return
        title = " ".join(" ".join(self._current_title_parts).split())
        href = clean_search_href(self._current_href)
        if title and href:
            self.results.append({"title": title, "url": href})
        self._capture_title = False
        self._current_href = ""
        self._current_title_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            text = " ".join(data.split())
            if text:
                self._current_title_parts.append(text)


def search_url(query: str) -> str:
    base = os.environ.get("JARVIS_WEB_SEARCH_URL", "https://duckduckgo.com/html/")
    joiner = "&" if "?" in base else "?"
    return f"{base}{joiner}q={quote_plus(query)}"


def parse_duckduckgo_results(html: str, limit: int) -> list[dict[str, str]]:
    parser = DuckDuckGoResultParser()
    parser.feed(html)
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for result in parser.results:
        url = result.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(result)
        if len(unique) >= limit:
            break
    return unique


def clean_search_href(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.path == "/l/" or parsed.path.endswith("/l/"):
        values = parse_qs(parsed.query).get("uddg", [])
        if values:
            return unquote(values[0])
    if parsed.scheme:
        return href
    return urljoin("https://duckduckgo.com", href)


def search_summary(query: str, results: list[dict[str, str]]) -> str:
    if not results:
        return f"No web results found for {query}."
    lines = [f"Top web results for {query}:"]
    for result in results:
        lines.append(f"- {result.get('title')}: {result.get('url')}")
    return "\n".join(lines)


def resolve_document_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def extract_pdf_text(path: Path) -> str:
    try:
        import pypdf  # type: ignore[import-not-found]
    except ImportError as error:
        raise ToolInputError("PDF extraction needs the optional pypdf package.") from error

    parts: list[str] = []
    with path.open("rb") as handle:
        reader = pypdf.PdfReader(handle)
        for page in reader.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                parts.append(page_text.strip())
    return "\n\n".join(parts)


def document_summary(path: Path, content: str) -> str:
    first = ""
    for line in content.splitlines():
        stripped = " ".join(line.split())
        if stripped:
            first = stripped
            break
    if first:
        return f"{path.name}: {first[:240]}"
    return f"{path.name}: no readable text extracted."
