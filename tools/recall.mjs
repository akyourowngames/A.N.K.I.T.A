import fs from 'node:fs';
import { PROFILE_FILE, PROJECTS_FILE, MEMORY_INDEX_FILE } from '../src/config.mjs';
import { ProfileStore } from '../src/profile.mjs';
import { ProjectStore } from '../src/projects.mjs';

export const name = 'recall';
export const description = 'Consult saved context before personalized advice or questions about the user/past work. Searches facts, project memory and session summaries. Interpret candidates semantically; empty query browses. Paginate before claiming absence.';
export const needsApproval = false;
export const readOnly = true;
export const parameters = { type: 'object', properties: {
  query: { type: 'string' }, project: { type: 'string', description: 'Project id/name, or personal; omit for all.' },
  offset: { type: 'integer', minimum: 0 }, limit: { type: 'integer', minimum: 1, maximum: 50 },
} };

export function run(args = {}, ctx = {}) {
  try {
    const profile = new ProfileStore(ctx.profileFile || PROFILE_FILE).load();
    const personalOnly = args.project === 'personal';
    const projects = personalOnly ? null : new ProjectStore(ctx.projectsFile || PROJECTS_FILE).load();
    const filter = args.project === 'personal' ? 'personal' : args.project ? projects.find(args.project)?.id : null;
    if (args.project && !filter) return 'Error: unknown project';
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
    const terms = [...new Set((String(args.query || '').toLocaleLowerCase().match(/[\p{L}\p{N}]+/gu) || []).filter(t => t.length > 2))];
    const scoped = rows.filter(r => !filter || (filter === 'personal' ? r.type === 'personal' : r.projectId === filter));
    const documents = scoped.map(r => `${r.text} ${r.project || ''} ${r.kind || ''}`.toLocaleLowerCase());
    // Rare terms outrank incidental words shared by many facts. This ranks
    // candidates only; the conversational model decides their meaning.
    const weights = terms.map(t => Math.log1p(scoped.length / (1 + documents.filter(d => d.includes(t)).length)));
    const ranked = scoped
      .map((r, i) => ({ ...r, score: terms.reduce((score, t, j) => score + (documents[i].includes(t) ? weights[j] : 0), 0) }))
      .sort((a, b) => b.score - a.score || String(b.at || '').localeCompare(String(a.at || '')));
    const matches = terms.length ? ranked.filter(r => r.score > 0) : ranked;
    const fallback = terms.length > 0 && matches.length === 0;
    const candidates = fallback ? ranked.sort((a, b) => Number(b.type === 'personal') - Number(a.type === 'personal') || String(b.at || '').localeCompare(String(a.at || ''))) : matches;
    const offset = Math.max(0, Number(args.offset) || 0), limit = Math.max(1, Math.min(50, Number(args.limit) || 20));
    return JSON.stringify({ mode: fallback || !terms.length ? 'browse' : 'search', matched: matches.length, total: candidates.length,
      ...(fallback ? { notice: 'No keyword matches. These are stored candidates, not asserted matches. Judge relevance from meaning; paginate or rephrase before saying nothing is known.' } : {}),
      results: candidates.slice(offset, offset + limit), nextOffset: offset + limit < candidates.length ? offset + limit : null });
  } catch (err) { return `Error: ${err.message}`; }
}
