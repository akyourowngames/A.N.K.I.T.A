from __future__ import annotations

import os
import re
from pathlib import Path


NORMAL_USER_FOLDERS = ("Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos")
KNOWN_FOLDER_ALIASES = {
    "desktop": "Desktop",
    "desk": "Desktop",
    "documents": "Documents",
    "document": "Documents",
    "docs": "Documents",
    "downloads": "Downloads",
    "download": "Downloads",
    "music": "Music",
    "songs": "Music",
    "pictures": "Pictures",
    "picture": "Pictures",
    "photos": "Pictures",
    "photo": "Pictures",
    "images": "Pictures",
    "image": "Pictures",
    "videos": "Videos",
    "video": "Videos",
}


def default_allowed_roots() -> list[Path]:
    home = Path.home()
    return [path for name in NORMAL_USER_FOLDERS if (path := home / name).exists()]


def allowed_roots(env_var: str = "LOCAL_FILE_ALLOWED_PATHS") -> list[Path]:
    raw = os.getenv(env_var, "").strip()
    roots = _split_path_env(raw) if raw else default_allowed_roots()
    resolved: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        expanded = root.expanduser().resolve(strict=False)
        key = str(expanded).casefold()
        if key not in seen:
            seen.add(key)
            resolved.append(expanded)
    return resolved


def ensure_allowed_path(path: str | Path, roots: list[Path] | None = None) -> Path:
    resolved = resolve_local_path(path)
    candidates = roots or allowed_roots()
    if any(_is_relative_to(resolved, root) for root in candidates):
        return resolved

    allowed = "; ".join(str(root) for root in candidates) or "<none>"
    raise ValueError(f"Path is outside allowed local folders. Allowed folders: {allowed}")


def format_allowed_roots(roots: list[Path] | None = None) -> str:
    candidates = roots or allowed_roots()
    return "\n".join(f"- {root}" for root in candidates) if candidates else "<none>"


def resolve_local_path(path: str | Path) -> Path:
    if isinstance(path, Path):
        return path.expanduser().resolve(strict=False)

    text = path.strip().strip('"').strip("'")
    known_folder = known_folder_path(text)
    if known_folder is not None:
        return known_folder.resolve(strict=False)
    return Path(text).expanduser().resolve(strict=False)


def known_folder_path(text: str) -> Path | None:
    normalized = _normalize_alias(text)
    folder_name = KNOWN_FOLDER_ALIASES.get(normalized)
    if not folder_name:
        return None
    return Path.home() / folder_name


def _split_path_env(raw: str) -> list[Path]:
    separator = ";" if ";" in raw else ","
    return [Path(part.strip()) for part in raw.split(separator) if part.strip()]


def _normalize_alias(text: str) -> str:
    lowered = text.strip().strip('"').strip("'").strip("`").lower()
    lowered = lowered.replace("\\", "/").rstrip("/")
    if "/" in lowered or ":" in lowered:
        return lowered

    words = re.findall(r"[a-z0-9]+", lowered)
    while words and words[0] in {"my", "the"}:
        words.pop(0)
    while words and words[-1] in {"folder", "folders", "directory", "directories", "dir"}:
        words.pop()
    return " ".join(words)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
