import json
import os
import shutil
import subprocess
import sys
import threading
import time
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import realtime_search


def _tokenize(text: str) -> List[str]:
    cleaned = text.lower()
    for ch in ",.;:!?()[]{}<>|/\\\t\r\n\"'":
        cleaned = cleaned.replace(ch, " ")
    return [t for t in cleaned.split(" ") if t]


def _score(query: str, title: str, snippet: str = "", duration_sec: Optional[int] = None) -> float:
    q = query.strip().lower()
    blob = f"{title} {snippet}".strip().lower()
    if not q or not blob:
        return 0.0
    seq = SequenceMatcher(None, q, blob).ratio()
    q_tokens = set(_tokenize(q))
    b_tokens = set(_tokenize(blob))
    overlap = (len(q_tokens & b_tokens) / max(1, len(q_tokens))) if q_tokens else 0.0
    penalty_terms = {"slowed", "reverb", "nightcore", "sped", "8d", "bass boosted"}
    # Only penalize unwanted variants — remix/lofi/live are often what users WANT
    soft_penalty_terms = {"remix", "lofi", "live", "cover", "acoustic"}
    penalty = 0.0
    for t in penalty_terms:
        if t in blob and t not in q:
            penalty += 0.10
    for t in soft_penalty_terms:
        if t in blob and t not in q:
            penalty += 0.03  # mild preference for original, but don't kill remixes
    if "official" in blob:
        penalty -= 0.05
    # Boost: user explicitly requested a variant (e.g. "lofi remix")
    for t in soft_penalty_terms | penalty_terms:
        if t in q and t in blob:
            penalty -= 0.04  # reward matching user intent
    if duration_sec is not None and duration_sec > 0:
        if duration_sec < 60 and "short" not in q and "reel" not in q:
            penalty += 0.25
        if duration_sec < 120 and "full" in q:
            penalty += 0.12
    return max(0.0, ((0.62 * overlap) + (0.38 * seq)) - penalty)


def _has_yt_dlp() -> bool:
    if shutil.which("yt-dlp"):
        return True
    probe = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], capture_output=True, text=True, shell=False, check=False)
    return probe.returncode == 0


def _ytdlp_argv() -> List[str]:
    bin_path = shutil.which("yt-dlp")
    if bin_path:
        return [bin_path]
    return [sys.executable, "-m", "yt_dlp"]


def _search_with_ytdlp(query: str, max_results: int) -> List[Dict[str, Any]]:
    limit = max(1, min(int(max_results), 20))
    yq = f"ytsearch{limit}:{query} official audio"
    argv = _ytdlp_argv() + [
        "--dump-single-json",
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        yq,
    ]
    startup_timeout_sec = float(os.environ.get("FFPLAY_TIMEOUT", "5"))
    proc = subprocess.run(argv, capture_output=True, text=True, shell=False, check=False, timeout=max(startup_timeout_sec, 45))
    if proc.returncode != 0:
        return []
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return []
    entries = payload.get("entries", []) if isinstance(payload, dict) else []
    if not isinstance(entries, list):
        return []
    out: List[Dict[str, Any]] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        vid = str(e.get("id", "")).strip()
        title = str(e.get("title", "")).strip()
        uploader = str(e.get("uploader", "")).strip()
        duration = e.get("duration")
        webpage = str(e.get("webpage_url", "")).strip()
        url = webpage or (f"https://www.youtube.com/watch?v={vid}" if vid else "")
        if not title or not url:
            continue
        snippet = uploader
        out.append(
            {
                "title": title,
                "url": url,
                "domain": "youtube.com",
                "snippet": snippet,
                "uploader": uploader,
                "duration_sec": int(duration) if isinstance(duration, (int, float)) and duration > 0 else None,
                "video_id": vid,
            }
        )
    return out


def _state_path(workspace_root: Path) -> Path:
    return workspace_root / ".ankita" / "music" / "player.json"


def _log_path(workspace_root: Path) -> Path:
    return workspace_root / ".ankita" / "music" / "player.log"


def _load_state(workspace_root: Path) -> Dict[str, Any]:
    path = _state_path(workspace_root)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(workspace_root: Path, payload: Dict[str, Any]) -> None:
    path = _state_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _read_tail(path: Path, max_chars: int = 1200) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    if len(text) <= max_chars:
        return text.strip()
    return text[-max_chars:].strip()


def _start_and_verify(
    argv: List[str],
    workspace_root: Path,
    startup_timeout_sec: float = 2.5,
) -> Dict[str, Any]:
    log_path = _log_path(workspace_root)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fp:
        fp.write("\n=== launch ===\n")
        fp.write("cmd: " + " ".join(argv) + "\n")
        fp.flush()
        proc = subprocess.Popen(
            argv,
            cwd=str(workspace_root),
            stdout=fp,
            stderr=fp,
            shell=False,
        )
    deadline = time.time() + max(0.5, startup_timeout_sec)
    while time.time() < deadline:
        code = proc.poll()
        if code is None:
            return {"ok": True, "pid": int(proc.pid), "log_path": str(log_path)}
        time.sleep(0.15)
    code = proc.poll()
    if code is None:
        return {"ok": True, "pid": int(proc.pid), "log_path": str(log_path)}
    return {
        "ok": False,
        "pid": int(proc.pid),
        "exit_code": int(code),
        "log_path": str(log_path),
        "log_tail": _read_tail(log_path),
    }


def search_music(query: str, max_results: int = 8) -> Dict[str, Any]:
    q = str(query or "").strip()
    if not q:
        raise ValueError("query is required")
    rows: List[Dict[str, Any]] = []
    engine = "google/duck-web"
    if _has_yt_dlp():
        yrows = _search_with_ytdlp(q, max_results=max_results)
        if yrows:
            rows = yrows
            engine = "yt-dlp-ytsearch"
    if not rows:
        base = realtime_search.search_web(f"{q} official audio music", max_results=max_results, include_urls=True)
        raw_rows = base.get("results", [])
        if isinstance(raw_rows, list):
            rows = [r for r in raw_rows if isinstance(r, dict)]
        engine = str(base.get("engine", engine))
    ranked: List[Dict[str, Any]] = []
    for row in rows:
        title = str(row.get("title", "")).strip()
        url = str(row.get("url", "")).strip()
        snippet = str(row.get("snippet", "")).strip()
        if not title or not url:
            continue
        duration_sec = int(row.get("duration_sec")) if isinstance(row.get("duration_sec"), (int, float)) else None
        score = _score(q, title, snippet, duration_sec=duration_sec)
        ranked.append(
            {
                "title": title,
                "url": url,
                "domain": str(row.get("domain", "")),
                "snippet": snippet,
                "score": round(score, 3),
                **({"uploader": row.get("uploader")} if row.get("uploader") else {}),
                **({"duration_sec": row.get("duration_sec")} if row.get("duration_sec") else {}),
                **({"video_id": row.get("video_id")} if row.get("video_id") else {}),
            }
        )
    ranked.sort(key=lambda r: float(r.get("score", 0.0)), reverse=True)
    best = ranked[0] if ranked else None
    return {
        "kind": "music_search",
        "query": q,
        "engine": engine,
        "results": ranked[: max(1, min(int(max_results), 20))],
        "best_match": best,
        "is_confident_match": bool(best and float(best.get("score", 0.0)) >= 0.62),
    }


def _build_player_command(url: str) -> Optional[List[str]]:
    mpv = shutil.which("mpv")
    vlc = shutil.which("vlc")
    ffplay = shutil.which("ffplay")
    ytdlp = shutil.which("yt-dlp")

    if ffplay and ytdlp:
        if os.name == "nt":
            # Fixed: PowerShell pipe doesn't use '& ' before the second command
            cmd = f'& "{ytdlp}" -f bestaudio -o - "{url}" | "{ffplay}" -nodisp -autoexit -loglevel error -i -'
            return ["powershell", "-NoProfile", "-Command", cmd]
        cmd = f'"{ytdlp}" -f bestaudio -o - "{url}" | "{ffplay}" -nodisp -autoexit -loglevel error -i -'
        return ["/bin/sh", "-lc", cmd]
    if mpv:
        return [mpv, "--no-video", "--really-quiet", url]
    if vlc:
        return [vlc, "--intf", "dummy", "--play-and-exit", url]
    return None


def _run_yt_dlp_download(url: str, workspace_root: Path) -> Optional[str]:
    temp_dir = workspace_root / ".ankita" / "music" / "downloads"
    temp_dir.mkdir(parents=True, exist_ok=True)
    out_tpl = str(temp_dir / "track-%(id)s.%(ext)s")

    ytdlp_argv = _ytdlp_argv()

    argv = ytdlp_argv + [
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        "-f",
        "bestaudio[ext=m4a]/bestaudio[acodec*=mp4a]/bestaudio",
        "-o",
        out_tpl,
        "--print",
        "after_move:filepath",
        url,
    ]
    proc = subprocess.run(argv, cwd=str(workspace_root), capture_output=True, text=True, shell=False, check=False, timeout=300)
    if proc.returncode != 0:
        return None
    lines = [ln.strip() for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if not lines:
        return None
    file_path = lines[-1]
    return file_path if Path(file_path).exists() else None


def _launch_windows_wmp_headless(local_file: str, workspace_root: Path) -> Optional[int]:
    safe = str(local_file).replace("'", "''")
    script = (
        "$ErrorActionPreference='SilentlyContinue'; "
        "$p=New-Object -ComObject WMPlayer.OCX; "
        f"$p.URL='{safe}'; "
        "$p.settings.autoStart=$true; "
        "$p.controls.play(); "
        "while($true){ "
        "$s=$p.playState; "
        "if($s -eq 1 -or $s -eq 8 -or $s -eq 10){ break }; "
        "Start-Sleep -Milliseconds 500 "
        "}"
    )
    res = _start_and_verify(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
        workspace_root=workspace_root,
        startup_timeout_sec=3.0,
    )
    if not bool(res.get("ok")):
        return None
    return int(res.get("pid", 0) or 0)


def _resolve_wmplayer_exe() -> Optional[str]:
    direct = shutil.which("wmplayer")
    if direct:
        return direct
    pf = os.environ.get("ProgramFiles", "")
    pfx86 = os.environ.get("ProgramFiles(x86)", "")
    candidates = [
        Path(pf) / "Windows Media Player" / "wmplayer.exe",
        Path(pfx86) / "Windows Media Player" / "wmplayer.exe",
    ]
    for c in candidates:
        try:
            if c.exists():
                return str(c)
        except Exception:
            continue
    return None


def _launch_wmplayer_exe(local_file: str, workspace_root: Path) -> Optional[int]:
    exe = _resolve_wmplayer_exe()
    if not exe:
        return None
    launched = _start_and_verify(
        [exe, "/play", "/close", local_file],
        workspace_root=workspace_root,
        startup_timeout_sec=3.0,
    )
    if not bool(launched.get("ok")):
        return None
    return int(launched.get("pid", 0) or 0)


def _fallback_windows_builtin(url: str, workspace_root: Path) -> Optional[Dict[str, Any]]:
    if os.name != "nt":
        return None
    local_file = _run_yt_dlp_download(url, workspace_root=workspace_root)
    if not local_file:
        return None
    # Prefer native wmplayer executable for audible playback reliability.
    pid = _launch_wmplayer_exe(local_file=local_file, workspace_root=workspace_root)
    if pid:
        return {"pid": pid, "source_url": url, "local_file": local_file, "launcher": "wmplayer-exe"}
    # Fallback to COM automation when wmplayer executable path is unavailable.
    pid2 = _launch_windows_wmp_headless(local_file=local_file, workspace_root=workspace_root)
    if pid2:
        return {"pid": pid2, "source_url": url, "local_file": local_file, "launcher": "wmp-com"}
    return None


def _queue_path(workspace_root: Path) -> Path:
    return workspace_root / ".ankita" / "music" / "queue.json"


_queue_lock = threading.Lock()


def _load_queue(workspace_root: Path) -> List[Dict[str, Any]]:
    path = _queue_path(workspace_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_queue(workspace_root: Path, queue: List[Dict[str, Any]]) -> None:
    path = _queue_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: write to temp file then rename to avoid partial reads
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(queue, ensure_ascii=True, indent=2), encoding="utf-8")
    tmp.replace(path)


def queue_music(workspace_root: Path, query: str) -> Dict[str, Any]:
    """Add a song to the music queue without playing it immediately."""
    q = str(query or "").strip()
    if not q:
        raise ValueError("query is required")
    found = search_music(q, max_results=5)
    
    # UPGRADE: Try all candidates down to 0.35 score instead of failing on first low match
    best = None
    candidates = found.get("results", [])
    for candidate in candidates:
        score = float(candidate.get("score", 0.0))
        if score >= 0.35:  # Lower threshold from 0.62 to 0.35
            best = candidate
            break
    
    if not best:
        candidate_names = [str(r.get("title", "")) for r in candidates[:3]]
        raise RuntimeError(f"No confident match found (all < 0.35). Top: {' | '.join(candidate_names)}")
    with _queue_lock:
        queue = _load_queue(workspace_root)
        entry = {
            "query": q,
            "title": str(best.get("title", "")),
            "url": str(best.get("url", "")),
            "score": float(best.get("score", 0.0)),
            "engine": found.get("engine", ""),
        }
        queue.append(entry)
        _save_queue(workspace_root, queue)
    return {
        "kind": "music_queue_add",
        "added": entry,
        "queue_length": len(queue),
        "position": len(queue),
    }


def show_queue(workspace_root: Path) -> Dict[str, Any]:
    """Show current music queue."""
    queue = _load_queue(workspace_root)
    return {
        "kind": "music_queue_show",
        "queue": queue,
        "queue_length": len(queue),
    }


def clear_queue(workspace_root: Path) -> Dict[str, Any]:
    """Clear the music queue."""
    _save_queue(workspace_root, [])
    return {"kind": "music_queue_clear", "cleared": True}


def play_next_in_queue(workspace_root: Path) -> Dict[str, Any]:
    """Play the next song in the queue."""
    queue = _load_queue(workspace_root)
    if not queue:
        return {"kind": "music_queue_next", "played": False, "reason": "queue_empty"}
    next_track = queue.pop(0)
    _save_queue(workspace_root, queue)
    url = str(next_track.get("url", ""))
    title = str(next_track.get("title", ""))
    if not url:
        return {"kind": "music_queue_next", "played": False, "reason": "no_url_in_track"}

    stop_music(workspace_root)
    cmd = _build_player_command(url)
    if cmd:
        launched = _start_and_verify(cmd, workspace_root=workspace_root, startup_timeout_sec=3.0)
        if launched.get("ok"):
            payload = {
                "pid": int(launched["pid"]),
                "query": next_track.get("query", ""),
                "title": title,
                "url": url,
                "cmd": cmd,
                "log_path": launched.get("log_path", ""),
                "engine": next_track.get("engine", ""),
            }
            _save_state(workspace_root, payload)
            return {
                "kind": "music_queue_next",
                "played": True,
                "pid": int(launched["pid"]),
                "title": title,
                "url": url,
                "remaining_in_queue": len(queue),
            }

    fallback = _fallback_windows_builtin(url=url, workspace_root=workspace_root)
    if fallback:
        payload = {
            "pid": fallback["pid"],
            "query": next_track.get("query", ""),
            "title": title,
            "url": url,
            "local_file": fallback["local_file"],
            "launcher": fallback["launcher"],
            "engine": next_track.get("engine", ""),
        }
        _save_state(workspace_root, payload)
        return {
            "kind": "music_queue_next",
            "played": True,
            "pid": fallback["pid"],
            "title": title,
            "url": url,
            "launcher": fallback["launcher"],
            "remaining_in_queue": len(queue),
        }

    return {"kind": "music_queue_next", "played": False, "reason": "no_player_available", "title": title}


def stop_music(workspace_root: Path) -> Dict[str, Any]:
    state = _load_state(workspace_root)
    pid = int(state.get("pid", 0) or 0)
    if pid <= 0:
        return {"kind": "music_stop", "stopped": False, "reason": "no_active_player"}
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False, capture_output=True, text=True)
        else:
            os.kill(pid, 15)
        _save_state(workspace_root, {})
        return {"kind": "music_stop", "stopped": True, "pid": pid}
    except Exception as err:
        return {"kind": "music_stop", "stopped": False, "pid": pid, "error": str(err)}


def current_music(workspace_root: Path) -> Dict[str, Any]:
    state = _load_state(workspace_root)
    pid = int(state.get("pid", 0) or 0)
    if pid <= 0:
        return {"kind": "music_current", "playing": False}
    return {
        "kind": "music_current",
        "playing": True,
        "pid": pid,
        "title": str(state.get("title", "")),
        "query": str(state.get("query", "")),
        "url": str(state.get("url", "")),
        "launcher": str(state.get("launcher", "")),
        "engine": str(state.get("engine", "")),
    }


def play_music(workspace_root: Path, query: str, headless: bool = True, stop_current: bool = True) -> Dict[str, Any]:
    if not headless:
        raise ValueError("only headless mode is supported")
    if stop_current:
        stop_music(workspace_root)
    found = search_music(query, max_results=8)
    candidates = found.get("results", [])
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("no music candidates found")
    
    # UPGRADE: Lower confidence threshold from 0.62 to 0.35 for better regional/niche music support
    # Try all candidates down to score 0.35 instead of failing on first low-confidence match
    best = found.get("best_match")
    if not best:
        raise RuntimeError("no best match found")
    
    # If confidence is low (< 0.62), try appending "song" or language hints for better results
    if float(best.get("score", 0.0)) < 0.62:
        # Try enhanced search with "song" appended
        enhanced_query = f"{query} song"
        enhanced_found = search_music(enhanced_query, max_results=5)
        enhanced_best = enhanced_found.get("best_match")
        if enhanced_best and float(enhanced_best.get("score", 0.0)) > float(best.get("score", 0.0)):
            # Use enhanced result if it's better
            found = enhanced_found
            candidates = found.get("results", [])
            best = enhanced_best

    errors: List[str] = []
    for row in candidates[:5]:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title", "")).strip()
        url = str(row.get("url", "")).strip()
        score = float(row.get("score", 0.0) or 0.0)
        # UPGRADE: Accept scores down to 0.35 (was 0.40) for better coverage
        if not title or not url or score < 0.35:
            continue

        cmd = _build_player_command(url)
        if cmd:
            launched = _start_and_verify(cmd, workspace_root=workspace_root, startup_timeout_sec=3.0)
            if not bool(launched.get("ok")):
                errors.append(
                    f"candidate failed: {title} (exit={launched.get('exit_code')}, log={launched.get('log_tail', '')})"
                )
                continue
            payload = {
                "pid": int(launched["pid"]),
                "query": query,
                "title": title,
                "url": url,
                "cmd": cmd,
                "log_path": launched.get("log_path", ""),
                "engine": found.get("engine", ""),
            }
            _save_state(workspace_root, payload)
            return {
                "kind": "music_play",
                "launched": True,
                "pid": int(launched["pid"]),
                "title": title,
                "url": url,
                "score": score,
                "headless": True,
                "engine": found.get("engine", ""),
            }

        fallback = _fallback_windows_builtin(url=url, workspace_root=workspace_root)
        if fallback:
            payload = {
                "pid": fallback["pid"],
                "query": query,
                "title": title,
                "url": url,
                "local_file": fallback["local_file"],
                "launcher": fallback["launcher"],
                "engine": found.get("engine", ""),
            }
            _save_state(workspace_root, payload)
            return {
                "kind": "music_play",
                "launched": True,
                "pid": fallback["pid"],
                "title": title,
                "url": url,
                "score": score,
                "headless": True,
                "launcher": fallback["launcher"],
                "engine": found.get("engine", ""),
            }

        errors.append(f"candidate failed: {title}")

    raise RuntimeError(
        "unable to launch headless music playback for top matches. "
        "Install one player stack: (yt-dlp+ffplay) or mpv or vlc. "
        + ("; ".join(errors[:3]) if errors else "")
    )
