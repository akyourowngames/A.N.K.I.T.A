import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import json, time, asyncio

from core import api_client
from core.config import get_api_key, get_base_url, get_default_model
from core.models import Message
import core.store as store
from core.chat import Conversation

app = FastAPI(title="ZUMBA API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
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
    data = store.get_session(session_id) if session_id else None
    msgs: List[Message] = []
    if data:
        for m in data.get("messages", []):
            if m.get("role") in ("user", "assistant"):
                msgs.append(Message(role=m["role"], content=m.get("content", "")))
    else:
        if system:
            msgs = [Message(role="system", content=system)]
    if system and not any(m.role == "system" for m in msgs):
        msgs.insert(0, Message(role="system", content=system))
    msgs.append(Message(role="user", content=user_text))
    try:
        from core.context_budget import build_window, get_context_limit
        msgs = build_window(msgs, model_limit=get_context_limit(), cache={})
    except Exception:
        pass
    return msgs

def _recall_block(query: str) -> str:
    try:
        import os
        if os.getenv("ZUMBA_NO_MEMORY") == "1":
            return ""
        from memory import get_memory
        mem = get_memory()
        return mem.recall(query, top_k=6, max_bytes=3500) or ""
    except Exception:
        return ""

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
    msgs = _build_messages(sid, body.system or "", body.message)
    mem_block = _recall_block(body.message)
    if mem_block:
        msgs.insert(0, Message(role="system", content="Relevant memory:\n" + mem_block))
    store.add_message(sid, "user", body.message)

    def gen():
        import queue as _q, threading as _th
        yield f"event: meta\ndata: {json.dumps({'session_id': sid, 'model': model})}\n\n"
        try:
            from mcpclient.manager import manager as _mgr, run_tool as _run_tool
            from mcpclient.agent import run_agent_loop
            try:
                mgr = _mgr()
                tools = mgr.all_tools()
            except Exception:
                tools, mgr = [], None
            if not tools:
                full = ""
                try:
                    for chunk in api_client.stream_chat_completion(msgs, model, api_key=key, max_tokens=body.max_tokens, temperature=body.temperature):
                        full += chunk
                        yield f"event: token\ndata: {json.dumps({'token': chunk})}\n\n"
                except Exception as e:
                    yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                    return
                try:
                    store.add_message(sid, "assistant", full)
                except Exception:
                    pass
                try:
                    from memory import get_memory as _gm
                    _gm().capture_async(body.message, full, session_id=sid, kind="chat")
                except Exception:
                    pass
                yield f"event: done\ndata: {json.dumps({'session_id': sid, 'full': full, 'tools_used': 0})}\n\n"
                return
            events: _q.Queue = _q.Queue()
            def on_tool(name, args, result):
                try:
                    events.put({"name": name, "args": args or {}, "result": (result or "")[:8000]})
                except Exception:
                    pass
            holder: dict = {}
            def _run():
                try:
                    from core.chat import Conversation as _C
                    from main import _mcp_preamble, _fit_window
                    try:
                        convo = _mcp_preamble(list(msgs), tools)
                    except Exception:
                        convo = list(msgs)
                    try:
                        convo = _fit_window(convo)
                    except Exception:
                        pass
                    res = run_agent_loop(convo, model,
                        call_model=lambda ms, m, tools, **kw: api_client.chat_completion(ms, m, api_key=key, tools=tools, max_tokens=body.max_tokens, temperature=body.temperature),
                        execute_tool=lambda n, a: _run_tool(n, a),
                        tools=tools, on_tool=on_tool, transcript_out=holder.setdefault("transcript", []))
                    holder["result"] = res
                except Exception as e:
                    holder["error"] = str(e)
            t = _th.Thread(target=_run, daemon=True)
            t.start()
            import time as _time
            seen = 0
            # stream tool events while agent runs
            while t.is_alive():
                drained = False
                while True:
                    try:
                        ev = events.get_nowait()
                    except Exception:
                        break
                    drained = True
                    seen += 1
                    yield f"event: tool_start\ndata: {json.dumps({'id': seen, 'name': ev['name'], 'args': ev['args']})}\n\n"
                    yield f"event: tool_end\ndata: {json.dumps({'id': seen, 'name': ev['name'], 'result': ev['result'][:4000]})}\n\n"
                # heartbeat to keep connection alive
                if not drained:
                    _time.sleep(0.15)
            t.join(timeout=5)
            while True:
                try:
                    ev = events.get_nowait()
                except Exception:
                    break
                seen += 1
                yield f"event: tool_start\ndata: {json.dumps({'id': seen, 'name': ev['name'], 'args': ev['args']})}\n\n"
                yield f"event: tool_end\ndata: {json.dumps({'id': seen, 'name': ev['name'], 'result': ev['result'][:4000]})}\n\n"
            if "error" in holder:
                yield f"event: error\ndata: {json.dumps({'error': holder['error']})}\n\n"
                return
            res = holder.get("result")
            full = (getattr(res, "content", "") or "") if res is not None else ""
            # persist transcript + reply
            try:
                tr = holder.get("transcript") or []
                for m in tr:
                    c = (m.content or "").strip() or "(tool call)"
                    store.add_message(sid, m.role, c)
            except Exception:
                pass
            try:
                store.add_message(sid, "assistant", full)
            except Exception:
                pass
            try:
                from memory import get_memory as _gm
                _gm().capture_async(body.message, full, session_id=sid, kind="chat")
            except Exception:
                pass
            # stream final text in chunks for typewriter effect
            CH = 24
            for i in range(0, len(full), CH):
                yield f"event: token\ndata: {json.dumps({'token': full[i:i+CH]})}\n\n"
            yield f"event: done\ndata: {json.dumps({'session_id': sid, 'full': full, 'tools_used': seen})}\n\n"
        except Exception as e:
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
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

@app.post("/api/voice/stt")
async def voice_stt(file: UploadFile = File(...)):
    data = await file.read()
    return {"transcript": "", "note": "STT not configured yet — plug Whisper/faster-whisper here. Received bytes: %d" % len(data),
            "ready_for": "frontend MediaRecorder webm/opus upload", "next": "POST /api/chat with transcript"}

class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "default"

@app.post("/api/voice/tts")
def voice_tts(body: TTSRequest):
    return {"audio_url": None, "note": "TTS not configured yet — plug Piper/XTTS/Edge-TTS here.",
            "ready_for": "frontend SpeechSynthesis fallback (implemented client-side)", "text": body.text[:500]}

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
