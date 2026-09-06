"""Anthropic contextual-retrieval lines + hypothetical questions (Phase 2).

Batched, cheap model, 429-aware. Auto-off without API key: every entry
point returns ("", []) on any failure — enrichment never blocks ingest
(the raw chunk text is always indexed synchronously first).
"""

from __future__ import annotations

import json
import os

_CTX_PROMPT = """Write a 1-2 sentence context line situating this chunk inside its document
for retrieval (Anthropic contextual retrieval). Name the document and section,
and what the chunk is about. No extra prose.

DOCUMENT: {title}
SECTION: {heading}
CHUNK:
{text}
Return JSON: {{"context": ".."}}"""

_HYDE_PROMPT = """Write 3 short hypothetical questions this chunk answers (for retrieval
indexing; fixes vocabulary mismatch). Return JSON: {{"questions": ["..", "..", ".."]}}

CHUNK:
{text}"""


def enabled() -> bool:
    try:
        n = int(os.getenv("ZUMBA_VAULT_CONTEXT_LINES", "1") or 1)
    except Exception:
        n = 1
    if n <= 0:
        return False
    try:
        from memory.llm import _api_available
        return bool(_api_available())
    except Exception:
        return False


def context_for_chunks(title: str, items: list[dict]) -> list[tuple[str, list[str]]]:
    if not enabled() or not items:
        return [("", []) for _ in items]
    out: list[tuple[str, list[str]]] = []
    try:
        from memory import llm as _llm
        for it in items[:24]:
            text = str(it.get("text") or "")[:1500]
            heading = str(it.get("heading") or "")
            ctx, hyps = "", []
            try:
                r = _llm.chat_json(_CTX_PROMPT.format(title=title[:120], heading=heading[:120], text=text),
                                   system="You write retrieval context lines. Valid JSON only.",
                                   max_tokens=200)
                if isinstance(r, dict) and r.get("context"):
                    ctx = str(r["context"])[:300]
            except Exception:
                ctx = ""
            try:
                r2 = _llm.chat_json(_HYDE_PROMPT.format(text=text),
                                    system="You write retrieval questions. Valid JSON only.",
                                    max_tokens=300)
                if isinstance(r2, dict) and isinstance(r2.get("questions"), list):
                    hyps = [str(q)[:200] for q in r2["questions"] if str(q).strip()][:3]
            except Exception:
                hyps = []
            out.append((ctx, hyps))
        while len(out) < len(items):
            out.append(("", []))
        return out
    except Exception:
        return [("", []) for _ in items]


def hyde_expand(query: str) -> list[str]:
    if (os.getenv("ZUMBA_VAULT_HYDE", "0") == "0"):
        return []
    try:
        from memory import llm as _llm
        r = _llm.chat_json(
            'Write 3 hypothetical answer snippets (1 sentence each) for: "' + query[:300] + '"\n'
            'Return JSON: {"snippets": ["..", "..", ".."]}',
            system="You write hypothetical answers. Valid JSON only.", max_tokens=400)
        if isinstance(r, dict) and isinstance(r.get("snippets"), list):
            return [str(s)[:300] for s in r["snippets"] if str(s).strip()][:3]
    except Exception:
        pass
    return []
