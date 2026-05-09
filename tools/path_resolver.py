from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_PATH_CONFIG = Path("config/path_aliases.json")


def resolve_local_path(value: str, base: Path | None = None) -> Path:
    raw = clean_path_text(value) or "."
    direct = expand_path(raw, base or Path.cwd())
    if direct.exists():
        return direct.resolve()
    if is_explicit_path(raw):
        return direct.resolve()

    alias = alias_path(raw, base or Path.cwd())
    if alias is not None:
        return alias.resolve()

    discovered = discover_named_path(raw, base or Path.cwd())
    if discovered is not None:
        return discovered.resolve()
    return direct.resolve()


def is_explicit_path(value: str) -> bool:
    path = Path(value)
    if path.is_absolute():
        return True
    return any(marker in value for marker in ("/", "\\", ".", "~", ":"))


def clean_path_text(value: str) -> str:
    text = value.strip()
    while len(text) >= 2 and text[0] in {"'", '"'} and text[-1] == text[0]:
        text = text[1:-1].strip()
    return text


def expand_path(value: str, base: Path) -> Path:
    path = Path(expand_template(value, base)).expanduser()
    if not path.is_absolute():
        path = base / path
    return path


def alias_path(value: str, base: Path) -> Path | None:
    key = canonical_text(value)
    config = load_path_config()
    aliases = config.get("aliases", {})
    if not isinstance(aliases, dict):
        return None
    for alias, template in aliases.items():
        if not isinstance(alias, str) or not isinstance(template, str):
            continue
        alias_key = canonical_text(alias)
        if alias_key == key or alias_key in key or key in alias_key:
            return expand_path(template, base)
    return None


def discover_named_path(value: str, base: Path) -> Path | None:
    key = canonical_text(value)
    if not key:
        return None
    config = load_path_config()
    roots = config.get("search_roots", [])
    if not isinstance(roots, list):
        return None
    max_depth = bounded_int(config.get("search_depth"), 1, 0, 4)
    for root_value in roots:
        if not isinstance(root_value, str) or not root_value.strip():
            continue
        root = expand_path(root_value, base)
        if not root.exists() or not root.is_dir():
            continue
        found = find_child_by_name(root, key, max_depth)
        if found is not None:
            return found
    return None


def find_child_by_name(root: Path, key: str, depth: int) -> Path | None:
    try:
        children = sorted(root.iterdir(), key=lambda item: item.name.lower())
    except OSError:
        return None
    for child in children:
        child_key = canonical_text(child.name)
        if key == child_key or key in child_key or child_key in key:
            return child
    if depth <= 0:
        return None
    for child in children:
        if not child.is_dir():
            continue
        found = find_child_by_name(child, key, depth - 1)
        if found is not None:
            return found
    return None


def load_path_config() -> dict[str, Any]:
    path = Path(os.environ.get("JARVIS_PATH_ALIASES_CONFIG", "").strip() or DEFAULT_PATH_CONFIG)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def expand_template(value: str, base: Path) -> str:
    replacements = template_values(base)
    result = value
    for key, replacement in replacements.items():
        result = result.replace("{" + key + "}", replacement)
    return os.path.expandvars(result)


def template_values(base: Path) -> dict[str, str]:
    home = str(Path.home())
    return {
        "cwd": str(base),
        "home": home,
        "userprofile": os.environ.get("USERPROFILE", home),
        "documents": str(Path.home() / "Documents"),
        "pictures": str(Path.home() / "Pictures"),
        "downloads": str(Path.home() / "Downloads"),
        "desktop": str(Path.home() / "Desktop"),
    }


def canonical_text(text: str) -> str:
    parts: list[str] = []
    last_space = False
    for char in text.casefold():
        if char.isalnum():
            parts.append(char)
            last_space = False
        elif char.isspace() and not last_space:
            parts.append(" ")
            last_space = True
    return "".join(parts).strip()


def bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))
