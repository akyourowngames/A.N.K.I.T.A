import { MAX_ATTACHMENTS, MAX_PENDING_CAPTURES } from '../browser-helper/protocol.mjs';
export const EMPTY_COMPANION_DRAFT = Object.freeze({ text: '', files: [], error: '', reading: false });
const LIMIT_ERROR = 'Attach up to ' + MAX_ATTACHMENTS + ' files at a time.';
const RECENT_RECEIPTS = MAX_PENDING_CAPTURES * 2; // Receipt identities; bounds duplicate tracking while covering the entire inbox.
export class CompanionDrafts {
  constructor() { this.snapshot = {}; this.listeners = new Set(); this.receipts = new Set(); }
  subscribe = listener => { this.listeners.add(listener); return () => this.listeners.delete(listener); };
  getSnapshot = () => this.snapshot;
  get(id) { return this.snapshot[id] || EMPTY_COMPANION_DRAFT; }
  hasReceipt(id) { return this.receipts.has(id); }
  update(id, updater) { this.snapshot = { ...this.snapshot, [id]: updater(this.get(id)) }; for (const listener of this.listeners) listener(); }
  capture(item) {
    if (this.receipts.has(item.id)) return true;
    if (this.get(item.threadId).files.length >= MAX_ATTACHMENTS) { this.update(item.threadId, draft => ({ ...draft, error: LIMIT_ERROR + ' Remove one to receive the captured page.' })); return false; }
    this.receipts.add(item.id);
    if (this.receipts.size > RECENT_RECEIPTS) this.receipts.delete(this.receipts.values().next().value);
    this.update(item.threadId, draft => ({ ...draft, files: [...draft.files, item.attachment], error: '' }));
    return true;
  }
  async read(id, files, reader) {
    if (!id || !files.length || this.get(id).reading) return { accepted: 0, error: 'A file is already being read for this teammate' };
    this.update(id, draft => ({ ...draft, reading: true, error: '' }));
    const room = Math.max(0, MAX_ATTACHMENTS - this.get(id).files.length), accepted = [], problems = [];
    for (const file of files.slice(0, room)) {
      try { accepted.push(await reader(file)); }
      catch (error) { problems.push(error instanceof Error ? error.message : String(error)); }
    }
    if (files.length > room) problems.push(LIMIT_ERROR);
    // A webpage may arrive while a file reader awaits; apply the cap at commit too.
    const available = Math.max(0, MAX_ATTACHMENTS - this.get(id).files.length);
    if (accepted.length > available) problems.push(LIMIT_ERROR);
    const added = accepted.slice(0, available), error = problems.join(' ');
    this.update(id, draft => ({ ...draft, files: [...draft.files, ...added], error, reading: false }));
    return { accepted: added.length, error };
  }
}
