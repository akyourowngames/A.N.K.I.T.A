const PROTOCOL_TIMEOUT_MS = 15_000; // Bounded CDP acknowledgements; approvals have their own deadline.
const TARGET_FILTER = [{ type: 'page', exclude: false }, { type: 'iframe', exclude: false }, { exclude: true }];

/** A guard on this job's own Chromium socket; never attaches to user Chrome. */
export class JobNetworkGuard {
  constructor(endpoint, authorize, onFailure = () => {}) {
    this.endpoint = endpoint; this.authorize = authorize;
    this.onFailure = onFailure;
    this.pending = new Map(); this.attaching = new Set(); this.targets = new Set(); this.sequence = 0;
  }
  async start() {
    if (typeof WebSocket !== 'function') throw new Error('This desktop runtime cannot guard background browser requests');
    this.socket = new WebSocket(this.endpoint);
    this.socket.addEventListener('close', () => { if (!this.closing) this.onFailure(new Error('Job browser network guard disconnected')); });
    this.socket.addEventListener('message', event => this.message(JSON.parse(event.data)));
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Job browser guard connection timed out')), PROTOCOL_TIMEOUT_MS);
      this.socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
      this.socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error('Job browser guard connection failed')); }, { once: true });
    });
    await this.send(null, 'Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: true, flatten: true, filter: TARGET_FILTER });
    await Promise.all([...this.attaching]);
  }
  attach(event) {
    if (this.targets.has(event.targetInfo.targetId)) return;
    this.targets.add(event.targetInfo.targetId);
    const ready = (async () => {
      await this.send(event.sessionId, 'Fetch.enable', { patterns: [{ urlPattern: '*', requestStage: 'Request' }] });
      await this.send(event.sessionId, 'Target.setAutoAttach', { autoAttach: true, waitForDebuggerOnStart: true, flatten: true, filter: TARGET_FILTER });
      await this.send(event.sessionId, 'Runtime.runIfWaitingForDebugger');
    })();
    this.attaching.add(ready);
    ready.catch(error => this.onFailure(error)).finally(() => this.attaching.delete(ready));
  }
  message(message) {
    if (message.id) {
      const entry = this.pending.get(message.id); if (!entry) return;
      this.pending.delete(message.id); clearTimeout(entry.timer);
      if (message.error) entry.reject(new Error(message.error.message)); else entry.resolve(message.result);
    } else if (message.method === 'Target.attachedToTarget') this.attach(message.params);
    else if (message.method === 'Fetch.requestPaused') {
      const event = message.params;
      void (async () => {
        try { await this.authorize(event); await this.send(message.sessionId, 'Fetch.continueRequest', { requestId: event.requestId }); }
        catch { await this.send(message.sessionId, 'Fetch.failRequest', { requestId: event.requestId, errorReason: 'BlockedByClient' }).catch(() => {}); }
      })().catch(() => {});
    }
  }
  send(sessionId, method, params = {}) {
    const id = ++this.sequence;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('Job browser guard command timed out')); }, PROTOCOL_TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timer });
      try { this.socket.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) })); }
      catch (error) { clearTimeout(timer); this.pending.delete(id); reject(error); }
    });
  }
  async close() {
    this.closing = true;
    for (const entry of this.pending.values()) { clearTimeout(entry.timer); entry.reject(new Error('Job browser closed')); }
    this.pending.clear(); this.socket?.close();
  }
}
