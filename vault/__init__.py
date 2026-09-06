"""Zumba Vault — god-tier local document RAG.

Drop files into ~/.zumba/vault/ (or point at folders) and they become
instantly answerable. Built ON TOP of the memory stack (bge-small ONNX
embedder, FTS5, sqlite-vec, RRF, context budget) — not a second RAG system.
"""

from vault.service import Vault, get_vault  # noqa: F401

__all__ = ["Vault", "get_vault"]
