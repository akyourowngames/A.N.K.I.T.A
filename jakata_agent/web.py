from __future__ import annotations

import argparse
import base64
import json
import random
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any, Callable, Iterator

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from jakata_agent.agent import JakataAgent
from jakata_agent.config import Settings, load_settings
from jakata_agent.router import PlanStep
from jakata_agent.runtime import JakataRuntime, create_runtime
from jakata_agent.tts import SarvamTTSClient


ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=32000)
    session_id: str | None = Field(default=None, max_length=200)
    tts: bool = False


@dataclass(slots=True)
class SessionContext:
    public_session_id: str
    runtime: JakataRuntime
    agent: JakataAgent
    chat_lock: Lock = field(default_factory=Lock)


@dataclass
class SessionManager:
    base_settings: Settings
    runtime_factory: Callable[[Settings], JakataRuntime] = create_runtime
    agent_builder: Callable[[JakataRuntime], JakataAgent] | None = None
    session_prefix: str = "web-"
    _lock: Lock = field(default_factory=Lock)
    _sessions: dict[str, SessionContext] = field(default_factory=dict)

    def get_or_create(self, session_id: str | None) -> SessionContext:
        public_id = (session_id or "").strip() or self.base_settings.session_id
        with self._lock:
            existing = self._sessions.get(public_id)
            if existing is not None:
                return existing
            storage_session_id = public_id
            if public_id != self.base_settings.session_id and not public_id.startswith(self.session_prefix):
                storage_session_id = f"{self.session_prefix}{public_id}"
            session_settings = replace(self.base_settings, session_id=storage_session_id)
            runtime = self.runtime_factory(session_settings)
            agent_builder = self.agent_builder or build_agent
            context = SessionContext(
                public_session_id=public_id,
                runtime=runtime,
                agent=agent_builder(runtime),
            )
            self._sessions[public_id] = context
            return context


def build_agent(runtime: JakataRuntime) -> JakataAgent:
    return JakataAgent(
        settings=runtime.settings,
        client=runtime.client,
        tools=runtime.tools,
        memory=runtime.memory,
        router=runtime.router,
        validator=runtime.validator,
        task_store=runtime.task_store,
        task_engine=runtime.task_engine,
    )


def create_app(
    *,
    base_settings: Settings | None = None,
    runtime_factory: Callable[[Settings], JakataRuntime] = create_runtime,
    agent_builder: Callable[[JakataRuntime], JakataAgent] = build_agent,
    session_manager: SessionManager | None = None,
    tts_client_factory: Callable[[Settings], Any] | None = None,
) -> FastAPI:
    if not FRONTEND_DIR.exists():
        raise RuntimeError(f"Frontend directory not found: {FRONTEND_DIR}")

    settings = base_settings or load_settings()
    manager = session_manager or SessionManager(
        base_settings=settings,
        runtime_factory=runtime_factory,
        agent_builder=agent_builder,
    )

    app = FastAPI(title="JAKATA Web", version="2.0.0")
    app.state.base_settings = settings
    app.state.session_manager = manager
    app.state.tts_client_factory = tts_client_factory or SarvamTTSClient.from_settings

    @app.get("/health")
    def health() -> dict[str, Any]:
        status = "healthy" if settings.tavily_api_key else "degraded"
        return {
            "status": status,
            "service": "jakata-web",
            "frontend": "jarvis",
            "models": settings.model_chain,
            "realtime_search": bool(settings.tavily_api_key),
            "tts": bool(settings.sarvam_api_key),
            "tts_speaker": settings.sarvam_tts_speaker,
        }

    @app.post("/chat/stream")
    def chat_stream(payload: ChatRequest) -> StreamingResponse:
        return _stream_response(manager, payload, mode="general", tts_client_factory=app.state.tts_client_factory)

    @app.post("/chat/realtime/stream")
    def chat_realtime_stream(payload: ChatRequest) -> StreamingResponse:
        return _stream_response(manager, payload, mode="realtime", tts_client_factory=app.state.tts_client_factory)

    @app.post("/chat/jarvis/stream")
    def chat_jarvis_stream(payload: ChatRequest) -> StreamingResponse:
        return _stream_response(manager, payload, mode="jarvis", tts_client_factory=app.state.tts_client_factory)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(FRONTEND_DIR / "index.html")

    @app.get("/{asset_path:path}")
    def frontend_asset(asset_path: str) -> FileResponse:
        if not asset_path:
            return FileResponse(FRONTEND_DIR / "index.html")
        path = _resolve_asset(FRONTEND_DIR, asset_path)
        return FileResponse(path)

    return app


def _stream_response(
    manager: SessionManager,
    payload: ChatRequest,
    *,
    mode: str,
    tts_client_factory: Callable[[Settings], Any],
) -> StreamingResponse:
    message = payload.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required.")

    context = manager.get_or_create(payload.session_id)

    def event_stream() -> Iterator[bytes]:
        with context.chat_lock:
            started = perf_counter()
            route, reasoning, search_step, general_steps, direct_answer = _resolve_route(context.agent, message, mode)
            first_chunk_sent = False
            tts_buffer = ""
            tts_spoken_chars = 0
            tts_closing_spoken = False
            tts_limit_reported = False
            try:
                yield _sse({"session_id": context.public_session_id, "chunk": "", "done": False})
                yield _sse({"activity": {"event": "query_detected", "message": message}, "done": False})

                if mode == "jarvis":
                    yield _sse(
                        {
                            "activity": {
                                "event": "decision",
                                "query_type": route,
                                "reasoning": reasoning,
                                "elapsed_ms": int((perf_counter() - started) * 1000),
                            },
                            "done": False,
                        }
                    )

                yield _sse({"activity": {"event": "routing", "route": route}, "done": False})
                yield _sse({"activity": {"event": "streaming_started", "route": route}, "done": False})
                if payload.tts:
                    if context.runtime.settings.sarvam_api_key:
                        yield _sse(
                            {
                                "activity": {
                                    "event": "tts_ready",
                                    "message": f"Voice ready: {context.runtime.settings.sarvam_tts_speaker}",
                                },
                                "done": False,
                            }
                        )
                    else:
                        yield _sse(
                            {
                                "activity": {
                                    "event": "tts_unavailable",
                                    "message": "SARVAM_API_KEY is not configured.",
                                },
                                "done": False,
                            }
                        )

                if direct_answer:
                    chunk_stream = context.agent.stream_direct_answer(message, direct_answer)
                elif route == "realtime":
                    yield _sse(
                        {
                            "activity": {
                                "event": "extracting_query",
                                "message": "Preparing a clean web query.",
                            },
                            "done": False,
                        }
                    )
                    query = str(search_step.args.get("query", "") if search_step else "").strip() or message
                    topic = str(search_step.args.get("topic", "general") if search_step else "general").strip() or "general"
                    max_results = int(search_step.args.get("max_results", 5) if search_step else 5)
                    yield _sse(
                        {
                            "activity": {
                                "event": "searching_web",
                                "message": f'Searching for "{query}"',
                                "query": query,
                            },
                            "done": False,
                        }
                    )
                    search_result = context.runtime.tools.execute(
                        "search_web",
                        {"query": query, "topic": topic, "max_results": max_results},
                    )
                    if search_result.ok:
                        results_payload = {
                            "query": query,
                            "answer": str(search_result.data.get("answer") or search_result.summary).strip(),
                            "results": list(search_result.data.get("results") or []),
                        }
                        yield _sse(
                            {
                                "activity": {
                                    "event": "search_completed",
                                    "message": f'Found {len(results_payload["results"])} web results.',
                                },
                                "done": False,
                            }
                        )
                        yield _sse({"search_results": results_payload, "done": False})
                        tool_results = [
                            {
                                "tool": "search_web",
                                "ok": True,
                                "summary": search_result.summary,
                                "data": search_result.data,
                                "error": search_result.error,
                                "rendered": search_result.summary,
                            }
                        ]
                        chunk_stream = context.agent.stream_tool_results_reply(message, tool_results)
                    else:
                        yield _sse(
                            {
                                "activity": {
                                    "event": "search_completed",
                                    "message": "Web search was unavailable. Falling back to standard chat.",
                                },
                                "done": False,
                            }
                        )
                        chunk_stream = context.agent.stream_general_chat(message)
                else:
                    yield _sse(
                        {
                            "activity": {
                                "event": "context_retrieved",
                                "message": "Memory and local tools are ready.",
                            },
                            "done": False,
                        }
                    )
                    tool_results = context.agent.execute_steps(general_steps)
                    if tool_results:
                        chunk_stream = context.agent.stream_tool_results_reply(message, tool_results)
                    else:
                        chunk_stream = context.agent.stream_general_chat(message)

                for current_model, chunk in chunk_stream:
                    if chunk and not first_chunk_sent:
                        first_chunk_sent = True
                        yield _sse(
                            {
                                "activity": {
                                    "event": "first_chunk",
                                    "route": route,
                                    "elapsed_ms": int((perf_counter() - started) * 1000),
                                },
                                "done": False,
                            }
                        )
                    if chunk or current_model:
                        yield _sse(
                            {
                                "chunk": chunk,
                                "model": current_model,
                                "session_id": context.public_session_id,
                                "done": False,
                            }
                        )
                    if payload.tts and chunk:
                        tts_buffer += chunk
                        segments, tts_buffer = _drain_tts_segments(tts_buffer)
                        for segment in segments:
                            tts_text, tts_spoken_chars, tts_closing_spoken = _next_tts_text_for_budget(
                                context.runtime.settings,
                                segment,
                                spoken_chars=tts_spoken_chars,
                                closing_spoken=tts_closing_spoken,
                            )
                            if tts_text:
                                yield from _tts_audio_events(context.runtime.settings, tts_client_factory, tts_text)
                            if tts_closing_spoken and not tts_limit_reported:
                                tts_limit_reported = True
                                yield _sse(
                                    {
                                        "activity": {
                                            "event": "tts_limited",
                                            "message": "Long reply voice was shortened; full text remains on screen.",
                                        },
                                        "done": False,
                                    }
                                )

                if payload.tts and tts_buffer.strip() and not tts_closing_spoken:
                    for segment in _final_tts_segments(tts_buffer):
                        tts_text, tts_spoken_chars, tts_closing_spoken = _next_tts_text_for_budget(
                            context.runtime.settings,
                            segment,
                            spoken_chars=tts_spoken_chars,
                            closing_spoken=tts_closing_spoken,
                        )
                        if tts_text:
                            yield from _tts_audio_events(context.runtime.settings, tts_client_factory, tts_text)
                        if tts_closing_spoken and not tts_limit_reported:
                            tts_limit_reported = True
                            yield _sse(
                                {
                                    "activity": {
                                        "event": "tts_limited",
                                        "message": "Long reply voice was shortened; full text remains on screen.",
                                    },
                                    "done": False,
                                }
                            )

                yield _sse({"session_id": context.public_session_id, "done": True})
            except Exception as exc:  # noqa: BLE001
                yield _sse({"error": str(exc), "session_id": context.public_session_id, "done": False})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _resolve_route(
    agent: JakataAgent,
    message: str,
    mode: str,
) -> tuple[str, str, PlanStep | None, list[PlanStep], str]:
    if mode == "realtime":
        decision = agent.plan(message)
        search_step = next((step for step in decision.steps if step.tool == "search_web"), None)
        if search_step is None:
            search_step = PlanStep(tool="search_web", args={"query": message, "topic": "general", "max_results": 5}, reason="explicit realtime mode")
        return "realtime", "Realtime mode selected.", search_step, [], ""

    decision = agent.plan(message)
    if decision.direct_answer:
        return "general", decision.steps[0].reason if decision.steps else "Planner answered directly.", None, [], decision.direct_answer
    search_step = next((step for step in decision.steps if step.tool == "search_web"), None)
    general_steps = [step for step in decision.steps if step.tool != "search_web"]

    if mode == "jarvis" and search_step is not None:
        reason = search_step.reason or "Planner selected live web search."
        return "realtime", reason, search_step, general_steps, ""

    if mode == "jarvis":
        primary_reason = decision.steps[0].reason if decision.steps else "Planner selected standard chat."
        return "general", primary_reason, None, general_steps, ""

    return "general", "General mode selected.", None, general_steps, ""


def _resolve_asset(root: Path, relative_path: str) -> Path:
    root = root.resolve()
    candidate = (root / relative_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise HTTPException(status_code=404, detail="Asset not found.")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="Asset not found.")
    return candidate


def _tts_audio_events(
    settings: Settings,
    tts_client_factory: Callable[[Settings], Any],
    text: str,
) -> Iterator[bytes]:
    clean_text = _clean_tts_text(text)
    if not clean_text or not settings.sarvam_api_key:
        return
    try:
        client = tts_client_factory(settings)
        audio = b"".join(client.stream(clean_text))
    except Exception as exc:  # noqa: BLE001
        yield _sse(
            {
                "activity": {
                    "event": "tts_error",
                    "message": f"TTS failed: {str(exc)[:160]}",
                },
                "done": False,
            }
        )
        return
    if audio:
        yield _sse(
            {
                "audio": base64.b64encode(audio).decode("ascii"),
                "audio_codec": settings.sarvam_tts_codec,
                "done": False,
            }
        )


def _next_tts_text_for_budget(
    settings: Settings,
    text: str,
    *,
    spoken_chars: int,
    closing_spoken: bool,
) -> tuple[str, int, bool]:
    clean_text = _clean_tts_text(text)
    if not clean_text or closing_spoken:
        return "", spoken_chars, closing_spoken
    max_chars = int(getattr(settings, "sarvam_tts_max_spoken_chars", 0) or 0)
    if max_chars <= 0:
        return clean_text, spoken_chars + len(clean_text), False
    if spoken_chars + len(clean_text) <= max_chars:
        return clean_text, spoken_chars + len(clean_text), False

    phrase = _long_tts_phrase(settings)
    remaining = max(0, max_chars - spoken_chars)
    prefix = _truncate_for_tts(clean_text, remaining)
    if prefix:
        return f"{prefix}. {phrase}", max_chars, True
    return phrase, max_chars, True


def _long_tts_phrase(settings: Settings) -> str:
    phrases = getattr(settings, "sarvam_tts_long_response_phrases", None) or [
        "The rest of the chat is on screen, sir. You can check it out."
    ]
    return random.choice([phrase for phrase in phrases if phrase.strip()] or ["The rest of the chat is on screen, sir."])


def _truncate_for_tts(text: str, max_chars: int) -> str:
    if max_chars < 80:
        return ""
    if len(text) <= max_chars:
        return text
    cut = text.rfind(" ", 0, max_chars)
    if cut < 80:
        cut = max_chars
    return text[:cut].rstrip(" ,;:-.")


def _drain_tts_segments(buffer: str, *, max_chars: int = 260) -> tuple[list[str], str]:
    segments: list[str] = []
    remaining = buffer
    while remaining:
        match = re.search(r"(?<=[.!?।])\s+|\n+", remaining)
        cut = match.end() if match else -1
        if cut < 0 and len(remaining) >= max_chars:
            cut = max(remaining.rfind(" ", 0, max_chars), remaining.rfind(",", 0, max_chars))
            if cut <= 0:
                cut = max_chars
        if cut < 0:
            break
        segment = remaining[:cut].strip()
        remaining = remaining[cut:].lstrip()
        if segment:
            segments.append(segment)
    return segments, remaining


def _final_tts_segments(buffer: str, *, max_chars: int = 260) -> list[str]:
    segments, remaining = _drain_tts_segments(buffer, max_chars=max_chars)
    tail = remaining.strip()
    if tail:
        segments.append(tail)
    return segments


def _clean_tts_text(text: str) -> str:
    cleaned = re.sub(r"`([^`]*)`", r"\1", text)
    cleaned = re.sub(r"[*_#>\[\]{}]", "", cleaned)
    cleaned = re.sub(r"^\s*[-•]\s*", "", cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r"https?://\S+", "link", cleaned)
    return " ".join(cleaned.split())


def _sse(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the JAKATA web frontend.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("jakata_agent.web:create_app", factory=True, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
