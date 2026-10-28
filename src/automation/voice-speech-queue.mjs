import { VOICE_SPEECH_GAP_MS, VOICE_TASK_LIMIT } from './voice-task-policy.mjs';

const MAX_SPEECH_PENDING = 24; // Clips: completed jobs plus a few interactive receipts, without an unbounded backlog.
const PRIORITY = Object.freeze({ receipt: 3, reply: 2, report: 2, progress: 0 });
const abortError = () => new DOMException('Voice playback interrupted.', 'AbortError');
function abortable(work, signal) {
  if (signal.aborted) return Promise.reject(abortError());
  return new Promise((resolve, reject) => {
    const abort = () => { cleanup(); reject(abortError()); };
    const cleanup = () => signal.removeEventListener('abort', abort);
    signal.addEventListener('abort', abort, { once: true });
    Promise.resolve(work).then(value => { cleanup(); resolve(value); }, error => { cleanup(); reject(error); });
  });
}
const notice = (callback, ...args) => { try { Promise.resolve(callback?.(...args)).catch(() => {}); } catch {} };

/** One output owner for every parallel job. Preparation is disposable; started sentences take turns. */
export class VoiceSpeechQueue {
  constructor({ play, stop = () => {}, gapMs = VOICE_SPEECH_GAP_MS, maxPending = MAX_SPEECH_PENDING, historyLimit = VOICE_TASK_LIMIT, onStart, onFinish, onError } = {}) {
    if (typeof play !== 'function') throw new TypeError('Voice speech needs a player.');
    if (!Number.isSafeInteger(maxPending) || maxPending < 1 || !Number.isSafeInteger(historyLimit) || historyLimit < 1 || !Number.isFinite(gapMs) || gapMs < 0) throw new TypeError('Invalid voice speech bounds.');
    Object.assign(this, { play, stop, gapMs, maxPending, historyLimit, onStart, onFinish, onError });
    this.queue = []; this.active = null; this.closed = false; this.paused = false; this.order = 0; this.waiters = [];
    this.reported = new Set(); // Deduplicate within the same bounded history as durable task receipts.
  }

  discard(entry) { entry.controller.abort(); entry.signal?.removeEventListener('abort', entry.externalAbort); entry.resolve(false); }
  stopOwned() { const entry = this.active; try { Promise.resolve(this.stop()).catch(error => notice(this.onError, error, entry)); } catch (error) { notice(this.onError, error, entry); } }
  drop(test) {
    for (const entry of this.queue.filter(test)) this.discard(entry);
    this.queue = this.queue.filter(entry => !test(entry));
  }
  offer(item) {
    if (this.closed || item.signal?.aborted) return Promise.resolve(false);
    if (!Object.hasOwn(PRIORITY, item.kind) || typeof item.prepare !== 'function') return Promise.reject(new TypeError('Invalid voice speech item.'));
    if (item.kind === 'report' && (this.reported.has(item.jobId) ||
      [this.active, ...this.queue].some(entry => entry?.kind === 'report' && entry.jobId === item.jobId))) return Promise.resolve(false);
    if (item.kind === 'progress') this.drop(entry => entry.kind === 'progress' && entry.jobId === item.jobId);
    if (item.kind === 'report') this.drop(entry => entry.kind === 'progress' && entry.jobId === item.jobId);
    if (this.queue.length >= this.maxPending) this.drop(entry => entry.kind === 'progress');
    if (this.queue.length >= this.maxPending) {
      notice(this.onError, new Error('Too many spoken reports are waiting. Results remain in the conversation.'), item);
      return Promise.resolve(false);
    }
    const result = new Promise(resolve => {
      const entry = { ...item, resolve, controller: new AbortController(), order: this.order++, begun: false, retry: false };
      entry.externalAbort = () => {
        entry.retry = false; entry.controller.abort();
        if (this.active === entry) this.stopOwned();
        else { this.queue = this.queue.filter(item => item !== entry); this.discard(entry); this.settled(); }
      };
      entry.signal?.addEventListener('abort', entry.externalAbort, { once: true });
      this.queue.push(entry);
      if (this.active && !this.active.begun &&
        (PRIORITY[item.kind] > PRIORITY[this.active.kind] || (item.jobId === this.active.jobId && this.active.kind === 'progress'))) {
        this.active.retry = this.active.kind === 'report'; this.active.controller.abort();
      }
      if (entry.signal?.aborted) entry.externalAbort();
    });
    this.pump(); return result;
  }

  pump() {
    if (this.active || this.closed || this.paused || !this.queue.length) { this.settled(); return; }
    this.queue.sort((a, b) => PRIORITY[b.kind] - PRIORITY[a.kind] || a.order - b.order);
    const entry = this.queue.shift(); this.active = entry;
    this.running = (async () => {
      let played = false;
      try {
        const signal = entry.controller.signal;
        const audio = await abortable(Promise.resolve().then(() => signal.aborted ? undefined : entry.prepare(signal)), signal);
        if (!audio || signal.aborted || this.closed || entry.beginPlayback?.() === false) return;
        entry.begun = true; notice(this.onStart, entry);
        // The player must settle on AbortSignal. Do not start another child merely
        // because an abort was requested; wait for this owned player to stop.
        await this.play(audio, { signal });
        played = !signal.aborted;
        if (played && this.gapMs > 0) await abortable(new Promise(resolve => {
          const timer = setTimeout(resolve, this.gapMs);
          signal.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, { once: true });
        }), signal);
      } catch (error) { if (error.name !== 'AbortError') notice(this.onError, error, entry); }
      finally {
        if (entry.begun) notice(this.onFinish, entry);
        if (played && entry.kind === 'report') {
          this.reported.add(entry.jobId);
          while (this.reported.size > this.historyLimit) this.reported.delete(this.reported.values().next().value);
        }
        this.active = null;
        if (entry.retry && !played && !this.closed && !entry.signal?.aborted) {
          entry.controller = new AbortController(); entry.begun = false; entry.retry = false; this.queue.push(entry);
        } else {
          entry.signal?.removeEventListener('abort', entry.externalAbort); entry.resolve(played);
        }
        this.pump();
      }
    })();
  }

  interrupt({ requeueReports = true } = {}) {
    this.paused = true;
    if (this.active) { this.active.retry = requeueReports && this.active.kind === 'report'; this.active.controller.abort(); this.stopOwned(); }
  }
  resume() { if (!this.closed) { this.paused = false; this.pump(); } }
  settled() { if (!this.active && !this.queue.length) for (const resolve of this.waiters.splice(0)) resolve(); }
  drain() { return !this.active && !this.queue.length ? Promise.resolve() : new Promise(resolve => this.waiters.push(resolve)); }
  async close() {
    this.closed = true; this.drop(() => true);
    if (this.active) { this.active.retry = false; this.active.controller.abort(); this.stopOwned(); }
    await this.running; this.settled();
  }
}
