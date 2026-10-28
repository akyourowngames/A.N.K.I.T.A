import { VOICE_SPEECH_GAP_MS, VOICE_TASK_LIMIT } from './voice-task-policy.mjs';

const MAX_SPEECH_PENDING = 24; // Clips: completed jobs plus a few interactive receipts, without an unbounded backlog.
const PRIORITY = Object.freeze({ receipt: 4, reply: 3, report: 2, progress: 0 });
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
    this.reports = new Map(); this.turn = 0; this.gatedTurn = null; this.interruption = null;
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
    if (item.kind === 'report' && (this.reports.has(item.jobId) || this.reported.has(item.jobId) ||
      [this.active, ...this.queue].some(entry => entry?.kind === 'report' && entry.jobId === item.jobId))) return Promise.resolve(false);
    if (item.kind === 'progress') this.drop(entry => entry.kind === 'progress' && entry.jobId === item.jobId);
    if (item.kind === 'report') this.drop(entry => entry.kind === 'progress' && entry.jobId === item.jobId);
    if (this.queue.length >= this.maxPending) this.drop(entry => entry.kind === 'progress');
    if (this.queue.length >= this.maxPending) {
      notice(this.onError, new Error('Too many spoken reports are waiting. Results remain in the conversation.'), item);
      return Promise.resolve(false);
    }
    const result = new Promise(resolve => {
      const parts = (item.parts?.length ? item.parts : [{ text: item.text || item.line?.text || '', prepare: item.prepare }]).map(part => ({ ...part }));
      const entry = { ...item, parts, text: parts.map(part => part.text || '').join(' '), cursor: 0, state: 'queued',
        resolve, controller: new AbortController(), order: this.order++, begun: false, retry: false };
      if (entry.kind === 'report') this.reports.set(entry.jobId, entry);
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

  priority(entry) { return entry.kind === 'report' && (entry.selected || entry.turn === this.turn) ? PRIORITY.reply : PRIORITY[entry.kind]; }
  allowed(entry) { return this.gatedTurn == null || entry.kind === 'receipt' || entry.turn === this.gatedTurn; }
  preparePart(part, signal) {
    if (part.audio) return Promise.resolve(part.audio);
    if (part.pending?.signal === signal) return part.pending.promise;
    const pending = { signal };
    pending.promise = abortable(Promise.resolve().then(() => signal.aborted ? undefined : part.prepare(signal)), signal)
      .then(audio => { if (!signal.aborted && !this.closed) part.audio = audio; return audio; })
      .finally(() => { if (part.pending === pending) delete part.pending; });
    part.pending = pending; return pending.promise;
  }

  pump() {
    if (this.active || this.closed || this.paused || !this.queue.some(entry => this.allowed(entry))) { this.settled(); return; }
    this.queue.sort((a, b) => this.priority(b) - this.priority(a) || a.order - b.order);
    const index = this.queue.findIndex(entry => this.allowed(entry));
    const [entry] = this.queue.splice(index, 1); this.active = entry;
    this.running = (async () => {
      let played = false;
      try {
        const signal = entry.controller.signal;
        for (; entry.cursor < entry.parts.length;) {
          const part = entry.parts[entry.cursor];
          const audio = await this.preparePart(part, signal);
          if (!audio || signal.aborted || this.closed || entry.beginPlayback?.() === false) return;
          part.audio = audio; entry.begun = true; entry.state = 'speaking';
          if (part.text) entry.line = { text: part.text };
          notice(this.onStart, entry);
          // At most one following sentence: hide its TTS latency under current playback.
          const nextPart = entry.parts[entry.cursor + 1];
          if (nextPart) void this.preparePart(nextPart, signal).catch(() => {});
          // Wait for this owned player to settle, even after requesting stop.
          await this.play(audio, { signal });
          notice(this.onFinish, entry); entry.begun = false;
          if (signal.aborted) break;
          entry.cursor++;
          if (this.gapMs > 0) await abortable(new Promise(resolve => {
            const timer = setTimeout(resolve, this.gapMs);
            signal.addEventListener('abort', () => { clearTimeout(timer); resolve(); }, { once: true });
          }), signal);
        }
        played = entry.cursor === entry.parts.length;
      } catch (error) { if (error.name !== 'AbortError') notice(this.onError, error, entry); }
      finally {
        if (entry.begun) notice(this.onFinish, entry);
        // Aborting the gap after the final sentence does not undo its delivery.
        played ||= entry.cursor === entry.parts.length;
        if (played && entry.kind === 'report') this.reported.add(entry.jobId);
        this.active = null;
        if (entry.retry && !played && !this.closed && !entry.signal?.aborted) {
          entry.controller = new AbortController(); entry.begun = false; entry.retry = false; entry.state = 'queued'; this.queue.push(entry);
        } else {
          entry.state = played ? 'delivered' : entry.park && !this.closed && !entry.signal?.aborted ? 'suspended' : 'unavailable';
          entry.signal?.removeEventListener('abort', entry.externalAbort); entry.resolve(played);
        }
        this.trimReports(); this.pump();
      }
    })();
  }

  trimReports() {
    for (const [id, entry] of this.reports) {
      if (this.reports.size <= this.historyLimit) break;
      if (this.active === entry || this.queue.includes(entry) || (this.interruption?.entry === entry && !this.interruption.accepted)) continue;
      this.reports.delete(id); this.reported.delete(id);
      for (const part of entry.parts) part.audio = null;
      if (this.interruption?.entry === entry) this.interruption.entry = null;
    }
    while (this.reported.size > this.historyLimit) this.reported.delete(this.reported.values().next().value);
  }

  reportState() {
    return [...this.reports.values()].map(entry => ({ id: entry.jobId, label: entry.label || '', text: entry.text,
      state: entry.state, completedText: entry.parts.slice(0, entry.cursor).map(part => part.text || '').join(' '),
      nextSentence: entry.parts[entry.cursor]?.text || '' }));
  }

  interrupt({ requeueReports = false } = {}) {
    this.paused = true;
    if (!requeueReports) {
      this.gatedTurn = ++this.turn;
      this.interruption = { turn: this.turn, entry: this.active?.kind === 'report' ? this.active : null, stopped: this.running, accepted: false };
    }
    if (this.active) {
      this.active.retry = requeueReports && this.active.kind === 'report';
      this.active.park = !requeueReports && this.active.kind === 'report';
      this.active.controller.abort(); this.stopOwned();
    }
    return this.turn;
  }
  acceptTurn(turn) {
    if (this.closed || turn !== this.turn) return false;
    if (this.interruption?.turn === turn) this.interruption.accepted = true;
    this.gatedTurn = turn; return true;
  }
  releaseTurn(turn) { if (turn === this.turn && this.gatedTurn === turn) { this.gatedTurn = null; this.pump(); } }
  finishTurn(turn) { this.releaseTurn(turn); }
  async falseInterruption(turn) {
    const interruption = this.interruption;
    if (this.closed || turn !== this.turn || !interruption || interruption.accepted) return false;
    await interruption.stopped;
    if (this.closed || turn !== this.turn || interruption.accepted) return false;
    const entry = interruption.entry;
    if (entry?.state === 'suspended') this.enqueueReport(entry);
    this.paused = false; this.releaseTurn(turn); this.pump(); return true;
  }
  enqueueReport(entry, repeat = false) {
    if (repeat) entry.cursor = 0;
    if (entry.cursor >= entry.parts.length || entry.signal?.aborted) return false;
    this.queue = this.queue.filter(item => item !== entry);
    entry.controller = new AbortController(); entry.begun = false; entry.retry = false; entry.park = false;
    entry.selected = true; entry.state = 'queued'; entry.resolve = () => {};
    entry.signal?.addEventListener('abort', entry.externalAbort, { once: true });
    this.queue.push(entry); return true;
  }
  async controlReport(action, { id, turn } = {}) {
    if (this.closed) throw new Error('This voice session has ended.');
    if (turn !== this.turn) throw new Error('This speech control belongs to an older interruption.');
    await this.interruption?.stopped;
    if (this.closed) throw new Error('This voice session has ended.');
    if (turn !== this.turn) throw new Error('This speech control belongs to an older interruption.');
    const interrupted = this.interruption?.entry;
    let entry = id ? this.reports.get(id) : interrupted || [...this.reports.values()].reverse().find(item => item.state === 'suspended');
    if (id && !entry) throw new Error('Spoken report not found or expired in this session.');
    if (action === 'next') {
      if (interrupted?.state === 'suspended') interrupted.state = 'dismissed';
      entry = [...this.queue].sort((a, b) => a.order - b.order).find(item => item.kind === 'report');
      if (entry) entry.selected = true;
    } else if (action === 'dismiss') {
      if (entry) { this.drop(item => item === entry); entry.state = 'dismissed'; }
    } else if (action === 'resume' || action === 'repeat') {
      entry ||= [...this.reports.values()].at(-1);
      if (!entry) throw new Error('No spoken report is available in this session.');
      if (this.active?.kind === 'report') {
        this.active.park = true; this.active.controller.abort(); this.stopOwned();
        await this.running;
        if (this.closed || turn !== this.turn) throw new Error('This speech control belongs to an older interruption.');
      }
      this.enqueueReport(entry, action === 'repeat');
    } else throw new Error('Unknown spoken report action.');
    this.releaseTurn(turn); this.pump();
    return { action, id: entry?.jobId || null, available: Boolean(entry), reports: this.reportState() };
  }
  resume() { if (!this.closed) { this.paused = false; this.pump(); } }
  settled() { if (!this.active && !this.queue.length) for (const resolve of this.waiters.splice(0)) resolve(); }
  drain() { return !this.active && !this.queue.length ? Promise.resolve() : new Promise(resolve => this.waiters.push(resolve)); }
  async close() {
    this.closed = true; this.drop(() => true);
    if (this.active) { this.active.retry = false; this.active.park = false; this.active.controller.abort(); this.stopOwned(); }
    await this.running; this.reports.clear(); this.reported.clear(); this.interruption = null; this.settled();
  }
}
