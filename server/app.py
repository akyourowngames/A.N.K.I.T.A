import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
from contextlib import asynccontextmanager
import json, time, asyncio

from core import api_client
from core.config import get_api_key, get_base_url, get_default_model
from core.models import Message
import core.store as store
from core.chat import Conversation
from core.chat_pipeline import build_messages as _pipeline_build, recall_block as _pipeline_recall
from server.tts import HEAVY_MALE_VOICES, tts_short_text as _tts_short_text

@asynccontextmanager
async def _lifespan(app: FastAPI):
    from knowledge import service as knowledge_service
    knowledge_service.start()
    try:
        from server.telegram_channel import start_if_configured
        start_if_configured(app)
    except Exception:
        pass
    yield
    knowledge_service.stop()
    try:
        from memory import get_memory as _gm
        _gm().flush(timeout=5.0)
    except Exception:
        pass

app = FastAPI(title="ZUMBA API", version="1.0.0", lifespan=_lifespan)
from server.knowledge_api import router as knowledge_router
app.include_router(knowledge_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    model: Optional[str] = None
    system: Optional[str] = "You are Zumba, a concise helpful personal assistant."
    stream: bool = False
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None

class SessionCreate(BaseModel):
    model: Optional[str] = None
    system: Optional[str] = None
    title: Optional[str] = "New chat"

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "zumba", "time": time.time()}

@app.get("/api/models")
def models(refresh: bool = False):
    try:
        ms = api_client.list_models()
        return {"models": [m.to_dict() for m in ms], "default": get_default_model()}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.get("/api/sessions")
def list_sessions(limit: int = 30, search: str = ""):
    store.migrate_legacy_dir(store.get_sessions_dir() if hasattr(store, "get_sessions_dir") else None) if False else None
    try:
        from core.config import get_sessions_dir
        store.migrate_legacy(get_sessions_dir())
    except Exception:
        pass
    return {"sessions": store.list_sessions(limit=limit, search=search)}

@app.post("/api/sessions")
def create_session(body: SessionCreate):
    from core.store import new_session_id, create_session as db_create
    sid = new_session_id()
    model = (body.model or get_default_model()).strip()
    db_create(sid, model, body.system or "", title=body.title or "New chat")
    return {"id": sid, "model": model}

@app.get("/api/sessions/{sid}")
def get_session(sid: str):
    data = store.get_session(sid)
    if not data:
        raise HTTPException(404, "session not found")
    return data

@app.delete("/api/sessions/{sid}")
def delete_session(sid: str):
    store.delete_session(sid)
    return {"deleted": sid}

def _build_messages(session_id: str, system: str, user_text: str):
    return _pipeline_build(session_id, system, user_text)

def _recall_block(query: str) -> str:
    return _pipeline_recall(query)

@app.post("/api/chat")
def chat(body: ChatRequest):
    model = (body.model or get_default_model()).strip()
    try:
        key = get_api_key(require=True)
    except RuntimeError as e:
        raise HTTPException(401, str(e))
    sid = body.session_id or store.new_session_id()
    if not store.get_session(sid):
        store.create_session(sid, model, body.system or "")
    msgs = _build_messages(sid, body.system or "", body.message)
    mem_block = _recall_block(body.message)
    if mem_block:
        msgs.insert(0, Message(role="system", content="Relevant memory:\n" + mem_block))
    store.add_message(sid, "user", body.message)
    try:
        result = api_client.chat_completion(msgs, model, api_key=key, max_tokens=body.max_tokens, temperature=body.temperature)
    except api_client.KiloError as e:
        raise HTTPException(502, str(e))
    store.add_message(sid, "assistant", result.content)
    try:
        from memory import get_memory as _gm
        _gm().capture_async(body.message, result.content, session_id=sid, kind="chat")
    except Exception:
        pass
    return {"session_id": sid, "reply": result.content, "model": result.model or model,
            "usage": {"prompt": result.usage.prompt_tokens, "completion": result.usage.completion_tokens, "total": result.usage.total_tokens}}

@app.post("/api/chat/agent")
def chat_agent(body: ChatRequest):
    model = (body.model or get_default_model()).strip()
    try:
        key = get_api_key(require=True)
    except RuntimeError as e:
        raise HTTPException(401, str(e))
    sid = body.session_id or store.new_session_id()
    if not store.get_session(sid):
        store.create_session(sid, model, body.system or "")

    def gen():
        import queue
        import threading
        import time
        started = time.monotonic()
        yield f"event: meta\ndata: {json.dumps({'session_id': sid, 'model': model})}\n\n"
        events = queue.Queue()
        holder = {"tools_used": 0, "transcript": []}
        def emit(kind, data):
            events.put((kind, data))
        def on_token(token):
            holder.setdefault("first_token_ms", round((time.monotonic() - started) * 1000))
            emit("token", {"token": token})
        def on_start(name, args):
            holder["tools_used"] += 1
            holder.setdefault("first_tool_ms", round((time.monotonic() - started) * 1000))
            emit("tool_start", {"id": holder["tools_used"], "name": name, "args": args})
        def on_end(name, args, result):
            emit("tool_end", {"id": holder["tools_used"], "name": name, "result": str(result or "")[:4000]})
        def run():
            try:
                msgs = _build_messages(sid, body.system or "", body.message)
                mem_block = _recall_block(body.message)
                if mem_block:
                    msgs.insert(0, Message(role="system", content="Relevant memory:\n" + mem_block))
                holder["context_ms"] = round((time.monotonic() - started) * 1000)
                store.add_message(sid, "user", body.message)
                from mcpclient.manager import manager, run_tool
                from mcpclient.agent import run_agent_loop
                tools = manager().all_tools()
                if tools:
                    from main import _mcp_preamble
                    msgs = _mcp_preamble(list(msgs), tools)
                result = run_agent_loop(
                    msgs, model,
                    call_model=lambda ms, m, tools, **kw: api_client.stream_agent_completion(
                        ms, m, api_key=key, tools=tools, max_tokens=body.max_tokens,
                        temperature=body.temperature, on_token=on_token),
                    execute_tool=run_tool, tools=tools, on_tool_start=on_start,
                    on_tool=on_end, transcript_out=holder["transcript"],
                )
                for message in holder["transcript"]:
                    store.add_message(sid, message.role, (message.content or "").strip() or "(tool call)")
                store.add_message(sid, "assistant", result.content)
                try:
                    from memory import get_memory
                    get_memory().capture_async(body.message, result.content, session_id=sid, kind="chat")
                except Exception as exc:
                    emit("memory_warning", {"error": "Memory capture failed: " + str(exc)})
                emit("done", {"session_id": sid, "full": result.content, "tools_used": holder["tools_used"],
                              "timing": {k: holder[k] for k in ("context_ms", "first_token_ms", "first_tool_ms") if k in holder},
                              "elapsed_ms": round((time.monotonic() - started) * 1000)})
            except Exception as exc:
                emit("error", {"error": str(exc)})
            finally:
                events.put(None)
        threading.Thread(target=run, daemon=True, name="zumba-agent").start()
        while True:
            try:
                event = events.get(timeout=15)
            except queue.Empty:
                yield ": heartbeat\n\n"
                continue
            if event is None:
                return
            kind, payload = event
            yield f"event: {kind}\ndata: {json.dumps(payload)}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/chat/stream")
def chat_stream(body: ChatRequest):
    model = (body.model or get_default_model()).strip()
    try:
        key = get_api_key(require=True)
    except RuntimeError as e:
        raise HTTPException(401, str(e))
    sid = body.session_id or store.new_session_id()
    if not store.get_session(sid):
        store.create_session(sid, model, body.system or "")
    msgs = _build_messages(sid, body.system or "", body.message)
    mem_block = _recall_block(body.message)
    if mem_block:
        msgs.insert(0, Message(role="system", content="Relevant memory:\n" + mem_block))
    store.add_message(sid, "user", body.message)

    def gen():
        yield f"event: meta\ndata: {json.dumps({'session_id': sid, 'model': model})}\n\n"
        full = ""
        try:
            for chunk in api_client.stream_chat_completion(msgs, model, api_key=key, max_tokens=body.max_tokens, temperature=body.temperature):
                full += chunk
                yield f"data: {json.dumps({'token': chunk})}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            return
        try:
            store.add_message(sid, "assistant", full)
        except Exception:
            pass
        try:
            from memory import get_memory
            get_memory().capture_async(body.message, full, session_id=sid, kind="chat")
        except Exception:
            pass
        yield f"event: done\ndata: {json.dumps({'session_id': sid, 'full': full})}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            try:
                body = ChatRequest(**json.loads(raw))
            except Exception:
                await ws.send_json({"type": "error", "error": "send JSON {message, session_id?, model?}"})
                continue
            model = (body.model or get_default_model()).strip()
            try:
                key = get_api_key(require=True)
            except RuntimeError as e:
                await ws.send_json({"type": "error", "error": str(e)})
                continue
            sid = body.session_id or store.new_session_id()
            if not store.get_session(sid):
                store.create_session(sid, model, body.system or "")
            msgs = _build_messages(sid, body.system or "", body.message)
            mem_block = _recall_block(body.message)
            if mem_block:
                msgs.insert(0, Message(role="system", content="Relevant memory:\n" + mem_block))
            store.add_message(sid, "user", body.message)
            await ws.send_json({"type": "start", "session_id": sid, "model": model})
            full = ""
            try:
                loop = asyncio.get_event_loop()
                def _run():
                    return api_client.chat_completion(msgs, model, api_key=key)
                result = await loop.run_in_executor(None, _run)
                full = result.content
                for i in range(0, len(full), 24):
                    await ws.send_json({"type": "token", "token": full[i:i+24]})
                    await asyncio.sleep(0.01)
            except Exception as e:
                await ws.send_json({"type": "error", "error": str(e)})
                continue
            try:
                store.add_message(sid, "assistant", full)
            except Exception:
                pass
            try:
                from memory import get_memory
                get_memory().capture_async(body.message, full, session_id=sid, kind="chat")
            except Exception:
                pass
            await ws.send_json({"type": "done", "session_id": sid, "full": full})
    except WebSocketDisconnect:
        return

@app.get("/api/memory/search")
def memory_search(q: str, top_k: int = 8):
    try:
        from memory import get_memory
        hits = get_memory().recall(q, top_k=top_k, max_bytes=4500)
        return {"query": q, "recall": hits}
    except Exception as e:
        raise HTTPException(500, str(e))

class MemoryAdd(BaseModel):
    text: str

@app.post("/api/memory/add")
def memory_add(body: MemoryAdd):
    try:
        from memory import get_memory
        mem = get_memory()
        mem.capture_async(body.text, "", session_id="api", kind="note")
        mem.flush(timeout=30.0)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/memory/retry")
def memory_retry():
    from memory import get_memory, inbox
    count = inbox.retry_failed()
    mem = get_memory()
    mem._restore_captures()
    return {"queued": count}


@app.get("/api/memory/captures")
def memory_captures():
    from memory import inbox
    return inbox.status()

@app.post("/api/voice/stt")
async def voice_stt(file: UploadFile = File(...)):
    data = await file.read()
    return {"transcript": "", "note": "STT not configured yet — plug Whisper/faster-whisper here. Received bytes: %d" % len(data),
            "ready_for": "frontend MediaRecorder webm/opus upload", "next": "POST /api/chat with transcript"}

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "en-US-GuyNeural"
    rate: Optional[str] = "-10%"
    pitch: Optional[str] = "-20Hz"



@app.get("/api/voice/voices")
def voice_voices():
    return {"default": HEAVY_MALE_VOICES[0], "heavy_male": HEAVY_MALE_VOICES}

@app.post("/api/voice/tts")
def voice_tts(body: TTSRequest):
    short = _tts_short_text(body.text)
    if not short:
        raise HTTPException(400, "empty text")
    voice = (body.voice or HEAVY_MALE_VOICES[0]).strip()
    if voice.lower() == "default":
        voice = HEAVY_MALE_VOICES[0]
    try:
        import asyncio as _asyncio
        import edge_tts as _edge
        import io as _io

        async def _gen(v: str):
            buf = _io.BytesIO()
            comm = _edge.Communicate(short, voice=v, rate=body.rate or "-10%", pitch=body.pitch or "-20Hz")
            async for chunk in comm.stream():
                if chunk.get("type") == "audio" and chunk.get("data"):
                    buf.write(chunk["data"])
            buf.seek(0)
            return buf.read()

        candidates = [voice] + [v for v in HEAVY_MALE_VOICES if v != voice]
        audio: bytes | None = None
        used = candidates[0]
        last_err = ""
        for v in candidates:
            try:
                audio = _asyncio.run(_gen(v))
                if audio:
                    used = v
                    break
            except Exception as e:
                last_err = str(e)[:200]
                continue
        if not audio:
            raise RuntimeError(last_err or "edge-tts produced no audio")
        return StreamingResponse(_io.BytesIO(audio), media_type="audio/mpeg",
            headers={"X-Voice": used, "X-Spoke-Text": short[:200], "Cache-Control": "no-cache"})
    except ImportError:
        # edge-tts not installed — frontend falls back to browser SpeechSynthesis
        return {"audio_url": None, "voice": voice, "spoke_text": short,
                "note": "pip install edge-tts for server-side Edge audio"}
    except Exception as e:
        raise HTTPException(502, f"edge-tts failed: {str(e)[:300]}")

@app.get("/api/telegram/status")
def telegram_status():
    import os
    try:
        from server import channel_store as _cs
        offset = _cs.get_next_offset("telegram")
    except Exception:
        offset = -1
    token_set = bool((os.getenv("ZUMBA_TG_BOT_TOKEN") or "").strip())
    allowed = (os.getenv("ZUMBA_TG_ALLOWED_CHAT_IDS") or "").strip()
    return {"configured": token_set, "allowed_chats": allowed, "next_offset": offset}

@app.websocket("/ws/voice")
async def ws_voice(ws: WebSocket):
    await ws.accept()
    await ws.send_json({"type": "ready", "message": "voice socket open — send {audio_chunk_b64} or {transcript}; server will reply with chat tokens"})
    try:
        while True:
            msg = await ws.receive_json()
            if "transcript" in msg:
                await ws.send_json({"type": "ack", "echo": msg["transcript"][:200], "hint": "now POST /api/chat/stream or send {message} here"})
            elif "message" in msg:
                await ws.send_json({"type": "token", "token": "(voice chat path: forward to /ws/chat — frontend already does this)"})
                await ws.send_json({"type": "done"})
            else:
                await ws.send_json({"type": "ack", "hint": "send base64 opus chunks as {audio_chunk_b64} — buffered for future Whisper"})
    except WebSocketDisconnect:
        return
