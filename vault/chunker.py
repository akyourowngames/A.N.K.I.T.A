"""Structure-aware markdown chunker (~350 tokens, 80 overlap).

Heading boundaries respected; fenced table/code blocks never split;
paragraphs kept whole; overlap carries the tail of the previous chunk.
Token estimate: chars/4 (same convention as context_budget).
"""

from __future__ import annotations

import os
import re

_FENCE = re.compile(r"^```")


def chunk_tokens() -> int:
    try:
        return max(100, int(os.getenv("ZUMBA_VAULT_CHUNK_TOKENS", "350") or 350))
    except Exception:
        return 350


def overlap_tokens() -> int:
    return 80


def estimate_tokens(text: str) -> float:
    return len(text or "") / 4.0


def _split_blocks(md: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    cur: list[str] = []
    kind = "para"
    in_fence = False
    for line in (md or "").splitlines():
        if _FENCE.match(line):
            if not in_fence:
                if cur:
                    blocks.append((kind, "\n".join(cur)))
                    cur = []
                in_fence = True
                cur = [line]
            else:
                cur.append(line)
                blocks.append(("fence", "\n".join(cur)))
                cur = []
                in_fence = False
            continue
        if in_fence:
            cur.append(line)
            continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            if cur:
                blocks.append((kind, "\n".join(cur)))
                cur = []
            blocks.append(("heading", line))
            kind = "para"
            continue
        if not line.strip():
            if cur:
                blocks.append((kind, "\n".join(cur)))
                cur = []
            continue
        if re.match(r"^\|.+\|$", line.strip()) and cur and re.match(r"^\|.+\|$", cur[-1].strip() if cur else ""):
            cur.append(line)
            kind = "table"
            continue
        cur.append(line)
    if cur:
        blocks.append(("fence" if in_fence else kind, "\n".join(cur)))
    return [(k, b) for k, b in blocks if b.strip()]


def chunk_markdown(md: str, target_tokens: int = 0, overlap: int = 0) -> list[dict]:
    target = target_tokens or chunk_tokens()
    ov = overlap or overlap_tokens()
    max_chars = int(target * 4)
    ov_chars = int(ov * 4)
    blocks = _split_blocks(md)
    chunks: list[dict] = []
    cur_text: list[str] = []
    cur_len = 0
    cur_heading = ""
    cur_level = 1
    for kind, body in blocks:
        if kind == "heading":
            m = re.match(r"^(#{1,4})\s+(.*)$", body)
            if cur_text and cur_len >= max_chars * 0.5:
                chunks.append({"text": "\n\n".join(cur_text).strip(), "heading": cur_heading,
                               "level": cur_level})
                tail = ("\n\n".join(cur_text))[-ov_chars:]
                cur_text, cur_len = ([tail] if tail.strip() else []), len(tail)
            if m:
                cur_level = len(m.group(1))
                cur_heading = m.group(2).strip()
            continue
        piece = body.strip()
        if not piece:
            continue
        if kind in ("fence", "table") and cur_text and cur_len + len(piece) + 2 > max_chars and cur_len > 0:
            chunks.append({"text": "\n\n".join(cur_text).strip(), "heading": cur_heading,
                           "level": cur_level})
            tail = ("\n\n".join(cur_text))[-ov_chars:]
            cur_text, cur_len = ([tail] if tail.strip() else []), len(tail)
        if kind in ("fence", "table") and len(piece) > max_chars:
            if cur_text:
                chunks.append({"text": "\n\n".join(cur_text).strip(), "heading": cur_heading,
                               "level": cur_level})
                cur_text, cur_len = [], 0
            chunks.append({"text": piece, "heading": cur_heading, "level": cur_level})
            continue
        if cur_len + len(piece) + 2 > max_chars and cur_text:
            chunks.append({"text": "\n\n".join(cur_text).strip(), "heading": cur_heading,
                           "level": cur_level})
            tail = ("\n\n".join(cur_text))[-ov_chars:]
            cur_text, cur_len = ([tail] if tail.strip() else []), len(tail)
        cur_text.append(piece)
        cur_len += len(piece) + 2
    if cur_text and "\n\n".join(cur_text).strip():
        chunks.append({"text": "\n\n".join(cur_text).strip(), "heading": cur_heading,
                       "level": cur_level})
    out = []
    for i, c in enumerate(chunks):
        out.append({"ordinal": i, "text": c["text"], "heading": c.get("heading", ""),
                    "level": c.get("level", 1)})
    return out
