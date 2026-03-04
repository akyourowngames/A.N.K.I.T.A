"""
A.N.K.I.T.A Memory System
==========================
3-layer persistent memory: Short-term (in-memory) → Mid-term (JSONL summaries)
→ Long-term (SQLite facts + ChromaDB semantic vectors).

All interfaces (CLI, GUI, Telegram) share one user identity: "ankita-user".
"""
from .manager import MemoryManager, get_memory_manager

__all__ = ["MemoryManager", "get_memory_manager"]
