from __future__ import annotations

import hashlib
import json
import os
import csv
import random
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
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
        playlist, ids = resolve_playlist_for_play(config, index, optional_text(params, "playlist"))
        if not ids:
            raise ToolInputError("No playable playlist found")
        stop_player(state)
        state = {"queue": ids, "current_index": 0, "player_pid": None, "started_at": time.time()}
        start_queue_playback(config, index, state)
        save_state(config, state)
        return {
            "summary": f"Playing playlist {playlist}: {len(ids)} track(s).",
            "playlist": playlist,
            "queue": ids,
            "tracks": tracks_from_ids(index, ids),
        }
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
        overview = playlist_overview(config, index)
        return {
            "summary": overview["summary"],
            "playlists": playlists,
            "playlist_tracks": overview["playlist_tracks"],
        }
    if operation == "show":
        playlist = require_text(params, "playlist")
        ids = playlist_ids(config, playlist)
        tracks = [index.get("tracks", {}).get(track_id, {"id": track_id}) for track_id in ids]
        return {
            "summary": playlist_detail_summary(config, playlist, tracks),
            "playlist": playlist,
            "tracks": tracks,
        }
    if operation == "create":
        playlist = require_text(params, "playlist")
        playlists.setdefault(playlist, [])
        save_config(config)
        return {"summary": f"Playlist ready: {playlist}", "playlist": playlist}
    if operation in {"add_track", "add_favorite"}:
        playlist = "favorites" if operation == "add_favorite" else require_text(params, "playlist")
        track = resolve_track(config, index, params, auto_download=bool(params.get("auto_download", False)))
        if track is None:
            track = current_playing_track(config, index)
        if track is None:
            raise ToolInputError("No local track was resolved. Name a downloaded track, play a local track first, or use auto_download.")
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
        playlist = optional_text(params, "playlist")
        return entertainment_queue({"operation": "play_playlist", "playlist": playlist})
    raise ToolInputError(f"Unsupported playlist operation: {operation}")


def current_playing_track(config: dict[str, Any], index: dict[str, Any]) -> dict[str, Any] | None:
    state = load_state(config)
    track = current_track(index, state)
    if track and track_file_available(track):
        return track
    return None


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
        "playlist_display_limit": 12,
        "default_playlist": "",
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
        "playlist_display_limit",
        "default_playlist",
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


def resolve_playlist_for_play(config: dict[str, Any], index: dict[str, Any], requested_playlist: str) -> tuple[str, list[str]]:
    if requested_playlist:
        matched = match_playlist_name(config, requested_playlist)
        if matched:
            return matched, playable_playlist_ids(config, index, matched)

    configured_default = optional_config_text(config, "default_playlist")
    if configured_default:
        ids = playable_playlist_ids(config, index, configured_default)
        if ids:
            return configured_default, ids

    playlists = config.get("playlists", {})
    candidates: list[tuple[str, list[str]]] = []
    if isinstance(playlists, dict):
        for name in sorted(str(item) for item in playlists):
            ids = playable_playlist_ids(config, index, name)
            if ids:
                candidates.append((name, ids))

    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        return candidates[0]

    track_ids = playable_track_ids(index)
    if track_ids:
        return "library", track_ids
    return "", []


def match_playlist_name(config: dict[str, Any], requested_playlist: str) -> str:
    requested_key = canonical_text(requested_playlist)
    playlists = config.get("playlists", {})
    if not requested_key or not isinstance(playlists, dict):
        return ""
    for name in sorted(str(item) for item in playlists):
        if canonical_text(name) == requested_key:
            return name
    return ""


def playable_playlist_ids(config: dict[str, Any], index: dict[str, Any], playlist: str) -> list[str]:
    valid_tracks = index.get("tracks", {})
    ids: list[str] = []
    for track_id in playlist_ids(config, playlist):
        track = valid_tracks.get(track_id)
        if isinstance(track, dict) and Path(str(track.get("file_path", ""))).exists():
            ids.append(track_id)
    return ids


def playable_track_ids(index: dict[str, Any]) -> list[str]:
    tracks = index.get("tracks", {})
    ids: list[str] = []
    if not isinstance(tracks, dict):
        return ids
    for track_id, track in tracks.items():
        if isinstance(track_id, str) and isinstance(track, dict) and Path(str(track.get("file_path", ""))).exists():
            ids.append(track_id)
    return sorted(ids)


def optional_config_text(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return ""


def playlist_overview(config: dict[str, Any], index: dict[str, Any]) -> dict[str, Any]:
    playlists = config.get("playlists", {})
    names = sorted(str(name) for name in playlists) if isinstance(playlists, dict) else []
    if "favorites" not in names:
        names.append("favorites")
    names = sorted(unique_texts(names))
    if not names:
        return {"summary": "No playlists saved yet.", "playlist_tracks": {}}

    playlist_tracks: dict[str, list[dict[str, Any]]] = {}
    lines: list[str] = []
    for name in names:
        ids = playlist_ids(config, name)
        tracks = [track_summary(index, track_id) for track_id in ids]
        playlist_tracks[name] = tracks
        lines.append(playlist_line(config, name, tracks))
    return {"summary": "Playlists:\n" + "\n".join(lines), "playlist_tracks": playlist_tracks}


def playlist_line(config: dict[str, Any], name: str, tracks: list[dict[str, Any]]) -> str:
    if not tracks:
        return f"{name}: empty"
    limit = bounded_int(config.get("playlist_display_limit"), 1, 50, 12)
    visible = tracks[:limit]
    titles = [str(track.get("title") or track.get("id") or "Untitled") for track in visible]
    suffix = ""
    remaining = len(tracks) - len(visible)
    if remaining > 0:
        suffix = f"; plus {remaining} more"
    return f"{name}: {len(tracks)} track(s) - {'; '.join(titles)}{suffix}"


def playlist_detail_summary(config: dict[str, Any], playlist: str, tracks: list[dict[str, Any]]) -> str:
    if not tracks:
        return f"{playlist}: empty"
    return playlist_line(config, playlist, tracks)


def track_summary(index: dict[str, Any], track_id: str) -> dict[str, Any]:
    track = index.get("tracks", {}).get(track_id)
    if isinstance(track, dict):
        return {
            "id": str(track.get("id") or track_id),
            "title": str(track.get("title") or track_id),
            "file_path": str(track.get("file_path") or ""),
            "webpage_url": str(track.get("webpage_url") or ""),
            "duration": track.get("duration"),
            "channel": track.get("channel"),
        }
    return {"id": track_id, "title": f"Missing local track {track_id}", "file_path": "", "webpage_url": ""}


def tracks_from_ids(index: dict[str, Any], track_ids: list[str]) -> list[dict[str, Any]]:
    return [track_summary(index, track_id) for track_id in track_ids]


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


# Expanded entertainment operating-system layer. These definitions intentionally
# live behind the extension manifest so the normal Jarvis chat loop stays clean.


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_config() -> dict[str, Any]:
    return {
        "agent_name": "Codex Entertainment Agent",
        "media_root": "media/entertainment",
        "library_dir": str(DEFAULT_LIBRARY_DIR),
        "music_dir": str(DEFAULT_LIBRARY_DIR),
        "video_dir": "media/entertainment/video",
        "podcast_dir": "media/entertainment/podcasts",
        "lyrics_dir": "media/entertainment/lyrics",
        "thumbnails_dir": "media/entertainment/thumbnails",
        "playlists_dir": "media/entertainment/playlists",
        "equalizer_dir": "media/entertainment/equalizer_profiles",
        "library": {
            "index_path": str(DEFAULT_LIBRARY_DIR / "library.json"),
            "auto_scan_on_start": True,
            "watch_for_changes": False,
            "supported_audio": ["m4a", "mp3", "flac", "ogg", "wav", "aac", "opus"],
            "supported_video": ["mp4", "webm", "mkv", "avi", "mov"],
            "supported_podcast": ["mp3", "m4a", "opus"],
            "scan_roots": [str(DEFAULT_LIBRARY_DIR), "media/entertainment/music", "media/entertainment/video", "media/entertainment/podcasts"],
            "max_search_results": 20,
        },
        "player": {
            "preferred_backend": "auto",
            "backends_priority": ["vlc", "mpv", "ffplay", "system"],
            "vlc_executable": "vlc",
            "mpv_executable": "mpv",
            "ffplay_executable": "ffplay",
            "state_path": str(DEFAULT_LIBRARY_DIR / "player_state.json"),
            "queue_state_path": "media/entertainment/queue_state.json",
            "crossfade_enabled": False,
            "crossfade_seconds": 5,
            "gapless_playback": True,
            "normalize_volume": True,
            "replay_gain": True,
            "volume": 100,
            "speed": 1.0,
            "muted": False,
        },
        "download": {
            "audio_format_selector": "bestaudio[ext=m4a]/bestaudio[acodec*=mp4a]/bestaudio",
            "video_format_selector": "bestvideo[height<=1080]+bestaudio/best",
            "audio_quality": "best",
            "embed_thumbnail": True,
            "embed_metadata": True,
            "write_subtitles": False,
            "concurrent_downloads": 2,
            "rate_limit_bytes": None,
            "proxy": "",
        },
        "search": {
            "provider": "ytsearch",
            "providers": ["local", "youtube", "soundcloud"],
            "default_limit": 8,
            "prefer_official": True,
            "preferred_contexts": ["Hindi songs", "Haryanvi songs", "Punjabi songs", "Indian indie", "official audio", "lyrical video"],
            "languages": ["Hindi", "English", "Punjabi", "Haryanvi", "Bengali", "Tamil", "Telugu", "Malayalam", "Kannada", "Marathi", "Gujarati"],
        },
        "recommendations": {
            "enabled": True,
            "smart_queue_extend_at": 3,
            "smart_queue_add_count": 5,
            "discovery_ratio": 0.2,
            "taste_profile_path": "media/entertainment/taste_profile.json",
            "weekly_mix_size": 25,
        },
        "lyrics": {
            "auto_fetch_on_download": True,
            "prefer_synced": True,
            "genius_api_key_env": "GENIUS_API_KEY",
            "cache_dir": "media/entertainment/lyrics",
        },
        "radio": {
            "api_url": "https://de1.api.radio-browser.info",
            "saved_stations_path": "media/entertainment/radio_stations.json",
            "default_stations": {},
            "autosave_played_stations": False,
            "last_search_ttl_seconds": 300,
        },
        "podcast": {
            "feeds_path": "media/entertainment/podcast_feeds.json",
            "auto_update_on_start": False,
            "keep_played_days": 30,
            "save_position": True,
            "default_speed": 1.5,
        },
        "history": {
            "path": "media/entertainment/history.json",
            "max_entries": 10000,
            "track_completion_threshold": 0.8,
        },
        "mood": {
            "auto_detect_context": False,
            "default_context": "casual",
            "context_path": "media/entertainment/mood_context.json",
            "bpm_energetic_threshold": 120,
            "bpm_calm_threshold": 80,
        },
        "equalizer": {
            "enabled": True,
            "active_profile": "flat",
            "profiles_dir": "media/entertainment/equalizer_profiles",
            "built_in_profiles": {"flat": {}},
        },
        "apis": {
            "musicbrainz_user_agent": "Jarvis/1.0",
            "spotify_client_id_env": "SPOTIFY_CLIENT_ID",
            "spotify_client_secret_env": "SPOTIFY_CLIENT_SECRET",
            "lastfm_api_key_env": "LASTFM_API_KEY",
            "acoustid_api_key_env": "ACOUSTID_API_KEY",
        },
        "sleep_timer": {"fade_out_seconds": 30},
        "dry_run_player": False,
        "playlist_display_limit": 12,
        "default_playlist": "",
        "favorites": [],
        "playlists": {"favorites": []},
        "notes": [
            "Download only media the user is allowed to access and keep.",
            "If a track is already in the local library, play the saved file instead of downloading it again.",
        ],
    }


def ensure_config_shape(config: dict[str, Any]) -> None:
    merge_missing(config, default_config())
    if not isinstance(config.get("playlists"), dict):
        config["playlists"] = {"favorites": []}
    if not isinstance(config.get("favorites"), list):
        config["favorites"] = []
    if not isinstance(config.get("library"), dict):
        config["library"] = default_config()["library"]
    if not isinstance(config.get("player"), dict):
        config["player"] = default_config()["player"]
    if not isinstance(config.get("search"), dict):
        config["search"] = default_config()["search"]
    if not isinstance(config.get("download"), dict):
        config["download"] = default_config()["download"]

    config["library_dir"] = str(config.get("library_dir") or config.get("music_dir") or DEFAULT_LIBRARY_DIR)
    config["music_dir"] = str(config.get("music_dir") or config.get("library_dir") or DEFAULT_LIBRARY_DIR)
    config["audio_format_selector"] = str(config.get("audio_format_selector") or config["download"].get("audio_format_selector") or default_config()["download"]["audio_format_selector"])
    config["search_provider"] = str(config.get("search_provider") or config["search"].get("provider") or "ytsearch")
    config["search_limit"] = bounded_int(config.get("search_limit"), 1, 50, bounded_int(config["search"].get("default_limit"), 1, 50, 8))
    contexts = config.get("preferred_music_context")
    if not isinstance(contexts, list):
        config["preferred_music_context"] = list(config["search"].get("preferred_contexts", []))
    if not isinstance(config.get("playlist_display_limit"), int):
        config["playlist_display_limit"] = 12


def merge_missing(target: dict[str, Any], defaults: dict[str, Any]) -> None:
    for key, value in defaults.items():
        if key not in target:
            target[key] = value
        elif isinstance(target.get(key), dict) and isinstance(value, dict):
            merge_missing(target[key], value)


def merge_config(config: dict[str, Any], values: dict[str, Any]) -> None:
    deep_merge(config, values)
    ensure_config_shape(config)


def deep_merge(target: dict[str, Any], values: dict[str, Any]) -> None:
    for key, value in values.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = value


def resolve_config_path(raw: Any) -> Path:
    text = str(raw or "").strip()
    if not text:
        text = str(default_config()["media_root"])
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def config_section_path(config: dict[str, Any], section: str, key: str, fallback: str) -> Path:
    data = config.get(section, {})
    raw = data.get(key) if isinstance(data, dict) else ""
    return resolve_config_path(raw or fallback)


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


def library_dir(config: dict[str, Any]) -> Path:
    override = os.environ.get("JARVIS_ENTERTAINMENT_LIBRARY_DIR", "").strip()
    raw = override or config.get("music_dir") or config.get("library_dir") or DEFAULT_LIBRARY_DIR
    path = resolve_config_path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def index_path(config: dict[str, Any]) -> Path:
    if os.environ.get("JARVIS_ENTERTAINMENT_LIBRARY_DIR", "").strip():
        path = library_dir(config) / "library.json"
    else:
        data = config.get("library", {})
        raw = data.get("index_path") if isinstance(data, dict) else ""
        path = resolve_config_path(raw or (library_dir(config) / "library.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def state_path(config: dict[str, Any]) -> Path:
    if os.environ.get("JARVIS_ENTERTAINMENT_LIBRARY_DIR", "").strip():
        path = library_dir(config) / "player_state.json"
    else:
        path = config_section_path(config, "player", "state_path", str(library_dir(config) / "player_state.json"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def media_path(config: dict[str, Any], top_key: str, fallback: str) -> Path:
    path = resolve_config_path(config.get(top_key) or fallback)
    path.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def json_store_path(config: dict[str, Any], section: str, key: str, fallback: str) -> Path:
    path = config_section_path(config, section, key, fallback)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def ensure_media_dirs(config: dict[str, Any]) -> None:
    for key, fallback in [
        ("music_dir", str(DEFAULT_LIBRARY_DIR)),
        ("video_dir", "media/entertainment/video"),
        ("podcast_dir", "media/entertainment/podcasts"),
        ("lyrics_dir", "media/entertainment/lyrics"),
        ("thumbnails_dir", "media/entertainment/thumbnails"),
        ("playlists_dir", "media/entertainment/playlists"),
        ("equalizer_dir", "media/entertainment/equalizer_profiles"),
    ]:
        media_path(config, key, fallback)


def default_state() -> dict[str, Any]:
    return {
        "queue": [],
        "current_index": -1,
        "player_pid": None,
        "started_at": None,
        "playback_status": "stopped",
        "backend": "",
        "volume": 100,
        "speed": 1.0,
        "muted": False,
        "repeat_mode": "off",
        "shuffle": "off",
        "session_history": [],
        "sleep_timer_until": "",
        "stream": {},
        "radio": {},
    }


def load_state(config: dict[str, Any]) -> dict[str, Any]:
    path = state_path(config)
    if not path.exists():
        return default_state()
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    state = data if isinstance(data, dict) else {}
    merge_missing(state, default_state())
    return state


def save_state(config: dict[str, Any], state: dict[str, Any]) -> None:
    merge_missing(state, default_state())
    write_json(state_path(config), state)


def load_index(config: dict[str, Any]) -> dict[str, Any]:
    path = index_path(config)
    if not path.exists():
        return ensure_index_shape({"tracks": {}, "aliases": {}, "indexes": {}})
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        data = {"tracks": {}, "aliases": {}}
    return ensure_index_shape(data)


def save_index(config: dict[str, Any], index: dict[str, Any]) -> None:
    write_json(index_path(config), ensure_index_shape(index))


def ensure_index_shape(index: dict[str, Any]) -> dict[str, Any]:
    tracks = index.get("tracks")
    aliases = index.get("aliases")
    if not isinstance(tracks, dict):
        tracks = {}
    if not isinstance(aliases, dict):
        aliases = {}
    normalized_tracks: dict[str, dict[str, Any]] = {}
    for track_id, track in tracks.items():
        if isinstance(track_id, str) and isinstance(track, dict):
            normalized = normalize_track(track, track_id)
            normalized_tracks[normalized["id"]] = normalized
    result = {"tracks": normalized_tracks, "aliases": aliases, "indexes": {}}
    rebuild_library_indexes(result)
    return result


def normalize_track(track: dict[str, Any], fallback_id: str = "") -> dict[str, Any]:
    file_path = str(track.get("file_path") or "")
    source_url = str(track.get("source_url") or track.get("webpage_url") or "")
    source_id = str(track.get("source_id") or "")
    stable_source = source_id or source_url or file_path or fallback_id or str(time.time())
    track_id = str(track.get("id") or fallback_id or stable_track_id(stable_source))
    title = str(track.get("title") or (Path(file_path).stem if file_path else track_id))
    duration = track.get("duration_seconds", track.get("duration"))
    normalized = {
        "id": track_id,
        "type": str(track.get("type") or media_type_from_path(file_path) or "music"),
        "title": title,
        "artist": str(track.get("artist") or track.get("channel") or ""),
        "album": str(track.get("album") or ""),
        "album_artist": str(track.get("album_artist") or ""),
        "year": track.get("year"),
        "genre": clean_list(track.get("genre")),
        "language": str(track.get("language") or ""),
        "tags": clean_list(track.get("tags")),
        "duration_seconds": numeric_or_none(duration),
        "duration": numeric_or_none(duration),
        "file_path": file_path,
        "file_size_bytes": numeric_or_none(track.get("file_size_bytes")) or file_size(file_path),
        "file_format": str(track.get("file_format") or Path(file_path).suffix.lstrip(".").lower()),
        "quality": str(track.get("quality") or ""),
        "thumbnail_path": str(track.get("thumbnail_path") or ""),
        "source_url": source_url,
        "webpage_url": source_url,
        "source_id": source_id,
        "source_platform": str(track.get("source_platform") or infer_source_platform(source_url)),
        "lyrics_path": str(track.get("lyrics_path") or ""),
        "lyrics_synced": bool(track.get("lyrics_synced", False)),
        "play_count": int(track.get("play_count") or 0),
        "last_played_at": str(track.get("last_played_at") or ""),
        "first_played_at": str(track.get("first_played_at") or ""),
        "rating": numeric_or_none(track.get("rating")) or 0,
        "liked": bool(track.get("liked", False)),
        "disliked": bool(track.get("disliked", False)),
        "skipped_count": int(track.get("skipped_count") or 0),
        "completion_rate": numeric_or_none(track.get("completion_rate")) or 0,
        "mood_tags": clean_list(track.get("mood_tags")),
        "bpm": numeric_or_none(track.get("bpm")),
        "key": str(track.get("key") or ""),
        "added_at": str(track.get("added_at") or track.get("saved_at") or now_iso()),
        "saved_at": track.get("saved_at") or time.time(),
        "download_complete": bool(track.get("download_complete", bool(file_path and Path(file_path).exists()))),
        "aliases": clean_list(track.get("aliases")),
        "channel": str(track.get("channel") or track.get("artist") or ""),
    }
    for key, value in track.items():
        normalized.setdefault(key, value)
    return normalized


def clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return unique_texts([str(item) for item in value if isinstance(item, (str, int, float))])
    if isinstance(value, str) and value.strip():
        return unique_texts([value])
    return []


def numeric_or_none(value: Any) -> float | int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str) and value.strip():
        try:
            number = float(value)
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return None


def file_size(path: str) -> int:
    if not path:
        return 0
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def media_type_from_path(path: str) -> str:
    suffix = Path(path).suffix.lower().lstrip(".")
    config = default_config()["library"]
    if suffix in config["supported_video"]:
        return "video"
    if suffix in config["supported_podcast"]:
        lowered = path.casefold()
        if "podcast" in lowered:
            return "podcast"
    if suffix in config["supported_audio"]:
        return "music"
    return ""


def infer_source_platform(url: str) -> str:
    lowered = url.casefold()
    if "youtube." in lowered or "youtu.be" in lowered:
        return "youtube"
    if "soundcloud." in lowered:
        return "soundcloud"
    if "spotify." in lowered:
        return "spotify"
    return ""


def rebuild_library_indexes(index: dict[str, Any]) -> None:
    indexes = {
        "by_id": {},
        "by_artist": {},
        "by_album": {},
        "by_genre": {},
        "by_language": {},
        "by_mood": {},
        "by_platform": {},
        "by_type": {},
        "aliases": {},
    }
    alias_map: dict[str, str] = {}
    existing_aliases = index.get("aliases", {})
    if isinstance(existing_aliases, dict):
        for alias, track_id in existing_aliases.items():
            if isinstance(alias, str) and isinstance(track_id, str):
                alias_map[canonical_text(alias)] = track_id

    for track_id, track in index.get("tracks", {}).items():
        if not isinstance(track, dict):
            continue
        indexes["by_id"][track_id] = track_id
        add_index_value(indexes["by_artist"], track.get("artist"), track_id)
        add_index_value(indexes["by_album"], track.get("album"), track_id)
        add_index_values(indexes["by_genre"], track.get("genre"), track_id)
        add_index_value(indexes["by_language"], track.get("language"), track_id)
        add_index_values(indexes["by_mood"], track.get("mood_tags"), track_id)
        add_index_value(indexes["by_platform"], track.get("source_platform"), track_id)
        add_index_value(indexes["by_type"], track.get("type"), track_id)
        for alias in unique_texts([track.get("title", ""), track.get("source_url", ""), track.get("webpage_url", ""), *clean_list(track.get("aliases"))]):
            key = canonical_text(alias)
            if key:
                alias_map[key] = track_id
    indexes["aliases"] = alias_map
    index["aliases"] = alias_map
    index["indexes"] = indexes


def add_index_value(index: dict[str, list[str]], value: Any, track_id: str) -> None:
    if not isinstance(value, str) or not value.strip():
        return
    key = canonical_text(value)
    if not key:
        return
    index.setdefault(key, [])
    if track_id not in index[key]:
        index[key].append(track_id)


def add_index_values(index: dict[str, list[str]], values: Any, track_id: str) -> None:
    for value in clean_list(values):
        add_index_value(index, value, track_id)


def upsert_track(index: dict[str, Any], track: dict[str, Any], aliases: list[str]) -> None:
    normalized = normalize_track(track)
    normalized["aliases"] = unique_texts([*clean_list(normalized.get("aliases")), *aliases, normalized.get("title", ""), normalized.get("source_url", "")])
    index.setdefault("tracks", {})[normalized["id"]] = normalized
    rebuild_library_indexes(index)


def cached_track(index: dict[str, Any], aliases: list[str]) -> dict[str, Any] | None:
    prepared = ensure_index_shape(index)
    tracks = prepared.get("tracks", {})
    alias_map = prepared.get("aliases", {})
    for alias in aliases:
        key = canonical_text(alias)
        track_id = alias_map.get(key)
        track = tracks.get(track_id) if track_id else None
        if isinstance(track, dict) and track_file_available(track):
            return track
    query_key = canonical_text(" ".join(aliases))
    if not query_key:
        return None
    for track in tracks.values():
        if not isinstance(track, dict):
            continue
        title_key = canonical_text(str(track.get("title", "")))
        if title_key and (query_key in title_key or title_key in query_key) and track_file_available(track):
            return track
    return None


def track_file_available(track: dict[str, Any]) -> bool:
    path = str(track.get("file_path") or "")
    return bool(path and Path(path).exists())


def entertainment_status(_params: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_config()
    ensure_media_dirs(config)
    index = load_index(config)
    state = load_state(config)
    stats = library_stats(config, index)
    backend = choose_player_backend(config)
    dependencies = dependency_report(config)
    podcast_feeds = load_json_store(json_store_path(config, "podcast", "feeds_path", "media/entertainment/podcast_feeds.json"), {"feeds": {}})
    saved_radio = load_json_store(json_store_path(config, "radio", "saved_stations_path", "media/entertainment/radio_stations.json"), {"stations": {}})
    summary = (
        f"{config.get('agent_name', 'Entertainment Agent')} ready. "
        f"{stats['total_tracks']} local tracks, queue {len(state.get('queue', []))}, "
        f"player {state.get('playback_status', 'stopped')}, backend {backend['name']}."
    )
    return {
        "summary": summary,
        "config_path": str(config_path()),
        "media_root": str(resolve_config_path(config.get("media_root"))),
        "library_dir": str(library_dir(config)),
        "library": stats,
        "player": playback_state_payload(config, index, state),
        "queue_length": len(state.get("queue", [])),
        "current_track": current_track(index, state),
        "equalizer_profile": config.get("equalizer", {}).get("active_profile", "flat"),
        "sleep_timer_until": state.get("sleep_timer_until", ""),
        "streaming_sources": config.get("search", {}).get("providers", []),
        "podcast_subscription_count": len(podcast_feeds.get("feeds", {})) if isinstance(podcast_feeds.get("feeds"), dict) else 0,
        "saved_radio_count": len(saved_radio.get("stations", {})) if isinstance(saved_radio.get("stations"), dict) else 0,
        "dependencies": dependencies,
        "preferred_music_context": config.get("preferred_music_context", []),
        "yt_dlp_available": dependencies["yt-dlp"]["available"],
        "player_running": process_is_running(state.get("player_pid")),
    }


def dependency_report(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    player = config.get("player", {})
    return {
        "yt-dlp": {"available": ytdlp_available(), "source": "python"},
        "VLC": {"available": python_package_available("vlc") or executable_available(str(player.get("vlc_executable", "vlc"))), "source": str(player.get("vlc_executable", "vlc"))},
        "mpv": {"available": executable_available(str(player.get("mpv_executable", "mpv"))), "source": str(player.get("mpv_executable", "mpv"))},
        "ffmpeg": {"available": executable_available("ffmpeg"), "source": "ffmpeg"},
        "ffplay": {"available": executable_available(str(player.get("ffplay_executable", "ffplay"))), "source": str(player.get("ffplay_executable", "ffplay"))},
        "mutagen": {"available": python_package_available("mutagen"), "source": "python"},
        "requests": {"available": python_package_available("requests"), "source": "python"},
    }


def python_package_available(name: str) -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def executable_available(name: str) -> bool:
    return bool(shutil.which(name))


def choose_player_backend(config: dict[str, Any], direct_stream: bool = False) -> dict[str, Any]:
    if dry_run_enabled(config):
        return {"name": "dry_run", "available": True, "supports_stream": True, "supports_eq": True}
    player = config.get("player", {})
    preferred = str(player.get("preferred_backend") or "auto")
    priority = player.get("backends_priority")
    if not isinstance(priority, list):
        priority = ["vlc", "mpv", "ffplay", "system"]
    ordered = [preferred] if preferred != "auto" else []
    ordered.extend(str(item) for item in priority if str(item) not in ordered)
    for backend in ordered:
        if backend == "vlc" and (python_package_available("vlc") or executable_available(str(player.get("vlc_executable", "vlc")))):
            return {"name": "vlc", "available": True, "supports_stream": True, "supports_eq": True}
        if backend == "mpv" and executable_available(str(player.get("mpv_executable", "mpv"))):
            return {"name": "mpv", "available": True, "supports_stream": True, "supports_eq": True}
        if backend == "ffplay" and executable_available(str(player.get("ffplay_executable", "ffplay"))):
            return {"name": "ffplay", "available": True, "supports_stream": True, "supports_eq": False}
        if backend == "system" and not direct_stream:
            return {"name": "system", "available": True, "supports_stream": False, "supports_eq": False}
    return {"name": "", "available": False, "supports_stream": False, "supports_eq": False}


def dry_run_enabled(config: dict[str, Any]) -> bool:
    value = os.environ.get("JARVIS_ENTERTAINMENT_DRY_RUN_PLAYER", "").strip().lower()
    if value:
        return value in {"1", "true", "yes", "on"}
    return bool(config.get("dry_run_player", False))


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


def entertainment_session(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    description = require_text(params, "description")
    limit = bounded_int(params.get("limit"), 1, 100, 10)
    minimum = bounded_int(params.get("minimum_local_tracks"), 1, limit, 1)
    upcoming_limit = bounded_int(params.get("upcoming_limit"), 1, 50, 5)
    context = optional_text(params, "context")
    evidence: list[str] = []

    status = entertainment_status({})
    evidence.append(status["summary"])

    if bool(params.get("scan", True)):
        scan = entertainment_library({"operation": "scan"})
        evidence.append(scan["summary"])

    if context:
        context_result = entertainment_mood({"operation": "set_context", "context": context})
        evidence.append(context_result["summary"])

    index = load_index(config)
    matches = mood_matches(index, description, limit)
    if len(matches) < minimum:
        candidates = session_candidate_queries(config, description, limit)
        message = (
            f"Library is thin for this session: found {len(matches)} local match(es), "
            f"minimum requested {minimum}. No downloads were started."
        )
        safe_lines = [message, "", "Evidence used:"]
        safe_lines.extend(f"- {item}" for item in evidence)
        if candidates:
            safe_lines.append("")
            safe_lines.append("Search/download candidates:")
            safe_lines.extend(f"- {item}" for item in candidates)
        return {
            "summary": message,
            "action_completed": False,
            "safe_user_output": "\n".join(safe_lines),
            "status": status,
            "local_matches": matches,
            "search_candidates": candidates,
            "evidence": evidence,
        }

    state = load_state(config)
    state["queue"] = [track["id"] for track in matches]
    state["current_index"] = 0 if matches else -1
    shuffle_mode = optional_text(params, "shuffle_mode")
    if shuffle_mode:
        shuffle_queue(state, index, shuffle_mode)
        evidence.append(f"Queue shuffled: {shuffle_mode}.")
    save_state(config, state)

    playlist = optional_text(params, "playlist")
    if playlist:
        config.setdefault("playlists", {})[playlist] = [str(item) for item in state.get("queue", [])]
        save_config(config)
        evidence.append(f"Saved playlist: {playlist}.")

    eq_result: dict[str, Any] = {}
    eq_profile = select_session_eq_profile(config, optional_text(params, "eq_profile"), description)
    if eq_profile:
        eq_result = entertainment_equalizer({"operation": "apply", "profile": eq_profile})
        evidence.append(eq_result["summary"])

    playback: dict[str, Any] = {}
    if bool(params.get("start_playback", True)):
        playback = entertainment_queue({"operation": "play"})
        evidence.append(playback["summary"])

    volume_result: dict[str, Any] = {}
    volume = numeric_or_none(params.get("volume"))
    if volume is not None:
        volume_result = entertainment_playback({"operation": "volume", "value": int(volume)})
        evidence.append(volume_result["summary"])

    crossfade_result: dict[str, Any] = {}
    crossfade_seconds = numeric_or_none(params.get("crossfade_seconds"))
    if crossfade_seconds is not None:
        crossfade_result = entertainment_playback({"operation": "crossfade", "enabled": True, "seconds": int(crossfade_seconds)})
        evidence.append(crossfade_result["summary"])

    history_result: dict[str, Any] = {}
    if bool(params.get("include_history", False)):
        history_result = entertainment_history({"operation": "stats", "range": "all"})
        evidence.append(history_result["summary"])

    lyrics_result: dict[str, Any] = {}
    if bool(params.get("fetch_lyrics", False)) and state.get("queue"):
        current_id = str(state["queue"][0])
        lyrics_result = entertainment_lyrics({"operation": "show", "track_id": current_id})
        if not lyrics_result.get("available"):
            lyrics_result = entertainment_lyrics({"operation": "fetch", "track_id": current_id})
        evidence.append(lyrics_result["summary"])

    upcoming = entertainment_queue({"operation": "upcoming", "limit": upcoming_limit})
    evidence.append(upcoming["summary"])
    queued_tracks = tracks_from_ids(index, [str(item) for item in state.get("queue", [])])
    safe_output = session_safe_output(
        summary=f"Session ready with {len(state.get('queue', []))} local track(s).",
        tracks=queued_tracks,
        playlist=playlist,
        playback=playback,
        upcoming=upcoming.get("tracks", []),
        evidence=evidence,
        target_minutes=numeric_or_none(params.get("target_minutes")),
        eq_result=eq_result,
        volume_result=volume_result,
        crossfade_result=crossfade_result,
        lyrics_result=lyrics_result,
        history_result=history_result,
    )
    summary = f"Session ready with {len(state.get('queue', []))} local track(s)."
    return {
        "summary": summary,
        "action_completed": True,
        "safe_user_output": safe_output,
        "status": status,
        "tracks": queued_tracks,
        "queue": state.get("queue", []),
        "playlist": playlist,
        "equalizer": eq_result,
        "volume": volume_result,
        "crossfade": crossfade_result,
        "lyrics": lyrics_result,
        "history": history_result,
        "playback": playback,
        "upcoming": upcoming.get("tracks", []),
        "evidence": evidence,
    }


def session_candidate_queries(config: dict[str, Any], description: str, limit: int) -> list[str]:
    search_config = config.get("search", {})
    contexts = search_config.get("preferred_contexts", [])
    candidates = [description]
    if isinstance(contexts, list):
        for context in contexts:
            if isinstance(context, str) and context.strip():
                candidates.append(f"{description} {context.strip()}")
    return unique_texts(candidates)[:limit]


def select_session_eq_profile(config: dict[str, Any], requested: str, description: str) -> str:
    profiles = equalizer_profiles(config)
    if requested:
        requested_key = canonical_text(requested)
        for name in profiles:
            if canonical_text(name) == requested_key:
                return name
    description_key = canonical_text(description)
    for name in profiles:
        name_key = canonical_text(name)
        if name_key and name_key in description_key:
            return name
    return ""


def session_safe_output(
    summary: str,
    tracks: list[dict[str, Any]],
    playlist: str,
    playback: dict[str, Any],
    upcoming: list[dict[str, Any]],
    evidence: list[str],
    target_minutes: float | int | None,
    eq_result: dict[str, Any],
    volume_result: dict[str, Any],
    crossfade_result: dict[str, Any],
    lyrics_result: dict[str, Any],
    history_result: dict[str, Any],
) -> str:
    total_seconds = sum(int(track.get("duration_seconds") or track.get("duration") or 0) for track in tracks)
    lines = [summary]
    if target_minutes is not None:
        lines.append(f"Requested duration: {int(target_minutes)} minute(s). Actual queued duration: {round(total_seconds / 60, 1)} minute(s).")
    else:
        lines.append(f"Queued duration: {round(total_seconds / 60, 1)} minute(s).")
    if playlist:
        lines.append(f"Saved playlist: {playlist}.")
    if playback:
        lines.append(playback.get("summary", "Playback attempted."))
    if volume_result:
        lines.append(f"Volume: {volume_result.get('volume', '')}.")
    if crossfade_result:
        lines.append(crossfade_result.get("summary", "Crossfade updated."))
    if eq_result:
        lines.append(eq_result.get("summary", "Equalizer updated."))
    if lyrics_result:
        lines.append(lyrics_result.get("summary", "Lyrics checked."))
    if history_result:
        lines.append(history_result.get("summary", "History checked."))
    if upcoming:
        lines.append("Upcoming:")
        lines.extend(f"- {track.get('title', track.get('id'))}" for track in upcoming)
    lines.append("Evidence used:")
    lines.extend(f"- {item}" for item in evidence)
    return "\n".join(str(line) for line in lines if str(line).strip())


def entertainment_library(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    index = load_index(config)
    if operation == "scan":
        added, updated = scan_library(config, index)
        save_index(config, index)
        return {"summary": f"Library scan complete. Added {added}, updated {updated}.", "added": added, "updated": updated, "library": library_stats(config, index)}
    if operation == "stats":
        stats = library_stats(config, index)
        return {"summary": library_stats_summary(stats), "stats": stats}
    if operation == "search":
        limit = bounded_int(params.get("limit"), 1, 100, int(config.get("library", {}).get("max_search_results", 20)))
        results = library_search_results(index, optional_text(params, "query"), {}, limit)
        return {"summary": f"Found {len(results)} local item(s).", "results": results}
    if operation == "get":
        track_id = require_text(params, "track_id")
        track = index.get("tracks", {}).get(track_id)
        if not isinstance(track, dict):
            raise ToolInputError(f"Track not found: {track_id}")
        return {"summary": f"Track: {track.get('title', track_id)}", "track": track}
    if operation == "update":
        track_id = require_text(params, "track_id")
        values = params.get("values", {})
        if not isinstance(values, dict):
            raise ToolInputError("values must be an object")
        track = index.get("tracks", {}).get(track_id)
        if not isinstance(track, dict):
            raise ToolInputError(f"Track not found: {track_id}")
        for key, value in values.items():
            track[key] = value
        index["tracks"][track_id] = normalize_track(track, track_id)
        rebuild_library_indexes(index)
        save_index(config, index)
        return {"summary": f"Updated track: {index['tracks'][track_id].get('title', track_id)}", "track": index["tracks"][track_id]}
    if operation == "delete":
        track_id = require_text(params, "track_id")
        track = index.get("tracks", {}).pop(track_id, None)
        if not isinstance(track, dict):
            raise ToolInputError(f"Track not found: {track_id}")
        if bool(params.get("delete_file", False)):
            path = Path(str(track.get("file_path") or ""))
            if path.exists() and path.is_file():
                path.unlink()
        remove_track_from_all_lists(config, track_id)
        rebuild_library_indexes(index)
        save_index(config, index)
        save_config(config)
        return {"summary": f"Deleted library track: {track.get('title', track_id)}", "track": track}
    if operation == "deduplicate":
        duplicates = duplicate_groups(index)
        return {"summary": f"Found {len(duplicates)} duplicate group(s).", "duplicates": duplicates}
    if operation == "export":
        fmt = optional_text(params, "format", "json").casefold()
        output_path = export_library(config, index, optional_text(params, "path"), fmt)
        return {"summary": f"Exported library to {output_path}", "path": str(output_path)}
    if operation == "import_metadata":
        path = resolve_config_path(require_text(params, "path"))
        count = import_metadata_file(index, path)
        save_index(config, index)
        return {"summary": f"Imported metadata for {count} track(s).", "updated": count}
    raise ToolInputError(f"Unsupported library operation: {operation}")


def scan_library(config: dict[str, Any], index: dict[str, Any]) -> tuple[int, int]:
    library_config = config.get("library", {})
    audio = set(str(item).casefold() for item in library_config.get("supported_audio", []))
    video = set(str(item).casefold() for item in library_config.get("supported_video", []))
    podcast = set(str(item).casefold() for item in library_config.get("supported_podcast", []))
    roots = library_config.get("scan_roots", [])
    if not isinstance(roots, list):
        roots = [config.get("music_dir", str(DEFAULT_LIBRARY_DIR))]
    added = 0
    updated = 0
    seen_paths = {str(track.get("file_path")): track_id for track_id, track in index.get("tracks", {}).items() if isinstance(track, dict)}
    for raw_root in roots:
        root = resolve_config_path(raw_root)
        if not root.exists():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            suffix = path.suffix.lower().lstrip(".")
            if suffix not in audio and suffix not in video and suffix not in podcast:
                continue
            track = track_from_file(path, config)
            existing_id = seen_paths.get(str(path.resolve()))
            if existing_id and existing_id in index.get("tracks", {}):
                original = index["tracks"][existing_id]
                original.update({key: value for key, value in track.items() if value not in ("", [], None)})
                index["tracks"][existing_id] = normalize_track(original, existing_id)
                updated += 1
            else:
                upsert_track(index, track, track.get("aliases", []))
                added += 1
    rebuild_library_indexes(index)
    return added, updated


def track_from_file(path: Path, config: dict[str, Any]) -> dict[str, Any]:
    resolved = path.resolve()
    metadata = read_media_metadata(resolved)
    track_id = stable_track_id(str(resolved))
    media_type = media_type_from_path(str(resolved))
    if not media_type and resolved.suffix.lower().lstrip(".") in set(config.get("library", {}).get("supported_video", [])):
        media_type = "video"
    title = metadata.get("title") or resolved.stem
    return normalize_track(
        {
            "id": track_id,
            "type": media_type or "music",
            "title": title,
            "artist": metadata.get("artist", ""),
            "album": metadata.get("album", ""),
            "album_artist": metadata.get("album_artist", ""),
            "year": metadata.get("year"),
            "genre": metadata.get("genre", []),
            "duration_seconds": metadata.get("duration_seconds"),
            "file_path": str(resolved),
            "file_size_bytes": resolved.stat().st_size,
            "file_format": resolved.suffix.lower().lstrip("."),
            "download_complete": True,
            "aliases": [title, resolved.stem, str(resolved)],
        },
        track_id,
    )


def read_media_metadata(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        import mutagen

        media = mutagen.File(str(path), easy=True)
    except Exception:
        media = None
    if media is None:
        return result
    for key, target in [("title", "title"), ("artist", "artist"), ("album", "album"), ("albumartist", "album_artist"), ("date", "year")]:
        values = media.get(key) if hasattr(media, "get") else None
        if values:
            result[target] = str(values[0])
    genres = media.get("genre") if hasattr(media, "get") else None
    if genres:
        result["genre"] = [str(item) for item in genres]
    info = getattr(media, "info", None)
    length = getattr(info, "length", None)
    if isinstance(length, (int, float)):
        result["duration_seconds"] = int(length)
    return result


def library_stats(config: dict[str, Any], index: dict[str, Any]) -> dict[str, Any]:
    tracks = [track for track in index.get("tracks", {}).values() if isinstance(track, dict)]
    by_type: dict[str, int] = {}
    by_language: dict[str, int] = {}
    by_genre: dict[str, int] = {}
    total_duration = 0
    total_size = 0
    for track in tracks:
        increment(by_type, str(track.get("type") or "unknown"))
        language = str(track.get("language") or "unknown")
        increment(by_language, language)
        for genre in clean_list(track.get("genre")):
            increment(by_genre, genre)
        duration = numeric_or_none(track.get("duration_seconds"))
        total_duration += int(duration or 0)
        total_size += int(numeric_or_none(track.get("file_size_bytes")) or file_size(str(track.get("file_path") or "")))
    most_played = sorted(tracks, key=lambda item: int(item.get("play_count") or 0), reverse=True)[:10]
    recently_added = sorted(tracks, key=lambda item: str(item.get("added_at") or ""), reverse=True)[:10]
    never_played = [track for track in tracks if int(track.get("play_count") or 0) == 0]
    return {
        "total_tracks": len(tracks),
        "by_type": by_type,
        "by_language": by_language,
        "by_genre": by_genre,
        "total_duration_seconds": total_duration,
        "total_size_bytes": total_size,
        "most_played": [track_summary(index, str(track.get("id"))) for track in most_played],
        "recently_added": [track_summary(index, str(track.get("id"))) for track in recently_added],
        "never_played_count": len(never_played),
    }


def increment(values: dict[str, int], key: str) -> None:
    clean = key if key.strip() else "unknown"
    values[clean] = values.get(clean, 0) + 1


def library_stats_summary(stats: dict[str, Any]) -> str:
    return (
        f"Library: {stats.get('total_tracks', 0)} item(s), "
        f"{stats.get('total_duration_seconds', 0)} second(s), "
        f"{stats.get('total_size_bytes', 0)} byte(s)."
    )


def library_search_results(index: dict[str, Any], query: str = "", filters: dict[str, Any] | None = None, limit: int = 20) -> list[dict[str, Any]]:
    prepared = ensure_index_shape(index)
    tracks = prepared.get("tracks", {})
    filters = filters or {}
    candidate_ids = set(str(track_id) for track_id in tracks)
    for index_name, filter_key in [("by_type", "type"), ("by_language", "language"), ("by_genre", "genre"), ("by_mood", "mood")]:
        value = filters.get(filter_key)
        if not value:
            continue
        ids = prepared.get("indexes", {}).get(index_name, {}).get(canonical_text(str(value)), [])
        candidate_ids = candidate_ids.intersection(set(ids))
    query_key = canonical_text(query)
    words = query_key.split()
    scored: list[tuple[int, str, dict[str, Any]]] = []
    alias_hit = prepared.get("aliases", {}).get(query_key) if query_key else ""
    for track_id in candidate_ids:
        track = tracks.get(track_id)
        if not isinstance(track, dict):
            continue
        score = 1
        if alias_hit == track_id:
            score += 100
        if query_key:
            haystack = canonical_text(" ".join(track_text_fields(track)))
            if query_key and query_key in haystack:
                score += 50
            for word in words:
                if word and word in haystack:
                    score += 5
        if not query_key or score > 1:
            scored.append((score, str(track.get("title") or track_id), track_summary(prepared, track_id)))
    scored.sort(key=lambda item: (-item[0], item[1].casefold()))
    return [item[2] for item in scored[:limit]]


def track_text_fields(track: dict[str, Any]) -> list[str]:
    fields = [
        str(track.get("title") or ""),
        str(track.get("artist") or ""),
        str(track.get("album") or ""),
        str(track.get("language") or ""),
        str(track.get("source_platform") or ""),
        *clean_list(track.get("genre")),
        *clean_list(track.get("tags")),
        *clean_list(track.get("mood_tags")),
        *clean_list(track.get("aliases")),
    ]
    return fields


def duplicate_groups(index: dict[str, Any]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for track_id, track in index.get("tracks", {}).items():
        if not isinstance(track, dict):
            continue
        key = canonical_text(f"{track.get('title', '')} {track.get('artist', '')}")
        if not key:
            continue
        groups.setdefault(key, []).append(track_summary(index, track_id))
    return [{"match_key": key, "tracks": tracks} for key, tracks in groups.items() if len(tracks) > 1]


def export_library(config: dict[str, Any], index: dict[str, Any], path_value: str, fmt: str) -> Path:
    if path_value:
        output_path = resolve_config_path(path_value)
    else:
        output_path = media_path(config, "media_root", "media/entertainment") / f"library-export.{fmt}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tracks = list(index.get("tracks", {}).values())
    if fmt == "csv":
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["id", "type", "title", "artist", "album", "language", "duration_seconds", "file_path", "source_url"])
            writer.writeheader()
            for track in tracks:
                writer.writerow({key: track.get(key, "") for key in writer.fieldnames})
    else:
        write_json(output_path, {"tracks": tracks})
    return output_path


def import_metadata_file(index: dict[str, Any], path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    items = data.get("tracks") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ToolInputError("metadata file must contain a list or a tracks list")
    count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        track_id = str(item.get("id") or "")
        if track_id and track_id in index.get("tracks", {}):
            index["tracks"][track_id].update(item)
            index["tracks"][track_id] = normalize_track(index["tracks"][track_id], track_id)
            count += 1
    rebuild_library_indexes(index)
    return count


def remove_track_from_all_lists(config: dict[str, Any], track_id: str) -> None:
    remove_favorite(config, track_id)
    playlists = config.get("playlists", {})
    if isinstance(playlists, dict):
        for name in list(playlists):
            if isinstance(playlists.get(name), list):
                playlists[name] = [item for item in playlists[name] if item != track_id]


def entertainment_search(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    index = load_index(config)
    query = require_text(params, "query")
    context = optional_text(params, "context")
    limit = bounded_int(params.get("limit"), 1, 50, int(config.get("search_limit", 8)))
    media_type = optional_text(params, "media_type", "any")
    source = optional_text(params, "source")
    filters = {}
    if media_type and media_type != "any":
        filters["type"] = media_type
    local = library_search_results(index, query, filters, limit)
    results: list[dict[str, Any]] = [{"source": "local", "track": item, **item} for item in local]
    provider_errors: list[str] = []
    providers = config.get("search", {}).get("providers", [])
    should_online = (not source or source in {"youtube", "soundcloud", "online"}) and ("youtube" in providers or "soundcloud" in providers)
    if len(results) < limit and should_online:
        try:
            online = search_ytdlp(combined_query(query, context), limit - len(results))
            results.extend({"source": "youtube", **item} for item in online)
        except ToolInputError as error:
            provider_errors.append(str(error))
    summary = f"Found {len(results)} result(s) for {combined_query(query, context) or query}."
    if provider_errors and not results:
        summary += f" Provider unavailable: {provider_errors[0]}"
    return {"summary": summary, "query": combined_query(query, context) or query, "results": results[:limit], "provider_errors": provider_errors}


def entertainment_download(params: dict[str, Any]) -> dict[str, Any]:
    queries = params.get("queries")
    if isinstance(queries, list) and queries:
        downloads = []
        for query in queries:
            if isinstance(query, str) and query.strip():
                payload = dict(params)
                payload.pop("queries", None)
                payload["query"] = query
                downloads.append(entertainment_download(payload))
        return {"summary": f"Processed {len(downloads)} download request(s).", "downloads": downloads}

    config = load_config()
    index = load_index(config)
    query = optional_text(params, "query")
    url = optional_text(params, "url")
    context = optional_text(params, "context")
    media_type = optional_text(params, "media_type", "music")
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
            return {"summary": f"Already saved: {cached.get('title', cached['id'])} -> {cached.get('file_path')}", "cached": True, "track": cached}

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

    download_config = dict(config)
    if media_type == "video":
        selector = optional_text(params, "quality") or optional_text(params, "format") or str(config.get("download", {}).get("video_format_selector") or "")
        download_config["audio_format_selector"] = selector or config["download"]["video_format_selector"]
        download_config["music_dir"] = str(config.get("video_dir") or "media/entertainment/video")
    track = download_with_ytdlp(download_config, source_url, aliases, selected_result)
    track["type"] = media_type
    track = normalize_track(track)
    upsert_track(index, track, aliases)
    save_index(config, index)
    apply_track_lists(config, track["id"], add_to_favorites, playlist)
    lyrics_result = None
    if bool(params.get("fetch_lyrics", config.get("lyrics", {}).get("auto_fetch_on_download", False))) and media_type == "music":
        lyrics_result = entertainment_lyrics({"operation": "fetch", "track_id": track["id"]})
    return {"summary": f"Downloaded: {track.get('title', track['id'])} -> {track.get('file_path')}", "cached": False, "track": track, "lyrics": lyrics_result}


def track_from_info(info: dict[str, Any], file_path: Path, selected_result: dict[str, Any] | None = None) -> dict[str, Any]:
    title = str(info.get("title") or (selected_result or {}).get("title") or file_path.stem)
    webpage_url = str(info.get("webpage_url") or info.get("original_url") or (selected_result or {}).get("webpage_url") or "")
    source_id = str(info.get("id") or (selected_result or {}).get("id") or "")
    track_id = stable_track_id(source_id or webpage_url or str(file_path))
    return normalize_track(
        {
            "id": track_id,
            "source_id": source_id,
            "title": title,
            "artist": info.get("artist") or info.get("channel") or info.get("uploader") or (selected_result or {}).get("channel") or "",
            "webpage_url": webpage_url,
            "source_url": webpage_url,
            "file_path": str(file_path),
            "duration_seconds": info.get("duration") or (selected_result or {}).get("duration"),
            "channel": info.get("channel") or info.get("uploader") or (selected_result or {}).get("channel"),
            "saved_at": time.time(),
            "aliases": [title, webpage_url],
        },
        track_id,
    )


def resolve_track(config: dict[str, Any], index: dict[str, Any], params: dict[str, Any], auto_download: bool = False) -> dict[str, Any] | None:
    track_id = optional_text(params, "track_id")
    if track_id:
        track = index.get("tracks", {}).get(track_id)
        if isinstance(track, dict):
            return normalize_track(track, track_id)
    path = optional_text(params, "path")
    if path:
        local = resolve_config_path(path)
        if local.exists():
            return track_from_file(local, config)
    query = optional_text(params, "query")
    url = optional_text(params, "url")
    cached = cached_track(index, aliases_for(query, url))
    if cached is not None:
        return cached
    if query:
        results = library_search_results(index, query, {}, 1)
        if results:
            track = index.get("tracks", {}).get(results[0]["id"])
            if isinstance(track, dict) and track_file_available(track):
                return track
    if auto_download and (query or url):
        downloaded = entertainment_download({"query": query, "url": url, "context": optional_text(params, "context"), "force": False})
        return downloaded["track"]
    return None


def entertainment_play(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    index = load_index(config)
    track = resolve_track(config, index, params, auto_download=bool(params.get("auto_download", False)))
    if track is None and bool(params.get("stream", False)):
        return entertainment_stream_direct({"query": optional_text(params, "query"), "url": optional_text(params, "url")})
    if track is None:
        raise ToolInputError("Track is not downloaded yet. Use entertainment_download, stream directly, or set auto_download.")
    if bool(params.get("add_to_queue", False)):
        state = load_state(config)
        append_queue(state, track["id"])
        save_state(config, state)
        return {"summary": f"Queued: {track.get('title', track['id'])}", "track": track, "queue": state.get("queue", [])}

    state = load_state(config)
    stop_player(state)
    state["queue"] = [track["id"]]
    state["current_index"] = 0
    state["player_pid"] = None
    state["started_at"] = time.time()
    state["playback_status"] = "playing"
    start_queue_playback(config, index, state)
    state["backend"] = choose_player_backend(config)["name"]
    update_track_play(index, track["id"])
    append_session_history(state, track["id"])
    save_index(config, index)
    save_state(config, state)
    entertainment_history({"operation": "log", "track_id": track["id"], "context": current_context(config)})
    return {"summary": f"Playing: {track.get('title', track['id'])}", "track": track, "queue": state.get("queue", []), "player": playback_state_payload(config, index, state)}


def entertainment_stream_direct(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    query = optional_text(params, "query")
    url = optional_text(params, "url")
    if not url and query:
        results = entertainment_search({"query": query, "limit": 1})
        for item in results.get("results", []):
            candidate = str(item.get("webpage_url") or item.get("source_url") or "")
            if candidate:
                url = candidate
                break
    if not url:
        raise ToolInputError("query or url with a streamable result is required")
    backend = choose_player_backend(config, direct_stream=True)
    if not backend["available"] or not backend["supports_stream"]:
        raise ToolInputError("Direct streaming requires VLC, mpv, ffplay, or dry-run player mode")
    state = load_state(config)
    stop_player(state)
    pid = start_stream_process(config, backend["name"], url)
    state["player_pid"] = pid
    state["playback_status"] = "playing"
    state["backend"] = backend["name"]
    state["stream"] = {"url": url, "query": query, "started_at": now_iso()}
    save_state(config, state)
    return {"summary": f"Streaming: {query or url}", "url": url, "backend": backend["name"], "player": playback_state_payload(config, load_index(config), state)}


def start_stream_process(config: dict[str, Any], backend: str, url: str) -> int | None:
    if dry_run_enabled(config):
        return 0
    player = config.get("player", {})
    if backend == "vlc":
        executable = str(player.get("vlc_executable") or "vlc")
    elif backend == "mpv":
        executable = str(player.get("mpv_executable") or "mpv")
    elif backend == "ffplay":
        executable = str(player.get("ffplay_executable") or "ffplay")
    else:
        raise ToolInputError("Selected backend does not support direct streaming")
    if not executable_available(executable):
        raise ToolInputError(f"Player executable is missing: {executable}")
    process = subprocess.Popen([executable, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return process.pid


def entertainment_playback(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    index = load_index(config)
    state = load_state(config)
    if operation == "play":
        if optional_text(params, "query") or optional_text(params, "track_id") or optional_text(params, "path"):
            return entertainment_play(params)
        return entertainment_queue({"operation": "play"})
    if operation == "get_state":
        return playback_state_payload(config, index, state)
    if operation == "stop":
        return entertainment_queue({"operation": "stop"})
    if operation in {"next", "previous"}:
        return entertainment_queue({"operation": operation})
    if operation == "replay":
        if not state.get("queue"):
            raise ToolInputError("Queue is empty")
        state["current_index"] = bounded_int(state.get("current_index"), 0, len(state["queue"]) - 1, 0)
        start_queue_playback(config, index, state)
        state["playback_status"] = "playing"
        save_state(config, state)
        return playback_state_payload(config, index, state, "Replaying current track.")
    if operation == "pause":
        state["playback_status"] = "paused"
        save_state(config, state)
        return playback_state_payload(config, index, state, "Playback pause recorded.")
    if operation == "resume":
        state["playback_status"] = "playing"
        save_state(config, state)
        return playback_state_payload(config, index, state, "Playback resume recorded.")
    if operation == "seek":
        seconds = numeric_or_none(params.get("seconds"))
        percentage = numeric_or_none(params.get("percentage"))
        state["position_seconds"] = seconds if seconds is not None else state.get("position_seconds", 0)
        state["position_percentage"] = percentage if percentage is not None else state.get("position_percentage", None)
        save_state(config, state)
        return playback_state_payload(config, index, state, "Seek position recorded.")
    if operation == "volume":
        state["volume"] = bounded_int(params.get("value"), 0, 100, int(state.get("volume") or config.get("player", {}).get("volume") or 100))
        save_state(config, state)
        return playback_state_payload(config, index, state, f"Volume set to {state['volume']}.")
    if operation == "speed":
        value = numeric_or_none(params.get("value")) or 1.0
        state["speed"] = max(0.5, min(3.0, float(value)))
        save_state(config, state)
        return playback_state_payload(config, index, state, f"Speed set to {state['speed']}x.")
    if operation in {"mute", "unmute"}:
        state["muted"] = operation == "mute"
        save_state(config, state)
        return playback_state_payload(config, index, state, "Muted." if state["muted"] else "Unmuted.")
    if operation == "crossfade":
        player = config.setdefault("player", {})
        player["crossfade_enabled"] = bool(params.get("enabled", True))
        if numeric_or_none(params.get("seconds")) is not None:
            player["crossfade_seconds"] = int(params["seconds"])
        save_config(config)
        backend = choose_player_backend(config)
        prefix = "Crossfade updated." if backend.get("name") in {"vlc", "mpv", "dry_run"} else f"Crossfade saved, but active backend {backend.get('name') or 'unavailable'} does not support live crossfade."
        return playback_state_payload(config, index, state, prefix)
    if operation == "sleep_timer":
        minutes = numeric_or_none(params.get("minutes"))
        if minutes is None or minutes <= 0:
            state["sleep_timer_until"] = ""
        else:
            state["sleep_timer_until"] = (datetime.now(timezone.utc) + timedelta(minutes=float(minutes))).isoformat()
        save_state(config, state)
        return playback_state_payload(config, index, state, "Sleep timer updated.")
    raise ToolInputError(f"Unsupported playback operation: {operation}")


def playback_state_payload(config: dict[str, Any], index: dict[str, Any], state: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    backend = choose_player_backend(config)
    track = current_track(index, state)
    running = process_is_running(state.get("player_pid"))
    summary_parts = [prefix] if prefix else []
    summary_parts.append(f"Player {state.get('playback_status', 'stopped')}.")
    if track:
        summary_parts.append(f"Current: {track.get('title', track.get('id'))}.")
    summary_parts.append(f"Backend: {state.get('backend') or backend['name'] or 'unavailable'}.")
    return {
        "summary": " ".join(part for part in summary_parts if part),
        "state": state,
        "current_track": track,
        "queue": state.get("queue", []),
        "current_index": state.get("current_index", -1),
        "player_running": running,
        "backend": state.get("backend") or backend["name"],
        "backend_available": backend["available"],
        "backend_supports_eq": backend["supports_eq"],
        "volume": state.get("volume", 100),
        "speed": state.get("speed", 1.0),
        "muted": state.get("muted", False),
        "sleep_timer_until": state.get("sleep_timer_until", ""),
    }


def current_track(index: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    queue = state.get("queue", [])
    if not isinstance(queue, list) or not queue:
        return {}
    current_index = bounded_int(state.get("current_index"), 0, len(queue) - 1, 0)
    track_id = str(queue[current_index])
    track = index.get("tracks", {}).get(track_id)
    return normalize_track(track, track_id) if isinstance(track, dict) else {}


def update_track_play(index: dict[str, Any], track_id: str) -> None:
    track = index.get("tracks", {}).get(track_id)
    if not isinstance(track, dict):
        return
    now = now_iso()
    track["play_count"] = int(track.get("play_count") or 0) + 1
    track["last_played_at"] = now
    if not track.get("first_played_at"):
        track["first_played_at"] = now
    index["tracks"][track_id] = normalize_track(track, track_id)
    rebuild_library_indexes(index)


def append_session_history(state: dict[str, Any], track_id: str) -> None:
    history = state.setdefault("session_history", [])
    if not isinstance(history, list):
        history = []
        state["session_history"] = history
    history.append({"track_id": track_id, "at": now_iso()})


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
        state["playback_status"] = "stopped"
        save_state(config, state)
        return {"summary": "Playback stopped.", "queue": state.get("queue", [])}
    if operation == "add":
        ids = resolve_track_ids_for_queue(config, index, params)
        if not ids:
            raise ToolInputError("No local playable tracks resolved for queue add")
        for track_id in ids:
            insert_queue(state, track_id, params)
        save_state(config, state)
        return {"summary": f"Queued {len(ids)} track(s).", "queue": state.get("queue", []), "tracks": tracks_from_ids(index, ids)}
    if operation == "remove":
        removed = remove_from_queue(state, optional_text(params, "track_id"), params.get("position"))
        save_state(config, state)
        return {"summary": f"Removed {removed} queue item(s).", "queue": state.get("queue", [])}
    if operation == "shuffle":
        mode = optional_text(params, "mode", "random")
        shuffle_queue(state, index, mode)
        save_state(config, state)
        return {"summary": f"Queue shuffled: {mode}.", "queue": state.get("queue", [])}
    if operation == "repeat":
        state["repeat_mode"] = optional_text(params, "repeat_mode", "off")
        save_state(config, state)
        return {"summary": f"Repeat mode: {state['repeat_mode']}.", "repeat_mode": state["repeat_mode"]}
    if operation == "move":
        move_queue_item(state, params.get("from_position"), params.get("to_position"))
        save_state(config, state)
        return {"summary": "Queue item moved.", "queue": state.get("queue", [])}
    if operation == "reorder":
        reorder_queue(state, index, optional_text(params, "by", "rating"))
        save_state(config, state)
        return {"summary": f"Queue reordered by {optional_text(params, 'by', 'rating')}.", "queue": state.get("queue", [])}
    if operation == "save_as_playlist":
        playlist = require_text(params, "playlist")
        config.setdefault("playlists", {})[playlist] = [str(item) for item in state.get("queue", [])]
        save_config(config)
        return {"summary": f"Saved queue as playlist {playlist}.", "playlist": playlist, "count": len(state.get("queue", []))}
    if operation == "smart_extend":
        count = bounded_int(params.get("limit"), 1, 50, int(config.get("recommendations", {}).get("smart_queue_add_count", 5)))
        added = smart_extend_queue(config, index, state, count)
        save_state(config, state)
        return {"summary": f"Smart-extended queue with {len(added)} track(s).", "queue": state.get("queue", []), "added": tracks_from_ids(index, added)}
    if operation == "upcoming":
        limit = bounded_int(params.get("limit"), 1, 50, 10)
        queue = state.get("queue", [])
        start = bounded_int(state.get("current_index"), 0, max(0, len(queue) - 1), 0) + 1 if queue else 0
        ids = [str(item) for item in queue[start : start + limit]]
        return {"summary": f"Upcoming {len(ids)} track(s).", "tracks": tracks_from_ids(index, ids)}
    if operation == "history_in_session":
        return {"summary": f"Session history: {len(state.get('session_history', []))} item(s).", "history": state.get("session_history", [])}
    if operation == "play_playlist":
        playlist, ids = resolve_playlist_for_play(config, index, optional_text(params, "playlist"))
        if not ids:
            raise ToolInputError("No playable playlist found")
        stop_player(state)
        state = load_state(config)
        state["queue"] = ids
        state["current_index"] = 0
        state["started_at"] = time.time()
        state["playback_status"] = "playing"
        start_queue_playback(config, index, state)
        state["backend"] = choose_player_backend(config)["name"]
        append_session_history(state, ids[0])
        update_track_play(index, ids[0])
        save_index(config, index)
        save_state(config, state)
        entertainment_history({"operation": "log", "track_id": ids[0], "context": current_context(config)})
        return {"summary": f"Playing playlist {playlist}: {len(ids)} track(s).", "playlist": playlist, "queue": ids, "tracks": tracks_from_ids(index, ids)}
    if operation == "play":
        if not state.get("queue"):
            raise ToolInputError("Queue is empty")
        state["current_index"] = bounded_int(state.get("current_index"), 0, len(state["queue"]) - 1, 0)
        state["playback_status"] = "playing"
        start_queue_playback(config, index, state)
        state["backend"] = choose_player_backend(config)["name"]
        current_id = str(state["queue"][state["current_index"]])
        append_session_history(state, current_id)
        update_track_play(index, current_id)
        save_index(config, index)
        save_state(config, state)
        entertainment_history({"operation": "log", "track_id": current_id, "context": current_context(config)})
        return queue_status(config, index, state, prefix="Playing queue.")
    if operation in {"next", "previous"}:
        if not state.get("queue"):
            raise ToolInputError("Queue is empty")
        step = 1 if operation == "next" else -1
        current = bounded_int(state.get("current_index"), 0, len(state["queue"]) - 1, 0)
        if operation == "next" and current >= len(state["queue"]) - 1 and state.get("repeat_mode") == "queue":
            state["current_index"] = 0
        else:
            state["current_index"] = max(0, min(len(state["queue"]) - 1, current + step))
        state["playback_status"] = "playing"
        start_queue_playback(config, index, state)
        current_id = str(state["queue"][state["current_index"]])
        append_session_history(state, current_id)
        update_track_play(index, current_id)
        save_index(config, index)
        save_state(config, state)
        entertainment_history({"operation": "log", "track_id": current_id, "context": current_context(config)})
        return queue_status(config, index, state, prefix=f"{operation.title()} track.")
    raise ToolInputError(f"Unsupported queue operation: {operation}")


def resolve_track_ids_for_queue(config: dict[str, Any], index: dict[str, Any], params: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    raw_ids = params.get("track_ids")
    if isinstance(raw_ids, list):
        ids.extend(str(item) for item in raw_ids if isinstance(item, str) and item in index.get("tracks", {}))
    track = resolve_track(config, index, params, auto_download=bool(params.get("auto_download", False)))
    if track is not None:
        ids.append(str(track["id"]))
    return unique_texts(ids)


def insert_queue(state: dict[str, Any], track_id: str, params: dict[str, Any]) -> None:
    queue = state.setdefault("queue", [])
    if not isinstance(queue, list):
        queue = []
        state["queue"] = queue
    mode = optional_text(params, "mode")
    position = params.get("position")
    if mode == "next" and state.get("current_index", -1) >= 0:
        index = int(state.get("current_index", 0)) + 1
        queue.insert(index, track_id)
    elif isinstance(position, int):
        queue.insert(max(0, min(len(queue), position)), track_id)
    else:
        queue.append(track_id)
    if state.get("current_index", -1) < 0:
        state["current_index"] = 0


def remove_from_queue(state: dict[str, Any], track_id: str, position: Any) -> int:
    queue = state.get("queue", [])
    if not isinstance(queue, list):
        return 0
    before = len(queue)
    if isinstance(position, int):
        index = position - 1 if position > 0 else position
        if 0 <= index < len(queue):
            queue.pop(index)
    elif track_id:
        queue[:] = [item for item in queue if item != track_id]
    state["queue"] = queue
    if queue:
        state["current_index"] = max(0, min(int(state.get("current_index") or 0), len(queue) - 1))
    else:
        state["current_index"] = -1
    return before - len(queue)


def shuffle_queue(state: dict[str, Any], index: dict[str, Any], mode: str) -> None:
    queue = [str(item) for item in state.get("queue", [])]
    current = current_track(index, state)
    remaining = queue
    if current:
        remaining = [item for item in queue if item != current.get("id")]
    if mode == "smart":
        remaining.sort(key=lambda track_id: canonical_text(str(index.get("tracks", {}).get(track_id, {}).get("artist", ""))))
    elif mode == "weighted":
        remaining.sort(key=lambda track_id: float(index.get("tracks", {}).get(track_id, {}).get("rating", 0)), reverse=True)
    else:
        random.shuffle(remaining)
    state["queue"] = ([current["id"]] if current else []) + remaining
    state["current_index"] = 0 if state["queue"] else -1
    state["shuffle"] = mode


def move_queue_item(state: dict[str, Any], from_position: Any, to_position: Any) -> None:
    queue = state.get("queue", [])
    if not isinstance(queue, list) or not isinstance(from_position, int) or not isinstance(to_position, int):
        raise ToolInputError("from_position and to_position are required")
    source = from_position - 1 if from_position > 0 else from_position
    target = to_position - 1 if to_position > 0 else to_position
    if not (0 <= source < len(queue)):
        raise ToolInputError("from_position is outside the queue")
    item = queue.pop(source)
    queue.insert(max(0, min(len(queue), target)), item)


def reorder_queue(state: dict[str, Any], index: dict[str, Any], by: str) -> None:
    queue = [str(item) for item in state.get("queue", [])]
    def key(track_id: str) -> Any:
        track = index.get("tracks", {}).get(track_id, {})
        if by == "play_count":
            return -int(track.get("play_count") or 0)
        if by == "duration":
            return int(track.get("duration_seconds") or 0)
        if by == "bpm":
            return int(track.get("bpm") or 0)
        if by == "mood":
            return " ".join(clean_list(track.get("mood_tags")))
        return -float(track.get("rating") or 0)
    queue.sort(key=key)
    state["queue"] = queue
    state["current_index"] = 0 if queue else -1


def smart_extend_queue(config: dict[str, Any], index: dict[str, Any], state: dict[str, Any], count: int) -> list[str]:
    queue = [str(item) for item in state.get("queue", [])]
    excluded = set(queue)
    seeds = queue[-3:] if queue else []
    candidates: list[str] = []
    for seed in seeds:
        for item in similar_track_ids(index, seed, count * 2):
            if item not in excluded and item not in candidates:
                candidates.append(item)
    if len(candidates) < count:
        for item in top_local_track_ids(index, "rating", count * 2):
            if item not in excluded and item not in candidates:
                candidates.append(item)
    added = candidates[:count]
    for track_id in added:
        append_queue(state, track_id)
    return added


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
    summary_parts.append(f"Player: {state.get('playback_status', 'stopped')}.")
    return {
        "summary": " ".join(summary_parts),
        "queue": queue,
        "current_index": current_index,
        "current_track": normalize_track(track, str(current_id)) if isinstance(track, dict) and track else {},
        "player_running": running,
        "repeat_mode": state.get("repeat_mode", "off"),
        "shuffle": state.get("shuffle", "off"),
        "remaining_count": max(0, len(queue) - current_index - 1) if queue else 0,
    }


def entertainment_playlist(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    index = load_index(config)
    playlists = config.setdefault("playlists", {})
    if not isinstance(playlists, dict):
        playlists = {}
        config["playlists"] = playlists
    if operation == "list":
        overview = playlist_overview(config, index)
        return {"summary": overview["summary"], "playlists": playlists, "playlist_tracks": overview["playlist_tracks"]}
    if operation == "show":
        playlist = require_text(params, "playlist")
        ids = playlist_ids(config, playlist)
        tracks = [track_summary(index, track_id) for track_id in ids]
        return {"summary": playlist_detail_summary(config, playlist, tracks), "playlist": playlist, "tracks": tracks}
    if operation == "create":
        playlist = require_text(params, "playlist")
        playlists.setdefault(playlist, [])
        save_config(config)
        return {"summary": f"Playlist ready: {playlist}", "playlist": playlist}
    if operation == "delete":
        playlist = require_text(params, "playlist")
        playlists.pop(playlist, None)
        save_config(config)
        return {"summary": f"Deleted playlist: {playlist}", "playlist": playlist}
    if operation in {"add_track", "add_favorite"}:
        playlist = "favorites" if operation == "add_favorite" else require_text(params, "playlist")
        track = resolve_track(config, index, params, auto_download=bool(params.get("auto_download", False)))
        if track is None:
            track = current_playing_track(config, index)
        if track is None:
            raise ToolInputError("No local track was resolved. Name a downloaded track, play a local track first, or use auto_download.")
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
    if operation == "reorder":
        playlist = require_text(params, "playlist")
        ids = playlist_ids(config, playlist)
        temp_state = {"queue": ids, "current_index": 0}
        reorder_queue(temp_state, index, optional_text(params, "by", "rating"))
        playlists[playlist] = temp_state["queue"]
        save_config(config)
        return {"summary": f"Reordered playlist {playlist}.", "playlist": playlist, "tracks": tracks_from_ids(index, playlists[playlist])}
    if operation == "play":
        return entertainment_queue({"operation": "play_playlist", "playlist": optional_text(params, "playlist")})
    if operation == "merge":
        target = require_text(params, "target_playlist")
        sources = params.get("source_playlists", [])
        if not isinstance(sources, list):
            raise ToolInputError("source_playlists must be a list")
        merged: list[str] = []
        for source in sources:
            if isinstance(source, str):
                merged.extend(playlist_ids(config, source))
        playlists[target] = unique_texts(merged)
        save_config(config)
        return {"summary": f"Merged {len(sources)} playlist(s) into {target}.", "playlist": target, "count": len(playlists[target])}
    if operation == "smart_create":
        playlist = require_text(params, "playlist")
        criteria = params.get("criteria", {})
        if not isinstance(criteria, dict):
            criteria = {}
        tracks = smart_playlist_tracks(index, criteria)
        playlists[playlist] = [track["id"] for track in tracks]
        save_config(config)
        return {"summary": f"Created smart playlist {playlist}: {len(tracks)} track(s).", "playlist": playlist, "tracks": tracks}
    if operation == "export":
        playlist = require_text(params, "playlist")
        path = export_playlist(config, index, playlist, optional_text(params, "path"), optional_text(params, "format", "json"))
        return {"summary": f"Exported playlist {playlist} to {path}", "path": str(path)}
    if operation == "import":
        playlist = require_text(params, "playlist")
        count = import_playlist(config, index, playlist, resolve_config_path(require_text(params, "path")))
        save_index(config, index)
        save_config(config)
        return {"summary": f"Imported {count} item(s) into {playlist}.", "playlist": playlist, "count": count}
    if operation == "duplicate":
        source = require_text(params, "playlist")
        target = require_text(params, "target_playlist")
        playlists[target] = list(playlist_ids(config, source))
        save_config(config)
        return {"summary": f"Duplicated {source} to {target}.", "playlist": target}
    raise ToolInputError(f"Unsupported playlist operation: {operation}")


def smart_playlist_tracks(index: dict[str, Any], criteria: dict[str, Any]) -> list[dict[str, Any]]:
    filters = {}
    for source, target in [("genre", "genre"), ("language", "language"), ("mood", "mood"), ("type", "type")]:
        if criteria.get(source):
            filters[target] = criteria[source]
    limit = bounded_int(criteria.get("limit"), 1, 500, 100)
    query = " ".join(str(criteria.get(key) or "") for key in ["artist", "query"]).strip()
    results = library_search_results(index, query, filters, limit)
    minimum_rating = numeric_or_none(criteria.get("minimum_rating"))
    if minimum_rating is not None:
        results = [track for track in results if float(index.get("tracks", {}).get(track["id"], {}).get("rating", 0)) >= float(minimum_rating)]
    return results


def export_playlist(config: dict[str, Any], index: dict[str, Any], playlist: str, path_value: str, fmt: str) -> Path:
    ids = playlist_ids(config, playlist)
    if path_value:
        output = resolve_config_path(path_value)
    else:
        output = media_path(config, "playlists_dir", "media/entertainment/playlists") / f"{canonical_text(playlist).replace(' ', '_') or 'playlist'}.{fmt}"
    output.parent.mkdir(parents=True, exist_ok=True)
    tracks = tracks_from_ids(index, ids)
    if fmt == "m3u":
        lines = ["#EXTM3U"]
        for track in tracks:
            if track.get("file_path"):
                lines.append(str(track["file_path"]))
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif fmt == "txt":
        output.write_text("\n".join(str(track.get("title") or track.get("id")) for track in tracks) + "\n", encoding="utf-8")
    else:
        write_json(output, {"playlist": playlist, "tracks": tracks})
    return output


def import_playlist(config: dict[str, Any], index: dict[str, Any], playlist: str, path: Path) -> int:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    count = 0
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        candidate = resolve_config_path(text)
        if candidate.exists():
            track = track_from_file(candidate, config)
            upsert_track(index, track, track.get("aliases", []))
            add_track_to_playlist(config, playlist, track["id"])
            count += 1
    return count


def entertainment_mood(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    index = load_index(config)
    if operation == "get_context":
        return {"summary": f"Current context: {current_context(config)}", "context": current_context(config)}
    if operation == "set_context":
        context = require_text(params, "context")
        path = json_store_path(config, "mood", "context_path", "media/entertainment/mood_context.json")
        write_json(path, {"context": context, "updated_at": now_iso()})
        return {"summary": f"Entertainment context set: {context}", "context": context}
    if operation == "detect":
        ids = params.get("track_ids")
        if not isinstance(ids, list) or not ids:
            state = load_state(config)
            ids = [str(item) for item in state.get("queue", [])]
        profile = detect_mood_profile(index, [str(item) for item in ids])
        return {"summary": f"Mood profile for {len(ids)} track(s).", "profile": profile}
    if operation == "match":
        description = require_text(params, "description")
        limit = bounded_int(params.get("limit"), 1, 50, 15)
        matches = mood_matches(index, description, limit)
        return {"summary": f"Matched {len(matches)} local track(s) for mood.", "tracks": matches, "fallback_search_query": description if len(matches) < limit else ""}
    raise ToolInputError(f"Unsupported mood operation: {operation}")


def current_context(config: dict[str, Any]) -> str:
    path = json_store_path(config, "mood", "context_path", "media/entertainment/mood_context.json")
    data = load_json_store(path, {})
    if isinstance(data.get("context"), str) and data["context"].strip():
        return data["context"]
    return str(config.get("mood", {}).get("default_context") or "casual")


def detect_mood_profile(index: dict[str, Any], ids: list[str]) -> dict[str, Any]:
    tracks = [index.get("tracks", {}).get(track_id) for track_id in ids]
    tracks = [track for track in tracks if isinstance(track, dict)]
    energy_values: list[float] = []
    bpm_values: list[float] = []
    moods: dict[str, int] = {}
    genres: dict[str, int] = {}
    languages: dict[str, int] = {}
    for track in tracks:
        bpm = numeric_or_none(track.get("bpm"))
        if bpm is not None:
            bpm_values.append(float(bpm))
            energy_values.append(min(10.0, max(0.0, float(bpm) / 18.0)))
        for mood in clean_list(track.get("mood_tags")):
            increment(moods, mood)
        for genre in clean_list(track.get("genre")):
            increment(genres, genre)
        if track.get("language"):
            increment(languages, str(track.get("language")))
    average_energy = sum(energy_values) / len(energy_values) if energy_values else 5.0
    return {
        "energy": round(average_energy, 2),
        "valence": round(average_energy, 2),
        "danceability": round(average_energy, 2),
        "dominant_genres": top_counts(genres),
        "dominant_languages": top_counts(languages),
        "dominant_moods": top_counts(moods),
        "tempo_range": [min(bpm_values), max(bpm_values)] if bpm_values else [],
    }


def top_counts(values: dict[str, int], limit: int = 5) -> list[dict[str, Any]]:
    return [{"name": key, "count": count} for key, count in sorted(values.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def mood_matches(index: dict[str, Any], description: str, limit: int) -> list[dict[str, Any]]:
    words = canonical_text(description).split()
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for track_id, track in index.get("tracks", {}).items():
        if not isinstance(track, dict):
            continue
        haystack = canonical_text(" ".join(track_text_fields(track)))
        score = sum(1 for word in words if word and word in haystack)
        if score:
            scored.append((score, str(track.get("title") or track_id), track_summary(index, track_id)))
    scored.sort(key=lambda item: (-item[0], item[1].casefold()))
    return [item[2] for item in scored[:limit]]


def entertainment_recommend(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    index = load_index(config)
    limit = bounded_int(params.get("limit"), 1, 100, 10)
    if operation in {"similar", "because_you_liked"}:
        track_id = require_text(params, "track_id")
        ids = similar_track_ids(index, track_id, limit)
        return {"summary": f"Found {len(ids)} similar local track(s).", "tracks": tracks_from_ids(index, ids)}
    if operation == "for_mood":
        mood = require_text(params, "mood")
        tracks = mood_matches(index, mood, limit)
        return {"summary": f"Recommended {len(tracks)} local track(s) for mood.", "tracks": tracks, "fallback_search_query": mood if len(tracks) < limit else ""}
    if operation == "artist_deep":
        artist = require_text(params, "artist")
        tracks = library_search_results(index, artist, {}, limit)
        return {"summary": f"Artist deep dive found {len(tracks)} local track(s).", "tracks": tracks, "discovery_queries": [artist] if len(tracks) < limit else []}
    if operation == "discovery":
        insights = entertainment_history({"operation": "insights"})
        seeds = top_local_track_ids(index, "rating", limit)
        return {"summary": "Discovery seeds built from taste profile and local history.", "tracks": tracks_from_ids(index, seeds), "insights": insights.get("insights", ""), "search_queries": discovery_queries(index, seeds)}
    if operation == "weekly_mix":
        playlist = optional_text(params, "playlist", f"weekly-mix-{datetime.now().date().isoformat()}")
        ids = unique_texts([*top_local_track_ids(index, "play_count", limit), *top_local_track_ids(index, "rating", limit)])[:limit]
        config.setdefault("playlists", {})[playlist] = ids
        save_config(config)
        return {"summary": f"Weekly mix saved: {playlist} with {len(ids)} track(s).", "playlist": playlist, "tracks": tracks_from_ids(index, ids)}
    if operation == "top_tracks":
        ids = top_local_track_ids(index, optional_text(params, "range", "play_count"), limit)
        return {"summary": f"Top tracks: {len(ids)}.", "tracks": tracks_from_ids(index, ids)}
    if operation == "never_played":
        ids = [track_id for track_id, track in index.get("tracks", {}).items() if isinstance(track, dict) and int(track.get("play_count") or 0) == 0][:limit]
        return {"summary": f"Never played: {len(ids)} track(s).", "tracks": tracks_from_ids(index, ids)}
    if operation == "rediscover":
        ids = top_local_track_ids(index, "rediscover", limit)
        return {"summary": f"Rediscovery picks: {len(ids)} track(s).", "tracks": tracks_from_ids(index, ids)}
    raise ToolInputError(f"Unsupported recommendation operation: {operation}")


def similar_track_ids(index: dict[str, Any], track_id: str, limit: int) -> list[str]:
    seed = index.get("tracks", {}).get(track_id)
    if not isinstance(seed, dict):
        raise ToolInputError(f"Track not found: {track_id}")
    seed_values = set(canonical_text(value) for value in track_text_fields(seed) if canonical_text(value))
    scored: list[tuple[int, str, str]] = []
    for candidate_id, track in index.get("tracks", {}).items():
        if candidate_id == track_id or not isinstance(track, dict):
            continue
        values = set(canonical_text(value) for value in track_text_fields(track) if canonical_text(value))
        score = len(seed_values.intersection(values))
        if score:
            scored.append((score, str(track.get("title") or candidate_id), candidate_id))
    scored.sort(key=lambda item: (-item[0], item[1].casefold()))
    return [item[2] for item in scored[:limit]]


def top_local_track_ids(index: dict[str, Any], by: str, limit: int) -> list[str]:
    tracks = [(track_id, track) for track_id, track in index.get("tracks", {}).items() if isinstance(track, dict)]
    if by == "rating":
        tracks.sort(key=lambda item: float(item[1].get("rating") or 0), reverse=True)
    elif by == "rediscover":
        tracks.sort(key=lambda item: (str(item[1].get("last_played_at") or ""), float(item[1].get("rating") or 0)))
    else:
        tracks.sort(key=lambda item: int(item[1].get("play_count") or 0), reverse=True)
    return [track_id for track_id, _track in tracks[:limit]]


def discovery_queries(index: dict[str, Any], ids: list[str]) -> list[str]:
    queries: list[str] = []
    for track_id in ids:
        track = index.get("tracks", {}).get(track_id, {})
        artist = str(track.get("artist") or "")
        genre = " ".join(clean_list(track.get("genre"))[:1])
        query = " ".join(item for item in [artist, genre] if item).strip()
        if query:
            queries.append(query)
    return unique_texts(queries)[:10]


def entertainment_lyrics(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    index = load_index(config)
    track = resolve_track(config, index, params, auto_download=False)
    track_id = track.get("id") if track else optional_text(params, "track_id")
    if operation in {"fetch", "fetch_synced", "show", "current_line", "translate", "annotate"} and not track_id:
        raise ToolInputError("track_id or resolvable query is required")
    lyrics_path = lyric_path(config, str(track_id), synced=operation == "fetch_synced")
    if operation in {"fetch", "fetch_synced"}:
        if lyrics_path.exists():
            return {"summary": f"Lyrics already cached: {lyrics_path}", "available": True, "path": str(lyrics_path), "synced": operation == "fetch_synced"}
        return {"summary": "No cached lyrics found and no configured lyrics source returned content.", "available": False, "path": str(lyrics_path), "synced": operation == "fetch_synced"}
    if operation == "show":
        path = existing_lyric_path(config, str(track_id))
        if not path:
            return {"summary": "No cached lyrics found for this track.", "available": False, "lyrics": ""}
        text = path.read_text(encoding="utf-8-sig")
        return {"summary": f"Lyrics from cache: {path}", "available": True, "lyrics": text, "path": str(path), "synced": path.suffix == ".lrc"}
    if operation == "current_line":
        path = lyric_path(config, str(track_id), synced=True)
        if not path.exists():
            return {"summary": "No synced lyrics cached for this track.", "available": False, "line": ""}
        line = current_lrc_line(path.read_text(encoding="utf-8-sig"), float(numeric_or_none(params.get("position_seconds")) or 0))
        return {"summary": "Current lyric line from synced cache.", "available": True, "line": line}
    if operation == "translate":
        shown = entertainment_lyrics({"operation": "show", "track_id": str(track_id)})
        if not shown.get("available"):
            return shown
        return {"summary": "Lyrics translation requires a configured translation provider; cached source lyrics are returned.", "available": False, "source_lyrics": shown.get("lyrics", ""), "target_language": optional_text(params, "target_language")}
    if operation == "search_lyrics":
        query = require_text(params, "query")
        matches = search_cached_lyrics(config, query)
        return {"summary": f"Found {len(matches)} cached lyric match(es).", "matches": matches}
    if operation == "annotate":
        annotation_path = lyric_path(config, str(track_id), synced=False).with_suffix(".annotations.json")
        data = load_json_store(annotation_path, {"annotations": []})
        data.setdefault("annotations", []).append({"line": optional_text(params, "line"), "annotation": require_text(params, "annotation"), "created_at": now_iso()})
        write_json(annotation_path, data)
        return {"summary": f"Saved lyric annotation: {annotation_path}", "path": str(annotation_path)}
    raise ToolInputError(f"Unsupported lyrics operation: {operation}")


def lyric_path(config: dict[str, Any], track_id: str, synced: bool = False) -> Path:
    directory = media_path(config, "lyrics_dir", "media/entertainment/lyrics")
    return directory / f"{track_id}.{ 'lrc' if synced else 'txt' }"


def existing_lyric_path(config: dict[str, Any], track_id: str) -> Path | None:
    for synced in [True, False]:
        path = lyric_path(config, track_id, synced=synced)
        if path.exists():
            return path
    return None


def parse_lrc_time(value: str) -> float | None:
    if ":" not in value:
        return None
    minute_text, second_text = value.split(":", 1)
    try:
        return int(minute_text) * 60 + float(second_text)
    except ValueError:
        return None


def current_lrc_line(text: str, position: float) -> str:
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line.startswith("[") or "]" not in line:
            continue
        stamp, content = line[1:].split("]", 1)
        seconds = parse_lrc_time(stamp)
        if seconds is not None and seconds <= position:
            current = content.strip()
    return current


def search_cached_lyrics(config: dict[str, Any], query: str) -> list[dict[str, Any]]:
    directory = media_path(config, "lyrics_dir", "media/entertainment/lyrics")
    key = canonical_text(query)
    matches = []
    for path in sorted(directory.glob("*")):
        if path.suffix not in {".txt", ".lrc"}:
            continue
        text = path.read_text(encoding="utf-8-sig")
        if key and key in canonical_text(text):
            matches.append({"path": str(path), "track_id": path.stem})
    return matches


def entertainment_radio(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    path = json_store_path(config, "radio", "saved_stations_path", "media/entertainment/radio_stations.json")
    store = load_json_store(path, {"stations": {}})
    if operation == "list_saved":
        stations = store.get("stations", {})
        return {"summary": f"Saved radio stations: {len(stations)}.", "stations": stations}
    if operation == "search":
        stations = radio_search(config, optional_text(params, "query"), optional_text(params, "country"), optional_text(params, "genre"), optional_text(params, "language"), bounded_int(params.get("limit"), 1, 50, 10))
        state = load_state(config)
        state["radio_last_search"] = {"query": optional_text(params, "query"), "stations": stations, "created_at": now_iso()}
        save_state(config, state)
        return {"summary": f"Found {len(stations)} radio station(s).", "stations": stations}
    if operation == "play":
        station = resolve_radio_station(config, store, params)
        if not station:
            raise ToolInputError("No playable radio station found")
        url = str(station.get("url") or station.get("url_resolved") or "")
        if not url:
            raise ToolInputError("Selected station has no stream URL")
        try:
            result = entertainment_stream_direct({"url": url, "query": str(station.get("name") or "")})
        except ToolInputError as error:
            station_name = str(station.get("name") or "the selected station")
            message = f"I found {station_name}, but I could not start the radio stream because {error}."
            return {
                "summary": message,
                "action_completed": False,
                "safe_user_output": message,
                "station": station,
                "stream_url": url,
                "error": str(error),
            }
        state = load_state(config)
        state["radio"] = {"station": station, "started_at": now_iso()}
        save_state(config, state)
        if bool(config.get("radio", {}).get("autosave_played_stations", False)):
            station_id = str(station.get("stationuuid") or stable_track_id(url))
            store.setdefault("stations", {})[station_id] = station
            write_json(path, store)
        result["summary"] = f"Playing radio: {station.get('name', url)}"
        result["station"] = station
        return result
    if operation == "stop":
        state = load_state(config)
        stop_player(state)
        state["radio"] = {}
        state["playback_status"] = "stopped"
        save_state(config, state)
        return {"summary": "Radio stopped."}
    if operation == "save":
        station = resolve_radio_station(config, store, params)
        if not station:
            raise ToolInputError("No station found to save")
        station_id = str(station.get("stationuuid") or stable_track_id(str(station.get("url") or station.get("name") or "")))
        store.setdefault("stations", {})[station_id] = station
        write_json(path, store)
        return {"summary": f"Saved radio station: {station.get('name', station_id)}", "station_id": station_id, "station": station}
    if operation == "remove_saved":
        station_id = require_text(params, "station_id")
        removed = store.setdefault("stations", {}).pop(station_id, None)
        write_json(path, store)
        return {"summary": f"Removed saved station: {station_id}", "removed": bool(removed)}
    if operation == "get_state":
        state = load_state(config)
        return {"summary": "Radio state.", "radio": state.get("radio", {})}
    if operation in {"trending", "similar_to_playing"}:
        state = load_state(config)
        query = optional_text(params, "query") or str(state.get("radio", {}).get("station", {}).get("tags", ""))
        stations = radio_search(config, query, optional_text(params, "country"), optional_text(params, "genre"), optional_text(params, "language"), bounded_int(params.get("limit"), 1, 50, 10))
        return {"summary": f"Radio discovery returned {len(stations)} station(s).", "stations": stations}
    raise ToolInputError(f"Unsupported radio operation: {operation}")


def radio_search(config: dict[str, Any], query: str, country: str, genre: str, language: str, limit: int) -> list[dict[str, Any]]:
    defaults = config.get("radio", {}).get("default_stations", {})
    matches: list[dict[str, Any]] = []
    search_terms = unique_texts([query, genre, language])
    if isinstance(defaults, dict):
        query_key = canonical_text(" ".join([query, country, genre, language]))
        for key, station in defaults.items():
            if isinstance(station, dict):
                haystack = canonical_text(" ".join(str(station.get(item, "")) for item in ["name", "query", "language", "genre"]) + " " + str(key))
                if not query_key or query_key in haystack or any(word in haystack for word in query_key.split()):
                    prepared = dict(station)
                    prepared.setdefault("stationuuid", str(key))
                    if prepared.get("url") or prepared.get("url_resolved"):
                        matches.append(prepared)
                    else:
                        search_terms.extend(
                            unique_texts(
                                [
                                    str(prepared.get("name") or ""),
                                    str(prepared.get("query") or ""),
                                    str(prepared.get("language") or ""),
                                    str(prepared.get("genre") or ""),
                                ]
                            )
                        )
    if len(matches) >= limit:
        return matches[:limit]
    api_url = str(config.get("radio", {}).get("api_url") or "").rstrip("/")
    if not api_url:
        return matches[:limit]
    seen = set(canonical_text(str(station.get("stationuuid") or station.get("url_resolved") or station.get("url") or station.get("name") or "")) for station in matches)
    for term in unique_texts(search_terms):
        for field in ["name", "tag"]:
            params = {"limit": str(limit - len(matches)), "hidebroken": "true", field: term}
            if country:
                params["country"] = country
            url = api_url + "/json/stations/search?" + urllib.parse.urlencode(params)
            try:
                with urllib.request.urlopen(url, timeout=8) as response:
                    data = json.loads(response.read().decode("utf-8", errors="replace"))
            except Exception:
                data = []
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    stream_url = str(item.get("url_resolved") or item.get("url") or "")
                    station_key = canonical_text(str(item.get("stationuuid") or stream_url or item.get("name") or ""))
                    if stream_url and station_key and station_key not in seen:
                        seen.add(station_key)
                        matches.append(item)
                        if len(matches) >= limit:
                            return matches[:limit]
    return matches[:limit]


def resolve_radio_station(config: dict[str, Any], store: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    station_id = optional_text(params, "station_id")
    stations = store.get("stations", {})
    if station_id and isinstance(stations, dict) and isinstance(stations.get(station_id), dict):
        return stations[station_id]
    if station_id:
        latest = latest_radio_search_station(config, station_id)
        if latest:
            return latest
    found = radio_search(config, optional_text(params, "query") or station_id, optional_text(params, "country"), optional_text(params, "genre"), optional_text(params, "language"), 1)
    return found[0] if found else {}


def latest_radio_search_station(config: dict[str, Any], station_id: str) -> dict[str, Any]:
    state = load_state(config)
    latest = state.get("radio_last_search", {})
    if not isinstance(latest, dict):
        return {}
    try:
        created_at = datetime.fromisoformat(str(latest.get("created_at", "")).replace("Z", "+00:00"))
    except ValueError:
        created_at = datetime.fromtimestamp(0, tz=timezone.utc)
    ttl = int(config.get("radio", {}).get("last_search_ttl_seconds") or 300)
    if datetime.now(timezone.utc) - created_at > timedelta(seconds=ttl):
        return {}
    stations = latest.get("stations", [])
    if not isinstance(stations, list):
        return {}
    station_key = canonical_text(station_id)
    for station in stations:
        if not isinstance(station, dict):
            continue
        identifiers = [
            str(station.get("stationuuid") or ""),
            str(station.get("name") or ""),
            str(station.get("url") or ""),
            str(station.get("url_resolved") or ""),
        ]
        if any(canonical_text(value) == station_key for value in identifiers):
            return station
    if stations and station_key and all(isinstance(item, dict) for item in stations):
        return stations[0]
    return {}


def entertainment_podcast(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    feeds_path = json_store_path(config, "podcast", "feeds_path", "media/entertainment/podcast_feeds.json")
    store = load_json_store(feeds_path, {"feeds": {}})
    if operation == "subscribe":
        url = require_text(params, "url")
        feed = parse_podcast_feed(url)
        podcast_id = stable_track_id(feed.get("title") or url)
        feed["id"] = podcast_id
        feed["url"] = url
        feed.setdefault("positions", {})
        store.setdefault("feeds", {})[podcast_id] = feed
        write_json(feeds_path, store)
        return {"summary": f"Subscribed to podcast: {feed.get('title', podcast_id)}", "podcast": feed}
    if operation == "unsubscribe":
        podcast_id = resolve_podcast_id(store, require_text(params, "podcast"))
        removed = store.setdefault("feeds", {}).pop(podcast_id, None)
        write_json(feeds_path, store)
        return {"summary": f"Unsubscribed: {podcast_id}", "removed": bool(removed)}
    if operation == "list":
        feeds = store.get("feeds", {})
        return {"summary": f"Subscribed podcasts: {len(feeds)}.", "podcasts": feeds}
    if operation == "episodes":
        podcast_id = resolve_podcast_id(store, require_text(params, "podcast"))
        feed = store.get("feeds", {}).get(podcast_id)
        if not isinstance(feed, dict):
            raise ToolInputError("Podcast not found")
        return {"summary": f"Episodes for {feed.get('title', podcast_id)}: {len(feed.get('episodes', []))}.", "episodes": feed.get("episodes", [])}
    if operation == "update":
        updated = 0
        for podcast_id, feed in list(store.get("feeds", {}).items()):
            if isinstance(feed, dict) and feed.get("url"):
                refreshed = parse_podcast_feed(str(feed["url"]))
                refreshed["id"] = podcast_id
                refreshed["url"] = feed["url"]
                refreshed["positions"] = feed.get("positions", {})
                store["feeds"][podcast_id] = refreshed
                updated += 1
        write_json(feeds_path, store)
        return {"summary": f"Updated {updated} podcast feed(s).", "updated": updated}
    if operation in {"mark_played", "mark_unplayed", "play_episode", "resume_episode", "download_episode"}:
        podcast_id, feed, episode = resolve_podcast_episode(store, params)
        if operation == "mark_played":
            episode["played"] = True
            write_json(feeds_path, store)
            return {"summary": f"Marked played: {episode.get('title', episode.get('id'))}", "episode": episode}
        if operation == "mark_unplayed":
            episode["played"] = False
            write_json(feeds_path, store)
            return {"summary": f"Marked unplayed: {episode.get('title', episode.get('id'))}", "episode": episode}
        if operation == "download_episode":
            path = download_podcast_episode(config, episode)
            episode["downloaded_path"] = str(path)
            write_json(feeds_path, store)
            return {"summary": f"Downloaded podcast episode: {path}", "path": str(path), "episode": episode}
        source = str(episode.get("downloaded_path") or episode.get("audio_url") or "")
        if not source:
            raise ToolInputError("Episode has no playable audio URL or downloaded file")
        result = entertainment_stream_direct({"url": source, "query": str(episode.get("title") or "")})
        speed = float(config.get("podcast", {}).get("default_speed") or 1.0)
        entertainment_playback({"operation": "speed", "value": speed})
        result["summary"] = f"{'Resuming' if operation == 'resume_episode' else 'Playing'} podcast episode: {episode.get('title', episode.get('id'))}"
        result["episode"] = episode
        result["podcast_id"] = podcast_id
        return result
    if operation == "queue_new":
        queued = []
        for _podcast_id, feed in store.get("feeds", {}).items():
            if not isinstance(feed, dict):
                continue
            for episode in feed.get("episodes", []):
                if isinstance(episode, dict) and not episode.get("played"):
                    queued.append(episode)
        return {"summary": f"Found {len(queued)} unplayed episode(s) to queue.", "episodes": queued}
    if operation == "delete_played":
        deleted = delete_played_podcast_files(store)
        write_json(feeds_path, store)
        return {"summary": f"Deleted {deleted} played episode file(s).", "deleted": deleted}
    if operation == "search_episodes":
        query = require_text(params, "query")
        matches = search_podcast_episodes(store, query, bounded_int(params.get("limit"), 1, 100, 20))
        return {"summary": f"Found {len(matches)} podcast episode(s).", "episodes": matches}
    raise ToolInputError(f"Unsupported podcast operation: {operation}")


def parse_podcast_feed(url: str) -> dict[str, Any]:
    if url.startswith("http://") or url.startswith("https://"):
        with urllib.request.urlopen(url, timeout=10) as response:
            content = response.read()
    else:
        content = resolve_config_path(url).read_bytes()
    root = ET.fromstring(content)
    channel = root.find("channel")
    if channel is None:
        channel = root
    title = child_text(channel, "title") or url
    description = child_text(channel, "description")
    episodes = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        audio_url = enclosure.get("url") if enclosure is not None else ""
        episode_title = child_text(item, "title") or audio_url
        episode_id = stable_track_id(episode_title + audio_url)
        episodes.append({"id": episode_id, "title": episode_title, "description": child_text(item, "description"), "published": child_text(item, "pubDate"), "audio_url": audio_url, "played": False, "position_seconds": 0})
    return {"title": title, "description": description, "episode_count": len(episodes), "episodes": episodes, "updated_at": now_iso()}


def child_text(node: Any, name: str) -> str:
    child = node.find(name)
    return child.text.strip() if child is not None and isinstance(child.text, str) else ""


def resolve_podcast_id(store: dict[str, Any], value: str) -> str:
    feeds = store.get("feeds", {})
    if value in feeds:
        return value
    key = canonical_text(value)
    for podcast_id, feed in feeds.items():
        if isinstance(feed, dict) and canonical_text(str(feed.get("title") or "")) == key:
            return str(podcast_id)
    raise ToolInputError(f"Podcast not found: {value}")


def resolve_podcast_episode(store: dict[str, Any], params: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    podcast_id = resolve_podcast_id(store, require_text(params, "podcast"))
    feed = store.get("feeds", {}).get(podcast_id)
    if not isinstance(feed, dict):
        raise ToolInputError("Podcast not found")
    episode_id = optional_text(params, "episode_id")
    episodes = feed.get("episodes", [])
    if episode_id:
        for episode in episodes:
            if isinstance(episode, dict) and episode.get("id") == episode_id:
                return podcast_id, feed, episode
    for episode in episodes:
        if isinstance(episode, dict) and not episode.get("played"):
            return podcast_id, feed, episode
    raise ToolInputError("Episode not found")


def download_podcast_episode(config: dict[str, Any], episode: dict[str, Any]) -> Path:
    url = str(episode.get("audio_url") or "")
    if not url:
        raise ToolInputError("Episode has no audio URL")
    directory = media_path(config, "podcast_dir", "media/entertainment/podcasts")
    suffix = Path(urllib.parse.urlparse(url).path).suffix or ".mp3"
    path = directory / f"{episode.get('id')}{suffix}"
    with urllib.request.urlopen(url, timeout=30) as response:
        path.write_bytes(response.read())
    return path


def delete_played_podcast_files(store: dict[str, Any]) -> int:
    deleted = 0
    for feed in store.get("feeds", {}).values():
        if not isinstance(feed, dict):
            continue
        for episode in feed.get("episodes", []):
            if isinstance(episode, dict) and episode.get("played") and episode.get("downloaded_path"):
                path = Path(str(episode["downloaded_path"]))
                if path.exists():
                    path.unlink()
                    deleted += 1
                episode.pop("downloaded_path", None)
    return deleted


def search_podcast_episodes(store: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
    key = canonical_text(query)
    matches = []
    for podcast_id, feed in store.get("feeds", {}).items():
        if not isinstance(feed, dict):
            continue
        for episode in feed.get("episodes", []):
            if not isinstance(episode, dict):
                continue
            text = canonical_text(str(episode.get("title", "")) + " " + str(episode.get("description", "")))
            if key in text:
                item = dict(episode)
                item["podcast_id"] = podcast_id
                item["podcast_title"] = feed.get("title", "")
                matches.append(item)
    return matches[:limit]


def entertainment_history(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    path = json_store_path(config, "history", "path", "media/entertainment/history.json")
    store = load_json_store(path, {"entries": []})
    if operation == "log":
        entry = {
            "track_id": optional_text(params, "track_id"),
            "start_time": now_iso(),
            "end_time": "",
            "duration_listened": numeric_or_none(params.get("duration_listened")) or 0,
            "skipped_at": numeric_or_none(params.get("skipped_at")),
            "context": optional_text(params, "context", current_context(config)),
            "source": optional_text(params, "source", "local"),
        }
        entries = store.setdefault("entries", [])
        entries.append(entry)
        max_entries = int(config.get("history", {}).get("max_entries") or 10000)
        store["entries"] = entries[-max_entries:]
        write_json(path, store)
        return {"summary": "Listening history logged.", "entry": entry}
    if operation == "recent":
        limit = bounded_int(params.get("limit"), 1, 100, 20)
        return {"summary": f"Recent history: {min(limit, len(store.get('entries', [])))} item(s).", "entries": list(reversed(store.get("entries", [])))[0:limit]}
    if operation == "stats":
        entries = filter_history_entries(store.get("entries", []), optional_text(params, "range", "all"))
        stats = history_stats(load_index(config), entries)
        return {"summary": history_summary(stats), "stats": stats}
    if operation == "timeline":
        return {"summary": f"Timeline entries: {len(store.get('entries', []))}.", "entries": store.get("entries", [])}
    if operation == "streak":
        streak = listening_streak(store.get("entries", []))
        return {"summary": f"Listening streak: {streak} day(s).", "streak_days": streak}
    if operation == "compare":
        entries = store.get("entries", [])
        return {"summary": "History compare returned aggregate counts.", "left_count": len(entries), "right_count": 0}
    if operation == "export":
        fmt = optional_text(params, "format", "json")
        output = resolve_config_path(optional_text(params, "path") or f"media/entertainment/history-export.{fmt}")
        if fmt == "csv":
            with output.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["track_id", "start_time", "duration_listened", "context", "source"])
                writer.writeheader()
                for entry in store.get("entries", []):
                    writer.writerow({key: entry.get(key, "") for key in writer.fieldnames})
        else:
            write_json(output, store)
        return {"summary": f"Exported history to {output}", "path": str(output)}
    if operation == "insights":
        stats = history_stats(load_index(config), filter_history_entries(store.get("entries", []), optional_text(params, "range", "this_week")))
        insight = history_summary(stats)
        return {"summary": insight, "insights": insight, "stats": stats}
    raise ToolInputError(f"Unsupported history operation: {operation}")


def filter_history_entries(entries: list[Any], range_name: str) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    if range_name == "today":
        cutoff = now - timedelta(days=1)
    elif range_name in {"this_week", "week"}:
        cutoff = now - timedelta(days=7)
    elif range_name in {"this_month", "month"}:
        cutoff = now - timedelta(days=31)
    else:
        cutoff = None
    result = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if cutoff is None:
            result.append(entry)
            continue
        try:
            timestamp = datetime.fromisoformat(str(entry.get("start_time", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if timestamp >= cutoff:
            result.append(entry)
    return result


def history_stats(index: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    artists: dict[str, int] = {}
    genres: dict[str, int] = {}
    languages: dict[str, int] = {}
    total = 0
    for entry in entries:
        total += int(numeric_or_none(entry.get("duration_listened")) or 0)
        track = index.get("tracks", {}).get(str(entry.get("track_id") or ""), {})
        if isinstance(track, dict):
            if track.get("artist"):
                increment(artists, str(track.get("artist")))
            if track.get("language"):
                increment(languages, str(track.get("language")))
            for genre in clean_list(track.get("genre")):
                increment(genres, genre)
    return {"entry_count": len(entries), "total_listening_seconds": total, "top_artists": top_counts(artists), "top_genres": top_counts(genres), "top_languages": top_counts(languages)}


def history_summary(stats: dict[str, Any]) -> str:
    top_artist = stats.get("top_artists", [])
    artist_text = top_artist[0]["name"] if top_artist else "none yet"
    return f"Listening: {stats.get('entry_count', 0)} plays, {stats.get('total_listening_seconds', 0)} second(s). Top artist: {artist_text}."


def listening_streak(entries: list[Any]) -> int:
    days = set()
    for entry in entries:
        if isinstance(entry, dict) and entry.get("start_time"):
            try:
                days.add(datetime.fromisoformat(str(entry["start_time"]).replace("Z", "+00:00")).date())
            except ValueError:
                pass
    streak = 0
    today = datetime.now(timezone.utc).date()
    while today - timedelta(days=streak) in days:
        streak += 1
    return streak


def entertainment_equalizer(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    eq = config.setdefault("equalizer", {})
    profiles = equalizer_profiles(config)
    if operation == "list_profiles":
        return {"summary": f"Equalizer profiles: {len(profiles)}.", "profiles": profiles}
    if operation == "get_active":
        return {"summary": f"Active EQ profile: {eq.get('active_profile', 'flat')}", "active_profile": eq.get("active_profile", "flat")}
    if operation == "apply":
        profile = require_text(params, "profile")
        if profile not in profiles:
            raise ToolInputError(f"EQ profile not found: {profile}")
        eq["active_profile"] = profile
        save_config(config)
        backend = choose_player_backend(config)
        return {"summary": f"Applied EQ profile: {profile}" if backend["supports_eq"] else f"EQ profile saved: {profile}; active backend does not support live EQ.", "profile": profile, "backend_supports_eq": backend["supports_eq"]}
    if operation == "create":
        profile = require_text(params, "profile")
        bands = params.get("bands", {})
        if not isinstance(bands, dict):
            raise ToolInputError("bands must be an object")
        path = media_path(config, "equalizer_dir", "media/entertainment/equalizer_profiles") / f"{canonical_text(profile).replace(' ', '_')}.json"
        write_json(path, {"name": profile, "bands": bands})
        return {"summary": f"Created EQ profile: {profile}", "path": str(path)}
    if operation == "delete":
        profile = require_text(params, "profile")
        deleted = False
        for path in media_path(config, "equalizer_dir", "media/entertainment/equalizer_profiles").glob("*.json"):
            data = load_json_store(path, {})
            if data.get("name") == profile or path.stem == canonical_text(profile).replace(" ", "_"):
                path.unlink()
                deleted = True
        return {"summary": f"Deleted EQ profile: {profile}", "deleted": deleted}
    if operation == "reset":
        eq["active_profile"] = "flat"
        save_config(config)
        return {"summary": "Equalizer reset to flat.", "active_profile": "flat"}
    raise ToolInputError(f"Unsupported equalizer operation: {operation}")


def equalizer_profiles(config: dict[str, Any]) -> dict[str, Any]:
    profiles = dict(config.get("equalizer", {}).get("built_in_profiles", {}))
    directory = media_path(config, "equalizer_dir", "media/entertainment/equalizer_profiles")
    for path in directory.glob("*.json"):
        data = load_json_store(path, {})
        name = str(data.get("name") or path.stem)
        profiles[name] = data.get("bands", {})
    return profiles


def entertainment_metadata(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    index = load_index(config)
    if operation in {"fetch", "write_tags", "fetch_art"}:
        track = resolve_track(config, index, params, auto_download=False)
        if track is None:
            raise ToolInputError("track_id, query, or path must resolve to a local track")
        if operation == "fetch":
            return {"summary": f"Local metadata for {track.get('title', track['id'])}.", "metadata": track, "online_enriched": False}
        if operation == "write_tags":
            values = params.get("values", {})
            if not isinstance(values, dict):
                raise ToolInputError("values must be an object")
            track.update(values)
            index["tracks"][track["id"]] = normalize_track(track, track["id"])
            save_index(config, index)
            return {"summary": f"Updated library metadata for {track.get('title', track['id'])}.", "track": index["tracks"][track["id"]], "file_tags_written": False}
        if operation == "fetch_art":
            thumbnail = str(track.get("thumbnail_path") or "")
            available = bool(thumbnail and Path(thumbnail).exists())
            return {"summary": "Album art already cached." if available else "No cached album art found for this track.", "available": available, "path": thumbnail}
    if operation == "batch_enrich":
        limit = bounded_int(params.get("limit"), 1, 1000, 100)
        count = 0
        for track_id, track in list(index.get("tracks", {}).items())[:limit]:
            if isinstance(track, dict):
                index["tracks"][track_id] = normalize_track(track, track_id)
                count += 1
        save_index(config, index)
        return {"summary": f"Batch-enriched {count} local metadata record(s).", "updated": count}
    if operation == "identify":
        path = resolve_config_path(require_text(params, "path"))
        if not path.exists():
            raise ToolInputError(f"File not found: {path}")
        track = track_from_file(path, config)
        return {"summary": f"Identified local file as {track.get('title', track['id'])}.", "track": track, "fingerprinted": False}
    raise ToolInputError(f"Unsupported metadata operation: {operation}")


def entertainment_share(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation")
    config = load_config()
    index = load_index(config)
    if operation == "now_playing":
        state = load_state(config)
        track = current_track(index, state)
        if not track and state.get("radio"):
            station = state["radio"].get("station", {})
            text = f"Now playing radio: {station.get('name', 'live station')}"
        elif track:
            text = f"Now playing: {track.get('title', track.get('id'))} - {track.get('artist', '')}".strip()
        else:
            text = "Nothing is playing right now."
        return {"summary": text, "text": text}
    if operation == "playlist_summary":
        playlist = require_text(params, "playlist")
        tracks = tracks_from_ids(index, playlist_ids(config, playlist))
        text = f"{playlist}: " + "; ".join(str(track.get("title") or track.get("id")) for track in tracks)
        return {"summary": text, "text": text}
    if operation == "stats_card":
        stats = entertainment_history({"operation": "stats", "range": optional_text(params, "range", "this_week")})
        text = stats["summary"]
        return {"summary": text, "text": text}
    if operation == "export_playlist_links":
        playlist = require_text(params, "playlist")
        links = [str(track.get("source_url") or track.get("webpage_url") or "") for track in tracks_from_ids(index, playlist_ids(config, playlist))]
        links = [link for link in links if link]
        text = "\n".join(links)
        return {"summary": f"Exported {len(links)} playlist link(s).", "text": text, "links": links}
    raise ToolInputError(f"Unsupported share operation: {operation}")


def load_json_store(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(fallback)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return dict(fallback)
    return data if isinstance(data, dict) else dict(fallback)


def track_summary(index: dict[str, Any], track_id: str) -> dict[str, Any]:
    track = index.get("tracks", {}).get(track_id)
    if isinstance(track, dict):
        normalized = normalize_track(track, track_id)
        return {
            "id": str(normalized.get("id") or track_id),
            "type": str(normalized.get("type") or ""),
            "title": str(normalized.get("title") or track_id),
            "artist": str(normalized.get("artist") or ""),
            "album": str(normalized.get("album") or ""),
            "language": str(normalized.get("language") or ""),
            "genre": clean_list(normalized.get("genre")),
            "mood_tags": clean_list(normalized.get("mood_tags")),
            "file_path": str(normalized.get("file_path") or ""),
            "webpage_url": str(normalized.get("webpage_url") or normalized.get("source_url") or ""),
            "source_url": str(normalized.get("source_url") or normalized.get("webpage_url") or ""),
            "duration": normalized.get("duration_seconds"),
            "duration_seconds": normalized.get("duration_seconds"),
            "channel": normalized.get("channel"),
            "rating": normalized.get("rating"),
            "play_count": normalized.get("play_count"),
        }
    return {"id": track_id, "title": f"Missing local track {track_id}", "file_path": "", "webpage_url": ""}
