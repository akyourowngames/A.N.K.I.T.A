# Zumba knowledge workspace

Open `http://localhost:3000/knowledge`. The existing chat remains at `/`, with a live memory preview in its sidebar.

## Run

From the repository root, run `python -m server.run`. In a second terminal run `cd frontend` and `npm run dev`. For a production frontend build use `npm run build`, then `npm start`.

The API binds to localhost. This is a single-user local workspace; internet hosting requires authentication, workspace isolation, TLS, deployment limits, and a shared worker/event architecture. Do not expose the API directly to the internet.

The existing Kilo configuration is used for extraction, identity resolution, verification and answers. Set `KILO_API_KEY` and optionally `ZUMBA_MEMORY_MODEL` using Zumba's existing configuration. Document excerpts go to that model. Local fastembed generates vectors; if unavailable, ingestion records a warning and keyword retrieval continues.

For the graph alone, `ZUMBA_KNOWLEDGE_MODEL` overrides the memory model. Malformed output or provider errors receive one attempt through the same gateway's `kilo-auto/free` route. Override that route with `ZUMBA_KNOWLEDGE_FALLBACK`, or set it to an empty string to disable fallback. Evidence metadata records attempted models. Global chat preferences are unchanged.

## Data and evidence

- Graph storage: `~/.zumba/knowledge/graph.db`. Override with `ZUMBA_KNOWLEDGE_HOME`.
- Read-only memory source: `~/.zumba/memory.db` and `~/.zumba/user.md`. Override the graph's source directory with `ZUMBA_MEMORY_HOME`.
- Memory capture journal: `~/.zumba/memory-inbox.db`. Accepted exchanges are written synchronously before entering memory's background queue. Pending captures are restored when the memory service starts; failures retain their original text and error.
- Uploaded originals, extracted chunks, entity mentions, directed relationships, evidence quotes, local vectors, resolution decisions and ingestion jobs live in the graph database. Uploaded content is deduplicated by SHA-256. Changing user.md produces a new immutable source version.
- Back up SQLite databases with the SQLite backup API or stop Zumba before copying databases. Include original memory, knowledge and inbox databases plus user.md. Persistence is not protection against disk loss or an explicit deletion.

The graph is an evidence view of historical source assertions, not an assertion that every past statement remains true today. Source dates and profile versions are retained. It re-extracts original user text instead of silently importing legacy edges that lack exact evidence. Assistant replies are excluded from authoritative user sources. Graph processing does not rewrite or erase the original memory graph.

### Parallel chunk processing

Chunks of one document are extracted and embedded concurrently in a bounded thread pool; the default parallelism is 3 and `ZUMBA_KNOWLEDGE_PARALLELISM` overrides it (set it to 1 for strictly serial processing). Database commits and LLM-backed identity resolution stay serialized afterwards, so each chunk is still committed atomically and completed chunks are never reprocessed. Higher parallelism is faster but more likely to hit free-tier rate limits; a rate-limited chunk fails the document the same as any other model error, visible and retryable in Documents.

### Live model diagnosis (2026-09-08)

- The configured memory model (`stepfun/step-3.7-flash:free`) produces valid, verified extraction JSON, but a full profile extraction takes roughly 60–90 seconds and 5,700 of 6,000 completion tokens. Larger sources sit close to the token cap; failed or empty responses are visible and retryable per source.
- The `kilo-auto/free` fallback route is reasoning-heavy: on long extraction prompts it spends the entire `max_tokens` budget on hidden reasoning and returns empty content. It remains only a last resort; a stronger primary model (`ZUMBA_MEMORY_MODEL` or `ZUMBA_KNOWLEDGE_MODEL`) is recommended for reliable ingestion.

## Pipeline

Upload → durable queue → format extraction → page/section chunks → LLM entities/relations → verbatim quote checks → independent entailment verification → local embeddings → context-aware LLM identity resolution → atomic per-chunk graph commit → server-sent event update.

Progress represents actual completed chunks and processing stages. There are no simulated timers or seeded demo nodes. Empty/unreadable PDFs fail visibly; scanned PDFs must first receive OCR. DOCX uses headings and paragraph/table order; page numbers are not fabricated. CSV uses proper quoted-record parsing without the vault parser's 200-row truncation. JSON is validated while retaining original text.

Entity matching combines normalized name/alias candidate retrieval, vector similarity, context and existing outgoing relations. Even identical names require an LLM identity decision. The resolution audit records the mention, decision, reason and chunk. Types are extensible strings, with no semantic regex/keyword classifiers.

Every displayed relationship has at least one quote in a stored source chunk. Confidence is a model estimate, not a calibrated probability; below 80% is styled as uncertain. Quote containment and independent model checking reduce unsupported assertions but cannot guarantee perfect semantic extraction. Review evidence for important decisions.

## Recovery and limits

Failed documents are retried from Documents. Completed chunks are not reprocessed. Workers claim durable jobs using SQLite transactions and a processing lease; interrupted jobs become eligible again after the lease expires (up to ten minutes). Run one API worker for this local architecture. Only pending documents are automatically processed; model failures remain visible for user-triggered retries.

Uploads are limited to 20 MB and 4 million extracted characters. DOCX expansion is limited to 80 MB. Source snapshots and evidence history are retained. Large collections increase memory use: graph snapshots currently contain the complete graph, and semantic retrieval scans stored chunk vectors. This is suitable for a personal workspace, not a distributed graph database. Benchmark on the target hardware before claiming a particular thousand-node frame rate.

Natural-language queries fuse keyword and vector rankings, include relevant typed graph relationships, validate all returned citations, and independently verify the answer. Source downloads and complete extracted chunks are available from the evidence inspector.

## API

The canvas-first UI keeps Graph, Documents and Memory in the rail. Filters are optional; selecting an entity/edge opens evidence. Documents includes individual retry and **Retry all failed**, which only queues failed sources and retains completed chunks.

## Interactive memory and response latency

Chat memory recall uses a 350 ms wait budget for deeper hybrid retrieval. Saved user.md, core blocks, lexical source matches and recent durable user statements remain available without waiting for embeddings or LLM extraction. Slow enrichment continues in the background with bounded caching. This may return less semantic context on a cold miss; explicit memory search still supports full retrieval. No keyword-based semantic classification was added.

Rolling conversation summaries are cached by session and refreshed off the request path. The agent endpoint sends metadata immediately, streams provider text deltas as received, and reports tool start before execution. Incomplete tool-call streams fail closed. Its final SSE event includes context, first-token and first-tool timing where available.

The chat sidebar and Memory panel show original saved user statements and actual processing states. Failed enrichment does not delete the inbox original and can be retried from Memory. Disk persistence survives restarts but requires backups; it is not a promise of infallible retention after deletion or disk failure.

`python scripts/check_chat_latency.py --live-model` measures local recall and a short reply from the configured chat model without saving a test chat. Provider queues, reasoning, rate limits, initial MCP connections and external tool execution cannot be guaranteed to finish within seconds.

For a production check while the development server is running, set PowerShell `$env:ZUMBA_NEXT_DIST='.next-check'` before `npm run build`; separate output avoids concurrent writes to `.next`.

## API routes

- `GET /api/knowledge`: graph, sources, jobs, profile, resolution audit and revision.
- `GET /api/knowledge/events`: real graph revisions over SSE, with reconnect support.
- `POST /api/knowledge/documents`: multipart upload.
- `GET /api/knowledge/documents/{id}`: page/section chunks.
- `GET /api/knowledge/documents/{id}/download`: original source bytes.
- `POST /api/knowledge/documents/{id}/retry`: resume a failed job.
- `POST /api/knowledge/documents/retry-failed`: resume failed sources, leaving active/completed sources untouched.
- `GET /api/memory/captures`: original saved user statements and processing counts.
- `POST /api/memory/retry`: queue failed durable memory captures again.
- `POST /api/knowledge/query`: question with verified supporting citations.

## Verification

`python -m pytest tests/test_knowledge.py -q` covers grounding, malformed model responses, alias audit, idempotency, resume, actual PDF pages, DOCX sections, CSV/JSON preservation, memory source versioning, API validation, durable capture and bounded shutdown. Models are test doubles only inside tests. `cd frontend; npm run build` checks the production frontend.
