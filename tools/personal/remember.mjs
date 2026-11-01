import { PROFILE_FILE } from '../../src/core/config.mjs';
import { ProfileStore, MAX_ALWAYS, INFERRED_CONFIDENCE } from '../../src/memory/profile.mjs';
import { getEmbeddings } from '../../src/memory/embeddings.mjs';
import { findSimilar, DEFAULT_DEDUP_THRESHOLD, DEFAULT_CONFLICT_LOW } from '../../src/memory/memory-similarity.mjs';

export const name = 'remember';
export const description = 'Persist personal facts across sessions/projects. add/list/update/forget; use IDs for corrections. Save before claiming success. always=true only for instructions meant to apply every turn.';
export const needsApproval = false;
export const parameters = {
  type: 'object', properties: {
    action: { type: 'string', enum: ['add', 'list', 'update', 'forget'] },
    id: { type: 'string' }, text: { type: 'string' }, kind: { type: 'string', description: 'Free-form semantic category.' },
    always: { type: 'boolean' }, query: { type: 'string' }, offset: { type: 'integer', minimum: 0 }, limit: { type: 'integer', minimum: 1, maximum: 100 },
  }, required: ['action'],
};

/**
 * A memory write must not silently create a second copy of a fact the user
 * already stated, and must not silently overwrite one it contradicts. Near
 * duplicates merge into the clearer wording; a likely contradiction is stored
 * but flagged so the reply can ask which is current.
 */
async function addWithChecks(s, args, ctx) {
  const config = ctx.config || {};
  const text = String(args.text || '').trim();
  if (!text) return { fact: s.add(args) };
  // Extraction passes the conversation timestamp so a merge cannot overwrite a
  // fact the user restated later. A direct tool call has no such timestamp.
  const at = typeof args.source?.at === 'string' ? Date.parse(args.source.at) : null;
  // A direct remember call is the user's own statement; only extraction, which
  // carries an evidence quote, is treated as an inference.
  const confidence = args.confidence ?? (args.source?.evidence ? INFERRED_CONFIDENCE : 1);
  // Exact duplicates are already merged by the store; skip the similarity pass.
  if (s.facts.some(f => f.text.trim().toLocaleLowerCase() === text.toLocaleLowerCase())) {
    return { fact: s.add({ ...args, confidence }) };
  }
  const embedder = getEmbeddings(config, { cacheDir: ctx.embeddingCacheDir, fetchImpl: ctx.embeddingFetch });
  let match = null;
  try {
    match = await findSimilar(text, s.facts, {
      embedder,
      dedup: config.memoryDedupThreshold ?? DEFAULT_DEDUP_THRESHOLD,
      conflictLow: config.memoryConflictLow ?? DEFAULT_CONFLICT_LOW,
      kind: args.kind || 'fact',
    });
  } catch { match = null; } // A similarity failure must never block saving.

  if (match?.kind === 'duplicate') {
    const target = new ProfileStore(s.file).load().facts.find(f => f.id === match.fact.id);
    // The fact vanished (forgotten) while the similarity check was in flight;
    // treat this as a new fact rather than failing the write.
    if (!target) return { fact: s.add({ ...args, confidence }) };
    // Never let older history overwrite wording the user stated more recently.
    const targetAt = Date.parse(target.source?.at || target.updatedAt || '');
    if (at !== null && Number.isFinite(targetAt) && targetAt > at) return { fact: target };
    // Same fact, clearer wording: keep one entry, keep its pin, record new evidence.
    const merged = s.update(target.id, { text, kind: args.kind || target.kind,
      always: args.always === undefined ? target.always : args.always,
      source: args.source ?? target.source });
    return { fact: merged, merged: { from: target.text, score: round(match.score) } };
  }
  // A direct remember call is the user's own statement; extraction is a guess.
  const fact = s.add({ ...args, confidence });
  if (match?.kind === 'conflict') {
    try { s.flagConflict(fact.id, match.fact.id); } catch { /* flagging is advisory */ }
    return { fact, conflict: { id: match.fact.id, text: match.fact.text, score: round(match.score) } };
  }
  return { fact };
}

const round = n => Math.round(Number(n) * 100) / 100;

export async function run(args = {}, ctx = {}) {
  try {
    const s = new ProfileStore(ctx.profileFile || PROFILE_FILE).load();
    if (args.action === 'list') {
      const matches = s.facts.filter(f => !args.query || f.text.toLocaleLowerCase().includes(String(args.query).toLocaleLowerCase()));
      const offset = Math.max(0, Number(args.offset) || 0);
      const limit = Math.max(1, Math.min(100, Number(args.limit) || 50));
      return JSON.stringify({ total: matches.length, facts: matches.slice(offset, offset + limit), nextOffset: offset + limit < matches.length ? offset + limit : null });
    }
    if (args.action === 'add') {
      const result = await addWithChecks(s, args, ctx);
      const pinned = s.facts.filter(f => f.always).length;
      return JSON.stringify({ action: 'add', ...result,
        ...(result.conflict ? { notice: 'This may contradict an earlier fact. Ask the user which is current, then update the older fact if they confirm.' } : {}),
        ...(result.merged ? { notice: 'Updated the existing fact instead of adding a duplicate.' } : {}),
        ...(pinned > MAX_ALWAYS ? { pinNotice: `Only the latest ${MAX_ALWAYS} pinned facts enter the prompt; all remain available through recall.` } : {}) });
    }
    const fact = args.action === 'update' ? s.update(args.id, args) : args.action === 'forget' ? s.forget(args.id) : null;
    if (!fact) return 'Error: use add, list, update, or forget.';
    return JSON.stringify({ action: args.action, fact, ...(s.facts.filter(f => f.always).length > MAX_ALWAYS ? { notice: `Only the latest ${MAX_ALWAYS} pinned facts enter the prompt; all remain available through recall.` } : {}) });
  } catch (err) { return `Error: ${err.message}`; }
}
