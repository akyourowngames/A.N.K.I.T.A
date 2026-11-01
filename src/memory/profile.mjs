import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { writeTextFile } from '../../tools/shared/_shared.mjs';
import { redactValue } from '../security/secret-scrubber.mjs';

export const MAX_ALWAYS = 12;
export const FACT_PROMPT_CAP = 160;
const key = text => text.trim().toLocaleLowerCase();
const DEFAULT_CONFIDENCE = 1; // A direct user statement is treated as certain.
export const INFERRED_CONFIDENCE = 0.6; // Extraction-guessed facts are softer.

/** Give an older fact the newer fields without changing its meaning. */
function normalizeFact(fact) {
  return {
    ...fact,
    confidence: Number.isFinite(fact.confidence) ? Math.min(1, Math.max(0, fact.confidence)) : DEFAULT_CONFIDENCE,
    lastRecalledAt: typeof fact.lastRecalledAt === 'string' ? fact.lastRecalledAt : null,
    recallCount: Math.max(0, Math.floor(Number(fact.recallCount) || 0)),
    conflictsWith: Array.isArray(fact.conflictsWith) ? fact.conflictsWith.filter(id => typeof id === 'string') : [],
  };
}

const clampConfidence = value => Number.isFinite(Number(value)) ? Math.min(1, Math.max(0, Number(value))) : DEFAULT_CONFIDENCE;

export class ProfileStore {
  constructor(file) {
    this.file = file;
    this.data = { version: 1, facts: [] };
  }

  load() {
    try {
      const data = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      if (!Array.isArray(data.facts)) throw new Error('invalid profile');
      // Older profiles carry only id/text/kind/always/source; the new fields are
      // additive and default rather than migrated, so a hand-edited file still loads.
      this.data = { version: 1, facts: data.facts.filter(f => f?.id && typeof f.text === 'string').map(normalizeFact), forgottenBefore: data.forgottenBefore || null };
    } catch (err) {
      // Do not silently overwrite damaged personal memory on the next write.
      if (err.code !== 'ENOENT') throw new Error(`Cannot read profile: ${err.message}`);
      this.data = { version: 1, facts: [] };
    }
    return this;
  }

  get facts() { return this.data.facts; }

  mutate(fn) {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const lock = `${this.file}.lock`;
    let fd;
    try {
      // A crashed synchronous write cannot legitimately hold this for a minute.
      try { if (Date.now() - fs.statSync(lock).mtimeMs > 60000) fs.unlinkSync(lock); } catch {}
      fd = fs.openSync(lock, 'wx');
    } catch { throw new Error('Profile is busy; retry the memory operation.'); }
    try {
      this.load();
      const result = fn();
      writeTextFile(this.file, JSON.stringify(redactValue(this.data), null, 2));
      return result;
    } finally {
      fs.closeSync(fd);
      fs.unlinkSync(lock);
    }
  }

  add({ text, kind = 'fact', always, source = null, confidence } = {}) {
    if (typeof text !== 'string' || !text.trim()) throw new Error('text is required');
    if (always !== undefined && typeof always !== 'boolean') throw new Error('always must be boolean');
    return this.mutate(() => {
      const existing = this.facts.find(f => key(f.text) === key(text));
      if (existing) {
        if (always !== undefined) existing.always = always;
        existing.source = source;
        existing.updatedAt = new Date().toISOString();
        if (confidence !== undefined) existing.confidence = clampConfidence(confidence);
        return existing;
      }
      const at = new Date().toISOString();
      const fact = { id: randomUUID(), text: text.trim(), kind: String(kind).slice(0, 40), always: always === true,
        createdAt: at, updatedAt: at, source, confidence: confidence === undefined ? DEFAULT_CONFIDENCE : clampConfidence(confidence),
        lastRecalledAt: null, recallCount: 0, conflictsWith: [] };
      this.facts.push(fact);
      return fact;
    });
  }

  /**
   * Mark two facts as contradicting without changing either text. Only the flag
   * is written; resolution stays an explicit user decision.
   */
  flagConflict(a, b) {
    if (!a || !b || a === b) return [];
    return this.mutate(() => {
      const left = this.facts.find(f => f.id === a), right = this.facts.find(f => f.id === b);
      if (!left || !right) return [];
      if (!left.conflictsWith.includes(b)) left.conflictsWith.push(b);
      if (!right.conflictsWith.includes(a)) right.conflictsWith.push(a);
      return [left, right];
    });
  }

  /** Drop a conflict flag once the user has resolved it either way. */
  clearConflict(a, b) {
    return this.mutate(() => {
      for (const [id, other] of [[a, b], [b, a]]) {
        const fact = this.facts.find(f => f.id === id);
        if (fact) fact.conflictsWith = fact.conflictsWith.filter(item => item !== other);
      }
    });
  }

  /** One batched write: a recall touches many facts but must not write per fact. */
  touchRecalled(ids, at = new Date().toISOString()) {
    const wanted = new Set((Array.isArray(ids) ? ids : []).filter(id => typeof id === 'string'));
    if (!wanted.size) return 0;
    return this.mutate(() => {
      let touched = 0;
      for (const fact of this.facts) {
        if (!wanted.has(fact.id)) continue;
        fact.lastRecalledAt = at;
        fact.recallCount = (fact.recallCount || 0) + 1;
        touched++;
      }
      return touched;
    });
  }

  update(id, patch = {}) {
    if (patch.text !== undefined && (typeof patch.text !== 'string' || !patch.text.trim())) throw new Error('text is required');
    if (patch.always !== undefined && typeof patch.always !== 'boolean') throw new Error('always must be boolean');
    return this.mutate(() => {
      const fact = this.facts.find(f => f.id === id);
      if (!fact) throw new Error(`No personal fact ${id}`);
      // Consolidation must not overwrite a newer user edit.
      if (patch.expectedUpdatedAt && fact.updatedAt !== patch.expectedUpdatedAt) throw new Error('Fact changed since extraction; retry');
      if (patch.text !== undefined) fact.text = patch.text.trim();
      if (patch.kind !== undefined) fact.kind = String(patch.kind).slice(0, 40);
      if (patch.always !== undefined) fact.always = patch.always;
      fact.source = patch.source ?? null;
      fact.updatedAt = new Date().toISOString();
      return fact;
    });
  }

  forget(id) {
    return this.mutate(() => {
      const fact = this.facts.find(f => f.id === id);
      if (!fact) throw new Error(`No personal fact ${id}`);
      this.data.facts = this.facts.filter(f => f.id !== id);
      // A forgotten fact must not leave dangling conflict pointers behind, or
      // every later recall keeps reporting a conflict that no longer exists.
      for (const other of this.data.facts) other.conflictsWith = other.conflictsWith.filter(item => item !== id);
      // Retain no deleted text. Older transcripts may no longer create personal
      // facts, preventing forgotten information from being silently relearned.
      this.data.forgottenBefore = new Date().toISOString();
      return fact;
    });
  }

  promptBlock() {
    const facts = this.facts.filter(f => f.always === true).slice(-MAX_ALWAYS);
    return facts.length ? ['Personal memory (user preferences; current requests take precedence):',
      ...facts.map(f => `  - ${f.text.replace(/\s+/g, ' ').slice(0, FACT_PROMPT_CAP)}`)].join('\n') : '';
  }
}
