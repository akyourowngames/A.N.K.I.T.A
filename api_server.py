from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from jarvis_nim import load_dotenv
from memory_brain import graph_export, memory_brain_reindex, memory_brain_status, search_memory_brain
from web_assistant import WebAssistantRuntime

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


@app.get("/api/dashboard")
def dashboard_state() -> dict[str, Any]:
    return compact_dashboard_state(health())


@app.get("/api/memory/status")
def memory_status() -> dict[str, Any]:
    try:
        return memory_brain_status(Path.cwd())
    except Exception as error:
        return {"enabled": False, "error": str(error)}


@app.get("/api/memory/graph")
def memory_graph() -> dict[str, Any]:
    try:
        return graph_export(Path.cwd())
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.get("/api/memory/search")
def memory_search(query: str, max_facts: int = 6, max_hops: int = 2) -> dict[str, Any]:
    try:
        return search_memory_brain(query, Path.cwd(), max_facts=max_facts, max_hops=max_hops)
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/memory/reindex")
def memory_reindex() -> dict[str, Any]:
    try:
        return memory_brain_reindex(Path.cwd())
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


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


def compact_dashboard_state(health_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": bool(health_payload.get("ok")),
        "assistant": {
            "name": clean_text(health_payload.get("assistant")) or "JARVIS",
            "model": clean_text(health_payload.get("model")) or "Unknown",
            "streaming": bool(health_payload.get("streaming")),
            "tools": int(health_payload.get("tools") or 0),
        },
    }


def clean_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
