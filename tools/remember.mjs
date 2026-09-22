import { PROFILE_FILE } from '../src/config.mjs';
import { ProfileStore, MAX_ALWAYS } from '../src/profile.mjs';

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

export function run(args = {}, ctx = {}) {
  try {
    const s = new ProfileStore(ctx.profileFile || PROFILE_FILE).load();
    if (args.action === 'list') {
      const matches = s.facts.filter(f => !args.query || f.text.toLocaleLowerCase().includes(String(args.query).toLocaleLowerCase()));
      const offset = Math.max(0, Number(args.offset) || 0);
      const limit = Math.max(1, Math.min(100, Number(args.limit) || 50));
      return JSON.stringify({ total: matches.length, facts: matches.slice(offset, offset + limit), nextOffset: offset + limit < matches.length ? offset + limit : null });
    }
    const fact = args.action === 'add' ? s.add(args) : args.action === 'update' ? s.update(args.id, args) : args.action === 'forget' ? s.forget(args.id) : null;
    if (!fact) return 'Error: use add, list, update, or forget.';
    return JSON.stringify({ action: args.action, fact, ...(s.facts.filter(f => f.always).length > MAX_ALWAYS ? { notice: `Only the latest ${MAX_ALWAYS} pinned facts enter the prompt; all remain available through recall.` } : {}) });
  } catch (err) { return `Error: ${err.message}`; }
}
