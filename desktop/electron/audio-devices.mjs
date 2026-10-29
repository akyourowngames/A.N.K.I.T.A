import { Worker } from 'node:worker_threads';
import { AUDIO_DEVICE_OPS as OPS, AUDIO_OUTPUT_CHANGED } from '../shared/audio-devices.mjs';

const DEVICE_CACHE_MS = 5000; // Milliseconds: share scans across the app/island; Refresh explicitly invalidates.
const WORKER_CLOSED = 'Audio device worker is closed.';

/** One lazy background owner for blocking OS discovery/routing. No speech or credentials cross this wire. */
export class DesktopAudioDevices {
  constructor({ createWorker = () => new Worker(new URL('./audio-device-worker.mjs', import.meta.url), { execArgv: [] }), cacheMs = DEVICE_CACHE_MS } = {}) {
    Object.assign(this, { createWorker, cacheMs });
    this.pending = new Map(); this.sequence = 0; this.worker = null; this.closed = false; this.cache = null; this.scan = null; this.generation = 0;
    this.routes = new Set(); this.listeners = new Set();
  }
  call(op, payload) {
    if (this.closed || (this.stopping && ![OPS.restore, OPS.close, OPS.unwatch].includes(op))) return Promise.reject(new Error(WORKER_CLOSED));
    if (!this.worker) {
      const worker = this.worker = this.createWorker();
      const fail = error => {
        if (this.worker !== worker) return;
        this.worker = null; this.invalidate();
        for (const listener of this.listeners) listener(); // Lost notifications immediately force protected playback.
        for (const entry of this.pending.values()) entry.reject(error);
        this.pending.clear();
      };
      worker.on('message', ({ id, value, error, event }) => {
        if (event === AUDIO_OUTPUT_CHANGED) { this.invalidate(); for (const listener of this.listeners) listener(); return; }
        const entry = this.pending.get(id); if (!entry) return;
        this.pending.delete(id); error ? entry.reject(new Error(error)) : entry.resolve(value);
        if (!this.pending.size) worker.unref();
      });
      worker.on('error', fail);
      worker.on('exit', () => fail(new Error('Audio device worker stopped. Try again.')));
    }
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject }); this.worker.ref();
      try { this.worker.postMessage({ id, op, payload }); }
      catch (error) { this.pending.delete(id); if (!this.pending.size) this.worker.unref(); reject(error); }
    });
  }
  invalidate() { this.cache = null; this.generation++; }
  async inspect() {
    if (this.closed || this.stopping) throw new Error(WORKER_CLOSED);
    if (this.cache && Date.now() - this.cache.at < this.cacheMs) return structuredClone(this.cache.value);
    if (!this.scan) {
      const generation = this.generation;
      this.scan = this.call(OPS.inspect).then(value => {
        if (generation === this.generation) this.cache = { value, at: Date.now() };
        return value;
      }).finally(() => { this.scan = null; });
    }
    return structuredClone(await this.scan);
  }
  async route(payload) {
    const value = await this.call(OPS.route, payload);
    if (value) this.invalidate();
    let restoring;
    const route = value && { device: value.device, restore: () => restoring ||= this.call(OPS.restore, { token: value.token, receipt: value.receipt })
      .then(result => { this.routes.delete(route); return result; })
      .catch(error => { restoring = null; throw error; }).finally(() => this.invalidate()) };
    if (route) this.routes.add(route);
    return route;
  }
  async watch(listener) {
    this.listeners.add(listener);
    let stopped = false;
    try {
      const isolated = await this.call(OPS.watch);
      return { isolated, stop: async () => {
        if (stopped) return; stopped = true; this.listeners.delete(listener);
        if (this.worker) await this.call(OPS.unwatch);
      } };
    } catch (error) { this.listeners.delete(listener); throw error; }
  }
  async close() {
    if (this.closing) return this.closing;
    this.stopping = true;
    this.closing = (async () => {
      for (const route of [...this.routes].reverse()) await route.restore();
      if (this.worker) await this.call(OPS.close);
    })().finally(async () => {
      this.closed = true;
      this.listeners.clear();
      const worker = this.worker;
      await worker?.terminate();
    });
    return this.closing;
  }
}
