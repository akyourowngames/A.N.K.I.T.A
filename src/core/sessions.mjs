import fs from 'node:fs';
import path from 'node:path';
import { randomUUID, createHash } from 'node:crypto';
import { JOURNAL_DIR } from './config.mjs';
import { localClock } from '../automation/notify.mjs';
import { writeTextFile } from '../../tools/shared/_shared.mjs';
import { redactValue } from '../security/secret-scrubber.mjs';

export function saveSession(file, data, { transform = redactValue } = {}) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  if (data.journaled) {
    try {
      const raw = fs.readFileSync(file, 'utf8');
      const previous = JSON.parse(raw);
      if (!previous.journaled && previous.messages?.length) {
        const id = createHash('sha256').update(raw).digest('hex').slice(0, 24);
        writeTextFile(path.join(path.dirname(file), `legacy-${id}.json`), JSON.stringify(transform(previous), null, 2));
      }
    } catch (err) { if (err.code !== 'ENOENT') throw err; }
  }
  writeTextFile(file, JSON.stringify(transform(data), null, 2));
}

/** Immutable per-turn transcripts survive autosave replacement and history trimming. */
export function recordTurn({ text, reply, projectId = null, sessionId = null, at = new Date().toISOString() }, { journalDir = JOURNAL_DIR, timeZone, transform = redactValue } = {}) {
  if (typeof text !== 'string' || !text.trim()) return null;
  const id = randomUUID();
  const folder = path.join(journalDir, localClock(new Date(at), timeZone).date);
  fs.mkdirSync(folder, { recursive: true });
  const file = path.join(folder, `${new Date(at).getTime()}-${id}.json`);
  writeTextFile(file, JSON.stringify(transform({ id, sessionId, savedAt: at, projectId, messages: [
    { role: 'user', content: text }, { role: 'assistant', content: String(reply || '') },
  ] })));
  return file;
}
