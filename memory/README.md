# Memory

Permanent memory lives here.

- `data/` is for editable `.txt` files. Add personal details, preferences, project notes, and stable facts here.
- `chats/` stores per-session transcripts.
- `store/` stores the local SQLite semantic-memory database.

The app re-indexes `data/*.txt` before memory search, so edits become searchable automatically.

For speed, unchanged files are skipped after their content hash has been indexed.

`MEMORY_BACKEND=nvidia` uses NVIDIA embeddings from `NVIDIA_BASE_URL` and caches query vectors in SQLite.

`MEMORY_SEARCH_MODE=hybrid` does fast local keyword/profile retrieval first, then semantic search when needed. Use `MEMORY_SEARCH_MODE=fast` for local-only retrieval or `MEMORY_SEARCH_MODE=semantic` for always-semantic retrieval.
