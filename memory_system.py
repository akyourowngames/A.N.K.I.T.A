from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis_nim import JarvisConfig, NimChatError, post_json, scan_json_objects


@dataclass(frozen=True)
class MemoryConfig:
    root: Path
    max_context_chars: int
    max_file_chars: int
    include_transcripts: bool
    extract_enabled: bool
    extract_background: bool
    extract_max_tokens: int
    context_prompt_file: Path

    @classmethod
    def from_env(cls, workspace: Path) -> "MemoryConfig":
        return cls(
            root=Path(os.environ.get("JARVIS_MEMORY_DIR", str(workspace / "memory"))),
            max_context_chars=env_int("MEMORY_CONTEXT_CHARS", 3500),
            max_file_chars=env_int("MEMORY_FILE_CHARS", 1500),
            include_transcripts=env_bool("MEMORY_INCLUDE_TRANSCRIPTS", False),
            extract_enabled=env_bool("MEMORY_EXTRACT_FROM_CHAT", True),
            extract_background=env_bool("MEMORY_EXTRACT_BACKGROUND", True),
            extract_max_tokens=env_int("MEMORY_EXTRACT_MAX_TOKENS", 500),
            context_prompt_file=Path(os.environ.get("MEMORY_CONTEXT_PROMPT_FILE", "prompts/memory_context.txt")),
        )


def env_int(name: str, fallback: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def env_bool(name: str, fallback: bool) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if not value:
        return fallback
    return value in {"1", "true", "yes", "on"}


def ensure_memory_workspace(config: MemoryConfig) -> None:
    config.root.mkdir(parents=True, exist_ok=True)
    user_file = config.root / "user.txt"
    if not user_file.exists():
        user_file.write_text(
            "\n".join(
                [
                    "User Memory",
                    "",
                    "Write stable details Jarvis should remember here.",
                    "",
                    "- Name:",
                    "- Preferences:",
                    "- Projects:",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    extracted_file = config.root / "extracted.txt"
    if not extracted_file.exists():
        extracted_file.write_text("Extracted Chat Memory\n\n", encoding="utf-8")


def load_memory_context(config: MemoryConfig) -> str:
    ensure_memory_workspace(config)
    chunks: list[str] = []
    used_chars = 0

    for path in memory_files(config.root, include_transcripts=config.include_transcripts):
        content = path.read_text(encoding="utf-8-sig")
        if not content.strip():
            continue

        relative = path.relative_to(config.root).as_posix()
        clipped = content[-config.max_file_chars :]
        chunk = f"## {relative}\n\n{clipped.strip()}\n"
        if used_chars + len(chunk) > config.max_context_chars:
            remaining = config.max_context_chars - used_chars
            if remaining <= 0:
                break
            chunks.append(chunk[:remaining])
            break
        chunks.append(chunk)
        used_chars += len(chunk)

    if not chunks:
        return ""

    template = config.context_prompt_file.read_text(encoding="utf-8-sig")
    return template.replace("{memory_chunks}", "\n".join(chunks))


def memory_files(root: Path, include_transcripts: bool = False) -> list[Path]:
    if not root.exists():
        return []
    files = []
    transcript_root = root / "transcripts"
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in {".md", ".txt"}:
            continue
        if not include_transcripts and is_relative_to(path, transcript_root):
            continue
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def memory_system_message(memory_context: str) -> dict[str, str] | None:
    if not memory_context.strip():
        return None
    return {"role": "system", "content": memory_context}


def remember_chat(config: MemoryConfig, nim_config: JarvisConfig, user_text: str, assistant_text: str) -> None:
    ensure_memory_workspace(config)
    append_transcript(config, user_text, assistant_text)
    if assistant_text.startswith("Saved memory to "):
        return
    if user_text.strip().endswith("?"):
        return
    if not config.extract_enabled:
        return

    if config.extract_background:
        thread = threading.Thread(
            target=extract_and_append_memory,
            args=(config, nim_config, user_text, assistant_text),
            daemon=True,
        )
        thread.start()
        return

    extract_and_append_memory(config, nim_config, user_text, assistant_text)


def extract_and_append_memory(
    config: MemoryConfig,
    nim_config: JarvisConfig,
    user_text: str,
    assistant_text: str,
) -> None:
    try:
        items = extract_memory_items(nim_config, user_text, assistant_text, config.extract_max_tokens)
    except NimChatError:
        return

    if items:
        append_extracted_memory(config, items)


def append_transcript(config: MemoryConfig, user_text: str, assistant_text: str) -> None:
    date = datetime.now().astimezone().date().isoformat()
    transcript_dir = config.root / "transcripts"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = transcript_dir / f"{date}.txt"
    entry = "\n".join(
        [
            f"## {datetime.now().astimezone().isoformat(timespec='seconds')}",
            "",
            f"User: {user_text}",
            "",
            f"Jarvis: {assistant_text}",
            "",
        ]
    )
    with transcript_path.open("a", encoding="utf-8") as handle:
        handle.write(entry)


def extract_memory_items(
    config: JarvisConfig,
    user_text: str,
    assistant_text: str,
    max_tokens: int,
) -> list[str]:
    model = memory_extraction_model(config)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "Extract durable user/project memory from the exchange. Return JSON only with an items array of concise markdown bullets. Use an empty array when nothing durable should be remembered.",
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"user": user_text, "assistant": assistant_text},
                    ensure_ascii=True,
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": False,
    }
    data = post_json(config, payload)
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not isinstance(content, str):
        return []

    parsed = parse_memory_json(content)
    if parsed is None:
        return prose_memory_fallback(content)

    if isinstance(parsed, dict):
        items = parsed.get("items")
    elif isinstance(parsed, list):
        items = parsed
    else:
        items = None
    if not isinstance(items, list):
        return []

    clean_items = []
    for item in items:
        if isinstance(item, str) and item.strip():
            clean_items.append(item.strip())
    return clean_items


def memory_extraction_model(config: JarvisConfig) -> str:
    for name in ["NVIDIA_MEMORY_MODEL", "NVIDIA_TOOL_MODEL"]:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return config.model


def parse_memory_json(content: str) -> Any:
    text = content.strip()
    candidates = [text, strip_markdown_fences(text)]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    for value in scan_json_objects(content):
        if isinstance(value, dict) and isinstance(value.get("items"), list):
            return value

    for value in scan_json_arrays(content):
        return value

    return None


def strip_markdown_fences(text: str) -> str:
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def scan_json_arrays(text: str) -> list[Any]:
    values = []
    start = None
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "[":
            if depth == 0:
                start = index
            depth += 1
            continue
        if char == "]" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start : index + 1]
                try:
                    values.append(json.loads(candidate))
                except json.JSONDecodeError:
                    pass
                start = None

    return values


def prose_memory_fallback(content: str) -> list[str]:
    lines = []
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        while line.startswith("- "):
            line = line[2:].strip()
        if line:
            lines.append(line)
    return lines[:5]


def append_extracted_memory(config: MemoryConfig, items: list[str]) -> None:
    path = config.root / "extracted.txt"
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [f"[{timestamp}]", ""]
    for item in items:
        line = item if item.startswith("- ") else f"- {item}"
        lines.append(line)
    lines.append("")

    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
