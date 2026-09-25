import fs from 'node:fs';
import { PROFILE_FILE, PROJECTS_FILE, MEMORY_INDEX_FILE } from '../../src/core/config.mjs';
import { ProfileStore } from '../../src/memory/profile.mjs';
import { ProjectStore } from '../../src/memory/projects.mjs';
import { getEmbeddings } from '../../src/memory/embeddings.mjs';

export const name = 'recall';
export const description = 'Consult saved context before personalized advice or questions about the user/past work. Searches facts, project memory and session summaries. Interpret candidates semantically; empty query browses. Paginate before claiming absence.';
export const needsApproval = false;
export const readOnly = true;
export const parameters = { type: 'object', properties: {
  query: { type: 'string' }, project: { type: 'string', description: 'Project id/name, or personal; omit for all.' },
  offset: { type: 'integer', minimum: 0 }, limit: { type: 'integer', minimum: 1, maximum: 50 },
} };

function collect(args, ctx) {
  const profile = new ProfileStore(ctx.profileFile || PROFILE_FILE).load();
  const personalOnly = args.project === 'personal';
  const projects = personalOnly ? null : new ProjectStore(ctx.projectsFile || PROJECTS_FILE).load();
  const filter = args.project === 'personal' ? 'personal' : args.project ? projects.find(args.project)?.id : null;
  if (args.project && !filter) throw new Error('unknown project');
  const rows = profile.facts.map(f => ({ type: 'personal', id: f.id, text: f.text, kind: f.kind, at: f.updatedAt, source: f.source }));
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

export async function run(args = {}, ctx = {}) {
  try {
    const scoped = collect(args, ctx);
    const terms = [...new Set((String(args.query || '').toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) || []).filter(t => t.length > 2))];
    const documents = scoped.map(r => `${r.text} ${r.project || ''} ${r.kind || ''}`.toLocaleLowerCase());
    // Rare terms outrank incidental words shared by many facts. This ranks
    // candidates only; the conversational model decides their meaning.
    const weights = terms.map(t => Math.log1p(scoped.length / (1 + documents.filter(d => d.includes(t)).length)));
    const ranked = scoped
      .map((r, i) => ({ ...r, score: terms.reduce((score, t, j) => score + (documents[i].includes(t) ? weights[j] : 0), 0) }))
      .sort((a, b) => b.score - a.score || String(b.at || '').localeCompare(String(a.at || '')));
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
        // Re-read the source of truth, with no second network wait, in that case.
        if (JSON.stringify(collect(args, ctx)) !== JSON.stringify(scoped)) {
          return run(args, { ...ctx, config: { ...ctx.config, embeddings: false } });
        }
        embedding = { status: semantic.status, indexed: semantic.indexed, total: semantic.total };
        if (semantic.scores.size) {
          // Semantic order is model-derived. Unindexed rows stay available during a
          // cold/partial build; lexical ranking only orders that remainder.
          const candidates = scoped.filter(r => semantic.scores.has(r))
            .map(r => ({ ...r, score: semantic.scores.get(r) }))
            .sort((a, b) => b.score - a.score);
          const indexedIds = new Set(candidates.map(r => `${r.type}:${r.projectId || ''}:${r.id}`));
          candidates.push(...ranked.filter(r => !indexedIds.has(`${r.type}:${r.projectId || ''}:${r.id}`)));
          return page(candidates, args, { mode: semantic.indexed === scoped.length ? 'semantic' : 'hybrid', embedding,
            notice: 'Similarity-ranked candidates, not established relevance. Judge meaning before using; unindexed candidates follow indexed ones.' });
        }
      }
    }
    const matches = terms.length ? ranked.filter(r => r.score > 0) : ranked;
    const fallback = terms.length > 0 && matches.length === 0;
    const candidates = fallback ? ranked.sort((a, b) => Number(b.type === 'personal') - Number(a.type === 'personal') || String(b.at || '').localeCompare(String(a.at || ''))) : matches;
    return page(candidates, args, { mode: fallback || !terms.length ? 'browse' : 'search', matched: matches.length,
      ...(embedding ? { embedding } : {}),
      ...(fallback ? { notice: 'No keyword matches. These are stored candidates, not asserted matches. Judge relevance from meaning; paginate or rephrase before saying nothing is known.' } : {}),
    });
  } catch (err) { return `Error: ${err.message}`; }
}

function page(candidates, args, meta) {
  const offset = Math.max(0, Math.floor(Number(args.offset) || 0)), limit = Math.max(1, Math.min(50, Math.floor(Number(args.limit) || 20)));
  return JSON.stringify({ ...meta, total: candidates.length, results: candidates.slice(offset, offset + limit), nextOffset: offset + limit < candidates.length ? offset + limit : null });
}
