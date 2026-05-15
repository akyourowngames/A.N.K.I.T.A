# Memory Brain v2

Jarvis memory stays TXT-first.

## Source Of Truth

- `memory/user.txt` stores stable user profile and preferences.
- `memory/extracted.txt` stores durable memory extracted from chat.
- `memory/transcripts/*.txt` stores raw chat history.
- `memory/wiki/pages/**/*.txt` stores source-backed wiki notes.

You can edit those files manually. The graph is generated from them.

## Generated Graph

Generated files live under `memory/graph/`:

- `memory.db` is the local SQLite graph/index.
- `graph.json` is a readable export for debugging and the web UI.
- `entity_index.json` maps normalized entity names to graph ids.
- `unresolved_conflicts.json` records possible duplicates or contradictions.
- `profile_summary.txt` is a compact generated profile summary.
- `retrieval_cache.json` is reserved for future cached retrieval.

The generated graph can be deleted and rebuilt without deleting TXT memory.

## Reindex

Run:

```bash
python -c "from memory_brain import memory_brain_reindex; print(memory_brain_reindex())"
```

Or ask Jarvis to use `memory_brain_reindex`.

Reindex scans:

- `memory/user.txt`
- `memory/extracted.txt`
- `memory/wiki/**/*.txt`
- transcripts only when `MEMORY_BRAIN_INCLUDE_TRANSCRIPTS=true`

## Retrieval

`memory_brain_search` combines:

- exact local text recall over indexed facts
- entity matching
- graph neighbor expansion
- recency, importance, and confidence boosts
- stale or contradiction warnings

Prompt injection is compact. Jarvis injects stable profile memory plus up to `MEMORY_BRAIN_MAX_FACTS` relevant facts, each with a source path.

## Conflicts

The graph does not overwrite TXT facts. If a later fact appears to supersede or contradict an older one, the graph adds `supersedes` and `contradicts` edges and writes a conflict record.

Review conflicts with `memory_conflicts`, then edit the TXT source manually if needed and reindex.

## Web Graph

The local API exposes:

- `GET /api/memory/status`
- `GET /api/memory/graph`
- `GET /api/memory/search?query=...`
- `POST /api/memory/reindex`

The Next.js UI has a Memory view in the sidebar. It renders graph nodes, edges, relationships, sources, search results, and a reindex button.

## Reset Graph

To reset the generated graph only, delete `memory/graph/` and reindex.

Do not delete `memory/user.txt`, `memory/extracted.txt`, transcripts, or wiki pages unless you intentionally want to remove source memory.

## External Engines Later

SQLite is the default. The modules keep graph, ingest, retrieval, conflict, and profile logic separate so a future adapter can target Mem0, Zep/Graphiti, or Neo4j without replacing TXT memory.

Keep external engines optional so local startup, first-token latency, and offline memory remain reliable.
