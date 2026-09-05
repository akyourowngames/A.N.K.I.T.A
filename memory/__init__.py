"""Zumba Memory — a temporal knowledge-graph memory system.

LLM-driven extraction, salience, write decisions and consolidation, backed by
locally-embedded hybrid retrieval (vector + full-text + Personalized PageRank
over a knowledge graph) stored in a single embedded SQLite database.

The public surface is :class:`memory.service.Memory`.
"""

from memory.service import Memory, get_memory  # noqa: F401

__all__ = ["Memory", "get_memory"]
__version__ = "0.1.0"