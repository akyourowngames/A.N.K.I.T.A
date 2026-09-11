"""Agentic tool-use loop: model asks for tools -> ZUMBA executes via MCP -> repeat."""
import json
from typing import Any, Callable

from core.models import Message, ChatResult
import mcpclient.tools as mt
from core.execution import ExecutionCancelled


def _tool_calls_from(response: Any) -> list:
    msg = response.get("choices", [{}])[0].get("message", {}) if isinstance(response, dict) else {}
    calls = msg.get("tool_calls") or []
    return calls if isinstance(calls, list) else []


def _transient(status: Any) -> bool:
    try:
        # 500 rides along: the NIM gateway emits transient 500s under load
        # (and after long tool-turn histories). Without this, one flaky turn
        # kills the whole answer with the "temporarily unreachable" fallback.
        return int(status) in (408, 429, 500, 502, 503)
    except Exception:
        return False


def _call_with_retry(call_model, convo, model, tools, call_kwargs, retries: int = 2, control=None):
    """Call the model, retrying transient gateway failures (408/429/500/502/503).
    429s already honor Retry-After inside api_client — only one agent-level retry
    there to avoid long stalls."""
    import time as _time

    last_exc = None
    attempts = retries + 1
    for attempt in range(attempts):
        if control:
            control.check()
        try:
            return call_model(convo, model, tools=tools, **call_kwargs)
        except Exception as exc:
            status = getattr(exc, "status_code", 0)
            last_exc = exc
            if _transient(status) and attempt < retries:
                delay = 3 * (attempt + 1) if int(status or 0) != 429 else 1
                if control:
                    control.emit('retry', attempt=attempt + 1, delay=delay)
                    control.wait(delay)
                else:
                    _time.sleep(delay)
                continue
            raise
    raise last_exc


def _progress_fallback(convo, model, last, exc) -> Any:
    """Synthesize a reply from completed tool work when the model stays
    unreachable — the turn ends with progress, not an ERROR panel."""
    from core.models import ChatResult as _CR

    names = [getattr(m, "name", "") for m in convo if getattr(m, "role", "") == "tool" and getattr(m, "name", "")]
    seen = list(dict.fromkeys(names))
    detail = (": " + ", ".join(seen[-6:])) if seen else ""
    return _CR(
        content="Model is temporarily unreachable (%s) after %d tool step(s)%s. "
        "Tool results are saved in history — say 'continue' and I will pick up from there." % (
            str(exc)[:160], len(names), detail),
        model=getattr(last, "model", model) if last is not None else model,
        raw=getattr(last, "raw", None) if last is not None else None,
    )


def run_agent_loop(
    messages: list,
    model: str,
    call_model: Callable[..., Any],
    execute_tool: Callable[[str, dict], str],
    tools: list,
    max_iterations: int = 10,
    on_tool: Any = None,
    on_tool_start: Any = None,
    transcript_out: Any = None,
    control: Any = None,
    **call_kwargs,
) -> Any:
    """Run the model until it produces a final text answer.

    call_model(messages, model, tools=...) -> ChatResult or dict-like with
    .content / raw. execute_tool(qualified_name, arguments) -> str.
    on_tool(name, args, result) is an optional UI hook.
    If transcript_out (a list) is given, the intermediate assistant+tool
    messages are appended to it (tool contents truncated) so callers can persist
    tool context across turns. Returns the final ChatResult.
    """
    convo = list(messages)
    kept = transcript_out if isinstance(transcript_out, list) else None
    last = None
    exhausted = False
    seen_calls = {}
    for _ in range(max_iterations):
        if control:
            control.check()
            control.emit('stage', stage='Thinking')
        try:
            last = _call_with_retry(call_model, convo, model, tools, call_kwargs, control=control)
        except ExecutionCancelled:
            raise
        except Exception as exc:
            if any(getattr(m, "role", "") == "tool" for m in convo):
                return _progress_fallback(convo, model, last, exc)
            raise
        raw_calls = _tool_calls_from(getattr(last, "raw", None) or {})
        if control:
            control.check()
        if not raw_calls:
            return last
        content = getattr(last, "content", "") or ""
        step = Message(role="assistant", content=content, tool_calls=raw_calls)
        convo.append(step)
        if kept is not None:
            kept.append(step)
        for call in raw_calls:
            if control:
                control.check()
            args = {}
            try:
                fn = call.get("function", {})
                name = str(fn.get("name", ""))
                args = fn.get("arguments", "{}")
                args = args if isinstance(args, dict) else __import__("json").loads(args or "{}")
                if not isinstance(args, dict):
                    raise ValueError('Tool arguments must be an object')
            except Exception:
                result = "ERROR: malformed tool call arguments."
                name = "?"
            else:
                fingerprint = (name, json.dumps(args, sort_keys=True, ensure_ascii=False))
                repeated = control and control.access(name) != 'read' and fingerprint in seen_calls
                if control:
                    control.step += 1
                    if not repeated:
                        control.request_approval(name, args)
                    control.emit('tool_start', id=control.step, name=name, args=args)
                if on_tool_start:
                    on_tool_start(name, args)
                if repeated:
                    result = 'Repeated identical call suppressed. Previous result: ' + seen_calls[fingerprint]
                else:
                    try:
                        result = str(execute_tool(name, args))
                    except ExecutionCancelled:
                        raise
                    except Exception as exc:
                        result = f'ERROR: {type(exc).__name__}: {exc}'
                    if control:
                        seen_calls[fingerprint] = result
                if control:
                    control.emit('tool_end', id=control.step, name=name, result=result[:8000], failed=result.startswith('ERROR:'))
            if on_tool:
                on_tool(name, args if isinstance(args, dict) else {}, result)
            tool_msg = Message(
                role="tool",
                content=result,
                tool_call_id=str(call.get("id", "") or ""),
                name=name,
            )
            convo.append(tool_msg)
            if kept is not None:
                kept.append(Message(
                    role="tool",
                    content=result[:6000],
                    tool_call_id=tool_msg.tool_call_id,
                    name=name,
                ))
    else:
        exhausted = True
    if exhausted:
        try:
            final = _call_with_retry(call_model, convo, model, None, call_kwargs, retries=1, control=control)
            if getattr(final, "content", ""):
                return final
            last = final
        except ExecutionCancelled:
            raise
        except Exception:
            pass
        names = []
        for m in convo:
            if getattr(m, "role", "") == "tool" and getattr(m, "name", ""):
                names.append(m.name)
        seen = list(dict.fromkeys(names[-8:]))
        summary = "Completed %d tool step(s)%s but hit the tool-turn limit (%d). Last results are in history — ask me to 'continue' and I will carry on from where it stopped." % (
            len(names), (": " + ", ".join(seen) if seen else ""), max_iterations)
        from core.models import ChatResult as _CR
        raw = getattr(last, "raw", None) if last is not None else None
        return _CR(content=summary, model=getattr(last, "model", model) or model, raw=raw)
    return last
