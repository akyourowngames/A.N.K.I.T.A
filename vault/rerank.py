"""Local cross-encoder reranker (optional, graceful).

Tries fastembed cross-encoder if present; otherwise falls back to
embedding-cosine scoring (deterministic, no network). ZUMBA_VAULT_RERANK=0
or any load failure -> caller skips rerank (parity preserved).
"""

from __future__ import annotations

import os


def enabled() -> bool:
    return (os.getenv("ZUMBA_VAULT_RERANK", "1") != "0")


_RERANKER = None


def _get_reranker():
    global _RERANKER
    if _RERANKER is not None:
        return _RERANKER
    try:
        from fastembed import TextCrossEncoder  # type: ignore
        _RERANKER = TextCrossEncoder(model_name="Xenova/ms-marco-MiniLM-L-6-v2")
        return _RERANKER
    except Exception:
        _RERANKER = False
        return None


def rerank(query: str, texts: list[str], top_k: int = 6) -> list[int]:
    """Return indices of texts ordered best-first (length top_k). Never raises."""
    if not texts:
        return []
    top_k = max(1, min(top_k, len(texts)))
    if not enabled():
        return list(range(top_k))
    try:
        ce = _get_reranker()
        if ce is not None:
            pairs = [[query, t[:2000]] for t in texts]
            scores = list(ce.rerank(query, texts))
            order = sorted(range(len(texts)), key=lambda i: float(scores[i]), reverse=True)
            return order[:top_k]
    except Exception:
        pass
    try:
        from memory import embedder as _emb
        qv = _emb.embed_text(query)
        if qv:
            import math
            scored = []
            for i, t in enumerate(texts):
                v = _emb.embed_text((t or "")[:2000])
                if not v:
                    scored.append((i, -1.0))
                    continue
                dot = sum(a * b for a, b in zip(qv, v))
                na = math.sqrt(sum(a * a for a in qv)) or 1.0
                nb = math.sqrt(sum(b * b for b in v)) or 1.0
                scored.append((i, dot / (na * nb)))
            scored.sort(key=lambda p: p[1], reverse=True)
            return [i for i, _ in scored[:top_k]]
    except Exception:
        pass
    return list(range(top_k))
