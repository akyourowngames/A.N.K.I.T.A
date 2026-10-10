import { performance } from 'node:perf_hooks';

const PROFILE_ENTRY_LIMIT = 256; // Records per process; repeated reloads replace the same component.
const PROFILE_DECIMALS = 1; // Millisecond display precision, not a timing threshold.

export class StartupProfile {
  constructor({ now = () => performance.now(), limit = PROFILE_ENTRY_LIMIT } = {}) {
    this.now = now; this.limit = limit; this.records = new Map();
  }
  finish(kind, name, started, status) {
    const key = `${kind}:${name}`;
    this.records.set(key, { kind, name, durationMs: Math.max(0, this.now() - started), status });
    while (this.records.size > this.limit) this.records.delete(this.records.keys().next().value);
  }
  clear() { this.records.clear(); }
  snapshot() { return [...this.records.values()].map(record => ({ ...record })).sort((a, b) => b.durationMs - a.durationMs); }
  format() {
    const records = this.snapshot();
    return `Startup timings (ms): ${records.length ? records.map(record => `${record.kind} ${record.name} ${record.durationMs.toFixed(PROFILE_DECIMALS)} ms (${record.status}; ${record.kind === 'plugin' ? `/mcp disable ${record.name}` : 'Plugins → Skills → Disable'})`).join(' · ') : 'no components measured yet'}`;
  }
}

export const startupProfile = new StartupProfile();
