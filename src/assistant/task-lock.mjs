import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';

const PRIVATE_MODE = 0o600; // POSIX owner-only files; platform ACLs remain authoritative.
const WRITER_PATTERN = /^(\.writer-(\d+)-([a-f0-9-]+))\.(?:choosing|json)$/; // Each contender owns unique publication paths for its lifetime.
const LEGACY_LOCK = '.write.lock'; // Never reclaim the unsafe compare/unlink protocol while an old writer might exist.
const BUSY = 'Assistant task checkpoint is busy; retry shortly.';

/** A nonblocking Lamport bakery lock. Dead contenders are ignored, never unlinked.
 * Publishing "choosing" before selecting a ticket prevents a new writer from
 * overtaking an observed contender. A collision fails closed instead of waiting
 * in the main process. Every writer removes only its own UUID-named marker.
 */
export function acquireTaskLock(folder, isProcessAlive) {
  if (fs.existsSync(path.join(folder, LEGACY_LOCK))) throw new Error('A legacy assistant checkpoint lock needs review before continuing.');
  const nonce = randomUUID(), base = `.writer-${process.pid}-${nonce}`;
  const marker = path.join(folder, base + '.json'), choosing = path.join(folder, base + '.choosing');
  const readLive = () => [...new Set(fs.readdirSync(folder).map(name => WRITER_PATTERN.exec(name)?.[1]).filter(Boolean))].flatMap(name => {
    const match = WRITER_PATTERN.exec(name + '.json');
    if (name === base || !isProcessAlive(Number(match[2]))) return [];
    if (fs.existsSync(path.join(folder, name + '.choosing'))) return [{ choosing: true, ticket: 0, nonce: match[3] }];
    const file = path.join(folder, name + '.json');
    try {
      const stat = fs.lstatSync(file);
      if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(BUSY);
      let value;
      try { value = JSON.parse(fs.readFileSync(file, 'utf8')); } catch (error) { if (error.code === 'ENOENT') return []; throw new Error(BUSY); }
      if (!Number.isSafeInteger(value.ticket) || value.ticket <= 0) throw new Error(BUSY);
      return [{ choosing: false, ticket: value.ticket, nonce: match[3] }];
    } catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  });
  let fd;
  try {
    fd = fs.openSync(choosing, 'wx', PRIVATE_MODE); fs.closeSync(fd); fd = undefined;
    const ticket = Math.max(0, ...readLive().map(other => other.ticket)) + 1;
    if (!Number.isSafeInteger(ticket)) throw new Error(BUSY);
    // Publish the immutable ticket before removing choosing. No replacement
    // rename is needed while another Windows process may be reading a marker.
    fs.writeFileSync(marker, JSON.stringify({ ticket }), { flag: 'wx', mode: PRIVATE_MODE });
    fs.unlinkSync(choosing);
    if (readLive().some(other => other.choosing || other.ticket < ticket || (other.ticket === ticket && other.nonce < nonce))) throw new Error(BUSY);
    return () => fs.unlinkSync(marker);
  } catch (error) {
    if (fd !== undefined) fs.closeSync(fd);
    try { fs.unlinkSync(choosing); } catch (cleanup) { if (cleanup.code !== 'ENOENT') throw cleanup; }
    try { fs.unlinkSync(marker); } catch (cleanup) { if (cleanup.code !== 'ENOENT') throw cleanup; }
    throw error;
  }
}
