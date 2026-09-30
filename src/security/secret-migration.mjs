import fs from 'node:fs';
import path from 'node:path';
import { redact, redactValue, detect } from './secret-scrubber.mjs';
import { writeTextFile } from '../../tools/shared/_shared.mjs';

const ARTIFACT_EXTENSIONS = new Set(['.json', '.jsonl', '.log', '.md', '.txt']);
const MIGRATION_VERSION = 1; // Increase only when a new migration is needed.
const MARKER_FILENAME = 'secret-scrubber-migration.json';

/** Only callers' transcript/log/export roots are scanned; symlinks are never followed. */
export function migrateSecrets({ roots, markerFile = null, force = false }) {
  if (!force && markerFile) {
    try { if (JSON.parse(fs.readFileSync(markerFile, 'utf8')).version === MIGRATION_VERSION) return { changedFiles: 0, redactions: 0, skipped: true }; } catch (error) { if (error.code !== 'ENOENT') throw error; }
  }
  const result = { changedFiles: 0, redactions: 0, skipped: false };
  function visit(file) {
    let stat; try { stat = fs.lstatSync(file); } catch (error) { if (error.code === 'ENOENT') return; throw error; }
    if (stat.isSymbolicLink()) return;
    if (stat.isDirectory()) { for (const name of fs.readdirSync(file)) visit(path.join(file, name)); return; }
    if (!stat.isFile() || !ARTIFACT_EXTENSIONS.has(path.extname(file).toLowerCase()) || file === markerFile) return;
    const raw = fs.readFileSync(file, 'utf8');
    let clean;
    if (path.extname(file) === '.json') {
      // Re-serialize JSON to catch escaped PEM blocks and object key context.
      try {
        const data = JSON.parse(raw), next = redactValue(data);
        if (JSON.stringify(next) === JSON.stringify(data)) return;
        clean = JSON.stringify(next, null, 2);
      } catch { clean = redact(raw); } // Preserve damaged transcript syntax; still redact recognizable secrets.
    } else clean = redact(raw);
    if (clean === raw) return;
    writeTextFile(file, clean);
    result.changedFiles++; result.redactions += Math.max(1, detect(raw).length);
  }
  for (const root of new Set(roots.filter(Boolean).map(value => path.resolve(value)))) visit(root);
  if (markerFile) writeTextFile(markerFile, JSON.stringify({ version: MIGRATION_VERSION, ...result, at: new Date().toISOString() }));
  return result;
}
export function migrationMarker(directory) { return path.join(directory, MARKER_FILENAME); }
