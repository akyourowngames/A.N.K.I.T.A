import { detect, redactValue, secretValues } from '../../src/security/secret-scrubber.mjs';
const SAVE_INTENT = /\b(?:save|store|remember)\b|\buse this (?:key|token|password)\b/i;
const NAMING = /\bas\s+(?:my\s+)?([a-z0-9][a-z0-9 -]*?(?:key|token|password))\b/i;
const MAX_NAME_LENGTH = 80; // Characters; leaves room for the multi-secret suffix.
const INTENT_VALUE = /^\s*[:=]?\s*["']?([^\s"',;]+)/; // A named save request still requires the core entropy/shape check.
const EXISTING_REFERENCE = /(\[(?:REDACTED:[^\]\r\n]+|STORED:keychain:[^\]\r\n]+)\])/; // Preserve markers even for short pasted passwords.

/** Owns references for one desktop process; raw values live only in memory/vault ciphertext. */
export class SecretHistory {
  constructor(store) { this.store = store; this.enabled = true; this.references = new Map(); }
  async prepare(text) {
    const hits = detect(text), naming = NAMING.exec(text), save = SAVE_INTENT.test(text);
    if (!hits.length && save && naming) {
      const offset = naming.index + naming[0].length, value = INTENT_VALUE.exec(text.slice(offset))?.[1];
      if (value && detect(`api_key=${value}`).length) { const start = text.indexOf(value, offset); hits.push({ type: 'generic_token', start, end: start + value.length }); }
    }
    const candidates = secretValues(text);
    for (const { value, type } of candidates) if (!this.references.has(value)) this.references.set(value, `[REDACTED:${type}]`);
    if (!hits.length || !save) return { redacted: hits.length, stored: [] };
    const named = naming?.[1];
    const stored = [];
    for (const [index, hit] of hits.entries()) {
      const raw = text.slice(hit.start, hit.end), values = secretValues(raw);
      const value = hit.type === 'encoded_secret' ? values.at(-1)?.value || raw : raw;
      const base = (named || hit.type).toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, MAX_NAME_LENGTH).replace(/-$/, '');
      const name = hits.length > 1 ? `${base}-${index + 1}` : base;
      await this.store.saveSecret(name, value);
      for (const candidate of [raw, value]) this.references.set(candidate, `[STORED:keychain:${name}]`); stored.push(name);
    }
    return { redacted: hits.length, stored };
  }
  clean = value => {
    const replace = item => {
      if (typeof item === 'string') return item.split(EXISTING_REFERENCE).map(part => {
        if (EXISTING_REFERENCE.test(part)) return part;
        for (const [secret, reference] of [...this.references].sort((a, b) => b[0].length - a[0].length)) if (this.enabled || reference.startsWith('[STORED:')) part = part.split(EXISTING_REFERENCE).map(piece => EXISTING_REFERENCE.test(piece) ? piece : piece.split(secret).join(reference)).join('');
        return part;
      }).join('');
      if (Array.isArray(item)) return item.map(replace);
      if (item && typeof item === 'object') return Object.fromEntries(Object.entries(item).map(([key, entry]) => [key, replace(entry)]));
      return item;
    };
    const copy = replace(value);
    return this.enabled ? redactValue(copy) : copy;
  };
}
