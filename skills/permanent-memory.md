# Permanent Memory

Core code: `core/memory.py`

Permanent memory has three layers:

- `memory/data/` contains editable `.txt` files from the user.
- `memory/chats/` contains session transcripts.
- `memory/store/` contains the local SQLite semantic memory database.

Use retrieved memory as context, not as absolute truth. Current user messages override older memory when they conflict.

When the user says "remember..." or shares stable profile/preferences, store the durable point in permanent memory.

Performance mode:

- Default `MEMORY_BACKEND=nvidia` uses NVIDIA embeddings from the configured `.env` model.
- `MEMORY_SEARCH_MODE=hybrid` keeps latency low by using pinned profile facts and keyword retrieval before semantic search.
- Semantic query embeddings are cached in `memory/store/memory.sqlite`.
- Set `MEMORY_SEARCH_MODE=fast` for local-only memory or `MEMORY_SEARCH_MODE=semantic` for always-semantic retrieval.
