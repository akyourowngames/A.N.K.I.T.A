import fs from 'node:fs';
import { PROFILE_FILE, PROJECTS_FILE, MEMORY_INDEX_FILE } from '../../src/core/config.mjs';
import { ProfileStore } from '../../src/memory/profile.mjs';
import { ProjectStore } from '../../src/memory/projects.mjs';
import { getEmbeddings } from '../../src/memory/embeddings.mjs';
import { isStale } from '../../src/memory/memory-similarity.mjs';

export const name = 'recall';
export const description = 'Consult saved context before personalized advice or questions about the user/past work. Searches facts, project memory and session summaries. Interpret candidates semantically; empty query browses. Paginate before claiming absence.';
export const needsApproval = false;
// Read-only for permission purposes. A successful recall also refreshes the
// ageing timestamp, which is skipped when the calling context is read-only.
export const readOnly = true;
export const parameters = { type: 'object', properties: {
  query: { type: 'string' }, project: { type: 'string', description: 'Project id/name, or personal; omit for all.' },
  offset: { type: 'integer', minimum: 0 }, limit: { type: 'integer', minimum: 1, maximum: 50 },
  includeStale: { type: 'boolean', description: 'Include facts not recalled in a long time.' },
} };

function collect(args, ctx) {
  const profile = new ProfileStore(ctx.profileFile || PROFILE_FILE).load();
  const personalOnly = args.project === 'personal';
  const projects = personalOnly ? null : new ProjectStore(ctx.projectsFile || PROJECTS_FILE).load();
  const filter = args.project === 'personal' ? 'personal' : args.project ? projects.find(args.project)?.id : null;
  if (args.project && !filter) throw new Error('unknown project');
  const rows = profile.facts.map(f => ({ type: 'personal', id: f.id, text: f.text, kind: f.kind, at: f.updatedAt, source: f.source,
    confidence: f.confidence, conflictsWith: f.conflictsWith, stale: isStale(f, { staleDays: ctx.config?.memoryStaleDays }) }));
  for (const p of projects?.projects || []) {
    for (const [field, type] of [['notes', 'note'], ['decisions', 'decision'], ['todos', 'todo']]) {
      for (const item of p[field] || []) rows.push({ ...item, type, projectId: p.id, project: p.name });
    }
  }
  try {
    const index = personalOnly ? { entries: [] } : JSON.parse(fs.readFileSync(ctx.memoryIndexFile || MEMORY_INDEX_FILE, 'utf8'));
    for (const entry of index.entries || []) if (entry.summary) rows.push({ type: 'summary', id: entry.id, text: entry.summary, at: entry.at, projectId: entry.projectId, source: entry.source });
  } catch (err) { if (err.code !== 'ENOENT') throw err; }
  return rows.filter(r => !filter || (filter === 'personal' ? r.type === 'personal' : r.projectId === filter));
}

/** Old, rarely recalled facts sink but are never deleted; only an explicit ask returns them. */
function visible(rows, args, config) {
  if (args.includeStale) return rows;
  return rows.filter(row => !row.stale);
}

/** Past the hard ageing window a fact is dropped from normal results entirely. */
function withinForgetWindow(rows, args, config) {
  const days = Number(config.memoryForgetDays);
  if (args.includeStale || !Number.isFinite(days) || days <= 0) return rows;
  const cutoff = Date.now() - days * 86400000;
  return rows.filter(row => {
    if (row.type !== 'personal') return true;
    const at = Date.parse(row.at || '');
    return !Number.isFinite(at) || at >= cutoff;
  });
}

/** Called in the background at startup and after writes, never awaited by chat. */
export async function warmRecall(ctx = {}) {
  const embedder = getEmbeddings(ctx.config || {}, { cacheDir: ctx.embeddingCacheDir, fetchImpl: ctx.embeddingFetch });
  if (!embedder) return;
  try { await embedder.warm(collect({}, ctx)); } catch {} // Optional indexing must not fail a memory write.
  // Pay the connection/cold-start cost now instead of on the user's first turn.
  try { await embedder.probe(); } catch {}
}

/**
 * Resolve with the promise's value, or with null once `ms` elapses first. The
 * underlying work is NOT cancelled: a slow query embedding finishes in the
 * background and stays cached, so a later recall is instant and semantic.
 */
function withBudget(promise, ms) {
  if (!(ms > 0)) return promise;
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => { if (!settled) { settled = true; clearTimeout(timer); resolve(value); } };
    const timer = setTimeout(() => finish(null), ms);
    timer.unref?.();
    promise.then(finish, () => finish(null));
  });
}

/** Rare terms outrank incidental words shared by many facts. Ranks candidates only. */
function rankRows(rows, terms) {
  const documents = rows.map(r => `${r.text} ${r.project || ''} ${r.kind || ''}`.toLocaleLowerCase());
  const weights = terms.map(t => Math.log1p(rows.length / (1 + documents.filter(d => d.includes(t)).length)));
  return rows
    .map((r, i) => ({ ...r, score: terms.reduce((score, t, j) => score + (documents[i].includes(t) ? weights[j] : 0), 0) }))
    .sort((a, b) => Number(Boolean(a.stale)) - Number(Boolean(b.stale)) || b.score - a.score || String(b.at || '').localeCompare(String(a.at || '')));
}

export async function run(args = {}, ctx = {}) {
  try {
    const scoped = withinForgetWindow(visible(collect(args, ctx), args, ctx.config), args, ctx.config || {});
    const terms = [...new Set((String(args.query || '').toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) || []).filter(t => t.length > 2))];
    const ranked = rankRows(scoped, terms);
    const call = await rank(args, scoped, ranked, ctx, terms);
    // Recalls are the ageing signal, so they are recorded in one batched write,
    // and only for the rows the caller actually received.
    touchPersonal(pageRows(call.candidates, args), ctx);
    return page(call.candidates, args, call.meta);
  } catch (err) { return `Error: ${err.message}`; }
}

/** Remember that these facts were useful, without a write per row. */
function touchPersonal(candidates, ctx) {
  // recall is advertised readOnly, and a read-only subagent must stay read-only:
  // the ageing signal is bookkeeping, never worth violating that contract.
  if (ctx.readOnly === true) return;
  try {
    const ids = candidates.filter(row => row.type === 'personal').map(row => row.id);
    if (ids.length) new ProfileStore(ctx.profileFile || PROFILE_FILE).load().touchRecalled(ids);
  } catch { /* Ageing bookkeeping must never fail a recall. */ }
}

async function rank(args, scoped, ranked, ctx, terms) {
  const embedder = String(args.query || '').trim() && scoped.length ? getEmbeddings(ctx.config || {}, {
    cacheDir: ctx.embeddingCacheDir, fetchImpl: ctx.embeddingFetch,
  }) : null;
  let embedding;
  if (embedder) {
    // A caller on the reply's critical path passes a short budget so a slow
    // provider cannot stall the turn; the model's own recall call has none.
    const budget = Number(ctx.embedBudgetMs);
    const semantic = await withBudget(embedder.rank(String(args.query), scoped, { signal: ctx.signal }), budget);
    if (semantic === null) {
      // Deferred: rank continues in the background and caches its vector.
      embedding = { status: 'deferred' };
    } else {
      // A user can correct/forget a fact while the network request is in flight.
      // Re-read the source of truth and rebuild the lexical ranking from it, with
      // no second network wait, so the removed or edited text cannot leak.
      const fresh = withinForgetWindow(visible(collect(args, ctx), args, ctx.config), args, ctx.config || {});
      if (JSON.stringify(fresh) !== JSON.stringify(scoped)) {
        return rank(args, fresh, rankRows(fresh, terms), { ...ctx, config: { ...ctx.config, embeddings: false } }, terms);
      }
      embedding = { status: semantic.status, indexed: semantic.indexed, total: semantic.total };
      if (semantic.scores.size) {
        // Semantic order is model-derived. Unindexed rows stay available during a
        // cold/partial build; lexical ranking only orders that remainder.
        const candidates = scoped.filter(r => semantic.scores.has(r))
          .map(r => ({ ...r, score: semantic.scores.get(r) }))
          .sort((a, b) => Number(Boolean(a.stale)) - Number(Boolean(b.stale)) || b.score - a.score);
        const indexedIds = new Set(candidates.map(r => `${r.type}:${r.projectId || ''}:${r.id}`));
        candidates.push(...ranked.filter(r => !indexedIds.has(`${r.type}:${r.projectId || ''}:${r.id}`)));
        return { candidates, meta: { mode: semantic.indexed === scoped.length ? 'semantic' : 'hybrid', embedding,
          notice: 'Similarity-ranked candidates, not established relevance. Judge meaning before using; unindexed candidates follow indexed ones.' } };
      }
    }
  }
  const matches = terms.length ? ranked.filter(r => r.score > 0) : ranked;
  const fallback = terms.length > 0 && matches.length === 0;
  const candidates = fallback ? ranked.sort((a, b) => Number(b.type === 'personal') - Number(a.type === 'personal') || String(b.at || '').localeCompare(String(a.at || ''))) : matches;
  return { candidates, meta: { mode: fallback || !terms.length ? 'browse' : 'search', matched: matches.length,
    ...(embedding ? { embedding } : {}),
    ...(fallback ? { notice: 'No keyword matches. These are stored candidates, not asserted matches. Judge relevance from meaning; paginate or rephrase before saying nothing is known.' } : {}),
  } };
}

function page(candidates, args, meta) {
  const offset = Math.max(0, Math.floor(Number(args.offset) || 0)), limit = Math.max(1, Math.min(50, Math.floor(Number(args.limit) || 20)));
  return JSON.stringify({ ...meta, total: candidates.length, results: candidates.slice(offset, offset + limit), nextOffset: offset + limit < candidates.length ? offset + limit : null });
}

/** The slice a caller actually receives; ageing must not credit the whole store. */
function pageRows(candidates, args) {
  const offset = Math.max(0, Math.floor(Number(args.offset) || 0)), limit = Math.max(1, Math.min(50, Math.floor(Number(args.limit) || 20)));
  return candidates.slice(offset, offset + limit);
}
