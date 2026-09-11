"""LLM reasoning for the memory system.

All semantic judgment — salience, entity/relation extraction, write decisions,
entity resolution, notes, community summaries and synthesis — is delegated to
the LLM through structured prompts. There is intentionally little hand-written
heuristic logic here: the model decides.

Reasoning goes through the KNOWLEDGE provider (Kilo step-3.7 free by
default: reliable structured JSON), never the chat model. Chat traffic is
untouched — see core.config.get_knowledge_llm.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Optional

from core.api_client import chat_completion
from core.models import Message

_lock = threading.Lock()
_client_negotiator = None


def _api_available() -> bool:
    try:
        from core.config import get_api_key

        get_api_key(require=True)
        return True
    except Exception:
        return False


def _memory_model() -> str:
    # Optional per-subsystem override; otherwise the knowledge provider
    # (Kilo step-3.7 free) — never the chat model.
    if os.getenv("ZUMBA_MEMORY_MODEL", "").strip():
        return os.getenv("ZUMBA_MEMORY_MODEL", "").strip()
    try:
        from core.config import get_knowledge_model

        return get_knowledge_model()
    except Exception:
        pass
    try:
        from core.config import KNOWLEDGE_DEFAULT_MODEL as _KM

        return _KM
    except Exception:
        return "stepfun/step-3.7-flash:free"


def _provider(api_key: str = "", base_url: str = "") -> dict:
    """Resolve the knowledge provider triple; explicit args always win."""
    try:
        from core.config import get_knowledge_llm

        resolved = get_knowledge_llm()
    except Exception:
        resolved = {}
    if api_key:
        resolved["api_key"] = api_key
    if base_url:
        resolved["base_url"] = base_url
    return resolved


def chat_text(prompt: str, system: str = "You are a precise memory curation engine.", model: str = "", max_tokens: int = 1000, temperature: float = 0.0, api_key: str = "", base_url: str = "") -> str:
    msgs = [Message(role="system", content=system), Message(role="user", content=prompt)]
    chosen = model or _memory_model()
    prov = _provider(api_key, base_url)
    result = chat_completion(msgs, chosen, api_key=prov.get("api_key", ""),
                             base_url=prov.get("base_url", ""),
                             max_tokens=max_tokens, temperature=temperature)
    return (result.content or "").strip()


def _attempts() -> int:
    try:
        return max(1, int(os.getenv("ZUMBA_LLM_ATTEMPTS", "3") or 3))
    except ValueError:
        return 3


def _backoff(attempt: int) -> None:
    import random as _random
    import time as _time

    _time.sleep(min(8.0, 1.0 * (2 ** attempt)) + _random.uniform(0, 0.5))


def chat_json(prompt: str, system: str = "You are a precise memory curation engine. Always answer with valid JSON only.", model: str = "", max_tokens: int = 1500, temperature: float = 0.0, api_key: str = "", base_url: str = ""):
    """Ask the LLM for a JSON object; return parsed dict/list or None on failure.

    Free-tier models flake (empty content, prose-wrapped or truncated JSON),
    so parse failures AND transport errors are retried with backoff
    (ZUMBA_LLM_ATTEMPTS, default 3) before giving up with None.
    """
    full_prompt = prompt + "\n\nReturn ONLY valid JSON. No prose, no markdown fences."
    last_exc = None
    for attempt in range(_attempts()):
        try:
            text = chat_text(
                full_prompt,
                system=system,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                api_key=api_key,
                base_url=base_url,
            )
        except Exception as exc:
            last_exc = exc
            _backoff(attempt)
            continue
        parsed = _extract_json(text)
        if isinstance(parsed, (dict, list)):
            return parsed
        _backoff(attempt)
    return None


def _strip_thinking(text: str) -> str:
    # Reasoning models emit <think>...</think> (sometimes unclosed on
    # truncation) before the payload — never part of the JSON.
    while "<think>" in text:
        start = text.find("<think>")
        end = text.find("</think>", start)
        if end == -1:
            # Unclosed tag (truncated thinking): drop only the marker and let
            # the balanced-span scanner below locate the JSON payload.
            text = text[:start] + text[start + len("<think>"):]
            continue
        text = text[:start] + text[end + len("</think>"):]
    return text


def _balanced_spans(text: str):
    """Yield string-aware balanced {...} / [...] spans, outermost first.

    The old scanner counted braces inside quoted strings ("a}b") and gave up
    after the first failed parse; this one skips string literals/escapes and
    keeps scanning past unparseable spans.
    """
    spans = []
    i, n = 0, len(text)
    while i < n:
        open_c = text[i]
        if open_c not in "{[":
            i += 1
            continue
        close_c = "}" if open_c == "{" else "]"
        depth = 0
        in_str = False
        esc = False
        start = i
        j = i
        ok = False
        while j < n:
            c = text[j]
            if in_str:
                if esc:
                    esc = False
                elif c == "\\":
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c in "{[":
                    depth += 1
                elif c in "}]":
                    depth -= 1
                    if depth == 0:
                        if (open_c == "{" and c == "}") or (open_c == "[" and c == "]"):
                            ok = True
                        break
                    if depth < 0:
                        break
            j += 1
        if ok:
            spans.append(text[start : j + 1])
            i = j + 1
        else:
            i = start + 1
    # Prefer objects over arrays, longer (more complete) spans first.
    spans.sort(key=lambda s: (s.startswith("{"), len(s)), reverse=True)
    return spans


def _extract_json(text: str):
    if not text:
        return None
    text = _strip_thinking(text).strip()
    if not text:
        return None
    # Try the whole thing as JSON first.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            return parsed
    except Exception:
        pass
    # Fenced code blocks (```json ... ``` or bare ``` ... ```).
    if "```" in text:
        import re as _re

        fences = _re.findall(r"```(?:json)?\s*(.*?)```", text, flags=_re.S)
        for fence in fences:
            try:
                parsed = json.loads(fence.strip())
                if isinstance(parsed, (dict, list)):
                    return parsed
            except Exception:
                continue
        # Fences whose JSON itself contains prose-wrapped payloads.
        for fence in fences:
            for span in _balanced_spans(fence):
                try:
                    return json.loads(span)
                except Exception:
                    continue
    # Last resort: scan prose for balanced JSON spans.
    for span in _balanced_spans(text):
        try:
            return json.loads(span)
        except Exception:
            continue
    return None


_MODEL_OUT_NAME = "model"