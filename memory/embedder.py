"""Local embedding provider.

Uses ``fastembed`` with a small ONNX model (bge-small-en-v1.5, 384-dim) so all
vector work stays on this machine with no API calls. The model is downloaded
once and cached. The embedder is a lazily-initialized singleton.
"""

from __future__ import annotations

import threading
from typing import Iterable, Optional

_EMBEDDER = None
_lock = threading.Lock()
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


def _get_model_name() -> str:
    # Allow a different local model via env, but default is small/batch-aware.
    import os

    return os.getenv("ZUMBA_EMBED_MODEL", DEFAULT_MODEL)


def get_embedder(
    model: Optional[str] = None,
    batch_size: int = 64,
    threads: Optional[int] = None,
):
    global _EMBEDDER
    name = model or _get_model_name()
    with _lock:
        if _EMBEDDER is None:
            from fastembed import TextEmbedding

            kwargs = {"model_name": name, "batch_size": batch_size}
            if threads:
                kwargs["threads"] = threads
            _EMBEDDER = TextEmbedding(**kwargs)
        return _EMBEDDER


def embed_texts(texts: Iterable[str]) -> list[list[float]]:
    """Embed a batch of strings into float vectors (list of lists)."""
    text_list = [t or " " for t in texts]
    if not text_list:
        return []
    emb = get_embedder()
    out = []
    for v in emb.embed(text_list):
        out.append(list(v))
    return out


def embed_text(text: str) -> list[float]:
    if not text:
        return []
    return embed_texts([text])[0]


def dim() -> int:
    return 384