"""Context window manager: keep every model call inside a token budget.

Long sessions + memory block + retained tool transcripts grow unbounded
until the API rejects them. This module estimates tokens without a
tokenizer dependency, keeps the must-have messages (system prompts, the
session anchor, recent turns), and condenses dropped middle turns into one
cached rolling summary.

Budget source: ``ZUMBA_CONTEXT_LIMIT`` env, fallback 8192 (safe for free
models). Reserve ``reserve_out`` tokens for the reply.
"""

from __future__ import annotations

import os
import re

_CODE_SPAN = re.compile(r"```.*?```", re.S)

TAIL_KEEP = 6
SUMMARY_REBUILD_GAP = 6
TOOL_KEEP_EXCHANGES = 2
TOOL_TRUNCATE_TO = 200


def get_context_limit() -> int:
    try:
        return max(2048, int(os.getenv("ZUMBA_CONTEXT_LIMIT", "8192") or 8192))
    except Exception:
        return 8192


def estimate_tokens(text: str) -> float:
    """Cheap monotonic token estimate: ~4 chars/token for prose, ~3.5 for
    code/JSON blocks, ~1.5 chars/token for non-ASCII runs. No dependencies."""
    if not text:
        return 0.0
    total = 0.0
    pos = 0
    for m in _CODE_SPAN.finditer(text):
        total += _plain_cost(text[pos:m.start()])
        total += len(m.group(0)) / 3.5
        pos = m.end()
    total += _plain_cost(text[pos:])
    return total


def _plain_cost(chunk: str) -> float:
    if not chunk:
        return 0.0
    non_ascii = sum(1 for c in chunk if ord(c) > 127)
    ascii_n = len(chunk) - non_ascii
    return ascii_n / 4.0 + non_ascii / 1.5


def message_tokens(msg) -> float:
    cost = estimate_tokens(getattr(msg, "content", "") or "")
    calls = getattr(msg, "tool_calls", None)
    if calls:
        import json as _json

        try:
            cost += len(_json.dumps(calls)) / 4.0
        except Exception:
            cost += 100.0
    return cost + 4.0  # per-message framing overhead


def _is_tool_msg(msg) -> bool:
    return getattr(msg, "role", "") == "tool" or bool(getattr(msg, "tool_calls", None))


def truncate_stale_tools(messages: list, keep_exchanges: int = TOOL_KEEP_EXCHANGES, to_chars: int = TOOL_TRUNCATE_TO) -> list:
    """Truncate tool transcripts older than the last `keep_exchanges` tool
    exchanges to `to_chars` chars. Returns the same list (mutates copies)."""
    from core.models import Message

    out = [Message(role=m.role, content=m.content, tool_calls=m.tool_calls,
                   tool_call_id=m.tool_call_id, name=m.name) for m in messages]
    # Index of the assistant message starting the Nth-from-last tool exchange.
    starts = [i for i, m in enumerate(out) if getattr(m, "role", "") == "assistant" and getattr(m, "tool_calls", None)]
    cutoff = starts[-keep_exchanges] if len(starts) >= keep_exchanges else (starts[0] if starts else len(out))
    for i, m in enumerate(out):
        if i < cutoff and getattr(m, "role", "") == "tool" and len(m.content) > to_chars:
            m.content = m.content[:to_chars] + "… [truncated]"
    return out


def _default_summarizer(dropped: list) -> str:
    try:
        from memory import llm as _llm

        bits = []
        for m in dropped:
            role = getattr(m, "role", "?")
            text = (getattr(m, "content", "") or "")[:500]
            bits.append(f"{role}: {text}")
        return _llm.chat_text(
            "Condense these dropped middle turns of a chat session into 5-10 terse "
            "bullets (decisions, facts, tool outcomes). Omit pleasantries.\n\n" + "\n".join(bits)[:6000],
            system="You are a precise conversation summarizer.",
            max_tokens=500,
        ).strip() or "(no salient content in dropped turns)"
    except Exception:
        return "(earlier session context unavailable)"


def build_window(messages: list, model_limit: int = 0, reserve_out: int = 1500,
                 cache: dict | None = None, summarizer=None) -> list:
    """Fit `messages` into `model_limit - reserve_out` tokens.

    Always keeps: system messages, the first user message (session anchor),
    and the last TAIL_KEEP messages (extended back over tool pairs). Middle
    overflow becomes one cached rolling summary (rebuilt only when >=
    SUMMARY_REBUILD_GAP new messages were dropped since the last build).
    `cache` is a caller-owned dict persisted across turns of a session.
    """
    from core.models import Message

    limit = model_limit or get_context_limit()
    budget = max(1000, limit - reserve_out)
    msgs = truncate_stale_tools(list(messages))
    if sum(message_tokens(m) for m in msgs) <= budget:
        return msgs

    systems = [m for m in msgs if m.role == "system"]
    rest = [m for m in msgs if m.role != "system"]
    anchor = None
    for m in rest:
        if m.role == "user":
            anchor = m
            break
    anchor_idx = rest.index(anchor) if anchor is not None else 0

    tail_start = max(0, len(rest) - TAIL_KEEP)
    while tail_start > 0 and rest[tail_start].role == "tool":
        tail_start -= 1
    if tail_start > anchor_idx + 1:
        while tail_start > anchor_idx + 1 and rest[tail_start - 1].role == "assistant" and rest[tail_start - 1].tool_calls:
            tail_start -= 1

    head = rest[:anchor_idx + 1] if anchor is not None else []
    tail = rest[tail_start:]
    middle = rest[len(head):tail_start]

    notes: list = []
    if middle:
        key_cache = cache if isinstance(cache, dict) else {}
        covered = int(key_cache.get("covered", -1))
        if key_cache.get("summary") and len(middle) - covered < SUMMARY_REBUILD_GAP:
            summary = key_cache["summary"]
        else:
            try:
                summary = (summarizer or _default_summarizer)(middle) or "(no salient content)"
            except Exception:
                summary = "(earlier session context unavailable)"
            key_cache["summary"] = summary
            key_cache["covered"] = len(middle)
        notes.append(Message(role="system", content=f"Session so far (rolling summary of {len(middle)} dropped turns):\n{summary}"))

    window = systems + head + notes + tail
    # Last-resort: if still over budget (giant single messages), drop oldest
    # non-system/anchor/tail messages one at a time.
    while sum(message_tokens(m) for m in window) > budget and len(window) > len(systems) + len(head) + len(tail):
        del window[len(systems) + len(head)]
    return window
