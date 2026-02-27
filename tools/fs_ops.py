import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Tuple

DEFAULT_IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
}


def resolve_safe_path(workspace_root: Path, raw_path: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("path must be a non-empty string")
    candidate = (workspace_root / raw_path).resolve()
    try:
        candidate.relative_to(workspace_root)
    except ValueError as err:
        raise ValueError(f"path escapes workspace: {raw_path}") from err
    return candidate


def to_rel(workspace_root: Path, path: Path) -> str:
    return str(path.relative_to(workspace_root)).replace("\\", "/")


def list_files(workspace_root: Path, path: str = ".", max_entries: int = 200) -> Dict[str, Any]:
    limit = max(1, min(int(max_entries), 1000))
    root = resolve_safe_path(workspace_root, path)
    if not root.exists():
        raise FileNotFoundError(f"path not found: {path}")

    entries: List[Dict[str, Any]] = []
    if root.is_file():
        st = root.stat()
        return {
            "entries": [{"path": to_rel(workspace_root, root), "type": "file", "size": st.st_size}],
            "truncated": False,
        }

    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_IGNORE_DIRS]
        current_path = Path(current)
        for d in sorted(dirnames):
            p = current_path / d
            entries.append({"path": to_rel(workspace_root, p), "type": "dir"})
            if len(entries) >= limit:
                return {"entries": entries, "truncated": True}
        for f in sorted(filenames):
            p = current_path / f
            try:
                size = p.stat().st_size
            except OSError:
                size = None
            entries.append({"path": to_rel(workspace_root, p), "type": "file", "size": size})
            if len(entries) >= limit:
                return {"entries": entries, "truncated": True}
    return {"entries": entries, "truncated": False}


_MAX_READ_BYTES = 50 * 1024 * 1024  # 50 MB hard limit


def _detect_encoding(raw: bytes) -> str:
    """Try to detect the best text encoding for a byte sequence.
    Falls back through UTF-8 → cp1252 → latin-1 → replace."""
    # Check for null bytes — likely binary
    if b"\x00" in raw[:512]:
        raise ValueError("file appears to be binary (null bytes in first 512 bytes)")
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            raw.decode(enc)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "latin-1"  # guaranteed to decode any byte sequence


def read_file(workspace_root: Path, path: str) -> Dict[str, Any]:
    target = resolve_safe_path(workspace_root, path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"file not found: {path}")

    # Guard: refuse files over 50 MB
    size = target.stat().st_size
    if size > _MAX_READ_BYTES:
        raise ValueError(
            f"file too large to read: {size / 1_048_576:.1f} MB "
            f"(limit is {_MAX_READ_BYTES // 1_048_576} MB). "
            "Use read_file_lines to read specific line ranges instead."
        )

    # Binary detection + encoding cascade
    raw = target.read_bytes()
    encoding = _detect_encoding(raw)
    text = raw.decode(encoding, errors="replace")
    return {"path": to_rel(workspace_root, target), "content": text, "encoding": encoding}


def search_text(workspace_root: Path, query: str, path: str = ".", max_results: int = 100) -> Dict[str, Any]:
    q = str(query).strip()
    if not q:
        raise ValueError("query is required")
    root = resolve_safe_path(workspace_root, path)
    if not root.exists():
        raise FileNotFoundError(f"path not found: {path}")

    limit = max(1, min(int(max_results), 300))

    rg = shutil.which("rg")
    if rg:
        cmd = [rg, "-n", "--no-heading", "--color", "never", "--hidden"]
        for ignore_dir in sorted(DEFAULT_IGNORE_DIRS):
            cmd.extend(["--glob", f"!{ignore_dir}/**"])
        cmd.extend([q, str(root)])
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if out.returncode not in (0, 1):
            raise RuntimeError(out.stderr.strip() or "rg failed")
        lines = [ln for ln in out.stdout.splitlines() if ln.strip()][:limit]
        return {"matches": lines, "truncated": len(lines) >= limit, "engine": "rg"}

    matches: List[str] = []
    if root.is_file():
        files = [root]
    else:
        files = []
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if any(part in DEFAULT_IGNORE_DIRS for part in p.parts):
                continue
            files.append(p)
    for file_path in files:
        try:
            for idx, line in enumerate(file_path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                if q in line:
                    matches.append(f"{to_rel(workspace_root, file_path)}:{idx}:{line}")
                    if len(matches) >= limit:
                        return {"matches": matches, "truncated": True, "engine": "python"}
        except OSError:
            continue
    return {"matches": matches, "truncated": False, "engine": "python"}


def write_file(workspace_root: Path, path: str, content: str, overwrite: bool = True) -> Dict[str, Any]:
    target = resolve_safe_path(workspace_root, path)
    existed = target.exists()
    if existed and not bool(overwrite):
        raise FileExistsError(f"file exists and overwrite=false: {path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(content), encoding="utf-8")
    return {"path": to_rel(workspace_root, target), "bytes": len(str(content).encode("utf-8")), "overwrote": existed}


def edit_file(
    workspace_root: Path,
    path: str,
    old_text: str,
    new_text: str,
    replace_all: bool = False,
) -> Dict[str, Any]:
    if old_text == "":
        raise ValueError("old_text must be non-empty")
    target = resolve_safe_path(workspace_root, path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(f"file not found: {path}")

    text = target.read_text(encoding="utf-8")
    if old_text not in text:
        raise ValueError("old_text not found in file")

    if replace_all:
        updated = text.replace(old_text, new_text)
        count = text.count(old_text)
    else:
        updated = text.replace(old_text, new_text, 1)
        count = 1
    target.write_text(updated, encoding="utf-8")
    return {"path": to_rel(workspace_root, target), "replacements": count}


def delete_path(workspace_root: Path, path: str, recursive: bool = False, missing_ok: bool = False) -> Dict[str, Any]:
    target = resolve_safe_path(workspace_root, path)
    if not target.exists():
        if missing_ok:
            return {"path": path, "deleted": False, "reason": "not_found"}
        raise FileNotFoundError(f"path not found: {path}")

    if target.is_dir():
        if not recursive:
            raise IsADirectoryError("target is a directory; set recursive=true")
        shutil.rmtree(target)
        return {"path": to_rel(workspace_root, target), "deleted": True, "type": "dir"}

    target.unlink()
    return {"path": to_rel(workspace_root, target), "deleted": True, "type": "file"}


def rename_path(workspace_root: Path, path: str, new_name: str, overwrite: bool = False) -> Dict[str, Any]:
    source = resolve_safe_path(workspace_root, path)
    if not source.exists():
        raise FileNotFoundError(f"path not found: {path}")
    n = str(new_name).strip()
    if not n or "/" in n or "\\" in n:
        raise ValueError("new_name must be a simple filename")

    dest = source.with_name(n)
    resolve_safe_path(workspace_root, str(dest.relative_to(workspace_root)))
    if dest.exists() and not overwrite:
        raise FileExistsError("destination exists; set overwrite=true")
    if dest.exists() and overwrite:
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    source.rename(dest)
    return {"from": to_rel(workspace_root, source), "to": to_rel(workspace_root, dest)}


def move_path(workspace_root: Path, src: str, dst: str, overwrite: bool = False) -> Dict[str, Any]:
    source = resolve_safe_path(workspace_root, src)
    dest = resolve_safe_path(workspace_root, dst)
    if not source.exists():
        raise FileNotFoundError(f"path not found: {src}")
    if dest.exists() and not overwrite:
        raise FileExistsError("destination exists; set overwrite=true")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and overwrite:
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    shutil.move(str(source), str(dest))
    return {"from": to_rel(workspace_root, source), "to": to_rel(workspace_root, dest)}


def copy_path(workspace_root: Path, src: str, dst: str, overwrite: bool = False, recursive: bool = False) -> Dict[str, Any]:
    source = resolve_safe_path(workspace_root, src)
    dest = resolve_safe_path(workspace_root, dst)
    if not source.exists():
        raise FileNotFoundError(f"path not found: {src}")
    if dest.exists() and not overwrite:
        raise FileExistsError("destination exists; set overwrite=true")
    dest.parent.mkdir(parents=True, exist_ok=True)

    if source.is_dir():
        if not recursive:
            raise IsADirectoryError("source is directory; set recursive=true")
        if dest.exists() and overwrite:
            shutil.rmtree(dest)
        shutil.copytree(source, dest)
        return {"from": to_rel(workspace_root, source), "to": to_rel(workspace_root, dest), "type": "dir"}

    if dest.exists() and overwrite:
        dest.unlink()
    shutil.copy2(source, dest)
    return {"from": to_rel(workspace_root, source), "to": to_rel(workspace_root, dest), "type": "file"}


def make_dir(workspace_root: Path, path: str, parents: bool = True, exist_ok: bool = True) -> Dict[str, Any]:
    target = resolve_safe_path(workspace_root, path)
    target.mkdir(parents=bool(parents), exist_ok=bool(exist_ok))
    return {"path": to_rel(workspace_root, target), "created": True}


def file_info(workspace_root: Path, path: str) -> Dict[str, Any]:
    target = resolve_safe_path(workspace_root, path)
    if not target.exists():
        raise FileNotFoundError(f"path not found: {path}")
    st = target.stat()
    return {
        "path": to_rel(workspace_root, target),
        "type": "dir" if target.is_dir() else "file",
        "size": st.st_size,
        "mtime": st.st_mtime,
    }


def read_file_lines(
    workspace_root: Path,
    path: str,
    start_line: int,
    end_line: int,
) -> Dict[str, Any]:
    """
    Read a specific range of lines from a file without loading the entire file.

    Lines are 1-indexed and inclusive on both ends, matching what editors show.
    Useful for the "Look Before You Leap" pattern — read the exact broken lines
    before calling edit_file_lines.

    Args:
        workspace_root: Workspace root for path resolution.
        path:           Path to the file (absolute or relative to workspace).
        start_line:     First line to return (1-indexed, inclusive).
        end_line:       Last line to return (1-indexed, inclusive).

    Returns:
        Dict with ok, path, start_line, end_line, content (str), line_count.
    """
    try:
        fpath = resolve_safe_path(workspace_root, path)
        if not fpath.is_file():
            return {"ok": False, "error": f"Not a file: {path}"}

        all_lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        total = len(all_lines)

        # Clamp to valid range (1-indexed → 0-indexed)
        s = max(1, start_line)
        e = min(end_line, total)
        if s > total:
            return {
                "ok": False,
                "error": f"start_line {start_line} exceeds file length {total}",
            }

        selected = all_lines[s - 1: e]
        # Prefix each line with its line number for easy LLM reference
        numbered = "".join(f"{s + i}: {line}" for i, line in enumerate(selected))

        return {
            "ok": True,
            "path": to_rel(workspace_root, fpath),
            "start_line": s,
            "end_line": e,
            "total_lines": total,
            "content": numbered,
            "line_count": len(selected),
        }
    except Exception as err:
        return {"ok": False, "error": str(err)}


def edit_file_lines(
    workspace_root: Path,
    path: str,
    start_line: int,
    end_line: int,
    new_content: str,
) -> Dict[str, Any]:
    """
    Surgically replace a specific range of lines in a file.

    Only the targeted lines are changed — all surrounding code is left intact.
    Lines are 1-indexed and inclusive on both ends.

    IMPORTANT: Always call read_file or read_file_lines first to confirm the
    exact line numbers before calling this function — never guess.

    Args:
        workspace_root: Workspace root for path resolution.
        path:           Path to the file (absolute or relative to workspace).
        start_line:     First line to replace (1-indexed, inclusive).
        end_line:       Last line to replace (1-indexed, inclusive).
        new_content:    Replacement text. May contain multiple lines separated
                        by \\n. A trailing newline will be added automatically
                        if missing so the file structure stays intact.

    Returns:
        Dict with ok, path, lines_replaced, total_lines_before, total_lines_after.
    """
    try:
        fpath = resolve_safe_path(workspace_root, path)
        if not fpath.is_file():
            return {"ok": False, "error": f"Not a file: {path}"}

        all_lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        total_before = len(all_lines)

        # Validate range
        s = max(1, start_line)
        e = min(end_line, total_before)
        if s > total_before:
            return {
                "ok": False,
                "error": f"start_line {start_line} exceeds file length {total_before}",
            }
        if s > e:
            return {
                "ok": False,
                "error": f"start_line {s} is greater than end_line {e}",
            }

        # Ensure new_content ends with a newline so surrounding lines stay intact
        if new_content and not new_content.endswith("\n"):
            new_content = new_content + "\n"

        # Split new_content into lines, preserving newlines
        replacement_lines = [ln if ln.endswith("\n") else ln + "\n"
                             for ln in new_content.splitlines()]

        # Perform the surgical replacement (0-indexed slice)
        all_lines[s - 1: e] = replacement_lines

        fpath.write_text("".join(all_lines), encoding="utf-8")
        total_after = len(all_lines)

        return {
            "ok": True,
            "path": to_rel(workspace_root, fpath),
            "start_line": s,
            "end_line": e,
            "lines_replaced": e - s + 1,
            "replacement_line_count": len(replacement_lines),
            "total_lines_before": total_before,
            "total_lines_after": total_after,
        }
    except Exception as err:
        return {"ok": False, "error": str(err)}


def check_syntax(workspace_root: Path, path: str) -> Dict[str, Any]:
    """
    Run a fast Python syntax and AST check on a file using the built-in
    compiler — no subprocess, no external linter required.

    Use this AFTER editing code with edit_file_lines, BEFORE running it
    with run_command. Catches indentation errors, SyntaxErrors, and
    malformed expressions instantly.

    Args:
        workspace_root: Workspace root for path resolution.
        path:           Path to the Python file to check.

    Returns:
        Dict with ok (bool), errors (list of error strings), and a summary.
    """
    try:
        import ast as _ast
        fpath = resolve_safe_path(workspace_root, path)

        if not fpath.is_file():
            return {"ok": False, "errors": [f"File not found: {path}"], "summary": "File not found."}

        if fpath.suffix.lower() not in {".py", ".pyw"}:
            return {
                "ok": False,
                "errors": [f"Not a Python file: {path}"],
                "summary": "check_syntax only supports .py/.pyw files.",
            }

        source = fpath.read_text(encoding="utf-8", errors="replace")
        errors = []

        # Step 1: compile() catches SyntaxError + IndentationError
        try:
            compile(source, str(fpath), "exec")
        except SyntaxError as e:
            errors.append(
                f"SyntaxError at line {e.lineno}: {e.msg} — {(e.text or '').strip()}"
            )

        # Step 2: ast.parse() catches additional structural issues
        if not errors:
            try:
                _ast.parse(source, filename=str(fpath))
            except SyntaxError as e:
                errors.append(
                    f"AST SyntaxError at line {e.lineno}: {e.msg} — {(e.text or '').strip()}"
                )

        if errors:
            return {
                "ok": False,
                "path": to_rel(workspace_root, fpath),
                "errors": errors,
                "summary": f"❌ {len(errors)} syntax error(s) found — fix before running.",
            }

        return {
            "ok": True,
            "path": to_rel(workspace_root, fpath),
            "errors": [],
            "summary": f"✅ Syntax OK — {fpath.name} is clean and ready to run.",
        }

    except Exception as err:
        return {"ok": False, "errors": [str(err)], "summary": f"check_syntax failed: {err}"}


def apply_patch(workspace_root: Path, patch: str) -> Dict[str, Any]:
    begin = "*** Begin Patch"
    end = "*** End Patch"
    add = "*** Add File: "
    delete = "*** Delete File: "
    update = "*** Update File: "
    move = "*** Move to: "

    raw = patch.strip()
    if not raw:
        raise ValueError("patch is empty")
    lines = raw.splitlines()
    if lines[0].strip() != begin or lines[-1].strip() != end:
        raise ValueError("patch must start with '*** Begin Patch' and end with '*** End Patch'")

    i = 1
    summary = {"added": [], "modified": [], "deleted": []}

    def is_hunk_header(line: str) -> bool:
        s = line.strip()
        return s.startswith(add) or s.startswith(delete) or s.startswith(update)

    while i < len(lines) - 1:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        if stripped.startswith(add):
            path = stripped[len(add) :].strip()
            target = resolve_safe_path(workspace_root, path)
            content_lines: List[str] = []
            i += 1
            while i < len(lines) - 1 and not is_hunk_header(lines[i].strip()):
                row = lines[i]
                if not row.startswith("+"):
                    raise ValueError(f"invalid add line for {path}: '{row}'")
                content_lines.append(row[1:])
                i += 1
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("\n".join(content_lines) + ("\n" if content_lines else ""), encoding="utf-8")
            summary["added"].append(to_rel(workspace_root, target))
            continue

        if stripped.startswith(delete):
            path = stripped[len(delete) :].strip()
            target = resolve_safe_path(workspace_root, path)
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            summary["deleted"].append(path.replace("\\", "/"))
            i += 1
            continue

        if stripped.startswith(update):
            path = stripped[len(update) :].strip()
            src = resolve_safe_path(workspace_root, path)
            if not src.exists() or not src.is_file():
                raise FileNotFoundError(f"file not found for update: {path}")

            i += 1
            move_to: str | None = None
            if i < len(lines) - 1 and lines[i].strip().startswith(move):
                move_to = lines[i].strip()[len(move) :].strip()
                i += 1

            op_lines: List[str] = []
            while i < len(lines) - 1 and not is_hunk_header(lines[i].strip()):
                row = lines[i]
                if row.strip() == "":
                    op_lines.append(" ")
                    i += 1
                    continue
                if row.startswith("@@"):
                    op_lines.append(row)
                elif row.startswith(" ") or row.startswith("+") or row.startswith("-"):
                    op_lines.append(row)
                else:
                    raise ValueError(f"invalid update line for {path}: '{row}'")
                i += 1

            updated = _apply_update_ops(src.read_text(encoding="utf-8"), op_lines, path)
            if move_to:
                dst = resolve_safe_path(workspace_root, move_to)
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(updated, encoding="utf-8")
                src.unlink()
                summary["modified"].append(to_rel(workspace_root, dst))
            else:
                src.write_text(updated, encoding="utf-8")
                summary["modified"].append(to_rel(workspace_root, src))
            continue

        raise ValueError(f"invalid patch hunk header: '{line}'")

    return summary


def _apply_update_ops(original_text: str, op_lines: List[str], path: str) -> str:
    lines = original_text.splitlines()
    trailing_newline = original_text.endswith("\n")

    cursor = 0
    idx = 0
    while idx < len(op_lines):
        if op_lines[idx].startswith("@@"):
            idx += 1
            continue

        block: List[str] = []
        while idx < len(op_lines) and not op_lines[idx].startswith("@@"):
            block.append(op_lines[idx])
            idx += 1

        old_lines: List[str] = []
        new_lines: List[str] = []
        for row in block:
            prefix = row[:1]
            body = row[1:] if row else ""
            if prefix == " ":
                old_lines.append(body)
                new_lines.append(body)
            elif prefix == "-":
                old_lines.append(body)
            elif prefix == "+":
                new_lines.append(body)
            else:
                raise ValueError(f"invalid update marker in {path}: '{row}'")

        if not old_lines and not new_lines:
            continue

        if not old_lines:
            lines[cursor:cursor] = new_lines
            cursor += len(new_lines)
            continue

        pos = _find_subsequence(lines, old_lines, cursor)
        if pos is None:
            raise ValueError(f"failed to find expected block in {path}: {old_lines[:3]}")
        lines[pos : pos + len(old_lines)] = new_lines
        cursor = pos + len(new_lines)

    out = "\n".join(lines)
    if trailing_newline:
        out += "\n"
    return out


def _find_subsequence(lines: List[str], pattern: List[str], start: int) -> int | None:
    if not pattern:
        return start
    limit = len(lines) - len(pattern)
    for i in range(max(start, 0), limit + 1):
        if lines[i : i + len(pattern)] == pattern:
            return i
    for i in range(max(start, 0), limit + 1):
        if [ln.rstrip() for ln in lines[i : i + len(pattern)]] == [p.rstrip() for p in pattern]:
            return i
    return None
