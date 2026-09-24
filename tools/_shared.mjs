import fs from "node:fs";
import { execFileSync } from 'node:child_process';
import path from "node:path";

/** Keeps UTF-8 output bounded without losing the start or final diagnostics. */
export function capOutput(value, maxBytes = 65536) {
  const text = String(value ?? "");
  const bytes = Buffer.from(text);
  const limit = Math.max(0, Math.floor(maxBytes));
  if (bytes.length <= limit) return text;
  const marker = `\n[output truncated: ${bytes.length} bytes total]\n`;
  if (limit <= Buffer.byteLength(marker)) return bytes.subarray(0, limit).toString('utf8').replace(/\uFFFD$/u, '');
  const room = limit - Buffer.byteLength(marker);
  const head = bytes.subarray(0, Math.ceil(room / 2)).toString('utf8').replace(/\uFFFD$/u, '');
  const tail = bytes.subarray(bytes.length - Math.floor(room / 2)).toString('utf8').replace(/^\uFFFD+/u, '');
  return head + marker + tail;
}

/** Bounded while collecting, not only after the child process exits. */
export class BoundedOutput {
  constructor(maxBytes = 65536) {
    this.maxBytes = maxBytes;
    this.head = Buffer.alloc(0);
    this.tail = Buffer.alloc(0);
    this.total = 0;
  }
  append(chunk) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk));
    this.total += bytes.length;
    const half = Math.floor(this.maxBytes / 2);
    const take = Math.max(0, half - this.head.length);
    this.head = Buffer.concat([this.head, bytes.subarray(0, take)]);
    this.tail = Buffer.concat([this.tail, bytes.subarray(take)]).subarray(-half);
  }
  toString() {
    if (this.total <= this.maxBytes) return Buffer.concat([this.head, this.tail]).toString('utf8');
    const marker = `\n[output truncated: ${this.total} bytes total]\n`;
    const half = Math.max(0, Math.floor((this.maxBytes - Buffer.byteLength(marker)) / 2));
    return this.head.subarray(0, half).toString('utf8').replace(/\uFFFD$/u, '') + marker +
      this.tail.subarray(-half).toString('utf8').replace(/^\uFFFD+/u, '');
  }
}

export function resolvePath(p, ctx = {}) {
  if (!p) return ctx.cwd || process.cwd();
  return path.isAbsolute(p) ? path.normalize(p) : path.resolve(ctx.cwd || process.cwd(), p);
}

export function numbered(content, offset, limit) {
  const lines = String(content).split(/\r?\n/);
  const total = lines.length;
  const start = Math.max(1, offset || 1);
  const end = Math.min(total, start + (limit || 400) - 1);
  const body = lines
    .slice(start - 1, end)
    .map((l, i) => `${start + i}: ${l}`)
    .join("\n");
  const note = end < total ? `\n[showing lines ${start}-${end} of ${total}]` : "";
  return body + note;
}

export function assertReadable(p) {
  if (!fs.existsSync(p)) throw new Error(`no such file: ${p}`);
  const stat = fs.statSync(p);
  if (stat.isDirectory()) throw new Error(`${p} is a directory (use list_dir)`);
  return stat;
}

export function isBinary(buf) {
  const n = Math.min(buf.length, 8000);
  for (let i = 0; i < n; i++) if (buf[i] === 0) return true;
  return false;
}

/**
 * Reads a text file, normalising to \n in memory and remembering the file's
 * own line ending so writes do not convert a CRLF file to LF (or vice versa).
 */
export function readTextFile(p) {
  const raw = fs.readFileSync(p, "utf8");
  const eol = raw.includes("\r\n") ? "\r\n" : "\n";
  return {
    raw,
    text: raw.replace(/\r\n/g, "\n"),
    eol,
    trailingNewline: /\n$/.test(raw),
  };
}

/**
 * Writes via a temp file in the same directory followed by a rename, so a
 * crash mid-write cannot leave a half-written file behind.
 */
export function writeTextFile(p, text, eol = "\n") {
  const out = eol === "\r\n" ? text.replace(/\r\n/g, "\n").replace(/\n/g, "\r\n") : text;
  const tmp = path.join(path.dirname(p), `.${path.basename(p)}.${process.pid}.tmp`);
  try {
    fs.writeFileSync(tmp, out);
    fs.renameSync(tmp, p);
  } catch (err) {
    try {
      fs.unlinkSync(tmp);
    } catch {}
    fs.writeFileSync(p, out);
  }
}

/** Re-applies the original trailing-newline convention after an edit. */
export function restoreTrailing(text, trailingNewline) {
  if (trailingNewline && !/\n$/.test(text)) return text + "\n";
  if (!trailingNewline && /\n$/.test(text)) return text.replace(/\n+$/, "");
  return text;
}

export const SKIP_DIRS = new Set([
  "node_modules",
  ".git",
  ".hg",
  ".svn",
  "dist",
  "build",
  ".next",
  ".cache",
  "__pycache__",
  ".venv",
  "venv",
  "coverage",
  ".turbo",
  "target",
]);

/** Depth-first file walk that skips noise directories. */
export function* walkFiles(root, { maxFiles = 10000, maxEntries = 30000, maxDepth = 20, maxMs = 3000, skip = SKIP_DIRS, onIncomplete = () => {} } = {}) {
  let seen = 0;
  let entriesSeen = 0;
  const deadline = Date.now() + maxMs;
  const stack = [[root, 0]];
  while (stack.length) {
    if (Date.now() > deadline || entriesSeen >= maxEntries) { onIncomplete('time or entry budget'); return; }
    const [dir, depth] = stack.pop();
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (++entriesSeen > maxEntries || Date.now() > deadline) { onIncomplete('time or entry budget'); return; }
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!skip.has(entry.name)) {
          if (depth < maxDepth) stack.push([full, depth + 1]);
          else onIncomplete('depth budget');
        }
      } else if (entry.isFile()) {
        yield full;
        if (++seen >= maxFiles) { onIncomplete('file budget'); return; }
      }
    }
  }
}

/** Git gives exact project ignore semantics; outside repositories use bounded traversal. */
export function* walkProjectFiles(root, options = {}) {
  const { maxFiles = 10000, maxDepth = 20, maxMs = 3000, onIncomplete = () => {} } = options;
  let ancestor = path.resolve(root);
  let gitProject = false;
  while (true) {
    if (fs.existsSync(path.join(ancestor, '.git'))) { gitProject = true; break; }
    const parent = path.dirname(ancestor);
    if (parent === ancestor) break;
    ancestor = parent;
  }
  if (!gitProject) { yield* walkFiles(root, options); return; }
  let raw;
  try {
    raw = execFileSync('git', ['-c', 'core.fsmonitor=false', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], {
      cwd: root, encoding: 'utf8', timeout: maxMs, maxBuffer: 4_000_000,
      windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'],
      env: { ...process.env, GIT_OPTIONAL_LOCKS: '0' },
    });
  } catch (error) {
    if (error.status === 128 || error.code === 'ENOENT') { yield* walkFiles(root, options); return; }
    onIncomplete('git inventory budget');
    return;
  }
  let count = 0;
  const deadline = Date.now() + maxMs;
  for (const relative of raw.split('\0')) {
    if (!relative) continue;
    if (Date.now() > deadline || count >= maxFiles) { onIncomplete('time or file budget'); return; }
    const parts = relative.split(/[/\\]/);
    if (parts.some(part => SKIP_DIRS.has(part))) continue;
    if (parts.length > maxDepth + 1) { onIncomplete('depth budget'); continue; }
    const file = path.join(root, relative);
    try { if (fs.statSync(file).isFile()) { count++; yield file; } } catch {}
  }
}

/** Converts a glob (`*`, `?`, `**`) into a RegExp anchored to the whole path. */
export function globToRegExp(pattern) {
  const escaped = String(pattern)
    .replace(/\*\*\//g, "\u0000")
    .replace(/\*\*/g, "\u0001")
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*/g, "[^/\\\\]*")
    .replace(/\?/g, "[^/\\\\]")
    .replace(/\u0000/g, "(?:.*[/\\\\])?")
    .replace(/\u0001/g, ".*");
  return new RegExp("^" + escaped + "$", "i");
}

export function relativeTo(root, file) {
  return path.relative(root, file).split(path.sep).join("/");
}

/**
 * A path the model can hand straight back to another tool: relative to the
 * working directory when the file lives inside it, otherwise absolute.
 *
 * Returning paths relative to a *search root* (e.g. "Pictures/a.jpg" when
 * globbing C:\Users\me from a different cwd) produces paths that no other
 * tool can resolve, which is how a working search still ends in failure.
 */
export function displayPath(cwd, file) {
  const abs = path.resolve(file);
  const base = path.resolve(cwd || process.cwd());
  const rel = path.relative(base, abs);
  if (!rel || rel.startsWith("..") || path.isAbsolute(rel)) return abs.split(path.sep).join("/");
  return rel.split(path.sep).join("/");
}
