import { TYPING_INTERVAL_MS, PROGRESS_INTERVAL_MS, PROGRESS_LABEL_CHARS } from './contract.mjs';

/** Capability-gated projection: never forward arbitrary tool arguments or deltas. */
export class ChannelProgress {
  constructor(adapter, ref, { heartbeatMs = TYPING_INTERVAL_MS, beatIntervalMs = PROGRESS_INTERVAL_MS, now = Date.now, enabled = true } = {}) {
    Object.assign(this, { adapter, ref, heartbeatMs, beatIntervalMs, now, enabled });
    this.caps = new Set(adapter.manifest.capabilities); this.lastBeat = -Infinity;
    this.closed = false; this.tail = Promise.resolve(); this.typingPending = false;
  }
  async typing() {
    if (this.closed || this.typingPending || !this.caps.has('typing')) return;
    this.typingPending = true;
    try { await this.adapter.typing(this.ref); } catch {}
    finally { this.typingPending = false; }
  }
  async react(state) { if (this.caps.has('react')) { try { await this.adapter.react(this.ref, state); } catch {} } }
  async start() {
    await Promise.all([this.react('received'), this.typing()]);
    if (!this.closed && this.caps.has('typing')) { this.timer = setInterval(() => { void this.typing(); }, this.heartbeatMs); this.timer.unref?.(); }
  }
  beat(event) {
    if (!this.enabled || this.closed || !['tool-call', 'tool-result'].includes(event?.type) || this.now() - this.lastBeat < this.beatIntervalMs) return;
    this.lastBeat = this.now();
    const name = String(event.name || 'tool').replace(/[^\w .-]/g, '').slice(0, PROGRESS_LABEL_CHARS);
    const text = event.type === 'tool-call' ? `Using ${name}…` : `${name} ${event.isError ? 'needs attention' : 'finished'}.`;
    this.tail = this.tail.then(async () => { if (!this.closed) await this.adapter.send({ ...this.ref, parts: [text], intent: 'progress', replyTo: this.ref.messageId }); }).catch(() => {});
  }
  async stop() { this.closed = true; clearInterval(this.timer); await this.tail; }
}
