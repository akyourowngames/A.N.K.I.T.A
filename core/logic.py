from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    core: Path
    skills: Path
    tool: Path
    memory: Path
    memory_chats: Path
    memory_data: Path
    memory_store: Path
    chat: Path

    @classmethod
    def from_root(cls, root: Path) -> "ProjectPaths":
        return cls(
            root=root,
            core=root / "core",
            skills=root / "skills",
            tool=root / "tool",
            memory=root / "memory",
            memory_chats=root / "memory" / "chats",
            memory_data=root / "memory" / "data",
            memory_store=root / "memory" / "store",
            chat=root / "chat",
        )


def read_markdown_skills(skills_dir: Path) -> str:
    files = [
        file_path
        for file_path in sorted(skills_dir.glob("*.md"))
        if not file_path.name.startswith("_")
        and file_path.stem.lower() != "permanent-memory"
    ]
    if not files:
        return "No skill files found yet."

    chunks: list[str] = []
    for file_path in files:
        text = sanitize_skill_text(file_path.read_text(encoding="utf-8")).strip()
        if text:
            chunks.append(f"## {file_path.name}\n{text}")

    return "\n\n".join(chunks) if chunks else "Skill files exist, but they are empty."


def sanitize_skill_text(text: str) -> str:
    internal_markers = ("tool code:", "core code:", "api key", ".env", "sqlite", "database")
    lines = []
    for line in text.splitlines():
        lowered = line.strip().lower()
        if any(marker in lowered for marker in internal_markers):
            continue
        lines.append(line)
    return "\n".join(lines)


def read_memory(memory_dir: Path) -> str:
    data_dir = memory_dir / "data"
    files = (
        sorted([*data_dir.glob("*.txt"), *data_dir.glob("*.md")])
        if data_dir.exists()
        else sorted(memory_dir.glob("*.txt"))
    )
    if not files:
        return "No memory files found yet."

    chunks: list[str] = []
    for file_path in files:
        text = file_path.read_text(encoding="utf-8").strip()
        if text:
            chunks.append(f"## {file_path.name}\n{text}")

    return "\n\n".join(chunks) if chunks else "Memory files exist, but they are empty."


def session_file(chat_dir: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return chat_dir / f"session-{stamp}.jsonl"


def append_chat_turn(path: Path, speaker: str, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "speaker": speaker,
        "text": text.strip(),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_chat_turns(path: Path, limit: int = 12) -> list[dict[str, str]]:
    if not path.exists():
        return []

    records: list[dict[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        speaker = str(record.get("speaker") or "").strip()
        text = str(record.get("text") or "").strip()
        if speaker and text:
            records.append({"speaker": speaker, "text": text})
    return records[-limit:]


def chat_turns_as_messages(
    turns: list[dict[str, str]],
    user_name: str,
    ai_name: str,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for turn in turns:
        speaker = turn["speaker"]
        role = "assistant" if speaker == ai_name else "user"
        messages.append({"role": role, "content": turn["text"]})
    return messages


def summarize_chat_turns(turns: list[dict[str, str]], limit: int = 8) -> str:
    if not turns:
        return "No session messages yet."

    lines = []
    for turn in turns[-limit:]:
        text = turn["text"]
        if len(text) > 300:
            text = f"{text[:297]}..."
        lines.append(f"{turn['speaker']}: {text}")
    return "\n".join(lines)
