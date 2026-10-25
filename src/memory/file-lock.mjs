import fs from "node:fs";
import path from "node:path";

/** A lock older than this is assumed to belong to a crashed writer. */
export const LOCK_STALE_MS = 600000;

/**
 * Runs `work` while holding `<file>.lock`. Returns undefined when another
 * process owns a live lock, so callers can skip quietly instead of queueing.
 */
export function withFileLock(file, work) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  let fd;
  try {
    try {
      if (Date.now() - fs.statSync(file).mtimeMs > LOCK_STALE_MS) fs.unlinkSync(file);
    } catch {}
    fd = fs.openSync(file, "wx");
  } catch (error) {
    if (error.code === "EEXIST") return undefined;
    throw error;
  }
  try {
    return work();
  } finally {
    fs.closeSync(fd);
    try {
      fs.unlinkSync(file);
    } catch {}
  }
}
