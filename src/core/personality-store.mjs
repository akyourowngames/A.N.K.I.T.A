import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { DEFAULT_PERSONALITY, PERSONALITY_VERSION, normalizePersonality } from './personality.mjs';

const MAX_CARD_BYTES = 16 * 1024; // UTF-8 bytes: upper bound before JSON parsing a manually edited card.
const PRIVATE_FILE_MODE = 0o600; // Owner-only access where the platform supports POSIX permissions.
const LOAD_NOTICE = "Couldn't read your saved personality. Using the default; edit and save in Settings to replace it.";

export class PersonalityStore {
  constructor(file) { this.file = file; this.profile = normalizePersonality(DEFAULT_PERSONALITY); this.notice = null; }
  load() {
    this.notice = null;
    this.profile = normalizePersonality(DEFAULT_PERSONALITY);
    try {
      if (fs.statSync(this.file).size > MAX_CARD_BYTES) throw new Error('Card too large');
      const saved = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      if (saved?.version !== PERSONALITY_VERSION || !saved.profile || typeof saved.profile !== 'object' || Array.isArray(saved.profile)) throw new Error('Unsupported card version');
      this.profile = normalizePersonality(saved.profile);
    } catch (error) {
      if (error.code !== 'ENOENT') this.notice = LOAD_NOTICE;
    }
    return this;
  }
  view() { return { profile: structuredClone(this.profile), notice: this.notice }; }
  save(input) {
    const profile = normalizePersonality(input);
    const text = JSON.stringify({ version: PERSONALITY_VERSION, profile }, null, 2);
    if (Buffer.byteLength(text) > MAX_CARD_BYTES) throw new Error('Personality card is too large.');
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const temp = path.join(path.dirname(this.file), `.${path.basename(this.file)}.${randomUUID()}.tmp`);
    try {
      fs.writeFileSync(temp, text, { mode: PRIVATE_FILE_MODE });
      fs.renameSync(temp, this.file);
      try { fs.chmodSync(this.file, PRIVATE_FILE_MODE); } catch { /* Windows can ignore POSIX permissions. */ }
    } finally { try { fs.unlinkSync(temp); } catch {} }
    this.profile = profile; this.notice = null;
    return this.view();
  }
}
