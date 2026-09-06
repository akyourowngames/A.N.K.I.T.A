"""LLM reasoning for the memory system.

All semantic judgment — salience, entity/relation extraction, write decisions,
entity resolution, notes, community summaries and synthesis — is delegated to
the LLM through structured prompts. There is intentionally little hand-written
heuristic logic here: the model decides.

Uses the same Kilo gateway client as the rest of zumba (strictly local
embeddings, but reasoning goes through the configured LLM).
"""

from __future__ import annotations

import json
import os
import threading
from typing import Optional

from core.api_client import KiloError, chat_completion
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
    if os.getenv("ZUMBA_MEMORY_MODEL", "").strip():
        return os.getenv("ZUMBA_MEMORY_MODEL", "").strip()
    try:
        from core.config import get_default_model

        m = (get_default_model() or "").strip()
        if m:
            return m
    except Exception:
        pass
    return "muse-spark-1.3-contributor-free"


def chat_text(prompt: str, system: str = "You are a precise memory curation engine.", model: str = "", max_tokens: int = 1000, temperature: float = 0.0) -> str:
    msgs = [Message(role="system", content=system), Message(role="user", content=prompt)]
    chosen = model or _memory_model()
    result = chat_completion(msgs, chosen, max_tokens=max_tokens, temperature=temperature)
    return (result.content or "").strip()


def chat_json(prompt: str, system: str = "You are a precise memory curation engine. Always answer with valid JSON only.", model: str = "", max_tokens: int = 1500, temperature: float = 0.0):
    """Ask the LLM for a JSON object; return parsed dict or None on failure."""
    text = chat_text(
        prompt + "\n\nReturn ONLY valid JSON. No prose, no markdown fences.",
        system=system,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return _extract_json(text)


def _extract_json(text: str):
    if not text:
        return None
    # Try the whole thing as JSON first.
    try:
        return json.loads(text)
    except Exception:
        pass
    # The model sometimes wraps in ```json ... ``` fences.
    if "```" in text:
        import re as _re

        for fence in _re.findall(r"```(?:json)?\s*(.*?)```", text, flags=_re.S):
            try:
                return json.loads(fence)
            except Exception:
                continue
    # Last resort: grab the outermost balanced { ... }.
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except Exception:
                    return None
    return None


_MODEL_OUT_NAME = "model"