import fs from "node:fs";
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
]);

/** Depth-first file walk that skips noise directories. */
export function* walkFiles(root, { maxFiles = 20000, skip = SKIP_DIRS } = {}) {
  let seen = 0;
  const stack = [root];
  while (stack.length) {
    const dir = stack.pop();
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!skip.has(entry.name)) stack.push(full);
      } else if (entry.isFile()) {
        yield full;
        if (++seen >= maxFiles) return;
      }
    }
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
