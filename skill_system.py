from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from extension_system import ExtensionCatalog


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    path: Path
    content: str


def load_skill_context(catalog: ExtensionCatalog, workspace: Path | None = None) -> str:
    skills = load_skills(default_skill_roots(catalog, workspace))
    if not skills:
        return ""
    max_chars = env_int("JARVIS_SKILL_CONTEXT_CHARS", 8000)
    parts: list[str] = ["Loaded Jarvis skills:"]
    used = len(parts[0])
    for skill in skills:
        block = render_skill(skill)
        if used + len(block) > max_chars:
            remaining = max_chars - used
            if remaining > 200:
                parts.append(block[:remaining])
            break
        parts.append(block)
        used += len(block)
    return "\n\n".join(parts).strip()


def default_skill_roots(catalog: ExtensionCatalog, workspace: Path | None = None) -> list[Path]:
    root = workspace or Path.cwd()
    configured = os.environ.get("JARVIS_SKILLS_DIR", "").strip()
    root_skill_dir = Path(configured).expanduser() if configured else root / "skills"
    if not root_skill_dir.is_absolute():
        root_skill_dir = root / root_skill_dir
    roots = [root_skill_dir]
    roots.extend(catalog.skill_roots())
    return roots


def load_skills(roots: list[Path]) -> list[Skill]:
    skills: list[Skill] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("SKILL.txt"), key=lambda item: str(item).lower()):
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            skill = load_skill(path)
            if skill is not None:
                skills.append(skill)
    return skills


def load_skill(path: Path) -> Skill | None:
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return None
    metadata, body = split_frontmatter(text)
    name = metadata.get("name") or path.parent.name
    description = metadata.get("description") or first_heading_or_line(body)
    return Skill(name=name, description=description, path=path.resolve(), content=body.strip())


def split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    metadata: dict[str, str] = {}
    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
        key, value = split_metadata_line(lines[index])
        if key:
            metadata[key] = value
    if end_index is None:
        return {}, text
    body = "\n".join(lines[end_index + 1 :])
    return metadata, body


def split_metadata_line(line: str) -> tuple[str, str]:
    if ":" not in line:
        return "", ""
    key, value = line.split(":", 1)
    key = key.strip()
    value = value.strip()
    if not key:
        return "", ""
    return key, value


def first_heading_or_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
        return stripped
    return ""


def render_skill(skill: Skill) -> str:
    header = f"## Skill: {skill.name}"
    if skill.description:
        header += f"\nDescription: {skill.description}"
    return f"{header}\n{skill.content}"


def env_int(name: str, fallback: int) -> int:
    value = os.environ.get(name, "").strip()
    if not value:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback
