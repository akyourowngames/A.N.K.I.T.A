from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from memory_system import MemoryConfig, ensure_memory_workspace, memory_files

from .registry import ToolInputError, optional_text, require_text


def wiki_status(params: dict[str, Any]) -> dict[str, Any]:
    root = wiki_root()
    pages = wiki_pages(root)
    return {
        "wiki_root": str(root),
        "page_count": len(pages),
        "pages": [page.relative_to(root).as_posix() for page in pages],
        "summary": f"Memory wiki has {len(pages)} pages at {root}.",
    }


def wiki_search(params: dict[str, Any]) -> dict[str, Any]:
    query = require_text(params, "query")
    limit = bounded_int(params.get("limit"), 10, 1, 50)
    root = wiki_root()
    candidates = wiki_pages(root)
    config = MemoryConfig.from_env(Path.cwd())
    ensure_memory_workspace(config)
    candidates.extend(memory_files(config.root, include_transcripts=False))
    matches: list[dict[str, Any]] = []
    for path in sorted(set(candidates), key=lambda item: str(item).lower()):
        try:
            text = path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            continue
        line_hits = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if query.lower() in line.lower():
                line_hits.append({"line": line_number, "text": line.strip()})
                if len(line_hits) >= 3:
                    break
        if line_hits:
            matches.append({"path": str(path), "matches": line_hits})
            if len(matches) >= limit:
                break
    return {
        "query": query,
        "count": len(matches),
        "matches": matches,
        "summary": wiki_search_summary(query, matches),
    }


def wiki_get(params: dict[str, Any]) -> dict[str, Any]:
    path_text = optional_text(params, "path", "")
    topic = optional_text(params, "topic", "")
    if path_text:
        path = resolve_wiki_path(path_text)
    elif topic:
        path = topic_path(topic)
    else:
        raise ToolInputError("path or topic is required")
    if not path.is_file():
        raise ToolInputError(f"wiki page does not exist: {path}")
    max_chars = bounded_int(params.get("max_chars"), 12000, 100, 200000)
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    return {
        "path": str(path),
        "topic": path.stem,
        "chars": len(content),
        "truncated": len(content) > max_chars,
        "content": content[:max_chars],
    }


def wiki_apply(params: dict[str, Any]) -> dict[str, Any]:
    topic = require_text(params, "topic")
    content = require_text(params, "content")
    source = optional_text(params, "source", "Jarvis chat")
    mode = optional_text(params, "mode", "append").lower()
    path = topic_path(topic)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = wiki_entry(topic, content, source)
    if mode == "replace" or not path.exists():
        path.write_text(entry, encoding="utf-8")
    else:
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n\n")
            handle.write(entry)
    return {
        "saved": True,
        "path": str(path),
        "topic": topic,
        "summary": f"Saved wiki note for {topic} at {path}.",
    }


def wiki_lint(params: dict[str, Any]) -> dict[str, Any]:
    root = wiki_root()
    pages = wiki_pages(root)
    findings: list[dict[str, str]] = []
    for page in pages:
        text = page.read_text(encoding="utf-8-sig", errors="replace")
        if "Source:" not in text:
            findings.append({"path": str(page), "finding": "Missing Source line."})
        if "Confidence:" not in text:
            findings.append({"path": str(page), "finding": "Missing Confidence line."})
    return {
        "page_count": len(pages),
        "finding_count": len(findings),
        "findings": findings,
        "summary": f"Wiki lint checked {len(pages)} pages and found {len(findings)} issues.",
    }


def wiki_root() -> Path:
    config = MemoryConfig.from_env(Path.cwd())
    ensure_memory_workspace(config)
    root = config.root / "wiki"
    root.mkdir(parents=True, exist_ok=True)
    (root / "pages").mkdir(parents=True, exist_ok=True)
    return root.resolve()


def wiki_pages(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return [path for path in root.rglob("*.txt") if path.is_file()]


def topic_path(topic: str) -> Path:
    return wiki_root() / "pages" / f"{safe_slug(topic)}.txt"


def safe_slug(value: str) -> str:
    chars: list[str] = []
    previous_dash = False
    for char in value.strip().lower():
        if char.isalnum():
            chars.append(char)
            previous_dash = False
        elif char in {" ", "-", "_", "."} and not previous_dash:
            chars.append("-")
            previous_dash = True
    slug = "".join(chars).strip("-")
    return slug if slug else "note"


def wiki_entry(topic: str, content: str, source: str) -> str:
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    return "\n".join(
        [
            f"Title: {topic}",
            f"Updated: {now}",
            f"Source: {source}",
            "Confidence: user-provided-or-tool-grounded",
            "",
            content.strip(),
        ]
    )


def resolve_wiki_path(value: str) -> Path:
    root = wiki_root()
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if not is_relative_to(resolved, root):
        raise ToolInputError("wiki path must stay inside the memory wiki")
    return resolved


def wiki_search_summary(query: str, matches: list[dict[str, Any]]) -> str:
    if not matches:
        return f"No memory wiki matches found for {query}."
    lines = [f"Memory wiki matches for {query}:"]
    for match in matches:
        first = match.get("matches", [{}])[0]
        lines.append(f"- {match.get('path')}: {first.get('text')}")
    return "\n".join(lines)


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


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
