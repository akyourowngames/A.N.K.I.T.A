import fs from 'node:fs';
import path from 'node:path';

const MAX_RESOURCE_WAITERS = 256; // Blocked tool calls: bound memory across a small pool of voice workers.
const MAX_RESOURCES_PER_CALL = 128; // Paths/interaction keys: reject oversized opaque batches before execution.
const MAX_RESOURCE_ALIASES = 64; // Link hops: fail closed on pathological alias chains instead of recursing forever.
const CYCLE_MESSAGE = 'Voice jobs need resources held by each other. Stop this job before retrying; completed actions were not undone.';
const abortError = () => new DOMException('Voice job cancelled while waiting for a shared resource.', 'AbortError');
const normalizedKey = key => key.replace(/\\/g, '/').replace(/\/+$/u, '') || '/';
const inside = (parent, child) => parent === child || child.startsWith(parent.endsWith('/') ? parent : `${parent}/`);

/** Resolve the closest existing ancestor too, so a new file through a junction has one identity. */
export function canonicalVoicePath(requested, cwd = process.cwd(), aliases = new Set()) {
  const absolute = path.resolve(cwd, requested);
  if (aliases.has(absolute) || aliases.size >= MAX_RESOURCE_ALIASES) throw new Error('Cannot coordinate a cyclic or excessively linked voice file path.');
  const seen = new Set(aliases).add(absolute);
  let ancestor = absolute;
  const missing = [];
  while (true) {
    try {
      const stat = fs.lstatSync(ancestor);
      if (stat.isSymbolicLink()) {
        const target = path.resolve(path.dirname(ancestor), fs.readlinkSync(ancestor));
        return canonicalVoicePath(path.join(target, ...missing), cwd, seen);
      }
      break;
    } catch (error) { if (error.code !== 'ENOENT') throw error; }
    const parent = path.dirname(ancestor);
    if (parent === ancestor) break;
    missing.unshift(path.basename(ancestor)); ancestor = parent;
  }
  const canonical = path.join(fs.realpathSync.native(ancestor), ...missing);
  return normalizedKey(process.platform === 'win32' ? canonical.toLowerCase() : canonical);
}

function resourcesOf(resources) {
  if (!Array.isArray(resources) || resources.length > MAX_RESOURCES_PER_CALL) throw new Error('Invalid or oversized voice resource request.');
  return resources.map(resource => {
    if (!['path', 'shared'].includes(resource?.kind) || !['read', 'write'].includes(resource?.mode) || typeof resource.key !== 'string' || !resource.key) throw new Error('Invalid voice resource.');
    return { kind: resource.kind, key: normalizedKey(resource.key), mode: resource.mode };
  });
}

function conflict(left, right) {
  if (left.kind !== right.kind || (left.mode === 'read' && right.mode === 'read')) return false;
  return left.kind === 'path' ? inside(left.key, right.key) || inside(right.key, left.key) : left.key === right.key;
}

/** Job-scoped leases: release only after the worker and its owned side effects settle. */
export class VoiceResourceBroker {
  constructor({ maxWaiters = MAX_RESOURCE_WAITERS } = {}) { this.maxWaiters = maxWaiters; this.held = new Map(); this.waiters = []; }
  get waitingCount() { return this.waiters.length; }
  owns(jobId) { return Boolean(this.held.get(jobId)?.length); }

  blockers(request, earlier = []) {
    const blockers = new Set();
    for (const [owner, resources] of this.held) if (owner !== request.jobId && resources.some(a => request.resources.some(b => conflict(a, b)))) blockers.add(owner);
    // Overlapping newcomers cannot continually overtake an already waiting writer.
    for (const waiter of earlier) if (waiter.jobId !== request.jobId && waiter.resources.some(a => request.resources.some(b => conflict(a, b)))) blockers.add(waiter.jobId);
    return blockers;
  }

  cycle(request) {
    const graph = new Map();
    for (const [index, waiter] of [...this.waiters, request].entries()) {
      const edges = graph.get(waiter.jobId) || new Set();
      for (const owner of this.blockers(waiter, this.waiters.slice(0, index))) edges.add(owner);
      graph.set(waiter.jobId, edges);
    }
    const visit = (owner, seen) => {
      if (seen.has(owner)) return false;
      const next = new Set(seen).add(owner);
      for (const target of graph.get(owner) || []) if (target === request.jobId || visit(target, next)) return true;
      return false;
    };
    return visit(request.jobId, new Set());
  }

  grant(request) {
    const held = this.held.get(request.jobId) || [];
    for (const resource of request.resources) {
      const existing = held.find(item => item.kind === resource.kind && item.key === resource.key);
      if (!existing) held.push(resource);
      else if (resource.mode === 'write') existing.mode = 'write';
    }
    this.held.set(request.jobId, held);
    request.signal?.removeEventListener('abort', request.abort);
    try { request.onWait?.(null); } catch { /* Observation cannot change ownership. */ }
    request.resolve();
  }

  async acquire(jobId, resources, { signal, onWait } = {}) {
    if (signal?.aborted) throw abortError();
    if (typeof jobId !== 'string' || !jobId) throw new Error('A voice resource needs a job identity.');
    const request = { jobId, resources: resourcesOf(resources), signal, onWait };
    if (!this.blockers(request, this.waiters).size) { this.grant({ ...request, resolve: () => {} }); return; }
    if (this.waiters.length >= this.maxWaiters) throw new Error('Too many voice actions are waiting. Stop a job before starting more.');
    if (this.cycle(request)) throw Object.assign(new Error(CYCLE_MESSAGE), { code: 'VOICE_RESOURCE_CYCLE' });
    return new Promise((resolve, reject) => {
      Object.assign(request, { resolve, reject, abort: () => {
        const index = this.waiters.indexOf(request);
        if (index >= 0) this.waiters.splice(index, 1);
        signal?.removeEventListener('abort', request.abort); reject(abortError()); this.pump();
      } });
      this.waiters.push(request); signal?.addEventListener('abort', request.abort, { once: true });
      try { onWait?.({ blockers: [...this.blockers(request, this.waiters.slice(0, -1))], resources: request.resources }); } catch {}
      if (signal?.aborted) request.abort();
    });
  }

  pump() {
    for (let index = 0; index < this.waiters.length;) {
      const request = this.waiters[index];
      if (this.blockers(request, this.waiters.slice(0, index)).size) { index++; continue; }
      this.waiters.splice(index, 1); this.grant(request);
    }
  }

  release(jobId) {
    this.held.delete(jobId);
    const removed = this.waiters.filter(request => request.jobId === jobId);
    this.waiters = this.waiters.filter(request => request.jobId !== jobId);
    for (const request of removed) { request.signal?.removeEventListener('abort', request.abort); request.reject(abortError()); }
    this.pump();
  }

  /** Hand finished-turn leases to its still-running command without an unlock gap. */
  transfer(jobId, holderId, { exclude = [] } = {}) {
    const held = this.held.get(jobId) || [];
    const keep = resource => exclude.some(item => item.kind === resource.kind && item.key === resource.key);
    const moving = held.filter(resource => !keep(resource));
    this.held.set(jobId, held.filter(keep));
    this.held.set(holderId, [...(this.held.get(holderId) || []), ...moving]);
  }
}
