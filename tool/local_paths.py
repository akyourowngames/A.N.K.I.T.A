from __future__ import annotations

import os
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
    "home": "",
    "user": "",
    "profile": "",
}


def default_allowed_roots() -> list[Path]:
    return default_quick_roots()


def default_quick_roots() -> list[Path]:
    roots = [Path.cwd(), Path.home()]
    roots.extend(Path.home() / name for name in NORMAL_USER_FOLDERS)
    roots.extend(_drive_roots())
    return _dedupe_existing_or_resolvable(roots)


def allowed_roots(env_var: str = "LOCAL_FILE_ALLOWED_PATHS") -> list[Path]:
    raw = os.getenv(env_var, "").strip()
    roots = _split_path_env(raw) if raw else default_quick_roots()
    return _dedupe_existing_or_resolvable(roots)


def local_file_access_is_restricted(env_var: str = "LOCAL_FILE_ALLOWED_PATHS") -> bool:
    raw = os.getenv(env_var, "").strip()
    if not raw:
        return False
    flag = os.getenv("LOCAL_FILE_RESTRICT_TO_ALLOWED_PATHS", "false").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def ensure_allowed_path(path: str | Path, roots: list[Path] | None = None, restrict: bool | None = None) -> Path:
    resolved = resolve_local_path(path)
    if restrict is None:
        restrict = local_file_access_is_restricted() if roots is None else _explicit_roots_are_restricted()
    if not restrict:
        return resolved

    candidates = _dedupe_existing_or_resolvable(roots or allowed_roots())
    if any(_is_relative_to(resolved, root) for root in candidates):
        return resolved

    allowed = "; ".join(str(root) for root in candidates) or "<none>"
    raise ValueError(f"Path is outside the configured local folders. Configured folders: {allowed}")


def format_allowed_roots(roots: list[Path] | None = None) -> str:
    candidates = _dedupe_existing_or_resolvable(roots or allowed_roots())
    if local_file_access_is_restricted():
        header = "Restricted to configured local folders:"
    else:
        header = "All local folders are accessible by default. Useful starting points:"
    lines = [header]
    lines.extend(f"- {root}" for root in candidates)
    return "\n".join(lines)


def resolve_local_path(path: str | Path) -> Path:
    if isinstance(path, Path):
        return path.expanduser().resolve(strict=False)

    text = path.strip().strip('"').strip("'")
    known_folder = known_folder_path(text)
    if known_folder is not None:
        return known_folder.resolve(strict=False)
    if not text:
        return Path.cwd().resolve(strict=False)
    return Path(text).expanduser().resolve(strict=False)


def known_folder_path(text: str) -> Path | None:
    normalized = _normalize_alias(text)
    if normalized in {"", "."}:
        return None
    folder_name = KNOWN_FOLDER_ALIASES.get(normalized)
    if folder_name is None:
        return None
    return Path.home() if not folder_name else Path.home() / folder_name


def _split_path_env(raw: str) -> list[Path]:
    separator = ";" if ";" in raw else ","
    return [Path(part.strip()) for part in raw.split(separator) if part.strip()]


def _normalize_alias(text: str) -> str:
    lowered = text.strip().strip('"').strip("'").strip("`").lower()
    lowered = lowered.replace("\\", "/").rstrip("/")
    if "/" in lowered or ":" in lowered:
        return lowered

    words = []
    current = []
    for char in lowered:
        if char.isalnum():
            current.append(char)
            continue
        if current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))

    while words and words[0] in {"my", "the"}:
        words.pop(0)
    while words and words[-1] in {"folder", "folders", "directory", "directories", "dir"}:
        words.pop()
    return " ".join(words)


def _drive_roots() -> list[Path]:
    roots: list[Path] = []
    if os.name != "nt":
        roots.append(Path("/"))
        return roots

    for letter_number in range(ord("A"), ord("Z") + 1):
        root = Path(f"{chr(letter_number)}:/")
        if root.exists():
            roots.append(root)
    return roots


def _dedupe_existing_or_resolvable(paths: list[Path]) -> list[Path]:
    resolved: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        expanded = path.expanduser().resolve(strict=False)
        key = str(expanded).casefold()
        if key not in seen:
            seen.add(key)
            resolved.append(expanded)
    return resolved


def _explicit_roots_are_restricted() -> bool:
    flag = os.getenv("LOCAL_FILE_RESTRICT_TO_ALLOWED_PATHS", "false").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
