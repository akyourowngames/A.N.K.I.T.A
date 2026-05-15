from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import subprocess
import time
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .registry import ToolInputError, optional_text, require_text


_PLAYER_PROCESSES: list[subprocess.Popen[Any]] = []


DEFAULT_CONFIG: dict[str, Any] = {
    "library_dir": "media/music/library",
    "database_path": "media/music/music_db.json",
    "state_path": "media/music/player_state.json",
    "download_command": "yt-dlp",
    "download_format": "bestaudio/best",
    "download_enabled": True,
    "dry_run_player": False,
    "player": "vlc",
    "vlc_command": "vlc",
    "vlc_extra_args": ["--no-video", "--play-and-exit"],
    "player_command": [],
    "media_extensions": [".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus", ".webm", ".mp4"],
    "match_cutoff": 0.52,
}


def music_status(params: dict[str, Any]) -> dict[str, Any]:
    context = music_context()
    database = load_database(context)
    if bool(params.get("scan")):
        database = scan_library(context, database)
        save_database(context, database)
    state = load_state(context)
    state = refresh_state(context, state)
    save_state(context, state)
    return {
        "library_dir": str(context["library_dir"]),
        "database_path": str(context["database_path"]),
        "track_count": len(database["tracks"]),
        "playlist_count": len(database["playlists"]),
        "favorite_count": len(database["favorites"]),
        "recent_count": len(database["recent"]),
        "queue_length": len(state["queue"]),
        "current_track": track_public(database["tracks"].get(state.get("current_track_id", ""))),
        "playback": state_public(state),
        "download_enabled": bool(context["config"].get("download_enabled")),
        "downloader_available": downloader_available(context),
        "player": player_status(context),
    }


def music_search(params: dict[str, Any]) -> dict[str, Any]:
    query = require_text(params, "query")
    context = music_context()
    database = scan_library(context, load_database(context))
    save_database(context, database)
    state = load_state(context)
    state["last_query"] = query
    state["last_query_at"] = time.time()
    limit = bounded_int(params.get("limit"), 5, 1, 20)
    local_matches = local_search(database, query, limit, context["match_cutoff"])
    remote_results: list[dict[str, Any]] = []
    if bool(params.get("include_remote")):
        remote_results = remote_search(context, query, limit)
        remember_remote_results(state, query, remote_results)
    save_state(context, state)
    return {
        "query": query,
        "local_matches": local_matches,
        "remote_results": remote_results,
        "searched_local_first": True,
    }


def music_download(params: dict[str, Any]) -> dict[str, Any]:
    query = optional_text(params, "query")
    url = optional_text(params, "url")
    context = music_context()
    state = load_state(context)
    if not query and not url:
        query = optional_text(state, "last_query")
    if not query and not url:
        raise ToolInputError("query or url is required")

    database = scan_library(context, load_database(context))
    if query:
        state["last_query"] = query
        state["last_query_at"] = time.time()
        save_state(context, state)
    existing = best_existing_track(database, query or url, context["match_cutoff"]) if query else existing_by_source(database, url)
    if existing:
        save_database(context, database)
        return {
            "downloaded": False,
            "already_existed": True,
            "track": track_public(existing),
            "searched_local_first": True,
        }

    if not bool(context["config"].get("download_enabled")):
        save_database(context, database)
        return {
            "downloaded": False,
            "already_existed": False,
            "blocked_reason": "download_disabled",
            "searched_local_first": True,
        }
    if not downloader_available(context):
        save_database(context, database)
        return {
            "downloaded": False,
            "already_existed": False,
            "blocked_reason": "downloader_not_available",
            "download_command": str(context["config"].get("download_command") or ""),
            "searched_local_first": True,
        }

    source = url or f"ytsearch1:{query}"
    downloaded_path = run_download(context, source)
    database = scan_library(context, database)
    track = track_for_path(database, downloaded_path)
    if track is None:
        track = register_track(
            database,
            downloaded_path,
            {
                "title": optional_text(params, "title") or query or downloaded_path.stem,
                "artist": optional_text(params, "artist"),
                "source": source,
            },
        )
        save_database(context, database)
    else:
        update_track_metadata(
            track,
            downloaded_path,
            {
                "title": optional_text(params, "title") or query or downloaded_path.stem,
                "artist": optional_text(params, "artist"),
                "source": source,
            },
        )
        save_database(context, database)
    return {
        "downloaded": True,
        "already_existed": False,
        "track": track_public(track),
        "searched_local_first": True,
    }


def music_play(params: dict[str, Any]) -> dict[str, Any]:
    context = music_context()
    database = scan_library(context, load_database(context))
    state = load_state(context)
    playlist_name = optional_text(params, "playlist")
    downloaded_before_play = False
    if playlist_name:
        track_ids = playlist_tracks(database, playlist_name)
        if not track_ids:
            save_database(context, database)
            return {"played": False, "blocked_reason": "playlist_not_found_or_empty", "playlist": playlist_name}
        state["queue"] = track_ids
        state["queue_index"] = 0
        tracks = [database["tracks"][track_id] for track_id in track_ids if track_id in database["tracks"]]
        if not tracks:
            save_database(context, database)
            return {"played": False, "blocked_reason": "playlist_tracks_missing", "playlist": playlist_name}
        stop_playback(state)
        playback = start_playlist_playback(context, tracks)
        track = tracks[0]
        state["current_track_id"] = track["id"]
        state["playback_status"] = playback["status"]
        state["backend"] = playback["backend"]
        state["player_pid"] = playback.get("pid")
        state["started_at"] = time.time()
        state["last_position_seconds"] = 0
        for queued_track in tracks:
            add_recent(database, queued_track["id"])
        save_state(context, state)
        save_database(context, database)
        return {
            "played": playback["started"],
            "downloaded_before_play": False,
            "track": track_public(track),
            "tracks": tracks_public(tracks),
            "playlist": playlist_public(database, playlist_key(playlist_name)),
            "playback": playback,
            "queue": queue_public(database, state),
            "searched_local_first": True,
        }
    else:
        if not optional_text(params, "query") and not optional_text(params, "track_id") and not optional_text(params, "path"):
            last_query = optional_text(state, "last_query")
            if last_query:
                params = dict(params)
                params["query"] = last_query
            else:
                current_track_id = optional_text(state, "current_track_id")
                if current_track_id:
                    params = dict(params)
                    params["track_id"] = current_track_id
        track = resolve_track_from_params(database, params, context["match_cutoff"])
        if track is None and bool(params.get("allow_download", True)):
            query = optional_text(params, "query")
            if query:
                download_result = music_download({"query": query})
                if download_result.get("downloaded") or download_result.get("already_existed"):
                    downloaded_before_play = bool(download_result.get("downloaded"))
                    database = load_database(context)
                    raw_track = download_result.get("track")
                    if isinstance(raw_track, dict):
                        track = database["tracks"].get(str(raw_track.get("id", "")))
                else:
                    return {
                        "played": False,
                        "blocked_reason": download_result.get("blocked_reason", "download_failed"),
                        "download": download_result,
                    }
        if track is None:
            save_database(context, database)
            return {"played": False, "blocked_reason": "track_not_found", "searched_local_first": True, "query": optional_text(params, "query")}
        if track["id"] not in state["queue"]:
            state["queue"].append(track["id"])
            state["queue_index"] = state["queue"].index(track["id"])

    if track is None:
        raise ToolInputError("track could not be resolved")
    query = optional_text(params, "query")
    if query:
        state["last_query"] = query
        state["last_query_at"] = time.time()
    stop_playback(state)
    playback = start_playback(context, track)
    state["current_track_id"] = track["id"]
    state["playback_status"] = playback["status"]
    state["backend"] = playback["backend"]
    state["player_pid"] = playback.get("pid")
    state["started_at"] = time.time()
    state["last_position_seconds"] = 0
    add_recent(database, track["id"])
    save_state(context, state)
    save_database(context, database)
    return {
        "played": playback["started"],
        "downloaded_before_play": downloaded_before_play,
        "track": track_public(track),
        "playback": playback,
        "queue": queue_public(database, state),
        "searched_local_first": True,
    }


def music_control(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation").lower()
    context = music_context()
    database = load_database(context)
    state = refresh_state(context, load_state(context))
    if operation == "state":
        save_state(context, state)
        return {"playback": state_public(state), "queue": queue_public(database, state)}
    if operation == "again":
        track_id = str(state.get("current_track_id") or "")
        if not track_id:
            return {"changed": False, "blocked_reason": "no_current_track"}
        track = database["tracks"].get(track_id)
        if not track:
            return {"changed": False, "blocked_reason": "current_track_missing"}
        stop_playback(state)
        playback = start_playback(context, track)
        state["playback_status"] = playback["status"]
        state["backend"] = playback["backend"]
        state["player_pid"] = playback.get("pid")
        state["started_at"] = time.time()
        save_state(context, state)
        return {"changed": playback["started"], "operation": operation, "track": track_public(track), "playback": playback}
    if operation in {"next", "previous"}:
        return play_relative(context, database, state, 1 if operation == "next" else -1)
    if operation in {"shuffle", "repeat"}:
        enabled = bool(params.get("enabled", True))
        state[operation] = enabled
        save_state(context, state)
        return {"changed": True, "operation": operation, "enabled": enabled, "playback": state_public(state)}
    if operation == "stop":
        stopped = stop_playback(state)
        state["playback_status"] = "stopped"
        state["player_pid"] = None
        save_state(context, state)
        return {"changed": stopped, "operation": operation, "playback": state_public(state)}
    if operation in {"pause", "resume", "play_pause"}:
        sent = send_media_key(operation)
        if sent:
            state["playback_status"] = "paused" if operation == "pause" else "playing"
            save_state(context, state)
        return {"changed": sent, "operation": operation, "playback": state_public(state), "control_method": "system_media_key"}
    raise ToolInputError(f"unsupported music operation: {operation}")


def music_playlist(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation").lower()
    name = optional_text(params, "name")
    context = music_context()
    database = scan_library(context, load_database(context))
    if operation == "list":
        return {"playlists": playlists_public(database)}
    if not name:
        raise ToolInputError("name is required")
    key = playlist_key(name)
    if operation == "create":
        database["playlists"].setdefault(key, {"name": name, "track_ids": [], "created_at": time.time(), "updated_at": time.time()})
        save_database(context, database)
        return {"changed": True, "playlist": playlist_public(database, key)}
    if operation == "delete":
        existed = key in database["playlists"]
        database["playlists"].pop(key, None)
        save_database(context, database)
        return {"changed": existed, "playlist": name}
    if operation == "show":
        return {"playlist": playlist_public(database, key)}
    if operation == "add_top":
        playlist = database["playlists"].setdefault(key, {"name": name, "track_ids": [], "created_at": time.time(), "updated_at": time.time()})
        count = bounded_int(params.get("count"), 3, 1, 20)
        allow_download = bool(params.get("allow_download", True))
        query = optional_text(params, "query")
        state = load_state(context)
        candidates = remote_candidates_for_followup(context, state, query, count)
        if query:
            state["last_query"] = query
            state["last_query_at"] = time.time()
            remember_remote_results(state, query, candidates)
            save_state(context, state)
        added_tracks: list[dict[str, Any]] = []
        already_present: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for candidate in candidates[:count]:
            track = track_from_candidate(database, candidate, context["match_cutoff"])
            download_result: dict[str, Any] | None = None
            if track is None and allow_download:
                download_result = download_candidate(candidate)
                if download_result.get("downloaded") or download_result.get("already_existed"):
                    database = load_database(context)
                    raw_track = download_result.get("track")
                    if isinstance(raw_track, dict):
                        track = database["tracks"].get(str(raw_track.get("id", "")))
            if track is None:
                failed.append(candidate_failure(candidate, download_result))
                continue
            playlist = database["playlists"].setdefault(key, {"name": name, "track_ids": [], "created_at": time.time(), "updated_at": time.time()})
            if track["id"] in playlist["track_ids"]:
                public = track_public(track)
                if public:
                    already_present.append(public)
            else:
                playlist["track_ids"].append(track["id"])
                public = track_public(track)
                if public:
                    added_tracks.append(public)
            playlist["updated_at"] = time.time()
            save_database(context, database)
        save_database(context, database)
        return {
            "changed": bool(added_tracks),
            "operation": operation,
            "requested_count": count,
            "candidate_count": len(candidates),
            "added_tracks": added_tracks,
            "already_present": already_present,
            "failed": failed,
            "playlist": playlist_public(database, key),
            "downloaded_or_reused_only": True,
        }
    if operation in {"add", "remove"}:
        playlist = database["playlists"].setdefault(key, {"name": name, "track_ids": [], "created_at": time.time(), "updated_at": time.time()})
        track = resolve_track_from_params(database, params, context["match_cutoff"])
        download_result: dict[str, Any] | None = None
        if track is None and operation == "add" and bool(params.get("allow_download", True)):
            query = optional_text(params, "query")
            if query:
                download_result = music_download({"query": query})
                if download_result.get("downloaded") or download_result.get("already_existed"):
                    database = load_database(context)
                    raw_track = download_result.get("track")
                    if isinstance(raw_track, dict):
                        track = database["tracks"].get(str(raw_track.get("id", "")))
                    playlist = database["playlists"].setdefault(key, {"name": name, "track_ids": [], "created_at": time.time(), "updated_at": time.time()})
        if track is None:
            save_database(context, database)
            result = {"changed": False, "blocked_reason": "track_not_found", "playlist": playlist_public(database, key)}
            if download_result is not None:
                result["download"] = download_result
            return result
        if operation == "add" and track["id"] not in playlist["track_ids"]:
            playlist["track_ids"].append(track["id"])
        if operation == "remove" and track["id"] in playlist["track_ids"]:
            playlist["track_ids"].remove(track["id"])
        playlist["updated_at"] = time.time()
        save_database(context, database)
        return {"changed": True, "operation": operation, "track": track_public(track), "playlist": playlist_public(database, key)}
    if operation == "play":
        save_database(context, database)
        return music_play({"playlist": name})
    raise ToolInputError(f"unsupported playlist operation: {operation}")


def music_library(params: dict[str, Any]) -> dict[str, Any]:
    operation = require_text(params, "operation").lower()
    context = music_context()
    database = scan_library(context, load_database(context)) if operation in {"scan", "list", "get", "favorite", "unfavorite"} else load_database(context)
    limit = bounded_int(params.get("limit"), 20, 1, 200)
    if operation == "scan":
        save_database(context, database)
        return {"changed": True, "track_count": len(database["tracks"]), "tracks": tracks_public(list(database["tracks"].values())[:limit])}
    if operation == "list":
        tracks = sorted(database["tracks"].values(), key=lambda item: sort_text(item.get("title") or item.get("filename") or ""))
        return {"tracks": tracks_public(tracks[:limit]), "track_count": len(database["tracks"])}
    if operation == "get":
        track = resolve_track_from_params(database, params, context["match_cutoff"])
        return {"track": track_public(track)}
    if operation in {"favorite", "unfavorite"}:
        track = resolve_track_from_params(database, params, context["match_cutoff"])
        if track is None:
            save_database(context, database)
            return {"changed": False, "blocked_reason": "track_not_found"}
        favorites = database["favorites"]
        if operation == "favorite" and track["id"] not in favorites:
            favorites.append(track["id"])
        if operation == "unfavorite" and track["id"] in favorites:
            favorites.remove(track["id"])
        save_database(context, database)
        return {"changed": True, "operation": operation, "track": track_public(track), "favorite_count": len(favorites)}
    if operation == "favorites":
        return {"tracks": tracks_public([database["tracks"][track_id] for track_id in database["favorites"] if track_id in database["tracks"]][:limit])}
    if operation == "recent":
        return {"tracks": tracks_public([database["tracks"][track_id] for track_id in database["recent"] if track_id in database["tracks"]][:limit])}
    raise ToolInputError(f"unsupported library operation: {operation}")


def music_context() -> dict[str, Any]:
    config_path = Path(os.environ.get("JARVIS_MUSIC_CONFIG", "config/music_agent.json")).expanduser()
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    config = dict(DEFAULT_CONFIG)
    if config_path.exists():
        loaded = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if isinstance(loaded, dict):
            config.update(loaded)
    library_dir = resolve_workspace_path(str(config["library_dir"]))
    database_path = resolve_workspace_path(str(config["database_path"]))
    state_path = resolve_workspace_path(str(config["state_path"]))
    library_dir.mkdir(parents=True, exist_ok=True)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    return {
        "config": config,
        "config_path": config_path,
        "library_dir": library_dir,
        "database_path": database_path,
        "state_path": state_path,
        "match_cutoff": float(config.get("match_cutoff") or DEFAULT_CONFIG["match_cutoff"]),
    }


def resolve_workspace_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def default_database() -> dict[str, Any]:
    return {"version": 1, "tracks": {}, "playlists": {}, "favorites": [], "recent": []}


def default_state() -> dict[str, Any]:
    return {
        "current_track_id": "",
        "queue": [],
        "queue_index": 0,
        "playback_status": "stopped",
        "backend": "",
        "started_at": None,
        "last_position_seconds": 0,
        "shuffle": False,
        "repeat": False,
        "player_pid": None,
        "last_query": "",
        "last_query_at": None,
        "last_remote_results": [],
        "last_remote_query": "",
    }


def load_database(context: dict[str, Any]) -> dict[str, Any]:
    path = context["database_path"]
    if not path.exists():
        return default_database()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default_database()
    if not isinstance(data, dict):
        return default_database()
    database = default_database()
    for key in database:
        if key in data:
            database[key] = data[key]
    if not isinstance(database["tracks"], dict):
        database["tracks"] = {}
    if not isinstance(database["playlists"], dict):
        database["playlists"] = {}
    if not isinstance(database["favorites"], list):
        database["favorites"] = []
    if not isinstance(database["recent"], list):
        database["recent"] = []
    return database


def save_database(context: dict[str, Any], database: dict[str, Any]) -> None:
    context["database_path"].write_text(json.dumps(database, indent=2, ensure_ascii=False), encoding="utf-8")


def load_state(context: dict[str, Any]) -> dict[str, Any]:
    path = context["state_path"]
    if not path.exists():
        return default_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return default_state()
    state = default_state()
    if isinstance(data, dict):
        for key in state:
            if key in data:
                state[key] = data[key]
    if not isinstance(state["queue"], list):
        state["queue"] = []
    if not isinstance(state["last_remote_results"], list):
        state["last_remote_results"] = []
    return state


def save_state(context: dict[str, Any], state: dict[str, Any]) -> None:
    context["state_path"].write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def scan_library(context: dict[str, Any], database: dict[str, Any]) -> dict[str, Any]:
    extensions = {str(item).lower() for item in context["config"].get("media_extensions", DEFAULT_CONFIG["media_extensions"])}
    seen_paths: set[str] = set()
    for path in sorted(context["library_dir"].rglob("*"), key=lambda item: str(item).lower()):
        if not path.is_file() or path.suffix.lower() not in extensions:
            continue
        track = register_track(database, path, {})
        seen_paths.add(track["path"])
    stale = [track_id for track_id, track in database["tracks"].items() if track.get("path") and track.get("path") not in seen_paths and is_under_library(track.get("path"), context["library_dir"])]
    for track_id in stale:
        database["tracks"].pop(track_id, None)
    database["favorites"] = [track_id for track_id in database["favorites"] if track_id in database["tracks"]]
    database["recent"] = [track_id for track_id in database["recent"] if track_id in database["tracks"]]
    for playlist in database["playlists"].values():
        if isinstance(playlist, dict) and isinstance(playlist.get("track_ids"), list):
            playlist["track_ids"] = [track_id for track_id in playlist["track_ids"] if track_id in database["tracks"]]
    return database


def is_under_library(path_value: Any, library_dir: Path) -> bool:
    if not isinstance(path_value, str):
        return False
    try:
        Path(path_value).resolve().relative_to(library_dir)
        return True
    except ValueError:
        return False


def register_track(database: dict[str, Any], path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    resolved = str(path.resolve())
    existing = track_for_path(database, path)
    if existing:
        update_track_metadata(existing, path, metadata)
        return existing
    filename_metadata = metadata_from_filename(path)
    title = clean_text(metadata.get("title")) or filename_metadata["title"]
    artist = clean_text(metadata.get("artist")) or filename_metadata["artist"]
    album = clean_text(metadata.get("album"))
    track_id = track_id_for(path, title, artist)
    track = {
        "id": track_id,
        "title": title,
        "artist": artist,
        "album": album,
        "path": resolved,
        "filename": path.name,
        "source": clean_text(metadata.get("source")),
        "added_at": time.time(),
        "updated_at": time.time(),
        "play_count": 0,
    }
    database["tracks"][track_id] = track
    return track


def update_track_metadata(track: dict[str, Any], path: Path, metadata: dict[str, Any]) -> None:
    for key in ["title", "artist", "album", "source"]:
        value = clean_text(metadata.get(key))
        if value and not track.get(key):
            track[key] = value
    track["path"] = str(path.resolve())
    track["filename"] = path.name
    track["updated_at"] = time.time()


def track_for_path(database: dict[str, Any], path: Path) -> dict[str, Any] | None:
    resolved = str(path.resolve())
    for track in database["tracks"].values():
        if isinstance(track, dict) and track.get("path") == resolved:
            return track
    return None


def metadata_from_filename(path: Path) -> dict[str, str]:
    text = path.stem
    for marker in [" - ", "_-_"]:
        if marker in text:
            parts = [part.strip() for part in text.split(marker) if part.strip()]
            if len(parts) >= 2:
                return {"artist": parts[0], "title": parts[-1]}
    return {"artist": "", "title": text.strip() or path.name}


def track_id_for(path: Path, title: str, artist: str) -> str:
    digest_input = "|".join([normalize_text(title), normalize_text(artist), str(path.resolve()).casefold()])
    return hashlib.sha1(digest_input.encode("utf-8")).hexdigest()[:16]


def local_search(database: dict[str, Any], query: str, limit: int, cutoff: float) -> list[dict[str, Any]]:
    normalized_query = normalize_text(query)
    scored: list[tuple[float, dict[str, Any]]] = []
    for track in database["tracks"].values():
        if not isinstance(track, dict):
            continue
        score = track_score(track, normalized_query)
        if score >= cutoff:
            scored.append((score, track))
    scored.sort(key=lambda item: (-item[0], sort_text(item[1].get("title") or item[1].get("filename") or "")))
    return [track_public(track, score) for score, track in scored[:limit]]


def track_score(track: dict[str, Any], normalized_query: str) -> float:
    fields = [
        track.get("title", ""),
        track.get("artist", ""),
        track.get("album", ""),
        track.get("filename", ""),
        " ".join([str(track.get("artist", "")), str(track.get("title", ""))]),
    ]
    best = 0.0
    for field in fields:
        normalized = normalize_text(str(field))
        if not normalized:
            continue
        if normalized_query and normalized_query in normalized:
            best = max(best, 1.0)
        if normalized and normalized in normalized_query:
            best = max(best, 0.95)
        best = max(best, SequenceMatcher(None, normalized_query, normalized).ratio())
    return best


def best_existing_track(database: dict[str, Any], query: str, cutoff: float) -> dict[str, Any] | None:
    matches = local_search(database, query, 1, cutoff)
    if not matches:
        return None
    return database["tracks"].get(matches[0]["id"])


def existing_by_source(database: dict[str, Any], source: str) -> dict[str, Any] | None:
    for track in database["tracks"].values():
        if isinstance(track, dict) and source and track.get("source") == source:
            return track
    return None


def resolve_track_from_params(database: dict[str, Any], params: dict[str, Any], cutoff: float) -> dict[str, Any] | None:
    track_id = optional_text(params, "track_id")
    if track_id and track_id in database["tracks"]:
        return database["tracks"][track_id]
    path_value = optional_text(params, "path")
    if path_value:
        path = resolve_workspace_path(path_value)
        track = track_for_path(database, path)
        if track:
            return track
    query = optional_text(params, "query")
    if query:
        return best_existing_track(database, query, cutoff)
    return None


def remote_search(context: dict[str, Any], query: str, limit: int) -> list[dict[str, Any]]:
    command = resolve_download_command(context)
    if not command:
        return []
    source = f"ytsearch{limit}:{query}"
    completed = subprocess.run(
        [command, "--dump-json", "--no-playlist", source],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if completed.returncode != 0:
        return []
    results = []
    for line in completed.stdout.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            results.append(
                {
                    "title": item.get("title") or "",
                    "artist": item.get("artist") or item.get("uploader") or "",
                    "duration": item.get("duration"),
                    "url": item.get("webpage_url") or item.get("original_url") or "",
                }
            )
        if len(results) >= limit:
            break
    return results


def remember_remote_results(state: dict[str, Any], query: str, results: list[dict[str, Any]]) -> None:
    remembered: list[dict[str, Any]] = []
    for index, item in enumerate(results, start=1):
        if not isinstance(item, dict):
            continue
        remembered.append(
            {
                "index": index,
                "query": query,
                "title": clean_text(item.get("title")),
                "artist": clean_text(item.get("artist")),
                "duration": item.get("duration"),
                "url": clean_text(item.get("url")),
            }
        )
    state["last_remote_query"] = query
    state["last_remote_results"] = remembered


def remote_candidates_for_followup(context: dict[str, Any], state: dict[str, Any], query: str | None, count: int) -> list[dict[str, Any]]:
    if query:
        return remote_search(context, query, count)
    remembered = state.get("last_remote_results")
    if not isinstance(remembered, list):
        return []
    candidates: list[dict[str, Any]] = []
    for item in remembered:
        if isinstance(item, dict):
            candidates.append(item)
        if len(candidates) >= count:
            break
    return candidates


def track_from_candidate(database: dict[str, Any], candidate: dict[str, Any], cutoff: float) -> dict[str, Any] | None:
    url = clean_text(candidate.get("url"))
    if url:
        existing = existing_by_source(database, url)
        if existing:
            return existing
    title = clean_text(candidate.get("title"))
    artist = clean_text(candidate.get("artist"))
    normalized_title = normalize_text(title)
    normalized_artist = normalize_text(artist)
    for track in database["tracks"].values():
        if not isinstance(track, dict):
            continue
        track_title = normalize_text(str(track.get("title") or ""))
        track_artist = normalize_text(str(track.get("artist") or ""))
        if normalized_title and track_title == normalized_title:
            if not normalized_artist or not track_artist or track_artist == normalized_artist:
                return track
    if title:
        strict_matches = local_search(database, title, 1, max(cutoff, 0.86))
        if strict_matches:
            return database["tracks"].get(strict_matches[0]["id"])
    return None


def download_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    title = clean_text(candidate.get("title"))
    artist = clean_text(candidate.get("artist"))
    url = clean_text(candidate.get("url"))
    params: dict[str, Any] = {}
    if url:
        params["url"] = url
    else:
        query = " ".join(part for part in [artist, title] if part).strip()
        if query:
            params["query"] = query
    if title:
        params["title"] = title
    if artist:
        params["artist"] = artist
    if not params.get("url") and not params.get("query"):
        return {"downloaded": False, "already_existed": False, "blocked_reason": "candidate_missing_source"}
    try:
        return music_download(params)
    except (ToolInputError, OSError, subprocess.SubprocessError) as exc:
        return {"downloaded": False, "already_existed": False, "blocked_reason": "download_failed", "error": str(exc)}


def candidate_failure(candidate: dict[str, Any], download_result: dict[str, Any] | None) -> dict[str, Any]:
    failure = {
        "title": clean_text(candidate.get("title")),
        "artist": clean_text(candidate.get("artist")),
        "url": clean_text(candidate.get("url")),
        "reason": "track_not_available",
    }
    if download_result is not None:
        failure["reason"] = str(download_result.get("blocked_reason") or "download_failed")
        if download_result.get("error"):
            failure["error"] = str(download_result.get("error"))
    return failure


def run_download(context: dict[str, Any], source: str) -> Path:
    library_dir = context["library_dir"]
    command = resolve_download_command(context)
    if not command:
        raise ToolInputError("yt-dlp is not available")
    output_template = "%(title).200B [%(id)s].%(ext)s"
    argv = [
        command,
        "--no-playlist",
        "--paths",
        str(library_dir),
        "--output",
        output_template,
        "--format",
        str(context["config"].get("download_format") or "bestaudio/best"),
        "--print",
        "after_move:filepath",
        source,
    ]
    completed = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    if completed.returncode != 0:
        raise ToolInputError(f"music download failed: {completed.stderr.strip() or completed.stdout.strip()}")
    candidates = [Path(line.strip()).expanduser() for line in completed.stdout.splitlines() if line.strip()]
    for candidate in reversed(candidates):
        resolved = candidate if candidate.is_absolute() else library_dir / candidate
        if resolved.exists():
            return resolved.resolve()
    media_files = [path for path in library_dir.rglob("*") if path.is_file()]
    if not media_files:
        raise ToolInputError("music download completed but no media file was found")
    return max(media_files, key=lambda item: item.stat().st_mtime).resolve()


def start_playback(context: dict[str, Any], track: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(track.get("path", "")))
    if not path.is_file():
        return {"started": False, "status": "missing_file", "backend": "", "path": str(path)}
    playback = start_playlist_playback(context, [track])
    if "paths" in playback:
        playback["path"] = str(path)
    return playback


def start_playlist_playback(context: dict[str, Any], tracks: list[dict[str, Any]]) -> dict[str, Any]:
    paths = [Path(str(track.get("path", ""))) for track in tracks]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        return {"started": False, "status": "missing_file", "backend": "", "paths": [str(path) for path in paths], "missing_paths": missing, "track_count": len(paths)}
    if bool(context["config"].get("dry_run_player")):
        return {"started": True, "status": "dry_run", "backend": "dry_run", "paths": [str(path) for path in paths], "track_count": len(paths)}
    player_name = str(context["config"].get("player") or "vlc").casefold()
    player_command = context["config"].get("player_command")
    if isinstance(player_command, list) and player_command:
        first_path = str(paths[0])
        path_values = [str(path) for path in paths]
        argv = [str(item).replace("{path}", first_path).replace("{paths}", os.pathsep.join(path_values)) for item in player_command]
        if not any("{path}" in str(item) or "{paths}" in str(item) for item in player_command):
            argv.extend(path_values)
        process = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        remember_player_process(process)
        return {"started": True, "status": "playing", "backend": "configured_player", "paths": path_values, "pid": process.pid, "track_count": len(paths)}
    if player_name == "vlc":
        vlc = resolve_vlc(context)
        if not vlc:
            return {"started": False, "status": "vlc_not_available", "backend": "vlc", "paths": [str(path) for path in paths], "track_count": len(paths)}
        extra_args = [str(item) for item in context["config"].get("vlc_extra_args", DEFAULT_CONFIG["vlc_extra_args"]) if isinstance(item, str)]
        process = subprocess.Popen([vlc, *extra_args, *[str(path) for path in paths]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        remember_player_process(process)
        return {"started": True, "status": "playing", "backend": "vlc", "paths": [str(path) for path in paths], "pid": process.pid, "command": vlc, "track_count": len(paths)}
    if os.name == "nt":
        os.startfile(str(paths[0]))  # type: ignore[attr-defined]
        return {"started": True, "status": "playing", "backend": "windows_default", "paths": [str(path) for path in paths], "track_count": 1}
    opener = shutil.which("xdg-open") or shutil.which("open")
    if opener:
        process = subprocess.Popen([opener, str(paths[0])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        remember_player_process(process)
        return {"started": True, "status": "playing", "backend": Path(opener).name, "paths": [str(path) for path in paths], "pid": process.pid, "track_count": 1}
    return {"started": False, "status": "no_player_available", "backend": "", "paths": [str(path) for path in paths], "track_count": len(paths)}


def remember_player_process(process: subprocess.Popen[Any]) -> None:
    reap_player_processes()
    _PLAYER_PROCESSES.append(process)


def reap_player_processes() -> None:
    _PLAYER_PROCESSES[:] = [process for process in _PLAYER_PROCESSES if process.poll() is None]


def player_status(context: dict[str, Any]) -> dict[str, Any]:
    player_name = str(context["config"].get("player") or "vlc").casefold()
    if player_name == "vlc":
        command = resolve_vlc(context)
        return {"name": "vlc", "available": bool(command), "command": command or ""}
    player_command = context["config"].get("player_command")
    if isinstance(player_command, list) and player_command:
        return {"name": "configured_player", "available": True, "command": " ".join(str(item) for item in player_command)}
    return {"name": player_name, "available": False, "command": ""}


def resolve_vlc(context: dict[str, Any]) -> str:
    configured = clean_text(os.environ.get("VLC_PATH")) or clean_text(context["config"].get("vlc_command"))
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path.resolve())
        found = shutil.which(configured)
        if found:
            return found
    found = shutil.which("vlc")
    return found or ""


def play_relative(context: dict[str, Any], database: dict[str, Any], state: dict[str, Any], offset: int) -> dict[str, Any]:
    queue = [track_id for track_id in state.get("queue", []) if track_id in database["tracks"]]
    if not queue:
        return {"changed": False, "blocked_reason": "queue_empty"}
    if bool(state.get("shuffle")) and offset > 0:
        index = random.randrange(len(queue))
    else:
        index = int(state.get("queue_index") or 0) + offset
    if index >= len(queue):
        index = 0 if bool(state.get("repeat")) else len(queue) - 1
    if index < 0:
        index = len(queue) - 1 if bool(state.get("repeat")) else 0
    state["queue"] = queue
    state["queue_index"] = index
    track = database["tracks"][queue[index]]
    stop_playback(state)
    playback = start_playback(context, track)
    state["current_track_id"] = track["id"]
    state["playback_status"] = playback["status"]
    state["backend"] = playback["backend"]
    state["player_pid"] = playback.get("pid")
    state["started_at"] = time.time()
    add_recent(database, track["id"])
    save_state(context, state)
    save_database(context, database)
    return {"changed": playback["started"], "track": track_public(track), "playback": playback, "queue": queue_public(database, state)}


def stop_playback(state: dict[str, Any]) -> bool:
    pid = state.get("player_pid")
    if isinstance(pid, int):
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, timeout=10)
            else:
                os.kill(pid, 15)
            return True
        except OSError:
            return False
    return send_media_key("stop")


def refresh_state(context: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    if state.get("playback_status") not in {"playing", "paused"}:
        return state
    if state.get("backend") == "dry_run":
        return state
    pid = state.get("player_pid")
    if isinstance(pid, int) and pid > 0 and not process_is_running(pid):
        state["playback_status"] = "stopped"
        state["player_pid"] = None
        state["last_position_seconds"] = elapsed_since(state.get("started_at"))
    return state


def process_is_running(pid: int) -> bool:
    if os.name == "nt":
        completed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return completed.returncode == 0 and str(pid) in completed.stdout
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def elapsed_since(value: Any) -> int:
    if isinstance(value, int | float):
        return max(0, int(time.time() - float(value)))
    return 0


def send_media_key(operation: str) -> bool:
    if os.name != "nt":
        return False
    char_by_operation = {"pause": "179", "resume": "179", "play_pause": "179", "stop": "178"}
    code = char_by_operation.get(operation)
    if not code:
        return False
    command = "$shell = New-Object -ComObject WScript.Shell; $shell.SendKeys([char]" + code + ")"
    completed = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=10)
    return completed.returncode == 0


def playlist_tracks(database: dict[str, Any], name: str) -> list[str]:
    playlist = database["playlists"].get(playlist_key(name))
    if not isinstance(playlist, dict):
        return []
    track_ids = playlist.get("track_ids")
    if not isinstance(track_ids, list):
        return []
    return [track_id for track_id in track_ids if isinstance(track_id, str) and track_id in database["tracks"]]


def playlist_key(name: str) -> str:
    return normalize_text(name).replace(" ", "-") or "playlist"


def playlists_public(database: dict[str, Any]) -> list[dict[str, Any]]:
    return [playlist_public(database, key) for key in sorted(database["playlists"], key=sort_text)]


def playlist_public(database: dict[str, Any], key: str) -> dict[str, Any] | None:
    playlist = database["playlists"].get(key)
    if not isinstance(playlist, dict):
        return None
    tracks = [database["tracks"][track_id] for track_id in playlist.get("track_ids", []) if track_id in database["tracks"]]
    return {"name": playlist.get("name") or key, "track_count": len(tracks), "tracks": tracks_public(tracks)}


def add_recent(database: dict[str, Any], track_id: str) -> None:
    track = database["tracks"].get(track_id)
    if not track:
        return
    track["play_count"] = int(track.get("play_count") or 0) + 1
    track["last_played_at"] = time.time()
    recent = [item for item in database["recent"] if item != track_id]
    recent.insert(0, track_id)
    database["recent"] = recent[:100]


def queue_public(database: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    queue = [track_public(database["tracks"].get(track_id)) for track_id in state.get("queue", []) if track_id in database["tracks"]]
    return {"index": state.get("queue_index", 0), "length": len(queue), "tracks": [track for track in queue if track]}


def tracks_public(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [public for public in (track_public(track) for track in tracks) if public]


def track_public(track: dict[str, Any] | None, score: float | None = None) -> dict[str, Any] | None:
    if not isinstance(track, dict):
        return None
    result = {
        "id": track.get("id"),
        "title": track.get("title"),
        "artist": track.get("artist"),
        "album": track.get("album"),
        "path": track.get("path"),
        "filename": track.get("filename"),
        "play_count": track.get("play_count", 0),
        "last_played_at": track.get("last_played_at"),
    }
    if score is not None:
        result["match_score"] = round(score, 3)
    return result


def state_public(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "current_track_id": state.get("current_track_id") or "",
        "playback_status": state.get("playback_status") or "stopped",
        "backend": state.get("backend") or "",
        "started_at": state.get("started_at"),
        "last_position_seconds": state.get("last_position_seconds") or 0,
        "shuffle": bool(state.get("shuffle")),
        "repeat": bool(state.get("repeat")),
    }


def downloader_available(context: dict[str, Any]) -> bool:
    return bool(resolve_download_command(context))


def resolve_download_command(context: dict[str, Any]) -> str:
    command = str(context["config"].get("download_command") or "")
    if not command:
        return ""
    path = Path(command).expanduser()
    if path.is_file():
        return str(path.resolve())
    return shutil.which(command) or ""


def clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    parts: list[str] = []
    last_space = False
    for char in normalized:
        if char.isalnum():
            parts.append(char)
            last_space = False
        elif char.isspace() or char in {"-", "_", ".", ",", ":", ";", "|", "/", "\\"}:
            if not last_space:
                parts.append(" ")
                last_space = True
    return " ".join("".join(parts).split())


def sort_text(value: Any) -> str:
    return normalize_text(str(value))


def bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.strip():
        try:
            number = int(value.strip())
        except ValueError:
            number = fallback
    else:
        number = fallback
    return max(minimum, min(maximum, number))
