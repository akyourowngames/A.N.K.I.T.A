import { BoundedOutput } from './_shared.mjs';
export const clamp = (value, fallback, min, max) => Number.isFinite(Number(value)) ? Math.min(max, Math.max(min, Math.floor(Number(value)))) : fallback;

/** Byte cursors include bytes no longer retained by the bounded stream. */
export class JobOutput extends BoundedOutput {
  constructor(maxBytes = 65536) { super(maxBytes); this.recent = Buffer.alloc(0); }
  append(chunk) {
    const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk));
    super.append(bytes);
    this.recent = Buffer.concat([this.recent, bytes]).subarray(-this.maxBytes);
  }
  read(since = 0, maxBytes = 16384) {
    const wanted = clamp(since, 0, 0, this.total);
    const start = this.total - this.recent.length;
    let offset = Math.max(start, wanted);
    while (offset < this.total && (this.recent[offset - start] & 0xc0) === 0x80) offset++;
    let end = Math.min(this.total, offset + maxBytes);
    while (end < this.total && end > offset && (this.recent[end - start] & 0xc0) === 0x80) end--;
    if (end === this.total && end > offset) {
      let lead = end - 1;
      while (lead > offset && (this.recent[lead - start] & 0xc0) === 0x80) lead--;
      const byte = this.recent[lead - start];
      const width = byte >= 0xf0 ? 4 : byte >= 0xe0 ? 3 : byte >= 0xc0 ? 2 : 1;
      if (lead + width > end) end = lead;
    }
    return { output: this.recent.subarray(offset - start, end - start).toString('utf8'),
      offset, next_offset: end, dropped: Math.max(0, start - wanted), more: end < this.total };
  }
}
export function jobsOf(ctx) {
  const state = ctx.state || (ctx.state = {});
  return state.jobs || (state.jobs = new Map());
}
export function jobInfo(job) {
  return { id: job.id, state: job.done ? (job.error ? 'failed' : 'done') : job.stopped ? 'stopping' : 'running',
    pid: job.child?.pid ?? null, command: job.command, cwd: job.cwd, exit_code: job.code,
    signal: job.signal || null, started_at: new Date(job.startedAt).toISOString(),
    ended_at: job.endedAt ? new Date(job.endedAt).toISOString() : null,
    stdin_open: !job.done && !!job.child?.stdin?.writable && !job.child.stdin.writableEnded,
    ...(job.error ? { error: job.error } : {}), ...(job.timedOut ? { timed_out: true } : {}) };
}
export function jobSnapshot(job, args = {}) {
  let since = args.since_offset ?? job.readOffset ?? 0;
  if (args.tail !== undefined) {
    const lines = clamp(args.tail, 20, 1, 1000);
    const text = job.out.recent.toString('utf8');
    const tail = text.replace(/\n$/, '').split('\n').slice(-lines).join('\n') + (text.endsWith('\n') ? '\n' : '');
    since = job.out.total - Buffer.byteLength(tail);
  }
  const read = job.out.read(since, clamp(args.max_bytes, 16384, 256, 65536));
  job.readOffset = Math.max(job.readOffset || 0, read.next_offset);
  return { ...jobInfo(job), ...read };
}
export function notifyJob(ctx, event, job) {
  try { ctx.state?.onJobEvent?.({ event, ...jobInfo(job) }); } catch {}
}
export function waitForExit(job, timeoutMs = 5000, signal) {
  if (!job || job.done) return Promise.resolve(true);
  if (signal?.aborted) return Promise.resolve(false);
  return new Promise(resolve => {
    const finish = () => {
      clearTimeout(timer);
      job.child?.off('close', finish);
      job.child?.off('error', finish);
      signal?.removeEventListener('abort', finish);
      resolve(job.done);
    };
    const timer = setTimeout(finish, Math.max(0, timeoutMs));
    job.child?.once('close', finish);
    job.child?.once('error', finish);
    signal?.addEventListener('abort', finish, { once: true });
  });
}
