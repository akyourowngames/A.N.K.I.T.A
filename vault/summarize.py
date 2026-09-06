"""RAPTOR-lite: LLM-written section + doc summaries (stored + embedded).

Conceptual questions ("what is this doc about?") hit summaries, not
chunk 47 of 300. Graceful: empty string on any failure.
"""

from __future__ import annotations

_SEC_PROMPT = """Summarize this document section in 2-4 sentences (key facts only).
DOCUMENT: {title}
SECTION: {heading}
TEXT:
{text}
Return the summary as plain prose, no bullets."""

_DOC_PROMPT = """Summarize this whole document in 4-8 sentences: what it is, key parties/
dates/numbers, and main topics. Plain prose.

DOCUMENT: {title}
SECTIONS:
{sections}"""


def _available() -> bool:
    try:
        from memory.llm import _api_available
        return bool(_api_available())
    except Exception:
        return False


def summarize_section(title: str, heading: str, text: str) -> str:
    if not _available() or not (text or "").strip():
        return ""
    try:
        from memory import llm as _llm
        return _llm.chat_text(_SEC_PROMPT.format(title=title[:120], heading=heading[:120],
                                                text=text[:4000]),
                              system="You summarize document sections precisely.",
                              max_tokens=300).strip()[:1200]
    except Exception:
        return ""


def summarize_doc(title: str, section_texts: list[str]) -> str:
    if not _available() or not section_texts:
        return ""
    try:
        from memory import llm as _llm
        blob = "\n".join(f"- {t[:400]}" for t in section_texts[:20])
        return _llm.chat_text(_DOC_PROMPT.format(title=title[:160], sections=blob[:5000]),
                              system="You summarize whole documents precisely.",
                              max_tokens=500).strip()[:2000]
    except Exception:
        return ""
