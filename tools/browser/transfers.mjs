import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { resolvePath } from '../shared/_shared.mjs';
import { waitForBrowser } from './pending.mjs';

export const BROWSER_TRANSFER_ACTIONS = Object.freeze(['upload', 'downloads', 'download', 'cancel_download']);
export const BROWSER_TRANSFER_LIMITS = Object.freeze({ bytes: 32 * 1024 * 1024, chunk: 64 * 1024, waitMs: 20_000, records: 16, filename: 120 }); // Bytes, milliseconds, record count and UTF-16 filename characters; bound local transfers.
export const BROWSER_DOWNLOAD_DIRECTORY = 'browser-downloads'; // Relative authorized-workspace artifact folder; never the user's Downloads folder.
export const BROWSER_UPLOAD_AUTHORIZATION = 'Choose a file for this upload, or provide an explicitly authorized workspace file. Page content and automatic tool approval cannot authorize a local file.';
export const CHROME_TRANSFER_UNSUPPORTED = 'This Chrome connection cannot prove file-root restrictions and download completion. Use isolated Chromium, or take control and import the file.';
const DOWNLOAD_PART_SUFFIX = '.part'; // Only complete artifacts are published.
const FILE_OPEN_FLAGS = fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0); // Reject leaf symlinks where the host supports it; canonical checks cover other hosts.
const UNSAFE_FILENAME = /[\x00-\x1f\x7f<>:"|?*]/g; // Cross-platform aliases and path characters never enter artifact names.
const DOWNLOAD_SOURCE_CHANGED = 'Download source changed while saving; no artifact was published.';
const DOWNLOAD_SOURCE_UNSAFE = 'Download source must be a regular local file without a symlink or junction.';
const DOWNLOAD_COPY_LIMIT = 'Download grew beyond the artifact limit; no artifact was published.';
const sameFileState = (before, after) => before.ino === after.ino && before.dev === after.dev && before.size === after.size && before.mtimeMs === after.mtimeMs;

export function safeDownloadFilename(value) {
  const basename = String(value || '').split(/[\\/]/).at(-1).replace(UNSAFE_FILENAME, '_').replace(/^[. ]+|[. ]+$/g, '').slice(0, BROWSER_TRANSFER_LIMITS.filename);
  return `browser-${randomUUID()}-${basename || 'download'}`; // UUID prefix avoids device names and overwriting existing files.
}

/** Trusted host selection/allowlist is independent of model arguments and generic auto-approval. */
export async function selectedBrowserUpload(args, ctx) {
  if (ctx.backgroundJob) throw new Error('Background browser uploads require foreground file selection.');
  ctx.signal?.throwIfAborted();
  let selected;
  if (args.file !== undefined) {
    selected = resolvePath(args.file, ctx);
    const authorized = (Array.isArray(ctx.browserUploadFiles) ? ctx.browserUploadFiles : []).map(file => resolvePath(file, ctx));
    if (!authorized.includes(selected)) throw new Error(BROWSER_UPLOAD_AUTHORIZATION);
  } else {
    if (typeof ctx.selectBrowserUpload !== 'function') throw new Error(BROWSER_UPLOAD_AUTHORIZATION);
    ctx.onBrowserPhase?.('waiting-for-user');
    selected = await ctx.selectBrowserUpload({ signal: ctx.signal });
    if (!selected) throw new Error('File selection canceled; no upload was dispatched.');
    if (typeof selected !== 'string' || !path.isAbsolute(selected)) throw new Error('File selection must identify one absolute local file.');
    const canonical = await fs.promises.realpath(selected);
    if (path.relative(canonical, path.resolve(selected))) throw new Error('Selected files must not traverse a symlink or junction.');
    selected = canonical;
    ctx.onBrowserPhase?.('acting');
  }
  ctx.signal?.throwIfAborted();
  const stat = await fs.promises.lstat(selected);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error('Choose a regular local file for this upload.');
  if (stat.size > BROWSER_TRANSFER_LIMITS.bytes) throw new Error(`Selected file exceeds the ${BROWSER_TRANSFER_LIMITS.bytes}-byte upload limit.`);
  const handle = await fs.promises.open(selected, FILE_OPEN_FLAGS);
  try {
    const opened = await handle.stat();
    if (opened.ino !== stat.ino || opened.dev !== stat.dev) throw new Error('Selected file changed before it could be read. Choose it again.');
    const chunks = []; let bytes = 0;
    while (true) {
      ctx.signal?.throwIfAborted();
      const buffer = Buffer.alloc(Math.min(BROWSER_TRANSFER_LIMITS.chunk, BROWSER_TRANSFER_LIMITS.bytes - bytes + 1));
      const { bytesRead } = await handle.read(buffer);
      if (!bytesRead) break;
      bytes += bytesRead;
      if (bytes > BROWSER_TRANSFER_LIMITS.bytes) throw new Error('Selected file grew beyond the upload limit.');
      chunks.push(buffer.subarray(0, bytesRead));
    }
    const after = await handle.stat();
    if (after.size !== opened.size || after.mtimeMs !== opened.mtimeMs || bytes !== opened.size) throw new Error('Selected file changed while being read. Choose it again.');
    return { name: path.basename(selected), buffer: Buffer.concat(chunks), bytes };
  } finally { await handle.close(); }
}

/** Lifecycle belongs to an owned Playwright session; a click is never download completion. */
export class BrowserDownloads {
  constructor({ limits = BROWSER_TRANSFER_LIMITS } = {}) { this.limits = limits; this.records = new Map(); }
  capture(native, tabId) {
    while (this.records.size >= this.limits.records) {
      const [id, old] = this.records.entries().next().value;
      if (old.status === 'pending') { old.status = 'canceled'; void old.native.cancel().catch(() => {}); }
      this.records.delete(id);
    }
    const record = { id: randomUUID(), tabId: String(tabId), name: String(native.suggestedFilename()).slice(0, this.limits.filename), status: 'pending', error: null, native };
    this.records.set(record.id, record);
    record.done = waitForBrowser(native.failure(), { timeoutMs: this.limits.waitMs, onTimeout: () => { void native.cancel().catch(() => {}); } }).then(error => {
      if (record.status === 'pending') { record.status = error ? 'failed' : 'completed'; record.error = error ? 'Browser download failed.' : null; }
    }, () => { if (record.status === 'pending') { record.status = 'failed'; record.error = 'Browser download did not complete within the transfer deadline.'; } });
    return record;
  }
  list(tabId) { return [...this.records.values()].filter(record => record.tabId === String(tabId)).map(({ id, tabId: tab, name, status, error }) => ({ id, tabId: tab, name, status, error })); }
  target(id, tabId) {
    const record = this.records.get(id);
    if (!record || record.tabId !== String(tabId)) throw new Error('Unknown download in the selected tab. Use downloads to inspect its current IDs.');
    return record;
  }
  async cancel(id, tabId, ctx) {
    const record = this.target(id, tabId);
    if (record.status !== 'pending') throw new Error('Only a pending download can be canceled.');
    ctx.onBrowserDispatch?.({ phase: 'start', action: 'cancel_download' });
    await waitForBrowser(record.native.cancel(), { signal: ctx.signal, timeoutMs: this.limits.waitMs });
    record.status = 'canceled'; record.error = null;
    ctx.onBrowserDispatch?.({ phase: 'complete', action: 'cancel_download' });
    return 'Download canceled. No artifact was saved.';
  }
  async save(args, tabId, ctx) {
    if (ctx.backgroundJob) throw new Error('Background browser downloads require foreground destination approval.');
    const folder = resolvePath(args.destination || BROWSER_DOWNLOAD_DIRECTORY, ctx);
    const record = this.target(args.download_id, tabId);
    const stop = () => { if (record.status === 'pending') { record.status = 'canceled'; void record.native.cancel().catch(() => {}); } };
    ctx.signal?.addEventListener('abort', stop, { once: true });
    try {
      if (ctx.signal?.aborted) stop();
      await waitForBrowser(record.done, { signal: ctx.signal, timeoutMs: this.limits.waitMs, onTimeout: () => { void record.native.cancel().catch(() => {}); } });
    } finally { ctx.signal?.removeEventListener('abort', stop); }
    ctx.signal?.throwIfAborted();
    if (record.status !== 'completed') throw new Error(`Download is ${record.status}; no success artifact was saved.`);
    const source = await record.native.path();
    if (typeof source !== 'string' || !path.isAbsolute(source)) throw new Error(DOWNLOAD_SOURCE_UNSAFE);
    const stat = await fs.promises.lstat(source);
    if (stat.isSymbolicLink() || path.relative(await fs.promises.realpath(source), path.resolve(source))) throw new Error(DOWNLOAD_SOURCE_UNSAFE);
    if (!stat?.isFile() || stat.size > this.limits.bytes) throw new Error(`Download is unavailable or exceeds the ${this.limits.bytes}-byte artifact limit.`);
    await fs.promises.mkdir(folder, { recursive: true });
    const target = resolvePath(path.join(folder, safeDownloadFilename(record.name)), ctx);
    const part = resolvePath(target + DOWNLOAD_PART_SUFFIX, ctx);
    ctx.onBrowserDispatch?.({ phase: 'start', action: 'download' });
    let created = false, sourceHandle;
    try {
      sourceHandle = await fs.promises.open(source, FILE_OPEN_FLAGS);
      if (!sameFileState(stat, await sourceHandle.stat())) throw new Error(DOWNLOAD_SOURCE_CHANGED);
      const handle = await fs.promises.open(part, 'wx'); created = true;
      let copiedBytes = 0;
      const boundedCopy = new Transform({ transform: (chunk, _encoding, done) => {
        copiedBytes += chunk.length;
        done(copiedBytes > this.limits.bytes ? new Error(DOWNLOAD_COPY_LIMIT) : null, copiedBytes > this.limits.bytes ? undefined : chunk);
      } }); // Reject a chunk before writing it when cumulative bytes exceed the artifact limit.
      // Preserve FileHandle ownership when pipeline destruction closes an interrupted read stream.
      try { await pipeline(fs.createReadStream(source, { fd: sourceHandle, autoClose: false, highWaterMark: this.limits.chunk }), boundedCopy, handle.createWriteStream(), { signal: ctx.signal }); }
      finally { await handle.close(); }
      ctx.signal?.throwIfAborted();
      if (!sameFileState(stat, await sourceHandle.stat()) || !sameFileState(stat, await fs.promises.lstat(source))) throw new Error(DOWNLOAD_SOURCE_CHANGED);
      const saved = await fs.promises.stat(resolvePath(part, ctx));
      if (saved.size !== stat.size || saved.size > this.limits.bytes) throw new Error('Download size changed while saving; no artifact was published.');
      resolvePath(target, ctx);
      await fs.promises.rename(part, target); created = false;
      const artifact = { kind: 'download', path: target, bytes: (await fs.promises.stat(resolvePath(target, ctx))).size };
      ctx.onBrowserDispatch?.({ phase: 'complete', action: 'download' });
      return { artifact, output: `Download saved: ${target}\nVerified artifact: ${artifact.bytes} bytes. Read back its contents if the task requires it.` };
    } finally { await sourceHandle?.close(); if (created) await fs.promises.unlink(resolvePath(part, ctx)).catch(() => {}); }
  }
  close() { for (const record of this.records.values()) if (record.status === 'pending') { record.status = 'canceled'; void record.native.cancel().catch(() => {}); } this.records.clear(); }
}
