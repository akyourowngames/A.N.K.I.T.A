import fs from "node:fs";
import path from "node:path";
import { createHash, randomUUID } from "node:crypto";

// Backup location (dir name): kept inside the workspace so undo works
// without config and never writes outside the workspace boundary.
export const BACKUP_DIR_NAME = ".ankita_backups";
// Directory-name characters (hex): one hashed directory per original path keeps
// "foo" and "foo.txt" backups separate and bounds the name for deep paths.
const BACKUP_KEY_CHARS = 32;
// Per-file backup cap (count): bounds disk use while keeping recent undo steps.
export const MAX_BACKUPS_PER_FILE = 20;
// Per-file backup cap (bytes): files larger than this are not copied (preview still shows them).
export const MAX_BACKUP_BYTES = 5_000_000;
// Timestamp format: filesystem-safe, sortable (YYYYMMDD-HHMMSS-mmm).
function stamp(now = Date.now()) {
  const d = new Date(now);
  const pad = (n, w = 2) => String(n).padStart(w, "0");
  return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}-${pad(d.getMilliseconds(), 3)}`;
}

function workspaceRoot(ctx = {}) {
  // Canonicalize the root the same way file paths are canonicalized: on Windows
  // an 8.3 short-name workspace (C:\Users\RUNNER~1\...) would otherwise never
  // match the realpath of its files, and every backup would fail the boundary.
  return canonicalPath(path.resolve(ctx.workspacePath || ctx.cwd || process.cwd()));
}

// Resolve a deleted file's parent so directory casing stays stable across backup and restore.
function canonicalPath(p) {
  const resolved = path.resolve(p);
  try {
    return fs.realpathSync.native(resolved);
  } catch {
    try {
      return path.join(fs.realpathSync.native(path.dirname(resolved)), path.basename(resolved));
    } catch {
      return resolved;
    }
  }
}

export function backupRoot(ctx = {}) {
  return path.join(workspaceRoot(ctx), BACKUP_DIR_NAME);
}

function safeRelative(root, p) {
  const rel = path.relative(root, canonicalPath(p));
  if (!rel || rel.startsWith("..") || path.isAbsolute(rel)) throw new Error("Path is outside the workspace boundary.");
  return rel;
}

// Store each original path in its own hashed directory: a shared filename prefix
// must never let "foo" list or prune the backups of "foo.txt".
function backupDir(originalPath, ctx = {}) {
  const rel = safeRelative(workspaceRoot(ctx), originalPath);
  const key = createHash("sha256").update(rel).digest("hex").slice(0, BACKUP_KEY_CHARS);
  return path.join(backupRoot(ctx), key);
}

export function listBackups(originalPath, ctx = {}) {
  const dir = backupDir(originalPath, ctx);
  let entries;
  try {
    entries = fs.readdirSync(dir, { withFileTypes: true }).filter((e) => e.isFile() || e.isDirectory());
  } catch {
    return [];
  }
  return entries
    .map((e) => e.name)
    .sort()
    .map((n) => path.join(dir, n));
}

function prune(originalPath, ctx) {
  const all = listBackups(originalPath, ctx);
  while (all.length > MAX_BACKUPS_PER_FILE) {
    const oldest = all.shift();
    try {
      fs.rmSync(oldest, { recursive: true, force: true });
    } catch {}
  }
}

/** Copy a file or directory to the backup store before a destructive write. Returns backup path or null. */
export function backupPath(originalPath, ctx = {}) {
  let stat;
  try {
    stat = fs.lstatSync(originalPath);
  } catch {
    return null;
  }
  if (stat.isSymbolicLink()) return null;
  if (stat.isFile() && stat.size > MAX_BACKUP_BYTES) return null;
  const dir = backupDir(originalPath, ctx);
  try {
    fs.mkdirSync(dir, { recursive: true });
  } catch {}
  const name = `${stamp()}.${randomUUID().slice(0, 8)}.bak`;
  const dest = path.join(dir, name);
  try {
    if (stat.isDirectory()) fs.cpSync(originalPath, dest, { recursive: true });
    else fs.copyFileSync(originalPath, dest);
  } catch {
    return null;
  }
  prune(originalPath, ctx);
  // Return the newest backup for this path (the one just created, modulo clock skew).
  const all = listBackups(originalPath, ctx);
  return all.length ? all[all.length - 1] : dest;
}

/** Restore the most recent (or indexed) backup over the original path. */
export function restoreBackup(originalPath, ctx = {}, index = -1) {
  const all = listBackups(originalPath, ctx);
  if (!all.length) throw new Error(`No backups for ${originalPath}`);
  const pick = index < 0 ? all.length + index : index;
  const src = all[pick];
  if (!src) throw new Error(`Backup index out of range: ${index}`);
  const stat = fs.lstatSync(src);
  try {
    fs.rmSync(originalPath, { recursive: true, force: true });
  } catch {}
  fs.mkdirSync(path.dirname(path.resolve(originalPath)), { recursive: true });
  if (stat.isDirectory()) fs.cpSync(src, path.resolve(originalPath), { recursive: true });
  else fs.copyFileSync(src, path.resolve(originalPath));
  return src;
}
