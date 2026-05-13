from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from jarvis_nim import load_dotenv
from web_assistant import WebAssistantRuntime
from tools.entertainment_agent import entertainment_context, entertainment_status

load_dotenv(Path.cwd() / ".env")


class ChatRequest(BaseModel):
    message: str
    session_id: str = ""


class ChatResponse(BaseModel):
    session_id: str
    reply: str


app = FastAPI(title="Jarvis Web Assistant")
runtime: WebAssistantRuntime | None = None


def configured_origins() -> list[str]:
    raw = os.environ.get("JARVIS_WEB_ALLOWED_ORIGINS", "").strip()
    origins = [item.strip() for item in raw.split(",") if item.strip()]
    if origins:
        return origins
    return ["http://localhost:3000", "http://127.0.0.1:3000"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


def get_runtime() -> WebAssistantRuntime:
    global runtime
    if runtime is None:
        runtime = WebAssistantRuntime.from_env(Path.cwd())
    return runtime


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        return get_runtime().health()
    except Exception as error:
        return {"ok": False, "error": str(error)}


@app.get("/api/entertainment/context")
def entertainment_context_state() -> dict[str, Any]:
    try:
        return entertainment_context({"operation": "get"})
    except Exception as error:
        return {"action_completed": False, "error": str(error), "lastSearchResults": []}


@app.get("/api/dashboard")
def dashboard_state() -> dict[str, Any]:
    health_payload = health()
    try:
        entertainment_payload = entertainment_status({})
        return compact_dashboard_state(health_payload, entertainment_payload)
    except Exception as error:
        payload = compact_dashboard_state(health_payload, None)
        payload["music"]["status"] = "Unavailable"
        payload["music"]["detail"] = str(error)
        return payload


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> dict[str, str]:
    try:
        return get_runtime().run_chat_turn(request.message, request.session_id)
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/chat/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    async def events() -> Any:
        try:
            async for event in get_runtime().stream_chat(request.message, request.session_id):
                yield sse_event(event)
        except Exception as error:
            yield sse_event({"type": "error", "message": str(error)})

    return StreamingResponse(events(), media_type="text/event-stream")


def sse_event(event: dict[str, str]) -> str:
    event_type = event.get("type", "message")
    return "event: " + event_type + "\n" + "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"


def compact_dashboard_state(health_payload: dict[str, Any], entertainment_payload: dict[str, Any] | None) -> dict[str, Any]:
    entertainment_payload = entertainment_payload if isinstance(entertainment_payload, dict) else {}
    library = clean_dict(entertainment_payload.get("library"))
    player = clean_dict(entertainment_payload.get("player"))
    state = clean_dict(player.get("state"))
    track = clean_dict(entertainment_payload.get("current_track")) or clean_dict(player.get("current_track"))
    player_running = bool(entertainment_payload.get("player_running") or player.get("player_running"))
    playback_status = clean_text(state.get("playback_status")) or "stopped"
    duration_seconds = clean_number(track.get("duration_seconds") or track.get("duration"))
    elapsed_seconds = playback_elapsed_seconds(player_running, playback_status, state, duration_seconds)

    return {
        "ok": bool(health_payload.get("ok")),
        "assistant": {
            "name": clean_text(health_payload.get("assistant")) or "JARVIS",
            "model": clean_text(health_payload.get("model")) or "Unknown",
            "streaming": bool(health_payload.get("streaming")),
            "tools": int(health_payload.get("tools") or 0),
        },
        "music": {
            "status": music_status_label(track, playback_status, player_running),
            "title": clean_text(track.get("title")) or "Nothing queued",
            "artist": clean_text(track.get("artist") or track.get("channel")),
            "source": clean_text(track.get("source") or track.get("source_platform")) or "local",
            "backend": clean_text(state.get("backend") or player.get("backend")) or "unavailable",
            "volume": int(clean_number(player.get("volume") or state.get("volume")) or 0),
            "queue_length": int(entertainment_payload.get("queue_length") or len(state.get("queue") or [])),
            "library_tracks": int(library.get("total_tracks") or 0),
            "duration_seconds": duration_seconds,
            "elapsed_seconds": elapsed_seconds,
            "progress_percent": progress_percent(elapsed_seconds, duration_seconds),
            "running": player_running,
            "detail": clean_text(player.get("summary") or entertainment_payload.get("summary")),
        },
    }


def clean_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def clean_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


def playback_elapsed_seconds(
    player_running: bool,
    playback_status: str,
    state: dict[str, Any],
    duration_seconds: float | None,
) -> int:
    if not player_running or playback_status.lower() != "playing":
        return 0
    started_at = clean_number(state.get("started_at"))
    if started_at is None:
        return 0
    elapsed = max(0, int(time.time() - started_at))
    if duration_seconds and duration_seconds > 0:
        return min(elapsed, int(duration_seconds))
    return elapsed


def progress_percent(elapsed_seconds: int, duration_seconds: float | None) -> int:
    if not duration_seconds or duration_seconds <= 0:
        return 0
    return max(0, min(100, round((elapsed_seconds / duration_seconds) * 100)))


def music_status_label(track: dict[str, Any], playback_status: str, player_running: bool) -> str:
    if not track:
        return "Idle"
    status = playback_status.strip().lower()
    if status == "playing" and player_running:
        return "Playing"
    if status == "playing":
        return "Last played"
    if status:
        return status.capitalize()
    return "Ready"
