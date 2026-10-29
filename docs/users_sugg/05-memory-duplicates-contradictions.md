# Problem: memory keeps near-duplicates and contradicting facts

## Problem

Two gaps in Ankita's memory consolidation, both leaning on the extractor model
to notice relationships it is not guaranteed to notice:

1. **Dedup is exact-text only.** `MemoryConsolidator.apply()` in
   `src/memory/consolidate.mjs` skips a candidate when the normalized text
   matches an existing fact, and the consolidation prompt says "Merge
   duplicates". But near-duplicate quotes — the user repeating a similar idea
   across sessions — depend on the extractor noticing, and there is no
   embedding-similarity gate before commit. The result is duplicate memories
   saying nearly the same thing.
2. **No contradiction detector.** A correction updates in place (the prompt
   requires an explicit correction to reference the existing fact's id, newer
   facts take precedence, and `apply()` writes with an `expectedUpdatedAt`
   guard). But if the extractor misses the link between the old fact and the
   new statement, both coexist. The commenter's example: "I like black coffee"
   today, "I switched to tea" next week — without detection, the memory holds
   both as if both were true.

Source: baumgaerben, Oct 11, 2026, on "How I built memory for my desktop AI
companion: every memory must quote the transcript". Status: agreed in thread.

## Design

The cheap fix is already half-built: `src/memory/embeddings.mjs` already
indexes every fact, so a cosine check against existing facts slots in cleanly
before commit. For contradictions, the existing correction machinery (fact id
reference + timestamp precedence + `expectedUpdatedAt` guard) is the right
destination — the missing piece is detection, not storage.

Retrieval, for the record, is already two-pass and is not the problem:
`personalMemoryContext` injects at most 6 candidates capped at 1600 chars, and
the recall tool expands via semantic rerank or lexical fallback.

## Solution

1. Pre-commit similarity gate: before `remember`, run a cosine check against
   existing facts via the embeddings index. On a near-duplicate, merge the
   overlapping quotes into one entry with multiple citation spans instead of
   committing a second fact.
2. Contradiction detection pass: when a new fact contradicts an existing one
   (same subject, incompatible claim), rewrite the old fact's text with the
   new evidence quote and timestamp rather than keeping both — the same
   update-in-place shape the explicit-correction path already uses.
3. Keep the extractor prompt's "Merge duplicates" instruction as a backstop,
   not the mechanism.

## Acceptance

- Fixture: the same idea stated similarly across two sessions → one memory
  entry with both quotes, not two entries.
- Fixture: contradictory statement a week later → the old fact is rewritten
  with the new quote and timestamp; a query returns the current fact only.
