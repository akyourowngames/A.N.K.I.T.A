from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import webbrowser
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlparse


@dataclass(frozen=True)
class MusicTrack:
    title: str
    webpage_url: str
    stream_url: str = ""
    duration: int | None = None
    artist: str = ""
    extractor: str = ""
    http_headers: dict[str, str] = field(default_factory=dict)
    source_query: str = ""


class MusicTool:
    name = "music"
    description = "Searches and plays requested music with yt-dlp and a local player."

    def __init__(
        self,
        resolver: Callable[[str], MusicTrack] | None = None,
        process_factory: Callable[..., subprocess.Popen[Any]] | None = None,
    ) -> None:
        self._resolver = resolver
        self._process_factory = process_factory or subprocess.Popen
        self._queue: deque[MusicTrack] = deque()
        self._lock = threading.RLock()
        self._process: subprocess.Popen[Any] | None = None
        self._current: MusicTrack | None = None
        self._current_backend = ""
        self._paused = False
        self._manual_stop = False
        self._monitor_thread: threading.Thread | None = None
        self._last_error = ""

    def run(
        self,
        action: str = "play",
        query: str = "",
        url: str = "",
        player: str = "",
        clear_queue: bool | None = None,
    ) -> str:
        action = (action or "play").strip().lower().replace("-", "_")
        query = (query or url or "").strip()

        if action in {"play", "start", "listen"}:
            return self._play_now(query, player=player, clear_queue=bool(clear_queue))
        if action in {"queue", "add"}:
            return self._queue_track(query, player=player)
        if action in {"stop", "quit", "close"}:
            return self._stop(clear_queue=True)
        if action == "pause":
            return self._pause()
        if action in {"resume", "unpause"}:
            return self._resume()
        if action in {"next", "skip"}:
            return self._next(player=player)
        if action in {"status", "now_playing"}:
            return self._status()
        if action in {"clear", "clear_queue"}:
            return self._clear_queue()

        return f"FAILED: unsupported music action '{action}'."

    def _play_now(self, query: str, *, player: str = "", clear_queue: bool = False) -> str:
        if not query:
            return "FAILED: Tell me the song, artist, playlist, or URL to play."

        try:
            track = self._resolve_track(query)
        except Exception as error:
            return f"FAILED: music lookup failed: {error}"

        with self._lock:
            if clear_queue:
                self._queue.clear()
            self._stop_locked(clear_queue=False)
            start_result = self._start_track_locked(track, player=player)
            if start_result.startswith("FAILED:"):
                return start_result
            return start_result

    def _queue_track(self, query: str, *, player: str = "") -> str:
        if not query:
            return "FAILED: Tell me what to add to the music queue."

        try:
            track = self._resolve_track(query)
        except Exception as error:
            return f"FAILED: music lookup failed: {error}"

        with self._lock:
            if self._is_playing_locked():
                self._queue.append(track)
                return f"Queued: {self._track_label(track)}\nQueue size: {len(self._queue)}"
            start_result = self._start_track_locked(track, player=player)
            if start_result.startswith("FAILED:"):
                return start_result
            return start_result

    def _stop(self, *, clear_queue: bool) -> str:
        with self._lock:
            had_track = self._current is not None or self._is_playing_locked() or bool(self._queue)
            self._stop_locked(clear_queue=clear_queue)
            return "Music stopped." if had_track else "No music is currently playing."

    def _pause(self) -> str:
        with self._lock:
            if not self._is_playing_locked():
                return "No music is currently playing."
            if self._paused:
                return "Music is already paused."
            if not self._send_player_input_locked("p"):
                return f"FAILED: pause is not supported by the active music backend ({self._current_backend or 'unknown'})."
            self._paused = True
            return "Music paused."

    def _resume(self) -> str:
        with self._lock:
            if not self._is_playing_locked():
                return "No music is currently playing."
            if not self._paused:
                return "Music is already playing."
            if not self._send_player_input_locked("p"):
                return f"FAILED: resume is not supported by the active music backend ({self._current_backend or 'unknown'})."
            self._paused = False
            return "Music resumed."

    def _next(self, *, player: str = "") -> str:
        with self._lock:
            if not self._queue:
                self._stop_locked(clear_queue=False)
                return "Music stopped. Queue is empty."
            self._stop_locked(clear_queue=False)
            next_track = self._queue.popleft()
            return self._start_track_locked(next_track, player=player)

    def _status(self) -> str:
        with self._lock:
            if self._last_error:
                return f"FAILED: {self._last_error}"
            if not self._current:
                return f"No music is currently playing.\nQueue size: {len(self._queue)}"
            state = "paused" if self._paused else "playing"
            return (
                f"Now {state}: {self._track_label(self._current)}\n"
                f"Backend: {self._current_backend or 'unknown'}\n"
                f"Queue size: {len(self._queue)}"
            )

    def _clear_queue(self) -> str:
        with self._lock:
            count = len(self._queue)
            self._queue.clear()
            return f"Cleared {count} queued track{'s' if count != 1 else ''}."

    def _resolve_track(self, query: str) -> MusicTrack:
        if self._resolver is not None:
            return self._resolver(query)

        try:
            from yt_dlp import YoutubeDL
        except ImportError as error:
            raise RuntimeError("yt-dlp is not installed. Run: pip install yt-dlp") from error

        target = query if _looks_like_url(query) else f"ytsearch1:{query}"
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": os.getenv("MUSIC_FORMAT", "bestaudio/best"),
            "default_search": "ytsearch1",
            "socket_timeout": _env_int("MUSIC_YTDLP_TIMEOUT_SECONDS", 12),
        }

        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(target, download=False)

        if not isinstance(info, dict):
            raise RuntimeError("yt-dlp returned no track information.")
        if info.get("entries"):
            entries = [entry for entry in info.get("entries", []) if isinstance(entry, dict)]
            if not entries:
                raise RuntimeError("No playable search results found.")
            info = entries[0]

        return _track_from_info(info, query)

    def _start_track_locked(self, track: MusicTrack, *, player: str = "") -> str:
        self._last_error = ""
        backend, command = self._player_command(track, player=player)
        if backend == "browser":
            webbrowser.open(track.webpage_url)
            self._process = None
            self._current = track
            self._current_backend = backend
            self._paused = False
            return f"Opened music in browser: {self._track_label(track)}"

        try:
            self._manual_stop = False
            self._process = self._launch_process(command, backend)
        except Exception as error:
            return f"FAILED: could not start music player ({backend}): {error}"

        self._current = track
        self._current_backend = backend
        self._paused = False
        self._ensure_monitor_locked(player=player)
        return f"Playing: {self._track_label(track)}\nBackend: {backend}"

    def _player_command(self, track: MusicTrack, *, player: str = "") -> tuple[str, list[str] | str]:
        requested = (player or os.getenv("MUSIC_PLAYER", "auto")).strip().lower()
        if requested in {"", "auto"}:
            backends = _configured_player_order()
        else:
            backends = [requested]

        for backend in backends:
            if backend == "custom":
                command = os.getenv("MUSIC_PLAYER_COMMAND", "").strip()
                if command:
                    return backend, _format_custom_command(command, track)
                continue
            if backend == "mpv":
                executable = _find_executable("mpv")
                if executable:
                    return backend, [
                        executable,
                        "--no-video",
                        "--force-window=no",
                        "--really-quiet",
                        "--input-terminal=yes",
                        f"--ytdl-format={os.getenv('MUSIC_FORMAT', 'bestaudio/best')}",
                        track.webpage_url,
                    ]
            if backend == "ffplay":
                executable = _find_executable("ffplay")
                if executable and track.stream_url:
                    command = [executable, "-nodisp", "-autoexit", "-loglevel", "error"]
                    if track.http_headers:
                        command.extend(["-headers", _ffmpeg_headers(track.http_headers)])
                    command.append(track.stream_url)
                    return backend, command
            if backend == "vlc":
                executable = _find_executable("vlc")
                if executable:
                    return backend, [executable, "--intf", "dummy", "--play-and-exit", track.webpage_url]
            if backend == "browser":
                return backend, []

        return "browser", []

    def _launch_process(self, command: list[str] | str, backend: str) -> subprocess.Popen[Any]:
        stdin = subprocess.PIPE if backend in {"mpv", "ffplay"} else subprocess.DEVNULL
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if isinstance(command, str):
            return self._process_factory(
                command,
                shell=True,
                stdin=stdin,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
        return self._process_factory(
            command,
            stdin=stdin,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

    def _ensure_monitor_locked(self, *, player: str = "") -> None:
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            return
        self._monitor_thread = threading.Thread(target=self._monitor_loop, args=(player,), daemon=True)
        self._monitor_thread.start()

    def _monitor_loop(self, player: str) -> None:
        while True:
            with self._lock:
                process = self._process
            if process is None:
                return

            try:
                process.wait()
            except Exception as error:
                with self._lock:
                    self._last_error = f"music player exited with an error: {error}"
                return

            with self._lock:
                if process is not self._process:
                    continue
                self._process = None
                if self._manual_stop:
                    self._current = None
                    self._current_backend = ""
                    self._manual_stop = False
                    return
                if not self._queue:
                    self._current = None
                    self._current_backend = ""
                    self._paused = False
                    return
                next_track = self._queue.popleft()
                start_result = self._start_track_locked(next_track, player=player)
                if start_result.startswith("FAILED:"):
                    self._last_error = start_result.removeprefix("FAILED:").strip()
                    self._current = None
                    self._current_backend = ""
                    return

    def _stop_locked(self, *, clear_queue: bool) -> None:
        if clear_queue:
            self._queue.clear()
        process = self._process
        self._manual_stop = True
        self._process = None
        self._current = None
        self._current_backend = ""
        self._paused = False
        if process is None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _send_player_input_locked(self, value: str) -> bool:
        process = self._process
        if process is None or process.stdin is None:
            return False
        try:
            process.stdin.write((value + "\n").encode("utf-8"))
            process.stdin.flush()
            return True
        except Exception:
            return False

    def _is_playing_locked(self) -> bool:
        process = self._process
        if process is None:
            return self._current is not None and self._current_backend == "browser"
        try:
            return process.poll() is None
        except Exception:
            return False

    @staticmethod
    def _track_label(track: MusicTrack) -> str:
        parts = [track.title.strip() or "Untitled track"]
        if track.artist:
            parts.append(f"by {track.artist}")
        if track.duration:
            parts.append(f"({track.duration // 60}:{track.duration % 60:02d})")
        return " ".join(parts)


def _track_from_info(info: dict[str, Any], source_query: str) -> MusicTrack:
    title = str(info.get("title") or info.get("fulltitle") or source_query).strip()
    webpage_url = str(info.get("webpage_url") or info.get("original_url") or info.get("url") or source_query).strip()
    stream_url = str(info.get("url") or "").strip()
    duration = _optional_int(info.get("duration"))
    artist = str(info.get("artist") or info.get("creator") or info.get("uploader") or "").strip()
    extractor = str(info.get("extractor_key") or info.get("extractor") or "").strip()
    headers = info.get("http_headers") if isinstance(info.get("http_headers"), dict) else {}
    return MusicTrack(
        title=title,
        webpage_url=webpage_url,
        stream_url=stream_url,
        duration=duration,
        artist=artist,
        extractor=extractor,
        http_headers={str(key): str(value) for key, value in headers.items()},
        source_query=source_query,
    )


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _configured_player_order() -> list[str]:
    raw = os.getenv("MUSIC_PLAYER_ORDER", "mpv,ffplay,vlc,browser")
    backends = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return backends or ["mpv", "ffplay", "vlc", "browser"]


def _find_executable(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    if name == "vlc":
        for path in (
            os.path.join(os.environ.get("ProgramFiles", ""), "VideoLAN", "VLC", "vlc.exe"),
            os.path.join(os.environ.get("ProgramFiles(x86)", ""), "VideoLAN", "VLC", "vlc.exe"),
        ):
            if path and os.path.exists(path):
                return path
    return ""


def _ffmpeg_headers(headers: dict[str, str]) -> str:
    return "".join(f"{key}: {value}\r\n" for key, value in headers.items())


def _format_custom_command(command: str, track: MusicTrack) -> str:
    replacements = {
        "{url}": track.webpage_url,
        "{webpage_url}": track.webpage_url,
        "{stream_url}": track.stream_url,
        "{title}": re.sub(r"[\r\n]+", " ", track.title),
    }
    for placeholder, value in replacements.items():
        command = command.replace(placeholder, value)
    return command


def _optional_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default
