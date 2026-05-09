from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from tools.registry import ToolInputError, optional_text, require_text


DEFAULT_CONFIG_PATH = Path("config/entertainment_agent.json")
DEFAULT_LIBRARY_DIR = Path("media/music")


def entertainment_status(_params: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_config()
    index = load_index(config)
    state = load_state(config)
    player_running = process_is_running(state.get("player_pid"))
    summary = (
        f"{config.get('agent_name', 'Entertainment Agent')} ready. "
        f"{len(index.get('tracks', {}))} local tracks. "
        f"Library: {library_dir(config)}. "
        f"yt-dlp: {'available' if ytdlp_available() else 'missing'}. "
        f"Player: {'running' if player_running else 'idle'}."
    )
    return {
        "summary": summary,
        "config_path": str(config_path()),
        "library_dir": str(library_dir(config)),
        "track_count": len(index.get("tracks", {})),
        "queue": state.get("queue", []),
        "current_index": state.get("current_index", -1),
        "player_running": player_running,
        "yt_dlp_available": ytdlp_available(),
        "preferred_music_context": config.get("preferred_music_context", []),
    }


def entertainment_search(params: dict[str, Any]) -> dict[str, Any]:
    query = require_text(params, "query")
    context = optional_text(params, "context")
    limit = bounded_int(params.get("limit"), 1, 20, int(load_config().get("search_limit", 5)))
    search_text = combined_query(query, context)
    results = search_ytdlp(search_text, limit)
    if results:
        summary = f"Found {len(results)} result(s) for {search_text}. First: {results[0].get('title', 'Untitled')}"
    else:
        summary = f"Found 0 result(s) for {search_text}."
    return {"summary": summary, "query": search_text, "results": results}


def entertainment_download(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    index = load_index(config)
    query = optional_text(params, "query")
    url = optional_text(params, "url")
    context = optional_text(params, "context")
    force = bool(params.get("force", False))
    add_to_favorites = bool(params.get("add_to_favorites", False))
    playlist = optional_text(params, "playlist")
    result_index = bounded_int(params.get("result_index"), 1, 20, 1)

    if not query and not url:
        raise ToolInputError("query or url is required")

    aliases = aliases_for(query, url)
    if not force:
        cached = cached_track(index, aliases)
        if cached is not None:
            apply_track_lists(config, cached["id"], add_to_favorites, playlist)
            summary = f"Already saved: {cached.get('title', cached['id'])} -> {cached.get('file_path')}"
            return {"summary": summary, "cached": True, "track": cached}

    source_url = url
    selected_result: dict[str, Any] | None = None
    if not source_url:
        results = search_ytdlp(combined_query(query, context), max(result_index, 3))
        if len(results) < result_index:
            raise ToolInputError("No search result found to download")
        selected_result = results[result_index - 1]
        source_url = str(selected_result.get("webpage_url") or selected_result.get("url") or "")
    if not source_url:
        raise ToolInputError("No downloadable URL found")

    track = download_with_ytdlp(config, source_url, aliases, selected_result)
    upsert_track(index, track, aliases)
    save_index(config, index)
    apply_track_lists(config, track["id"], add_to_favorites, playlist)
    summary = f"Downloaded: {track.get('title', track['id'])} -> {track.get('file_path')}"
    return {"summary": summary, "cached": False, "track": track}


def entertainment_play(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    index = load_index(config)
    add_to_queue = bool(params.get("add_to_queue", False))
    track = resolve_track(config, index, params, auto_download=bool(params.get("auto_download", False)))
    if track is None:
        raise ToolInputError("Track is not downloaded yet. Use entertainment_download or set auto_download.")
    if add_to_queue:
        state = load_state(config)
        append_queue(state, track["id"])
        save_state(config, state)
        return {"summary": f"Queued: {track.get('title', track['id'])}", "track": track, "queue": state.get("queue", [])}

    state = {"queue": [track["id"]], "current_index": 0, "player_pid": None, "started_at": time.time()}
    start_queue_playback(config, index, state)
    save_state(config, state)
    return {"summary": f"Playing: {track.get('title', track['id'])}", "track": track, "queue": state.get("queue", [])}


def entertainment_queue(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    index = load_index(config)
    state = load_state(config)

    if operation == "status":
        return queue_status(config, index, state)
    if operation == "clear":
        stop_player(state)
        state = default_state()
        save_state(config, state)
        return {"summary": "Queue cleared.", "queue": []}
    if operation == "stop":
        stop_player(state)
        state["player_pid"] = None
        save_state(config, state)
        return {"summary": "Playback stopped.", "queue": state.get("queue", [])}
    if operation == "add":
        track = resolve_track(config, index, params, auto_download=bool(params.get("auto_download", False)))
        if track is None:
            raise ToolInputError("Track is not downloaded yet. Use entertainment_download or auto_download.")
        append_queue(state, track["id"])
        save_state(config, state)
        return {"summary": f"Queued: {track.get('title', track['id'])}", "queue": state.get("queue", [])}
    if operation == "play_playlist":
        playlist = require_text(params, "playlist")
        ids = playlist_ids(config, playlist)
        if not ids:
            raise ToolInputError(f"Playlist is empty or missing: {playlist}")
        stop_player(state)
        state = {"queue": ids, "current_index": 0, "player_pid": None, "started_at": time.time()}
        start_queue_playback(config, index, state)
        save_state(config, state)
        return {"summary": f"Playing playlist {playlist}: {len(ids)} track(s).", "queue": ids}
    if operation == "play":
        if not state.get("queue"):
            raise ToolInputError("Queue is empty")
        state["current_index"] = bounded_int(state.get("current_index"), 0, len(state["queue"]) - 1, 0)
        start_queue_playback(config, index, state)
        save_state(config, state)
        return queue_status(config, index, state, prefix="Playing queue.")
    if operation in {"next", "previous"}:
        if not state.get("queue"):
            raise ToolInputError("Queue is empty")
        step = 1 if operation == "next" else -1
        current = bounded_int(state.get("current_index"), 0, len(state["queue"]) - 1, 0)
        state["current_index"] = max(0, min(len(state["queue"]) - 1, current + step))
        start_queue_playback(config, index, state)
        save_state(config, state)
        return queue_status(config, index, state, prefix=f"{operation.title()} track.")
    raise ToolInputError(f"Unsupported queue operation: {operation}")


def entertainment_playlist(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    index = load_index(config)
    playlists = config.setdefault("playlists", {})
    if not isinstance(playlists, dict):
        playlists = {}
        config["playlists"] = playlists

    if operation == "list":
        names = sorted(str(name) for name in playlists)
        return {"summary": f"Playlists: {', '.join(names) if names else 'none'}", "playlists": playlists}
    if operation == "show":
        playlist = require_text(params, "playlist")
        ids = playlist_ids(config, playlist)
        tracks = [index.get("tracks", {}).get(track_id, {"id": track_id}) for track_id in ids]
        return {"summary": f"{playlist}: {len(ids)} track(s).", "playlist": playlist, "tracks": tracks}
    if operation == "create":
        playlist = require_text(params, "playlist")
        playlists.setdefault(playlist, [])
        save_config(config)
        return {"summary": f"Playlist ready: {playlist}", "playlist": playlist}
    if operation in {"add_track", "add_favorite"}:
        playlist = "favorites" if operation == "add_favorite" else require_text(params, "playlist")
        track = resolve_track(config, index, params, auto_download=bool(params.get("auto_download", False)))
        if track is None:
            raise ToolInputError("Track is not downloaded yet. Use entertainment_download or auto_download.")
        add_track_to_playlist(config, playlist, track["id"])
        if operation == "add_favorite":
            add_favorite(config, track["id"])
        save_config(config)
        return {"summary": f"Added to {playlist}: {track.get('title', track['id'])}", "track": track, "playlist": playlist}
    if operation in {"remove_track", "remove_favorite"}:
        playlist = "favorites" if operation == "remove_favorite" else require_text(params, "playlist")
        track_id = require_text(params, "track_id")
        remove_track_from_playlist(config, playlist, track_id)
        if operation == "remove_favorite":
            remove_favorite(config, track_id)
        save_config(config)
        return {"summary": f"Removed from {playlist}: {track_id}", "playlist": playlist}
    if operation == "play":
        playlist = require_text(params, "playlist")
        return entertainment_queue({"operation": "play_playlist", "playlist": playlist})
    raise ToolInputError(f"Unsupported playlist operation: {operation}")


def entertainment_config(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    if operation == "get":
        return {"summary": f"Entertainment config: {config_path()}", "config": config}
    if operation == "update":
        values = params.get("values", {})
        if not isinstance(values, dict):
            raise ToolInputError("values must be an object")
        merge_config(config, values)
        save_config(config)
        return {"summary": f"Updated entertainment config: {config_path()}", "config": config}
    raise ToolInputError(f"Unsupported config operation: {operation}")


def config_path() -> Path:
    value = os.environ.get("JARVIS_ENTERTAINMENT_CONFIG", "").strip()
    return Path(value) if value else DEFAULT_CONFIG_PATH


def load_config() -> dict[str, Any]:
    path = config_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            ensure_config_shape(data)
            return data
    data = default_config()
    save_config(data)
    return data


def save_config(config: dict[str, Any]) -> None:
    ensure_config_shape(config)
    write_json(config_path(), config)


def default_config() -> dict[str, Any]:
    return {
        "agent_name": "Codex Entertainment Agent",
        "library_dir": str(DEFAULT_LIBRARY_DIR),
        "audio_format_selector": "bestaudio[ext=m4a]/bestaudio[acodec*=mp4a]/bestaudio",
        "search_provider": "ytsearch",
        "search_limit": 5,
        "preferred_music_context": ["Hindi songs", "Haryanvi songs", "official audio"],
        "favorites": [],
        "playlists": {"favorites": []},
    }


def ensure_config_shape(config: dict[str, Any]) -> None:
    fallback = default_config()
    for key, value in fallback.items():
        config.setdefault(key, value)
    if not isinstance(config.get("playlists"), dict):
        config["playlists"] = {"favorites": []}
    if not isinstance(config.get("favorites"), list):
        config["favorites"] = []


def merge_config(config: dict[str, Any], values: dict[str, Any]) -> None:
    allowed = {
        "agent_name",
        "library_dir",
        "audio_format_selector",
        "search_provider",
        "search_limit",
        "preferred_music_context",
        "favorites",
        "playlists",
        "notes",
    }
    for key, value in values.items():
        if key in allowed:
            config[key] = value
    ensure_config_shape(config)


def library_dir(config: dict[str, Any]) -> Path:
    override = os.environ.get("JARVIS_ENTERTAINMENT_LIBRARY_DIR", "").strip()
    raw = override or str(config.get("library_dir", DEFAULT_LIBRARY_DIR))
    path = Path(raw)
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def index_path(config: dict[str, Any]) -> Path:
    return library_dir(config) / "library.json"


def state_path(config: dict[str, Any]) -> Path:
    return library_dir(config) / "player_state.json"


def load_index(config: dict[str, Any]) -> dict[str, Any]:
    path = index_path(config)
    if not path.exists():
        return {"tracks": {}, "aliases": {}}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        return {"tracks": {}, "aliases": {}}
    data.setdefault("tracks", {})
    data.setdefault("aliases", {})
    return data


def save_index(config: dict[str, Any], index: dict[str, Any]) -> None:
    write_json(index_path(config), index)


def default_state() -> dict[str, Any]:
    return {"queue": [], "current_index": -1, "player_pid": None, "started_at": None}


def load_state(config: dict[str, Any]) -> dict[str, Any]:
    path = state_path(config)
    if not path.exists():
        return default_state()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    return data if isinstance(data, dict) else default_state()


def save_state(config: dict[str, Any], state: dict[str, Any]) -> None:
    write_json(state_path(config), state)


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def ytdlp_available() -> bool:
    try:
        import yt_dlp  # noqa: F401

        return True
    except Exception:
        return False


def search_ytdlp(query: str, limit: int) -> list[dict[str, Any]]:
    try:
        import yt_dlp
    except Exception as error:
        raise ToolInputError("yt-dlp is not installed") from error

    search_url = f"ytsearch{limit}:{query}"
    options = {"quiet": True, "no_warnings": True, "noprogress": True, "skip_download": True, "extract_flat": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(search_url, download=False)
    entries = info.get("entries", []) if isinstance(info, dict) else []
    results: list[dict[str, Any]] = []
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            continue
        video_id = str(entry.get("id") or "")
        webpage_url = str(entry.get("webpage_url") or entry.get("url") or "")
        if video_id and "youtube.com" not in webpage_url and "youtu.be" not in webpage_url:
            webpage_url = f"https://www.youtube.com/watch?v={video_id}"
        results.append(
            {
                "index": index,
                "id": video_id,
                "title": str(entry.get("title") or "Untitled"),
                "webpage_url": webpage_url,
                "duration": entry.get("duration"),
                "channel": entry.get("channel") or entry.get("uploader"),
            }
        )
    return results


def download_with_ytdlp(
    config: dict[str, Any],
    url: str,
    aliases: list[str],
    selected_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        import yt_dlp
    except Exception as error:
        raise ToolInputError("yt-dlp is not installed") from error

    target_dir = library_dir(config)
    options = {
        "format": str(config.get("audio_format_selector") or default_config()["audio_format_selector"]),
        "outtmpl": str(target_dir / "%(title).180B [%(id)s].%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "windowsfilenames": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            if isinstance(info, dict) and "entries" in info:
                entries = [entry for entry in info.get("entries", []) if isinstance(entry, dict)]
                info = entries[0] if entries else info
            file_path = Path(ydl.prepare_filename(info)).resolve()
    except Exception as error:
        raise ToolInputError(f"Download failed: {error}") from error

    if not file_path.exists():
        file_path = find_downloaded_file(target_dir, str(info.get("id") or ""))
    track = track_from_info(info, file_path, selected_result)
    track["aliases"] = unique_texts([*aliases, track.get("title", ""), track.get("webpage_url", "")])
    return track


def find_downloaded_file(directory: Path, video_id: str) -> Path:
    if video_id:
        marker = f"[{video_id}]"
        for path in directory.iterdir():
            if marker in path.name:
                return path.resolve()
    raise ToolInputError("Download finished but the saved file was not found")


def track_from_info(info: dict[str, Any], file_path: Path, selected_result: dict[str, Any] | None = None) -> dict[str, Any]:
    title = str(info.get("title") or (selected_result or {}).get("title") or file_path.stem)
    webpage_url = str(info.get("webpage_url") or info.get("original_url") or (selected_result or {}).get("webpage_url") or "")
    source_id = str(info.get("id") or (selected_result or {}).get("id") or "")
    track_id = stable_track_id(source_id or webpage_url or str(file_path))
    return {
        "id": track_id,
        "source_id": source_id,
        "title": title,
        "webpage_url": webpage_url,
        "file_path": str(file_path),
        "duration": info.get("duration") or (selected_result or {}).get("duration"),
        "channel": info.get("channel") or info.get("uploader") or (selected_result or {}).get("channel"),
        "saved_at": time.time(),
    }


def stable_track_id(value: str) -> str:
    clean = value.strip()
    digest = hashlib.sha1(clean.encode("utf-8")).hexdigest()[:12]
    prefix = canonical_text(clean)[:24].replace(" ", "_")
    return f"{prefix}_{digest}" if prefix else digest


def upsert_track(index: dict[str, Any], track: dict[str, Any], aliases: list[str]) -> None:
    tracks = index.setdefault("tracks", {})
    tracks[track["id"]] = track
    alias_map = index.setdefault("aliases", {})
    for alias in unique_texts([*aliases, *track.get("aliases", [])]):
        key = canonical_text(alias)
        if key:
            alias_map[key] = track["id"]


def cached_track(index: dict[str, Any], aliases: list[str]) -> dict[str, Any] | None:
    tracks = index.get("tracks", {})
    alias_map = index.get("aliases", {})
    for alias in aliases:
        track_id = alias_map.get(canonical_text(alias))
        track = tracks.get(track_id) if track_id else None
        if isinstance(track, dict) and Path(str(track.get("file_path", ""))).exists():
            return track
    query_key = canonical_text(" ".join(aliases))
    if query_key:
        for track in tracks.values():
            if not isinstance(track, dict):
                continue
            title_key = canonical_text(str(track.get("title", "")))
            if query_key and title_key and (query_key in title_key or title_key in query_key):
                if Path(str(track.get("file_path", ""))).exists():
                    return track
    return None


def resolve_track(
    config: dict[str, Any],
    index: dict[str, Any],
    params: dict[str, Any],
    auto_download: bool = False,
) -> dict[str, Any] | None:
    track_id = optional_text(params, "track_id")
    if track_id:
        track = index.get("tracks", {}).get(track_id)
        if isinstance(track, dict):
            return track
    path = optional_text(params, "path")
    if path:
        local = Path(path)
        if local.exists():
            return {"id": stable_track_id(str(local.resolve())), "title": local.stem, "file_path": str(local.resolve())}
    query = optional_text(params, "query")
    url = optional_text(params, "url")
    cached = cached_track(index, aliases_for(query, url))
    if cached is not None:
        return cached
    if auto_download and (query or url):
        downloaded = entertainment_download(
            {
                "query": query,
                "url": url,
                "context": optional_text(params, "context"),
                "force": False,
            }
        )
        return downloaded["track"]
    return None


def aliases_for(query: str, url: str) -> list[str]:
    return unique_texts([query, url])


def combined_query(query: str, context: str) -> str:
    return " ".join(item for item in [query.strip(), context.strip()] if item).strip()


def canonical_text(text: str) -> str:
    parts: list[str] = []
    last_was_space = False
    for char in text.casefold():
        if char.isalnum():
            parts.append(char)
            last_was_space = False
        elif char.isspace() and not last_was_space:
            parts.append(" ")
            last_was_space = True
    return "".join(parts).strip()


def unique_texts(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        text = value.strip()
        key = canonical_text(text)
        if key and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def bounded_int(value: Any, minimum: int, maximum: int, fallback: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def apply_track_lists(config: dict[str, Any], track_id: str, add_to_favorites: bool, playlist: str) -> None:
    changed = False
    if add_to_favorites:
        add_favorite(config, track_id)
        add_track_to_playlist(config, "favorites", track_id)
        changed = True
    if playlist:
        add_track_to_playlist(config, playlist, track_id)
        changed = True
    if changed:
        save_config(config)


def add_favorite(config: dict[str, Any], track_id: str) -> None:
    favorites = config.setdefault("favorites", [])
    if isinstance(favorites, list) and track_id not in favorites:
        favorites.append(track_id)


def remove_favorite(config: dict[str, Any], track_id: str) -> None:
    favorites = config.get("favorites", [])
    if isinstance(favorites, list):
        config["favorites"] = [item for item in favorites if item != track_id]


def add_track_to_playlist(config: dict[str, Any], playlist: str, track_id: str) -> None:
    playlists = config.setdefault("playlists", {})
    if not isinstance(playlists, dict):
        playlists = {}
        config["playlists"] = playlists
    items = playlists.setdefault(playlist, [])
    if isinstance(items, list) and track_id not in items:
        items.append(track_id)


def remove_track_from_playlist(config: dict[str, Any], playlist: str, track_id: str) -> None:
    playlists = config.get("playlists", {})
    if isinstance(playlists, dict) and isinstance(playlists.get(playlist), list):
        playlists[playlist] = [item for item in playlists[playlist] if item != track_id]


def playlist_ids(config: dict[str, Any], playlist: str) -> list[str]:
    if playlist == "favorites":
        favorites = config.get("favorites", [])
        if isinstance(favorites, list) and favorites:
            return [str(item) for item in favorites]
    playlists = config.get("playlists", {})
    if isinstance(playlists, dict) and isinstance(playlists.get(playlist), list):
        return [str(item) for item in playlists[playlist]]
    return []


def append_queue(state: dict[str, Any], track_id: str) -> None:
    queue = state.setdefault("queue", [])
    if not isinstance(queue, list):
        queue = []
        state["queue"] = queue
    queue.append(track_id)
    if state.get("current_index", -1) < 0:
        state["current_index"] = 0


def queue_status(config: dict[str, Any], index: dict[str, Any], state: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    queue = state.get("queue", [])
    current_index = bounded_int(state.get("current_index"), 0, max(0, len(queue) - 1), 0) if queue else -1
    current_id = queue[current_index] if queue and current_index >= 0 else ""
    track = index.get("tracks", {}).get(current_id, {}) if current_id else {}
    running = process_is_running(state.get("player_pid"))
    summary_parts = [prefix.strip()] if prefix else []
    summary_parts.append(f"Queue: {len(queue)} track(s).")
    if track:
        summary_parts.append(f"Current: {track.get('title', current_id)}.")
    summary_parts.append(f"Player: {'running' if running else 'idle'}.")
    return {"summary": " ".join(summary_parts), "queue": queue, "current_index": current_index, "current_track": track, "player_running": running}


def start_queue_playback(config: dict[str, Any], index: dict[str, Any], state: dict[str, Any]) -> None:
    stop_player(state)
    queue = state.get("queue", [])
    if not isinstance(queue, list) or not queue:
        raise ToolInputError("Queue is empty")
    start = bounded_int(state.get("current_index"), 0, len(queue) - 1, 0)
    paths: list[Path] = []
    for track_id in queue[start:]:
        track = index.get("tracks", {}).get(track_id)
        if isinstance(track, dict):
            path = Path(str(track.get("file_path", "")))
            if path.exists():
                paths.append(path.resolve())
    if not paths:
        raise ToolInputError("No playable files found in queue")
    pid = start_player_process(paths)
    state["player_pid"] = pid
    state["started_at"] = time.time()


def start_player_process(paths: list[Path]) -> int | None:
    if os.environ.get("JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER", "").strip().lower() in {"1", "true", "yes", "on"}:
        return 0
    if os.name == "nt":
        command = powershell_media_player_command(paths)
        encoded = command.encode("utf-16le")
        import base64

        process = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", base64.b64encode(encoded).decode("ascii")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return process.pid
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    process = subprocess.Popen([opener, str(paths[0])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return process.pid


def powershell_media_player_command(paths: list[Path]) -> str:
    escaped_paths = []
    for path in paths:
        uri = path.as_uri().replace("'", "''")
        escaped_paths.append(f"'{uri}'")
    uri_array = "@(" + ",".join(escaped_paths) + ")"
    return f"""
Add-Type -AssemblyName PresentationCore
$uris = {uri_array}
foreach ($rawUri in $uris) {{
  $player = New-Object System.Windows.Media.MediaPlayer
  $player.Open([Uri]::new($rawUri))
  $started = Get-Date
  while (-not $player.NaturalDuration.HasTimeSpan) {{
    Start-Sleep -Milliseconds 100
    if (((Get-Date) - $started).TotalSeconds -gt 10) {{ break }}
  }}
  $player.Volume = 1.0
  $player.Play()
  while ($player.NaturalDuration.HasTimeSpan -and $player.Position -lt $player.NaturalDuration.TimeSpan) {{
    Start-Sleep -Milliseconds 250
  }}
  Start-Sleep -Milliseconds 300
  $player.Stop()
  $player.Close()
}}
"""


def stop_player(state: dict[str, Any]) -> None:
    pid = state.get("player_pid")
    if not isinstance(pid, int) or pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass


def process_is_running(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == "nt":
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
