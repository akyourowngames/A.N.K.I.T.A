import asyncio
from typing import List, Optional
from core.models import Message
import core.store as store


try:
    from identity.persona import GEO_BRIEF as _GEO_BRIEF
except Exception:
    _GEO_BRIEF = ""

DEFAULT_SYSTEM = ("You are Zumba, a concise helpful personal assistant. " + _GEO_BRIEF).strip()


def _agent_answer(msgs, model: str, key: str, max_tokens, temperature) -> "str | None":
    """Run the MCP agent loop (tools available). Returns reply or None if no tools."""
    try:
        from mcpclient.manager import manager as _mgr, run_tool as _run_tool
        from mcpclient.agent import run_agent_loop
        mgr = _mgr()
        tools = mgr.all_tools()
    except Exception:
        return None
    if not tools:
        return None
    try:
        from main import _mcp_preamble as _pre
        convo = _pre(list(msgs), tools)
    except Exception:
        convo = list(msgs)
    res = run_agent_loop(
        convo, model,
        call_model=lambda ms, m, tools, **kw: __import__("core.api_client", fromlist=["chat_completion"]).chat_completion(
            ms, m, api_key=key, tools=tools, max_tokens=max_tokens, temperature=temperature),
        execute_tool=lambda n, a: _run_tool(n, a),
        tools=tools, max_iterations=10)
    return (getattr(res, "content", "") or "")


def build_messages(session_id: str, system: str, user_text: str) -> List[Message]:
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


def recall_block(query: str) -> str:
    try:
        import os
        if os.getenv("ZUMBA_NO_MEMORY") == "1":
            return ""
        from memory import get_memory
        mem = get_memory()
        return mem.recall(query, top_k=6, max_bytes=3500) or ""
    except Exception:
        return ""


def answer(session_id: str, text: str, system: str = DEFAULT_SYSTEM,
           model: Optional[str] = None, max_tokens: Optional[int] = None,
           temperature: Optional[float] = None) -> str:
    from core import api_client
    from core.config import get_api_key, get_default_model
    chosen = (model or get_default_model()).strip()
    key = get_api_key(require=True)
    if not store.get_session(session_id):
        store.create_session(session_id, chosen, system or "")
    msgs = build_messages(session_id, system or "", text)
    mem_block = recall_block(text)
    if mem_block:
        msgs.insert(0, Message(role="system", content="Relevant memory:\n" + mem_block))
    store.add_message(session_id, "user", text)
    try:
        agent_reply = _agent_answer(msgs, chosen, key, max_tokens, temperature)
    except Exception:
        agent_reply = None
    if agent_reply and agent_reply.strip():
        store.add_message(session_id, "assistant", agent_reply)
        try:
            from memory import get_memory as _gm
            _gm().capture_async(text, agent_reply, session_id=session_id, kind="chat")
        except Exception:
            pass
        return agent_reply
    result = api_client.chat_completion(msgs, chosen, api_key=key,
                                        max_tokens=max_tokens, temperature=temperature)
    store.add_message(session_id, "assistant", result.content)
    try:
        from memory import get_memory as _gm
        _gm().capture_async(text, result.content, session_id=session_id, kind="chat")
    except Exception:
        pass
    return result.content


async def aanswer(session_id: str, text: str, system: str = DEFAULT_SYSTEM,
                  model: Optional[str] = None, max_tokens: Optional[int] = None,
                  temperature: Optional[float] = None) -> str:
    return await asyncio.to_thread(answer, session_id, text, system, model, max_tokens, temperature)
