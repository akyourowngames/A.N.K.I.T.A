import { CONTROL_ROUTES, CONTROL_RETRY_MS, CONTROL_RETRY_MAX_MS, CONTROL_ACCESS_REMOVED, CONTROL_REPAIR_MESSAGE } from './control-protocol.mjs';

/** Reconnects transport sessions, never browser commands. Pairing lives in extension-private storage. */
export class BrowserConnection {
  constructor({ load, save, post, execute, onResume = async () => {}, schedule = (callback, ms) => { const timer = setTimeout(callback, ms); return () => clearTimeout(timer); } }) {
    Object.assign(this, { load, save, post, execute, schedule, onResume });
    this.running = null; this.controller = null; this.cancelRetry = null;
    this.state = { connected: false, paired: false, paused: false }; this.delay = CONTROL_RETRY_MS;
  }
  status() { return { ...this.state }; }
  async wake() {
    if (this.running) return;
    this.cancelRetry?.(); this.cancelRetry = null;
    const controller = new AbortController(); this.controller = controller;
    this.running = this.run(controller).catch(error => {
      this.state.connected = false;
      if (!controller.signal.aborted) {
        if (error.code === CONTROL_ACCESS_REMOVED) { this.state.needsPairing = true; this.state.notice = CONTROL_REPAIR_MESSAGE; return; }
        if (error.status === 423) this.state.paused = true;
        this.state.notice = 'Desktop unavailable. Reconnecting automatically.';
        this.cancelRetry = this.schedule(() => { this.cancelRetry = null; void this.wake(); }, this.delay);
        this.delay = Math.min(this.delay * 2, CONTROL_RETRY_MAX_MS);
      }
    }).finally(() => { if (this.controller === controller) { this.running = null; this.controller = null; } });
    // The long-running receiver remains private; waking does not wait for a task or the desktop.
    await Promise.resolve();
  }
  async run(controller) {
    let session = await this.load(); const signal = controller.signal;
    signal.throwIfAborted();
    this.state = { connected: false, paired: Boolean(session), paused: Boolean(session?.paused) };
    if (!session?.control) return;
    if (session.paused) {
      const remote = await this.post(session, CONTROL_ROUTES.status, { helperId: session.helperId }, signal);
      if (!(remote.resumeVersion > (session.resumeVersion || 0))) return;
      session = { ...session, paused: false, resumeVersion: remote.resumeVersion }; await this.save(session); await this.onResume();
    }
    const { sessionId, resumeVersion } = await this.post(session, CONTROL_ROUTES.connect, { helperId: session.helperId, clientId: crypto.randomUUID() }, signal);
    if (resumeVersion > (session.resumeVersion || 0)) { session = { ...session, resumeVersion }; await this.save(session); await this.onResume(); }
    signal.throwIfAborted();
    this.state = { connected: true, paired: true, paused: false }; this.delay = CONTROL_RETRY_MS;
    const auth = { helperId: session.helperId, sessionId };
    while (!signal.aborted) {
      const { command } = await this.post(session, CONTROL_ROUTES.next, auth, signal);
      signal.throwIfAborted();
      if (!command) continue;
      let result, error;
      try { result = await this.execute(command.operation, signal, () => this.post(session, CONTROL_ROUTES.claim, { ...auth, id: command.id }, signal)); }
      catch (caught) { error = { message: caught.message, dispatched: caught.dispatched !== false }; }
      signal.throwIfAborted();
      // Never retry a result POST: a lost receipt must not cause the action to be dispatched twice.
      await this.post(session, CONTROL_ROUTES.result, { ...auth, id: command.id, result, error }, signal);
    }
  }
  stop() { this.cancelRetry?.(); this.cancelRetry = null; this.controller?.abort(); this.state.connected = false; }
  async pause() { this.stop(); await this.running; const session = await this.load(); if (session) await this.save({ ...session, paused: true }); this.state.paused = true; }
  async resume() { this.stop(); await this.running; const session = await this.load(); if (session) await this.save({ ...session, paused: false }); this.delay = CONTROL_RETRY_MS; await this.wake(); }
}
