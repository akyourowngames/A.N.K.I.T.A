"""God-tier local filesystem tools for Zumba — no shell needed for file work.

Reads (direct): fs_read (windowed + symbol context), fs_grep (rg-first
content search), fs_find (instant filename locate via rg --files),
fs_list, fs_info, fs_glob, fs_tree.
Writes (backup + diff + audit): fs_write, fs_edit (unique-match cascade),
fs_insert, fs_replace_lines, fs_apply_patch (V4A multi-file atomic),
fs_batch (transactional), fs_undo, fs_mkdir, fs_move, fs_delete.

Conventions (match websearch.py / scrape.py / geo.py):
- ERROR: text prefix on failures, never raise into chat.
- ZUMBA_NO_FS=1 kill-switch.
- Unrestricted paths (god-mode, like shell); every mutation is appended
  to ~/.zumba/fs_audit.log and auto-backed-up under .zumba_backups.

  Unrestricted is an explicit owner decision (see PR #20 discussion):
  no jail, no denylist. Safety comes from backups + diffs + audit +
  confirm gates on delete/overwrite — not from path restrictions.
  Callers that need confinement must enforce it themselves.
"""

from __future__ import annotations

import difflib
import fnmatch
import functools
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

_FS_WRITE_LOCK = threading.Lock()


def _locked(fn):
    """Serialize mutating ops process-wide (model calls are also grouped
    under the fs TOOL_GROUP lock; this covers direct/CLI callers)."""

    @functools.wraps(fn)
    def wrapper(*a, **k):
        with _FS_WRITE_LOCK:
            return fn(*a, **k)

    return wrapper

MAX_READ_LINES = 2000
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv",
             ".pytest_cache", ".mypy_cache", ".ruff_cache", "dist", "build"}


def enabled() -> bool:
    return os.getenv("ZUMBA_NO_FS", "") != "1"


def max_output() -> int:
    try:
        return max(500, int(os.getenv("ZUMBA_FS_MAX_OUTPUT", "8000") or 8000))
    except Exception:
        return 8000


def search_timeout_s() -> float:
    try:
        return max(2.0, min(120.0, float(os.getenv("ZUMBA_FS_SEARCH_TIMEOUT", "15") or 15)))
    except Exception:
        return 15.0


# ---- paths / display ----

def resolve(path: str = ".") -> Path:
    p = (path or ".").strip() or "."
    return Path(p).expanduser().absolute()


def _display(path: Path) -> str:
    try:
        rel = Path(path).resolve().relative_to(Path.home().resolve())
        return str(Path("~") / rel)
    except Exception:
        return str(path)


def _is_binary(path: Path, check_bytes: int = 1024) -> bool:
    try:
        with open(path, "rb") as f:
            return b"\x00" in f.read(check_bytes)
    except Exception:
        return False


def truncate(text: str, cap: int = 0) -> str:
    cap = cap or max_output()
    if len(text) <= cap:
        return text
    head = cap * 4 // 5
    return text[:head] + f"\n[...truncated {len(text) - cap} chars; showing head+tail...]\n" + text[-head:]


# ---- ignore policy (.gitignore-aware, like Friday) ----

def _load_ignore(root: Path) -> list[str]:
    pats: list[str] = []
    for name in (".gitignore", ".ignore"):
        f = root / name
        if not f.is_file():
            continue
        try:
            for raw in f.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if line and not line.startswith(("#", "!")):
                    pats.append(line)
        except Exception:
            pass
    return pats


def _ignored(path: Path, root: Path, pats: list[str] | None = None) -> bool:
    try:
        rel = path.relative_to(root)
    except Exception:
        rel = path
    if any(part in SKIP_DIRS for part in rel.parts):
        return True
    pats = pats if pats is not None else _load_ignore(root)
    posix = rel.as_posix()
    for pat in pats:
        if pat.endswith("/"):
            if posix == pat.rstrip("/") or posix.startswith(pat):
                return True
            continue
        p = pat.lstrip("/")
        if "/" in p:
            if fnmatch.fnmatch(posix, p) or fnmatch.fnmatch(posix, "*/" + p):
                return True
        elif fnmatch.fnmatch(path.name, p):
            return True
    return False


# ---- audit + backups ----

def _audit(tool: str, detail: str) -> None:
    try:
        from core.store import zumba_home
        log = zumba_home() / "fs_audit.log"
    except Exception:
        log = Path.home() / ".zumba" / "fs_audit.log"
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{ts} | {tool} | {detail[:400]}\n")
    except Exception:
        pass


def _backup_path(path: Path, label: str = "auto") -> Path:
    root = path.parent / ".zumba_backups"
    root.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in label)[:40]
    return root / f"{path.name}.{ts}.{safe}.bak"


def _create_backup(path: Path, label: str = "auto") -> str:
    if not path.is_file():
        return ""
    try:
        bp = _backup_path(path, label)
        shutil.copy2(path, bp)
        return str(bp)
    except Exception:
        return ""


def atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Byte-exact variant — rollback must never decode/re-encode (mojibake)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, str(path))
    except BaseException:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _diff(old: str, new: str, name: str = "file") -> str:
    d = difflib.unified_diff(old.splitlines(), new.splitlines(),
                             fromfile=f"a/{name}", tofile=f"b/{name}", lineterm="")
    return "\n".join(d) or "No changes."


def _read_lines(path: Path) -> tuple[list[str], bool, str]:
    content = path.read_text(encoding="utf-8", errors="replace")
    trailing = content.endswith("\n")
    nl = "\r\n" if "\r\n" in content and content.count("\r\n") >= content.count("\n") / 2 else "\n"
    return content.splitlines(), trailing, nl


def _join(lines: list[str], trailing: bool, nl: str) -> str:
    out = nl.join(lines)
    if trailing and (out or lines):
        out += nl
    return out


# ================= READS =================

def fs_read(path: str, start_line: int = 1, num_lines: int = 200) -> str:
    p = resolve(path)
    if not p.exists():
        return f"ERROR: file not found: {path}"
    if not p.is_file():
        return f"ERROR: not a file: {path}"
    try:
        if _is_binary(p):
            return f"ERROR: binary file, cannot display: {_display(p)}"
    except Exception as exc:
        return f"ERROR: cannot read {path}: {exc}"
    n = max(1, min(int(num_lines or 200), MAX_READ_LINES))
    start = max(1, int(start_line or 1))
    try:
        with open(p, encoding="utf-8", errors="replace") as h:
            all_lines = [ln.rstrip("\n") for ln in h]
    except Exception as exc:
        return f"ERROR: cannot read {path}: {exc}"
    total = len(all_lines)
    end = min(total, start + n - 1)
    sel = all_lines[start - 1:end] if start <= total else []
    parts = [f"[File: {_display(p)} ({total} lines total)]"]
    ctx = _symbol_context(p, all_lines, start)
    if ctx:
        parts.append("Context:")
        parts.extend(ctx)
    if start > 1:
        parts.append(f"({min(start - 1, total)} more lines above)")
    for i, ln in enumerate(sel, start):
        parts.append(f"{i:>6}\t{ln}")
    if end < total:
        parts.append(f"({total - end} more lines below)")
    return truncate("\n".join(parts))


def _symbol_context(path: Path, lines: list[str], start: int) -> list[str]:
    """Nearby imports / enclosing scope — structural only (no semantic gates)."""
    if start <= 1:
        return []
    suf = path.suffix.lower()
    if suf not in (".py", ".js", ".jsx", ".ts", ".tsx", ".md"):
        return []
    ctx: list[str] = []
    if suf == ".py":
        for i, ln in enumerate(lines[:80], 1):
            s = ln.strip()
            if i < start and s.startswith(("import ", "from ")):
                ctx.append(f"  import {i}: {ln.rstrip()}")
                if len(ctx) >= 6:
                    break
        for i in range(min(start - 1, len(lines)), 0, -1):
            s = lines[i - 1].lstrip()
            if re.match(r"(async\s+def|def|class)\s+", s):
                ctx.append(f"  scope {i}: {lines[i - 1].rstrip()}")
                break
    elif suf in (".js", ".jsx", ".ts", ".tsx"):
        for i in range(min(start - 1, len(lines)), 0, -1):
            s = lines[i - 1].strip()
            if re.match(r"(export\s+)?(async\s+)?function\s+|class\s+|const\s+\w+\s*=", s):
                ctx.append(f"  scope {i}: {lines[i - 1].rstrip()}")
                break
    else:
        for i in range(min(start - 1, len(lines)), 0, -1):
            if lines[i - 1].lstrip().startswith("#"):
                ctx.append(f"  heading {i}: {lines[i - 1].rstrip()}")
                break
    return ctx[:8]


def _rg() -> str:
    return shutil.which("rg") or ""


def fs_grep(pattern: str, path: str = ".", glob: str = "", context: int = 0,
            case_sensitive: bool = False, max_results: int = 100) -> str:
    """Line-oriented content search. rg --vimgrep first, Python fallback."""
    if not (pattern or "").strip():
        return "ERROR: 'pattern' is required."
    root = resolve(path)
    if not root.exists():
        return f"ERROR: path not found: {path}"
    if root.is_file():
        root = root.parent
    if not root.is_dir():
        return f"ERROR: not a directory: {path}"
    cap = max(1, min(int(max_results or 100), 500))
    ctx = max(0, min(int(context or 0), 10))
    hits = _grep_rg(pattern, root, glob, ctx, case_sensitive, cap)
    if hits is None:
        hits = _grep_py(pattern, root, glob, ctx, case_sensitive, cap)
    if not hits:
        return f"No matches for {pattern!r} in {_display(root)}."
    lines = [f"Found {len(hits)} match(es) for {pattern!r} in {_display(root)}:"]
    for h in hits[:cap]:
        lines.append(f"{_display(Path(h[0]))}:{h[1]}: {h[2][:500]}")
        for c in h[3]:
            lines.append(f"  {c}")
    if len(hits) > cap:
        lines.append(f"... and {len(hits) - cap} more")
    return truncate("\n".join(lines))


def _grep_rg(pattern: str, root: Path, glob: str, ctx: int,
             case_sensitive: bool, cap: int) -> list | None:
    rg = _rg()
    if not rg:
        return None
    cmd = [rg, "--vimgrep", "--no-heading", "--max-columns", "500",
           "--max-count", "5"]
    if not case_sensitive:
        cmd.append("-i")
    if ctx:
        cmd += ["-C", str(ctx)]
    if (glob or "").strip():
        cmd += ["-g", glob.strip()]
    cmd += ["--", pattern, str(root)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=search_timeout_s())
    except Exception:
        return None
    if r.returncode not in (0, 1):
        return None
    out: list = []
    pending_ctx: list[str] = []
    for ln in (r.stdout or "").splitlines():
        if ln.startswith("--"):
            continue
        if ln.startswith("-") and ctx:
            pending_ctx.append(" " + ln[1:].strip()[:300])
            continue
        m = re.match(r"^(.+?):(\d+):(\d+):(.*)$", ln)
        if not m:
            continue
        entry = [m.group(1), int(m.group(2)), m.group(4).strip(), pending_ctx]
        pending_ctx = []
        out.append(entry)
        if len(out) >= cap:
            break
    return out


def _grep_py(pattern: str, root: Path, glob: str, ctx: int,
             case_sensitive: bool, cap: int) -> list:
    try:
        rx = re.compile(pattern, 0 if case_sensitive else re.I)
    except re.error:
        rx = re.compile(re.escape(pattern), 0 if case_sensitive else re.I)
    pats = _load_ignore(root)
    out: list = []
    for dirpath, dirs, files in os.walk(root):
        cur = Path(dirpath)
        dirs[:] = [d for d in dirs if not _ignored(cur / d, root, pats)]
        for fn in files:
            fp = cur / fn
            if _ignored(fp, root, pats):
                continue
            if glob.strip() and not fnmatch.fnmatch(fn, glob.strip()):
                continue
            try:
                if _is_binary(fp):
                    continue
                text = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            per = 0
            for i, ln in enumerate(text, 1):
                if rx.search(ln):
                    if ctx:
                        snips = []
                        for s in range(max(1, i - ctx), min(len(text), i + ctx) + 1):
                            mark = ">" if s == i else " "
                            snips.append(f"{mark}{s}: {text[s - 1].strip()[:300]}")
                    else:
                        snips = []
                    out.append([str(fp), i, ln.strip()[:500], snips])
                    per += 1
                    if len(out) >= cap or per >= 5:
                        break
            if len(out) >= cap:
                return out
    return out


def fs_find(name: str, path: str = ".", max_results: int = 50) -> str:
    """Instant global filename locate: rg --files + fuzzy rank, os.walk fallback."""
    if not (name or "").strip():
        return "ERROR: 'name' is required."
    root = resolve(path)
    if not root.exists():
        return f"ERROR: path not found: {path}"
    if not root.is_dir():
        return f"ERROR: not a directory: {path}"
    cap = max(1, min(int(max_results or 50), 500))
    cands = _find_rg(root)
    if cands is None:
        cands = _find_walk(root)
    q = name.strip().lower()
    ranked: list[tuple[int, str]] = []
    for c in cands:
        base = Path(c).name.lower()
        score = _find_score(base, c.lower(), q)
        if score is not None:
            ranked.append((score, c))
    ranked.sort(key=lambda t: (t[0], t[1].lower()))
    if not ranked:
        return f"No files matching {name!r} under {_display(root)}."
    lines = [f"Found {len(ranked)} file(s) matching {name!r} under {_display(root)}:"]
    for _, c in ranked[:cap]:
        try:
            sz = Path(c).stat().st_size
            size = f"{sz}B" if sz < 1024 else (f"{sz / 1024:.1f}KB" if sz < 1048576 else f"{sz / 1048576:.1f}MB")
        except Exception:
            size = "?"
        lines.append(f"  {_display(Path(c))}  {size}")
    if len(ranked) > cap:
        lines.append(f"... and {len(ranked) - cap} more")
    return truncate("\n".join(lines))


def _find_score(base: str, full: str, q: str) -> int | None:
    if base == q:
        return 0
    if base.startswith(q):
        return 1
    if q in base:
        return 2
    if q in full:
        return 3
    qparts = [p for p in re.split(r"[\s_\-]+", q) if p]
    if qparts and all(p in base for p in qparts):
        return 4
    return None


def _find_rg(root: Path) -> list | None:
    rg = _rg()
    if not rg:
        return None
    try:
        r = subprocess.run([rg, "--files", str(root)], capture_output=True,
                           text=True, errors="replace", timeout=search_timeout_s())
    except Exception:
        return None
    if r.returncode != 0:
        return None
    return [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]


def _find_walk(root: Path) -> list:
    pats = _load_ignore(root)
    out: list = []
    for dirpath, dirs, files in os.walk(root):
        cur = Path(dirpath)
        dirs[:] = [d for d in dirs if not _ignored(cur / d, root, pats)]
        for fn in files:
            fp = cur / fn
            if not _ignored(fp, root, pats):
                out.append(str(fp))
            if len(out) >= 20000:
                return out
    return out


def fs_list(path: str = ".", max_items: int = 30, sort: str = "name") -> str:
    d = resolve(path)
    if not d.exists():
        return f"ERROR: directory not found: {path}"
    if not d.is_dir():
        return f"ERROR: not a directory: {path}"
    sk = (sort or "name").lower()
    try:
        items = list(d.iterdir())
    except Exception as exc:
        return f"ERROR: cannot list {path}: {exc}"
    if sk in ("mtime", "activity"):
        items.sort(key=lambda p: (p.is_file(), -(p.stat().st_mtime if _safe_stat(p) else 0)))
    elif sk == "size":
        items.sort(key=lambda p: (p.is_file(), -(_safe_stat(p).st_size if p.is_file() and _safe_stat(p) else 0)))
    else:
        items.sort(key=lambda p: (p.is_file(), p.name.lower()))
    cap = max(1, min(int(max_items or 30), 2000))
    lines = [f"[Directory: {_display(d)}]"]
    for it in items[:cap]:
        if it.is_dir():
            lines.append(f"  [dir]  {it.name}/")
        else:
            try:
                sz = it.stat().st_size
                size = f"{sz}B" if sz < 1024 else (f"{sz / 1024:.1f}KB" if sz < 1048576 else f"{sz / 1048576:.1f}MB")
            except Exception:
                size = "?"
            lines.append(f"  [file] {it.name}  {size}")
    if len(items) > cap:
        lines.append(f"... and {len(items) - cap} more item(s)")
    return "\n".join(lines)


def _safe_stat(p: Path):
    try:
        return p.stat()
    except Exception:
        return None


def fs_info(path: str) -> str:
    p = resolve(path)
    if not p.exists() and not p.is_symlink():
        return f"ERROR: not found: {path}"
    try:
        st = p.lstat()
    except Exception as exc:
        return f"ERROR: cannot stat {path}: {exc}"
    kind = "symlink" if p.is_symlink() else ("directory" if p.is_dir() else ("file" if p.is_file() else "unknown"))
    lines = [f"[File Info: {_display(p)}]", f"  Type: {kind}",
             f"  Size: {st.st_size:,} bytes",
             f"  Modified: {datetime.fromtimestamp(st.st_mtime, tz=timezone.utc):%Y-%m-%d %H:%M:%S UTC}"]
    if p.is_symlink():
        try:
            lines.append(f"  Link target: {os.readlink(p)}")
        except Exception:
            pass
    elif p.is_file():
        lines.append(f"  Binary: {'yes' if _is_binary(p) else 'no'}")
    return "\n".join(lines)


def fs_glob(pattern: str, path: str = ".", max_results: int = 50) -> str:
    if not (pattern or "").strip():
        return "ERROR: 'pattern' is required."
    root = resolve(path)
    if not root.exists():
        return f"ERROR: path not found: {path}"
    if not root.is_dir():
        return f"ERROR: not a directory: {path}"
    cap = max(1, min(int(max_results or 50), 500))
    pats = _load_ignore(root)
    matches: list[Path] = []
    try:
        for m in root.rglob(pattern.strip()):
            if _ignored(m, root, pats):
                continue
            matches.append(m)
            if len(matches) >= cap:
                break
    except Exception as exc:
        return f"ERROR: glob failed: {exc}"
    if not matches:
        return f"No matches for '{pattern}' in {_display(root)}."
    matches.sort(key=lambda x: (x.is_file(), str(x).lower()))
    lines = [f"Found {len(matches)} match(es) for '{pattern}':"]
    for m in matches:
        lines.append(f"  {'[dir] ' if m.is_dir() else '[file] '}{_display(m)}")
    if len(matches) >= cap:
        lines.append(f"... (capped at {cap} results)")
    return "\n".join(lines)


def fs_tree(path: str = ".", max_depth: int = 3) -> str:
    root = resolve(path)
    if not root.exists():
        return f"ERROR: path not found: {path}"
    if not root.is_dir():
        return f"ERROR: not a directory: {path}"
    depth = max(1, min(int(max_depth or 3), 10))
    pats = _load_ignore(root)
    lines = [f"[Tree: {_display(root)}]", root.name + "/"]

    def walk(cur: Path, d: int, prefix: str) -> None:
        if d > depth:
            return
        try:
            items = sorted([i for i in cur.iterdir() if not _ignored(i, root, pats)],
                           key=lambda x: (x.is_file(), x.name.lower()))
        except Exception:
            lines.append(f"{prefix}[access denied]")
            return
        for i, it in enumerate(items):
            last = i == len(items) - 1
            conn, child = ("└── ", "    ") if last else ("├── ", "│   ")
            lines.append(f"{prefix}{conn}{it.name}{'/' if it.is_dir() else ''}")
            if it.is_dir() and d < depth:
                walk(it, d + 1, prefix + child)

    walk(root, 1, "")
    return truncate("\n".join(lines))


# ================= WRITES (backup + diff + audit) =================

def _write_result(tool: str, path: Path, old: str, new: str, action: str) -> str:
    name = path.name or str(path)
    diff = _diff(old, new, name)
    if diff == "No changes.":
        return f"No changes for {_display(path)}."
    _audit(tool, f"{action} {_display(path)}")
    return f"{action} {_display(path)} (backup kept under .zumba_backups)\n{diff}"


def fs_write(path: str, content: str, dry_run: bool = False) -> str:
    if not (path or "").strip():
        return "ERROR: 'path' is required."
    if content is None:
        return "ERROR: 'content' is required."
    p = resolve(path)
    if p.exists() and not p.is_file():
        return f"ERROR: not a file: {path}"
    old = ""
    if p.is_file():
        try:
            old = p.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"ERROR: cannot read {path}: {exc}"
    if dry_run:
        return f"[DRY RUN] Would {'overwrite' if old else 'create'} {_display(p)} ({len(content.encode('utf-8')):,} bytes):\n{_diff(old, content, p.name)}"
    try:
        if p.is_file():
            _create_backup(p, "write")
        atomic_write(p, content)
    except Exception as exc:
        return f"ERROR: write failed for {path}: {exc}"
    return _write_result("fs_write", p, old, content, "Overwrote" if old else "Created")


def _closest_match(old_text: str, content: str, threshold: float = 0.6) -> str | None:
    from difflib import SequenceMatcher
    old_lines = old_text.splitlines()
    lines = content.splitlines()
    if not old_lines or not lines:
        return None
    best, idx = 0.0, 0
    w = len(old_lines)
    for i in range(len(lines) - w + 1):
        r = SequenceMatcher(None, old_lines, lines[i:i + w]).ratio()
        if r > best:
            best, idx = r, i
    if best >= threshold:
        return "\n".join(lines[idx:idx + w])
    return None


def fs_edit(path: str, old_text: str, new_text: str, occurrence: int = 0,
            dry_run: bool = False) -> str:
    """Unique-match replace with cascade: exact -> occurrence -> whitespace -> suggest."""
    if not (path or "").strip():
        return "ERROR: 'path' is required."
    if not (old_text or ""):
        return "ERROR: 'old_text' is required."
    if new_text is None:
        return "ERROR: 'new_text' is required."
    p = resolve(path)
    if not p.is_file():
        return f"ERROR: file not found: {path}"
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"ERROR: cannot read {path}: {exc}"
    nl = "\r\n" if "\r\n" in content else "\n"
    new_norm = str(new_text).replace("\r\n", "\n").replace("\r", "\n").replace("\n", nl)
    count = content.count(old_text)
    if count == 1 and not occurrence:
        new_content = content.replace(old_text, new_norm, 1)
    elif count > 1 and occurrence:
        if occurrence < 1 or occurrence > count:
            return (f"ERROR: occurrence {occurrence} out of range "
                    f"({count} matches in {_display(p)}).")
        idx = -1
        for _ in range(occurrence):
            idx = content.find(old_text, idx + 1)
        new_content = content[:idx] + new_norm + content[idx + len(old_text):]
    elif count > 1:
        first = [i + 1 for i, ln in enumerate(content.splitlines()) if old_text in ln][:10]
        hint = f" Matching lines: {', '.join(map(str, first))}." if first else ""
        return (f"ERROR: old_text matches {count} locations in {_display(p)}."
                f" Add more context or pass occurrence=1..{count}.{hint}")
    else:
        # whitespace-normalized match
        old_lns = old_text.replace("\r\n", "\n").split("\n")
        cl = content.replace("\r\n", "\n").split("\n")
        match_at = None
        norm_old = [f"{len(l) - len(l.lstrip())}:{l.strip()}" for l in old_lns]
        for i in range(len(cl) - len(norm_old) + 1):
            if [f"{len(l) - len(l.lstrip())}:{l.strip()}" for l in cl[i:i + len(norm_old)]] == norm_old:
                match_at = i
                break
        if match_at is not None:
            rep = str(new_text).split("\n")
            new_content = "\n".join(cl[:match_at] + rep + cl[match_at + len(norm_old):])
            if content.endswith("\n") and not new_content.endswith("\n"):
                new_content += "\n"
            new_content = new_content.replace("\n", nl) if nl != "\n" else new_content
        else:
            sug = _closest_match(old_text, content)
            if sug:
                return (f"ERROR: no match for old_text in {_display(p)}.\n"
                        f"Did you mean:\n---\n{sug}\n---")
            return f"ERROR: no match for old_text in {_display(p)}."
    if dry_run:
        return f"[DRY RUN] Would edit {_display(p)}:\n{_diff(content, new_content, p.name)}"
    try:
        _create_backup(p, "edit")
        atomic_write(p, new_content)
    except Exception as exc:
        return f"ERROR: edit failed for {path}: {exc}"
    return _write_result("fs_edit", p, content, new_content, "Edited")


def fs_insert(path: str, line: int, text: str, position: str = "after",
              dry_run: bool = False) -> str:
    if not (path or "").strip():
        return "ERROR: 'path' is required."
    if text is None:
        return "ERROR: 'text' is required."
    p = resolve(path)
    if not p.is_file():
        return f"ERROR: file not found: {path}"
    pos = (position or "after").lower()
    if pos not in ("before", "after"):
        return "ERROR: 'position' must be before or after."
    try:
        lines, trailing, nl = _read_lines(p)
    except Exception as exc:
        return f"ERROR: cannot read {path}: {exc}"
    # line == len+1 with after == append; line == 1 with before == prepend
    lo, hi = 1, len(lines) + (1 if pos == "after" else 0)
    try:
        ln = int(line)
    except Exception:
        return "ERROR: 'line' must be a number."
    if ln < lo or ln > max(hi, 1):
        return f"ERROR: invalid line {line}; file has {len(lines)} line(s)."
    at = ln - 1 if pos == "before" else ln
    new_lines = lines[:at] + str(text).splitlines() + lines[at:]
    new_content = _join(new_lines, trailing if trailing or new_lines else True, nl)
    if dry_run:
        return f"[DRY RUN] Would insert {pos} line {ln} in {_display(p)}:\n{_diff(chr(10).join(lines), new_content, p.name)}"
    try:
        _create_backup(p, "insert")
        atomic_write(p, new_content)
    except Exception as exc:
        return f"ERROR: insert failed for {path}: {exc}"
    old_content = nl.join(lines) + (nl if trailing else "")
    return _write_result("fs_insert", p, old_content, new_content, f"Inserted {pos} line {ln} in")


def fs_replace_lines(path: str, start: int, end: int, new_text: str,
                     dry_run: bool = False) -> str:
    if not (path or "").strip():
        return "ERROR: 'path' is required."
    if new_text is None:
        return "ERROR: 'new_text' is required."
    p = resolve(path)
    if not p.is_file():
        return f"ERROR: file not found: {path}"
    try:
        lines, trailing, nl = _read_lines(p)
    except Exception as exc:
        return f"ERROR: cannot read {path}: {exc}"
    try:
        s, e = int(start), int(end)
    except Exception:
        return "ERROR: 'start'/'end' must be numbers."
    if s < 1 or e < s or e > len(lines):
        return f"ERROR: invalid range {start}-{end}; file has {len(lines)} line(s)."
    new_lines = lines[:s - 1] + str(new_text).splitlines() + lines[e:]
    new_content = _join(new_lines, trailing, nl)
    if dry_run:
        return f"[DRY RUN] Would replace lines {s}-{e} in {_display(p)}:\n{_diff(chr(10).join(lines), new_content, p.name)}"
    try:
        _create_backup(p, "replace_lines")
        atomic_write(p, new_content)
    except Exception as exc:
        return f"ERROR: replace failed for {path}: {exc}"
    old_content = nl.join(lines) + (nl if trailing else "")
    return _write_result("fs_replace_lines", p, old_content, new_content,
                         f"Replaced lines {s}-{e} in")


# ---- V4A apply_patch (context-anchored, multi-file, atomic) ----

def _parse_v4a(patch: str) -> tuple[list, str]:
    """Parse V4A patch into ops. Returns (ops, error). Never raises."""
    ops: list = []
    cur = None
    cur_hunk = None
    for raw in (patch or "").splitlines():
        if raw.startswith("*** Add File:"):
            if cur:
                ops.append(cur)
            cur = {"op": "add", "path": raw[len("*** Add File:"):].strip(), "lines": []}
            cur_hunk = None
        elif raw.startswith("*** Update File:"):
            if cur:
                ops.append(cur)
            cur = {"op": "update", "path": raw[len("*** Update File:"):].strip(), "hunks": []}
            cur_hunk = None
        elif raw.startswith("*** Delete File:"):
            if cur:
                ops.append(cur)
            cur = {"op": "delete", "path": raw[len("*** Delete File:"):].strip()}
            cur_hunk = None
        elif raw.startswith("@@"):
            if not cur or cur["op"] != "update":
                return [], "ERROR: '@@' anchor outside an Update File block."
            cur_hunk = {"anchor": raw[2:].strip(), "ctx": [], "old": [], "new": []}
            cur["hunks"].append(cur_hunk)
        elif raw.startswith("+") and cur and cur["op"] == "add":
            cur["lines"].append(raw[1:])
        elif cur and cur["op"] == "update" and cur_hunk is not None and raw[:1] in (" ", "-", "+"):
            if raw.startswith(" "):
                cur_hunk["ctx"].append(raw[1:])
                cur_hunk["old"].append(raw[1:])
                cur_hunk["new"].append(raw[1:])
            elif raw.startswith("-"):
                cur_hunk["old"].append(raw[1:])
            else:
                cur_hunk["new"].append(raw[1:])
        elif raw.strip() == "" and cur and cur["op"] == "add":
            cur["lines"].append("")
        elif raw.strip() == "" and cur and cur["op"] == "update":
            # blank line closes the current hunk (separator between hunks).
            # A following hunk without @@ continues positionally, so split
            # hunks still apply in order.
            if cur_hunk is not None and (cur_hunk["old"] or cur_hunk["new"]):
                cur_hunk = None
            continue
        elif raw.strip() == "":
            continue
        else:
            if cur and cur["op"] == "add":
                cur["lines"].append(raw)
            elif (cur and cur["op"] == "update" and cur_hunk is None
                    and raw[:1] in (" ", "-", "+")):
                # continuation after a blank-line hunk split: new positional
                # hunk. Checked BEFORE the bare-anchor fallback below —
                # prefixed lines are hunk content, never anchors.
                cur_hunk = {"anchor": "", "ctx": [], "old": [], "new": []}
                cur["hunks"].append(cur_hunk)
                if raw.startswith(" "):
                    cur_hunk["ctx"].append(raw[1:])
                    cur_hunk["old"].append(raw[1:])
                    cur_hunk["new"].append(raw[1:])
                elif raw.startswith("-"):
                    cur_hunk["old"].append(raw[1:])
                else:
                    cur_hunk["new"].append(raw[1:])
            elif cur and cur["op"] == "update" and cur_hunk is None:
                # bare context line before any @@ — treat as anchor
                cur_hunk = {"anchor": raw.strip(), "ctx": [], "old": [], "new": []}
                cur["hunks"].append(cur_hunk)
            else:
                return [], f"ERROR: cannot parse patch line: {raw[:120]}"
    if cur:
        ops.append(cur)
    if not ops:
        return [], "ERROR: empty patch."
    for op in ops:
        if not op.get("path"):
            return [], "ERROR: patch block missing a path."
        if op["op"] == "update" and not op.get("hunks"):
            return [], f"ERROR: empty update hunk for {op['path']}."
    return ops, ""


def _apply_hunks(lines: list[str], hunks: list, fname: str) -> tuple[list[str] | None, str]:
    """Apply hunks sequentially in memory. Returns (new_lines, error)."""
    cur = list(lines)
    pos = 0
    for hi, h in enumerate(hunks, 1):
        anchor = (h.get("anchor") or "").strip()
        start = pos
        if anchor:
            found = -1
            for i in range(pos, len(cur)):
                if cur[i].strip() == anchor:
                    found = i
                    break
            if found < 0:
                for i in range(0, pos):
                    if cur[i].strip() == anchor:
                        found = i
                        break
            if found < 0:
                return None, (f"ERROR: {fname} hunk {hi}: anchor not found: {anchor[:120]}")
            start = found + 1
        old, new = h["old"], h["new"]
        if not old and not new:
            return None, f"ERROR: {fname} hunk {hi}: empty hunk."
        # locate `old` block at/after start (drift-tolerant ±20 like patchwise)
        at = -1
        for i in range(max(0, start - 20), min(len(cur), start + 21) - len(old) + 1):
            if cur[i:i + len(old)] == old:
                if at >= 0:
                    return None, (f"ERROR: {fname} hunk {hi}: pattern matches "
                                  f"multiple locations; add an @@ anchor.")
                at = i
        if at < 0:
            # full-file search before giving up
            for i in range(0, len(cur) - len(old) + 1):
                if cur[i:i + len(old)] == old:
                    if at >= 0:
                        return None, (f"ERROR: {fname} hunk {hi}: pattern matches "
                                      f"multiple locations; add an @@ anchor.")
                    at = i
        if at < 0:
            return None, (f"ERROR: {fname} hunk {hi}: context does not match "
                          f"the file (old: {old[0][:120] if old else ''}).")
        cur = cur[:at] + new + cur[at + len(old):]
        pos = at + len(new)
    return cur, ""


@_locked
def fs_apply_patch(patch: str, dry_run: bool = False) -> str:
    if not (patch or "").strip():
        return "ERROR: 'patch' is required."
    ops, err = _parse_v4a(patch)
    if err:
        return err
    # Phase 1: validate everything in memory.
    planned: list[tuple[Path, str, str, str]] = []  # path, old, new, label
    for op in ops:
        p = resolve(op["path"])
        if op["op"] == "add":
            if p.exists():
                return (f"ERROR: Add File refused, already exists: {_display(p)} "
                        f"(use Update File).")
            planned.append((p, "", "\n".join(op["lines"]) + "\n", "Created"))
        elif op["op"] == "delete":
            if not p.is_file():
                return f"ERROR: Delete File not found: {_display(p)}"
            planned.append((p, "__DELETE__", "", "Deleted"))
        else:
            if not p.is_file():
                return f"ERROR: Update File not found: {_display(p)}"
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                return f"ERROR: cannot read {_display(p)}: {exc}"
            trailing = content.endswith("\n")
            lines = content.splitlines()
            new_lines, herr = _apply_hunks(lines, op["hunks"], p.name)
            if herr:
                return herr
            new_content = "\n".join(new_lines or [])
            if trailing:
                new_content += "\n"
            if new_content == content:
                return f"ERROR: patch makes no changes to {_display(p)}."
            planned.append((p, content, new_content, "Patched"))
    if dry_run:
        parts = [f"[DRY RUN] Patch validates: {len(planned)} file(s)"]
        for p, old, new, label in planned:
            parts.append(f"--- {label} {_display(p)} ---")
            parts.append(_diff(old if old != "__DELETE__" else "", new, p.name))
        return truncate("\n".join(parts))
    # Phase 2: apply (backups first so any I/O failure still allows undo).
    undo: list[tuple[Path, bytes | None]] = []
    try:
        for p, old, _, _ in planned:
            if old == "":
                undo.append((p, None))  # add: rollback unlinks
                continue
            _create_backup(p, "patch")
            try:
                undo.append((p, p.read_bytes()))
            except Exception:
                undo.append((p, None))
        results = []
        for p, old, new, label in planned:
            if old == "__DELETE__":
                p.unlink()
            else:
                atomic_write(p, new)
            _audit("fs_apply_patch", f"{label} {_display(p)}")
            results.append(f"{label} {_display(p)}")
        return "Patch applied atomically: " + "; ".join(results)
    except Exception as exc:
        for p, data in reversed(undo):
            try:
                if data is None:
                    if p.is_file():
                        p.unlink()
                else:
                    atomic_write_bytes(p, data)
            except Exception:
                pass
        return (f"ERROR: patch apply failed and rolled back "
                f"(backups kept under .zumba_backups): {exc}")


def _missing_parents(target: Path) -> list[str]:
    """Ancestors of target that do not exist yet (deepest last)."""
    out: list[str] = []
    for parent in [target.parent, *target.parent.parents]:
        if parent.exists():
            break
        out.append(str(parent))
    return out


@_locked
def fs_batch(operations: list, dry_run: bool = False) -> str:
    """Transactional multi-op: write/edit/insert/replace_lines/delete/move/mkdir."""
    if not isinstance(operations, list) or not operations:
        return "ERROR: 'operations' must be a non-empty list."
    if len(operations) > 100:
        return "ERROR: too many operations (max 100)."
    snaps: dict[Path, bytes | None] = {}
    journal: list[tuple[str, str, str]] = []

    def remember(p: Path) -> None:
        if p not in snaps:
            snaps[p] = p.read_bytes() if p.is_file() else None

    def rollback() -> None:
        # reverse structural ops first (moves back, created dirs + parents
        # removed if empty, deleted dirs recreated), then restore file bytes.
        for kind, a, b in reversed(journal):
            try:
                if kind == "move":
                    if Path(b).exists():
                        Path(a).parent.mkdir(parents=True, exist_ok=True)
                        os.replace(str(b), str(a))
                elif kind == "mkdir":
                    try:
                        Path(a).rmdir()
                    except Exception:
                        pass
                    try:
                        for parent in reversed(json.loads(b or "[]")):
                            try:
                                Path(parent).rmdir()
                            except Exception:
                                pass
                    except Exception:
                        pass
                elif kind == "rmdir":
                    Path(a).mkdir(parents=True, exist_ok=True)
                elif kind == "parents":
                    try:
                        for parent in reversed(json.loads(b or "[]")):
                            try:
                                Path(parent).rmdir()
                            except Exception:
                                pass
                    except Exception:
                        pass
            except Exception:
                pass
        for p, data in snaps.items():
            try:
                if data is None:
                    if p.is_file():
                        p.unlink()
                else:
                    atomic_write_bytes(p, data)
            except Exception:
                pass

    results: list[str] = []
    try:
        for i, op in enumerate(operations, 1):
            if not isinstance(op, dict):
                raise ValueError(f"operation {i}: must be an object")
            action = str(op.get("action", "")).lower().strip()
            if action == "write":
                p = resolve(str(op.get("path", "")))
                remember(p)
                content = str(op.get("content", ""))
                if not dry_run:
                    if p.is_file():
                        _create_backup(p, "batch")
                    else:
                        journal.append(("parents", str(p), json.dumps(_missing_parents(p))))
                    atomic_write(p, content)
                results.append(f"{i}. write {_display(p)}")
            elif action == "edit":
                p = resolve(str(op.get("path", "")))
                if not p.is_file():
                    raise ValueError(f"operation {i}: file not found: {op.get('path')}")
                remember(p)
                content = p.read_text(encoding="utf-8", errors="replace")
                old = str(op.get("old_text", ""))
                if content.count(old) != 1:
                    raise ValueError(f"operation {i}: old_text matches {content.count(old)} locations in {p.name}")
                new_content = content.replace(old, str(op.get("new_text", "")), 1)
                if not dry_run:
                    _create_backup(p, "batch")
                    atomic_write(p, new_content)
                results.append(f"{i}. edit {_display(p)}")
            elif action == "insert":
                p = resolve(str(op.get("path", "")))
                if not p.is_file():
                    raise ValueError(f"operation {i}: file not found: {op.get('path')}")
                remember(p)
                lines, trailing, nl = _read_lines(p)
                ln = int(op.get("line", 0))
                pos = str(op.get("position", "after")).lower()
                at = ln - 1 if pos == "before" else ln
                if not 0 <= at <= len(lines):
                    raise ValueError(f"operation {i}: invalid line {ln}")
                new_content = _join(lines[:at] + str(op.get("text", "")).splitlines() + lines[at:], trailing, nl)
                if not dry_run:
                    _create_backup(p, "batch")
                    atomic_write(p, new_content)
                results.append(f"{i}. insert {_display(p)}:{ln}")
            elif action == "replace_lines":
                p = resolve(str(op.get("path", "")))
                if not p.is_file():
                    raise ValueError(f"operation {i}: file not found: {op.get('path')}")
                remember(p)
                lines, trailing, nl = _read_lines(p)
                s, e = int(op.get("start", 0)), int(op.get("end", 0))
                if s < 1 or e < s or e > len(lines):
                    raise ValueError(f"operation {i}: invalid range {s}-{e}")
                new_content = _join(lines[:s - 1] + str(op.get("new_text", "")).splitlines() + lines[e:], trailing, nl)
                if not dry_run:
                    _create_backup(p, "batch")
                    atomic_write(p, new_content)
                results.append(f"{i}. replace_lines {_display(p)}:{s}-{e}")
            elif action == "delete":
                p = resolve(str(op.get("path", "")))
                if not p.exists():
                    raise ValueError(f"operation {i}: not found: {op.get('path')}")
                if p.is_dir() and any(p.iterdir()):
                    raise ValueError(f"operation {i}: directory not empty: {op.get('path')}")
                remember(p)
                if not dry_run:
                    if p.is_dir():
                        journal.append(("rmdir", str(p), ""))
                        p.rmdir()
                    else:
                        p.unlink()
                results.append(f"{i}. delete {_display(p)}")
            elif action == "move":
                s, d = resolve(str(op.get("source", ""))), resolve(str(op.get("destination", "")))
                if not s.exists():
                    raise ValueError(f"operation {i}: source not found: {op.get('source')}")
                if d.exists() and not op.get("confirm"):
                    raise ValueError(f"operation {i}: destination exists: {op.get('destination')} (confirm=true required to overwrite)")
                remember(s)
                remember(d)
                if not dry_run:
                    journal.append(("move", str(s), str(d)))
                    journal.append(("parents", str(d), json.dumps(_missing_parents(d))))
                    d.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(str(s), str(d))
                results.append(f"{i}. move {_display(s)} -> {_display(d)}")
            elif action in ("mkdir", "create_directory"):
                p = resolve(str(op.get("path", "")))
                if not dry_run:
                    if not p.exists():
                        journal.append(("mkdir", str(p), json.dumps(_missing_parents(p))))
                    p.mkdir(parents=True, exist_ok=True)
                results.append(f"{i}. mkdir {_display(p)}")
            else:
                raise ValueError(f"operation {i}: unsupported action {action!r}")
    except Exception as exc:
        if not dry_run:
            rollback()
        return f"ERROR: batch failed and rolled back: {exc}"
    if not dry_run:
        for line in results:
            _audit("fs_batch", line)
    tag = "[DRY RUN] Batch validates" if dry_run else "Batch applied"
    return f"{tag}: {len(operations)} operation(s)\n" + "\n".join(results)


def fs_undo(path: str, dry_run: bool = False) -> str:
    if not (path or "").strip():
        return "ERROR: 'path' is required."
    p = resolve(path)
    root = p.parent / ".zumba_backups"
    cands = sorted(root.glob(f"{p.name}.*.bak"), key=lambda x: x.name, reverse=True) if root.is_dir() else []
    if not cands:
        return f"ERROR: no backup found for {_display(p)}."
    latest = cands[0]
    try:
        if dry_run:
            cur = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
            old = latest.read_text(encoding="utf-8", errors="replace")
            return f"[DRY RUN] Would restore {_display(p)} from {_display(latest)}:\n{_diff(cur, old, p.name)}"
        if p.is_file():
            _create_backup(p, "before_undo")
        shutil.copy2(latest, p)
    except Exception as exc:
        return f"ERROR: undo failed: {exc}"
    _audit("fs_undo", f"restored {_display(p)} from {_display(latest)}")
    return f"Restored {_display(p)} from backup {_display(latest)}."


def fs_mkdir(path: str) -> str:
    if not (path or "").strip():
        return "ERROR: 'path' is required."
    p = resolve(path)
    if p.exists():
        return f"ERROR: already exists: {_display(p)}" if not p.is_dir() else f"Directory already exists: {_display(p)}"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        return f"ERROR: mkdir failed: {exc}"
    _audit("fs_mkdir", str(_display(p)))
    return f"Created directory {_display(p)}."


def fs_move(source: str, destination: str, confirm: bool = False) -> str:
    if not (source or "").strip() or not (destination or "").strip():
        return "ERROR: 'source' and 'destination' are required."
    s, d = resolve(source), resolve(destination)
    if not s.exists():
        return f"ERROR: source not found: {source}"
    if d.exists() and not confirm:
        return (f"ERROR: destination exists: {_display(d)}. "
                f"Pass confirm=true to overwrite.")
    try:
        d.parent.mkdir(parents=True, exist_ok=True)
        over = " (overwrote existing)" if d.exists() else ""
        os.replace(str(s), str(d))
    except Exception as exc:
        return f"ERROR: move failed: {exc}"
    _audit("fs_move", f"{_display(s)} -> {_display(d)}")
    return f"Moved {_display(s)} -> {_display(d)}{over}."


def fs_delete(path: str, confirm: bool = False) -> str:
    if not (path or "").strip():
        return "ERROR: 'path' is required."
    if not confirm:
        return "ERROR: confirm=true is required to delete."
    p = resolve(path)
    if not p.exists():
        return f"ERROR: not found: {path}"
    if p.is_dir() and any(p.iterdir()):
        return f"ERROR: directory not empty: {_display(p)} (delete contents first)."
    try:
        if p.is_dir():
            p.rmdir()
        else:
            p.unlink()
    except Exception as exc:
        return f"ERROR: delete failed: {exc}"
    _audit("fs_delete", str(_display(p)))
    return f"Deleted {_display(p)}."

