from __future__ import annotations

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
