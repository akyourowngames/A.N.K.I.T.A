from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ExtensionError(Exception):
    pass


@dataclass(frozen=True)
class Extension:
    root: Path
    manifest_path: Path
    id: str
    name: str
    description: str
    tools: list[dict[str, Any]]
    prompt_files: list[Path]
    skill_dirs: list[Path]
    env: list[str]
    display_templates: dict[str, str]


@dataclass(frozen=True)
class ExtensionCatalog:
    root: Path
    extensions: list[Extension]

    def tool_descriptors(self) -> list[dict[str, Any]]:
        descriptors: list[dict[str, Any]] = []
        for extension in self.extensions:
            descriptors.extend(extension.tools)
        return descriptors

    def prompt_context(self) -> str:
        parts: list[str] = []
        for extension in self.extensions:
            for path in extension.prompt_files:
                if not path.exists():
                    continue
                text = path.read_text(encoding="utf-8-sig").strip()
                if text:
                    parts.append(f"## {extension.name}\n{text}")
        return "\n\n".join(parts).strip()

    def skill_roots(self) -> list[Path]:
        roots: list[Path] = []
        for extension in self.extensions:
            roots.extend(extension.skill_dirs)
        return roots

    def display_templates(self) -> dict[str, str]:
        templates: dict[str, str] = {}
        for extension in self.extensions:
            templates.update(extension.display_templates)
        return templates

    def status_lines(self) -> list[str]:
        lines: list[str] = []
        for extension in self.extensions:
            tool_count = len(extension.tools)
            skill_count = len(extension.skill_dirs)
            lines.append(f"- {extension.id}: {tool_count} tools, {skill_count} skill roots")
        return lines


def load_extension_catalog(root: Path | None = None) -> ExtensionCatalog:
    extension_root = (root or Path(os.environ.get("JARVIS_EXTENSIONS_DIR", "extensions"))).resolve()
    if not extension_root.exists():
        return ExtensionCatalog(root=extension_root, extensions=[])

    disabled = split_env_list(os.environ.get("JARVIS_DISABLED_EXTENSIONS", ""))
    enabled_filter = split_env_list(os.environ.get("JARVIS_ENABLED_EXTENSIONS", ""))
    extensions: list[Extension] = []
    for child in sorted((item for item in extension_root.iterdir() if item.is_dir()), key=lambda item: item.name.lower()):
        manifest_path = child / "extension.json"
        if not manifest_path.exists():
            continue
        extension = load_extension_manifest(manifest_path)
        if extension.id in disabled:
            continue
        if enabled_filter and extension.id not in enabled_filter:
            continue
        extensions.append(extension)
    return ExtensionCatalog(root=extension_root, extensions=extensions)


def split_env_list(value: str) -> set[str]:
    items: set[str] = set()
    for raw in value.split(","):
        item = raw.strip()
        if item:
            items.add(item)
    return items


def load_extension_manifest(path: Path) -> Extension:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as error:
        raise ExtensionError(f"Extension manifest is not valid JSON: {path}") from error
    if not isinstance(data, dict):
        raise ExtensionError(f"Extension manifest must be an object: {path}")

    root = path.parent.resolve()
    extension_id = required_text(data, "id", path)
    name = optional_text(data, "name", extension_id)
    description = optional_text(data, "description", "")
    tools = read_tool_descriptors(data, path)
    prompt_files = resolve_path_list(root, data.get("prompt_files"), path)
    skill_dirs = resolve_path_list(root, data.get("skill_dirs"), path)
    env = read_text_list(data.get("env"), path, "env")
    display_templates = read_display_templates(data.get("display_templates"), path)
    return Extension(
        root=root,
        manifest_path=path.resolve(),
        id=extension_id,
        name=name,
        description=description,
        tools=tools,
        prompt_files=prompt_files,
        skill_dirs=skill_dirs,
        env=env,
        display_templates=display_templates,
    )


def read_tool_descriptors(data: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    tools = data.get("tools", [])
    if not isinstance(tools, list):
        raise ExtensionError(f"Extension tools must be a list: {path}")
    descriptors: list[dict[str, Any]] = []
    for entry in tools:
        if not isinstance(entry, dict):
            raise ExtensionError(f"Extension tool entries must be objects: {path}")
        descriptors.append(entry)
    return descriptors


def read_display_templates(value: Any, path: Path) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ExtensionError(f"Extension display_templates must be an object: {path}")
    templates: dict[str, str] = {}
    for key, template in value.items():
        if isinstance(key, str) and isinstance(template, str):
            templates[key] = template
    return templates


def resolve_path_list(root: Path, value: Any, manifest_path: Path) -> list[Path]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ExtensionError(f"Manifest path list must be a list: {manifest_path}")
    paths: list[Path] = []
    for raw in value:
        if not isinstance(raw, str) or not raw.strip():
            continue
        resolved = (root / raw.strip()).resolve()
        if not is_relative_to(resolved, root):
            raise ExtensionError(f"Manifest path leaves extension root: {raw}")
        paths.append(resolved)
    return paths


def read_text_list(value: Any, path: Path, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ExtensionError(f"Extension {field} must be a list: {path}")
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            result.append(item.strip())
    return result


def required_text(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ExtensionError(f"Extension manifest field is required: {key} in {path}")
    return value.strip()


def optional_text(data: dict[str, Any], key: str, fallback: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
