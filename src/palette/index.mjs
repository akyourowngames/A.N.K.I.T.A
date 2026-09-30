const PREFIX_SCORE = 100; // Prefix > word boundary > fuzzy > keyword matches.
const WORD_SCORE = 70;
const FUZZY_SCORE = 40;
const KEYWORD_PENALTY = 70; // Even a fuzzy title outranks an exact keyword.
const MANIFEST_LIMIT = 20; // Entries per skill; bounds untrusted contribution size.
const TITLE_LIMIT = 100; // Characters displayed in a single palette row.
const HINT_LIMIT = 300;
const KEYWORDS_LIMIT = 20;
export const COMMANDS = Object.freeze([
  { id: 'command:new-chat', title: 'New teammate', hint: 'Create another assistant', keywords: ['new chat', 'agent'], command: 'new-teammate' },
  { id: 'command:settings', title: 'Settings', hint: 'Providers, appearance and preferences', keywords: ['config', 'model'], command: 'settings' },
  { id: 'command:jobs', title: 'Scheduled tasks', hint: 'Upcoming runs and heartbeat', keywords: ['cron', 'reminder', 'schedule'], command: 'jobs' },
  { id: 'command:export', title: 'Export conversation', hint: 'Save a protected Markdown transcript', keywords: ['download', 'history'], command: 'export' },
  { id: 'command:updates', title: 'Check for updates', hint: 'Look for a newer Ankita release', keywords: ['upgrade', 'version'], command: 'updates' },
  { id: 'command:plugins', title: 'Plugins and skills', hint: 'Manage connected apps and skills', keywords: ['connectors', 'integration'], command: 'plugins' },
]);
export function validatePalette(entries) {
  if (entries === undefined) return [];
  if (!Array.isArray(entries) || entries.length > MANIFEST_LIMIT) throw new Error('Invalid palette manifest');
  const ids = new Set();
  return entries.map(entry => {
    if (!entry || !/^[a-z0-9-]{1,64}$/.test(entry.id) || ids.has(entry.id) || typeof entry.title !== 'string' || !entry.title.trim() || entry.title.length > TITLE_LIMIT || (entry.hint !== undefined && (typeof entry.hint !== 'string' || entry.hint.length > HINT_LIMIT)) || (entry.keywords !== undefined && (!Array.isArray(entry.keywords) || entry.keywords.length > KEYWORDS_LIMIT || entry.keywords.some(word => typeof word !== 'string' || word.length > TITLE_LIMIT)))) throw new Error('Invalid palette entry');
    ids.add(entry.id); return { id: entry.id, title: entry.title.trim(), hint: entry.hint || '', keywords: entry.keywords || [] };
  });
}
export function buildIndex({ skills = [], jobs = [] } = {}) {
  return [...COMMANDS.map(entry => ({ ...entry, source: 'command' })), ...skills.flatMap(skill => [
    { id: `skill:${skill.name}`, source: 'skill', skill: skill.name, title: skill.name, hint: skill.description, keywords: [skill.name] },
    ...validatePalette(skill.palette).map(entry => ({ ...entry, id: `skill:${skill.name}:${entry.id}`, source: 'skill', skill: skill.name })),
  ]), ...jobs.map(job => ({ id: `job:${job.id}`, jobId: job.id, source: 'job', title: job.name, hint: `${job.cronLabel} · ${job.enabled === false ? 'paused' : job.timeZone || ''}`, nextRunAt: job.nextRunAt, keywords: ['schedule', 'job', job.kind || 'routine'] }))];
}
function score(value, query) {
  const text = String(value || '').toLocaleLowerCase();
  if (text.startsWith(query)) return PREFIX_SCORE;
  if (text.split(/[^\p{L}\p{N}]+/u).some(word => word.startsWith(query))) return WORD_SCORE;
  let offset = 0, gap = 0;
  for (const char of query) { const next = text.indexOf(char, offset); if (next < 0) return null; gap += next - offset; offset = next + 1; }
  return FUZZY_SCORE - gap / Math.max(1, text.length);
}
export function search(entries, input = '') {
  const query = String(input).toLocaleLowerCase().trim();
  if (!query) return entries;
  return entries.map(entry => {
    const titleScore = score(entry.title, query);
    const keywordScore = Math.max(...(entry.keywords || []).map(word => { const rank = score(word, query); return rank === null ? -Infinity : rank - KEYWORD_PENALTY; }), -Infinity);
    return { entry, rank: Math.max(titleScore ?? -Infinity, keywordScore) };
  }).filter(item => Number.isFinite(item.rank)).sort((a, b) => b.rank - a.rank || a.entry.title.localeCompare(b.entry.title)).map(item => item.entry);
}
