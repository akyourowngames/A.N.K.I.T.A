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


def env_float(name: str, fallback: float) -> float:
    value = os.environ.get(name, "").strip()
    if not value:
        return fallback
    try:
        return float(value)
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


def load_memory_context(config: MemoryConfig, user_text: str = "", include_dynamic: bool = True) -> str:
    ensure_memory_workspace(config)
    if env_bool("MEMORY_BRAIN_ENABLED", True):
        try:
            from memory_brain import load_memory_brain_context

            brain_context = load_memory_brain_context(user_text, config, include_dynamic=include_dynamic)
            if brain_context.strip():
                template = config.context_prompt_file.read_text(encoding="utf-8-sig")
                return template.replace("{memory_chunks}", brain_context)
        except Exception:
            pass

    return load_txt_memory_context(config)


def load_txt_memory_context(config: MemoryConfig) -> str:
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
        if env_bool("MEMORY_BRAIN_WRITE_STRUCTURED", True):
            candidates = extract_memory_candidates(nim_config, user_text, assistant_text, config.extract_max_tokens)
            items = memory_items_from_candidates(candidates)
        else:
            items = extract_memory_items(nim_config, user_text, assistant_text, config.extract_max_tokens)
    except NimChatError:
        return

    if items:
        append_extracted_memory(config, items)
        schedule_memory_indexes(config, nim_config)


def extract_memory_candidates(
    config: JarvisConfig,
    user_text: str,
    assistant_text: str,
    max_tokens: int,
) -> list[dict[str, Any]]:
    model = memory_extraction_model(config)
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Extract durable user/project memory from the exchange. Return JSON only with a candidates array. "
                    "Each candidate needs text, type, entities, relations, importance, confidence, should_save, and reason. "
                    "Use an empty array when nothing durable should be remembered. Do not save secrets, passwords, tokens, "
                    "API keys, private keys, or random temporary chat."
                ),
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
        legacy_items = prose_memory_fallback(content)
        return [
            {
                "text": item,
                "type": "fact",
                "entities": [],
                "relations": [],
                "importance": 0.5,
                "confidence": 0.55,
                "should_save": True,
                "reason": "Parsed from prose fallback.",
            }
            for item in legacy_items
        ]
    if isinstance(parsed, dict):
        raw_candidates = parsed.get("candidates", [])
        if not isinstance(raw_candidates, list) and isinstance(parsed.get("items"), list):
            raw_candidates = [
                {
                    "text": str(item),
                    "type": "fact",
                    "entities": [],
                    "relations": [],
                    "importance": 0.5,
                    "confidence": 0.55,
                    "should_save": True,
                    "reason": "Legacy item array.",
                }
                for item in parsed["items"]
                if isinstance(item, str)
            ]
    elif isinstance(parsed, list):
        raw_candidates = parsed
    else:
        raw_candidates = []
    return clean_memory_candidates(raw_candidates)


def clean_memory_candidates(raw_candidates: list[Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for raw in raw_candidates:
        if isinstance(raw, str):
            raw = {"text": raw}
        if not isinstance(raw, dict):
            continue
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        candidate = {
            "text": text.strip(),
            "type": clean_memory_type(raw.get("type")),
            "entities": clean_text_list(raw.get("entities")),
            "relations": clean_relations(raw.get("relations")),
            "importance": bounded_float(raw.get("importance"), 0.5),
            "confidence": bounded_float(raw.get("confidence"), 0.6),
            "should_save": bool(raw.get("should_save", True)),
            "reason": str(raw.get("reason", "")).strip(),
        }
        if should_save_memory_candidate(candidate):
            candidates.append(candidate)
    return dedupe_candidates(candidates)


def should_save_memory_candidate(candidate: dict[str, Any]) -> bool:
    if not candidate.get("should_save", True):
        return False
    try:
        from memory_conflicts import is_secret_like

        if is_secret_like(str(candidate.get("text", ""))):
            return False
    except Exception:
        return False
    return float(candidate.get("importance", 0.0)) >= env_float("MEMORY_CANDIDATE_MIN_IMPORTANCE", 0.2)


def memory_items_from_candidates(candidates: list[dict[str, Any]]) -> list[str]:
    items: list[str] = []
    for candidate in candidates:
        text = str(candidate.get("text", "")).strip()
        if not text:
            continue
        memory_type = clean_memory_type(candidate.get("type"))
        entities = clean_text_list(candidate.get("entities"))
        relations = candidate.get("relations", [])
        parts = [f"[{memory_type}] {text}"]
        if entities:
            parts.append("Entities: " + ", ".join(entities[:8]))
        if isinstance(relations, list) and relations:
            rendered = []
            for relation in relations[:5]:
                if not isinstance(relation, dict):
                    continue
                source = str(relation.get("source", "")).strip()
                kind = str(relation.get("relation", "")).strip()
                target = str(relation.get("target", "")).strip()
                if source and kind and target:
                    rendered.append(f"{source} -> {kind} -> {target}")
            if rendered:
                parts.append("Relations: " + "; ".join(rendered))
        items.append(" | ".join(parts))
    return items


def clean_memory_type(value: Any) -> str:
    allowed = {
        "profile",
        "preference",
        "project",
        "task",
        "fact",
        "event",
        "decision",
        "constraint",
        "relationship",
        "skill",
    }
    if isinstance(value, str):
        clean = value.strip().casefold()
        if clean in allowed:
            return clean
    return "fact"


def clean_text_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            clean = item.strip()
            if clean not in result:
                result.append(clean)
    return result


def clean_relations(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    relations: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source = item.get("source")
        relation = item.get("relation")
        target = item.get("target")
        if not all(isinstance(part, str) and part.strip() for part in [source, relation, target]):
            continue
        relations.append({"source": source.strip(), "relation": relation.strip(), "target": target.strip()})
    return relations


def dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for candidate in candidates:
        key = " ".join(str(candidate.get("text", "")).casefold().split())
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return result


def bounded_float(value: Any, fallback: float) -> float:
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            number = float(value.strip())
        except ValueError:
            number = fallback
    else:
        number = fallback
    return max(0.0, min(1.0, number))


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


def schedule_vector_reindex(config: MemoryConfig, nim_config: JarvisConfig) -> None:
    if not env_bool("MEMORY_VECTOR_BACKGROUND_REINDEX", True):
        return
    thread = threading.Thread(target=reindex_vector_memory_safely, args=(config, nim_config), daemon=True)
    thread.start()


def schedule_memory_indexes(config: MemoryConfig, nim_config: JarvisConfig) -> None:
    schedule_vector_reindex(config, nim_config)
    schedule_brain_reindex(config)


def schedule_brain_reindex(config: MemoryConfig) -> None:
    if not env_bool("MEMORY_BRAIN_ENABLED", True):
        return
    if not env_bool("MEMORY_BRAIN_AUTO_REINDEX", True):
        return
    thread = threading.Thread(target=reindex_brain_memory_safely, args=(config,), daemon=True)
    thread.start()


def reindex_brain_memory_safely(config: MemoryConfig) -> None:
    try:
        from memory_brain import memory_brain_reindex

        memory_brain_reindex(Path.cwd(), config)
    except Exception:
        return


def reindex_vector_memory_safely(config: MemoryConfig, nim_config: JarvisConfig) -> None:
    try:
        from vector_memory import VectorMemoryConfig, build_vector_index

        vector_config = VectorMemoryConfig.from_env(Path.cwd())
        build_vector_index(config, vector_config, nim_config)
    except Exception:
        return
