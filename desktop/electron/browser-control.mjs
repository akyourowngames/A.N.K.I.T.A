import { randomUUID } from 'node:crypto';
import { CONTROL_POLL_MS, CONTROL_ONLINE_MS, CONTROL_COMMAND_MS, CONTROL_MAX_PENDING, CONTROL_INTERRUPTED, CONTROL_OFFLINE, CONTROL_OPERATIONS, CONTROL_ACCESS_REMOVED, CONTROL_REPAIR_MESSAGE } from '../browser-helper/control-protocol.mjs';

const fail = (status, message) => Object.assign(new Error(message), { status });
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Ephemeral commands sit above durable pairing. Nothing here is replayed after a restart. */
export class BrowserControl {
  constructor({ activeHelper, onChange = () => {}, now = Date.now }) {
    this.activeHelper = activeHelper; this.onChange = onChange; this.now = now;
    this.session = null; this.pending = new Map(); this.waiter = null; this.closed = false;
  }
  status() {
    const helper = this.activeHelper();
    return { paired: Boolean(helper), paused: helper?.paused === true, resumeVersion: helper?.resumeVersion || 0,
      connected: Boolean(!this.closed && helper && !helper.paused && this.session?.helperId === helper.id && this.now() - this.session.seen < CONTROL_ONLINE_MS) };
  }
  connect(helperId, clientId) {
    const helper = this.activeHelper();
    if (this.closed || helper?.id !== helperId) throw Object.assign(fail(403, CONTROL_REPAIR_MESSAGE), { code: CONTROL_ACCESS_REMOVED });
    if (helper.paused) throw fail(423, 'Browser connection is paused. Choose Reconnect to resume.');
    if (!UUID.test(clientId || '')) throw fail(400, 'Invalid browser connection identity');
    if (this.session?.clientId !== clientId || this.session.helperId !== helperId) {
      this.interrupt();
      this.session = { helperId, clientId, sessionId: randomUUID(), seen: this.now() };
    }
    this.session.seen = this.now(); this.onChange();
    return { sessionId: this.session.sessionId, resumeVersion: helper.resumeVersion || 0 };
  }
  admit(helperId, sessionId) {
    if (this.closed || this.activeHelper()?.id !== helperId || this.activeHelper()?.paused || this.session?.helperId !== helperId || this.session?.sessionId !== sessionId) throw fail(409, 'Browser session expired; reconnect with the saved pairing');
    this.session.seen = this.now();
  }
  async next(helperId, sessionId, signal) {
    this.admit(helperId, sessionId);
    if (this.waiter) throw fail(409, 'Only one receiver may use this browser session');
    const take = () => {
      const entry = [...this.pending.values()].find(item => item.sessionId === sessionId && !item.delivered);
      if (!entry) return null;
      entry.delivered = true;
      return { id: entry.id, operation: entry.operation };
    };
    const available = take();
    if (available) return { command: available };
    return new Promise(resolve => {
      const finish = () => {
        clearTimeout(timer); signal?.removeEventListener('abort', finish);
        if (this.waiter === finish) this.waiter = null;
        resolve({ command: signal?.aborted ? null : take() });
      };
      const timer = setTimeout(finish, CONTROL_POLL_MS); timer.unref?.();
      this.waiter = finish; signal?.addEventListener('abort', finish, { once: true });
      if (signal?.aborted) finish();
    });
  }
  execute(operation, { signal } = {}) {
    signal?.throwIfAborted();
    if (!this.status().connected) return Promise.reject(new Error(CONTROL_OFFLINE));
    if (!operation || !CONTROL_OPERATIONS.includes(operation.action) || typeof operation.scope !== 'string' || !operation.scope) return Promise.reject(new Error('Unsupported browser extension operation'));
    if (this.pending.size >= CONTROL_MAX_PENDING) return Promise.reject(new Error('Browser command queue is full'));
    return new Promise((resolve, reject) => {
      const id = randomUUID(), sessionId = this.session.sessionId;
      const settle = (error, result) => {
        if (!this.pending.delete(id)) return;
        clearTimeout(timer); signal?.removeEventListener('abort', cancel);
        error ? reject(error) : resolve(result);
      };
      const cancel = () => settle(Object.assign(new Error(entry.delivered ? CONTROL_INTERRUPTED : 'Browser action cancelled before dispatch'), { dispatched: entry.delivered }));
      const timer = setTimeout(cancel, CONTROL_COMMAND_MS); timer.unref?.();
      const entry = { id, operation, sessionId, delivered: false, settle };
      this.pending.set(id, entry); signal?.addEventListener('abort', cancel, { once: true });
      if (signal?.aborted) cancel(); else this.waiter?.();
    });
  }
  result(helperId, { sessionId, id, result, error }) {
    this.admit(helperId, sessionId);
    const entry = this.pending.get(id);
    if (!entry?.delivered || entry.sessionId !== sessionId) throw fail(409, 'Browser command result is stale or already delivered');
    entry.settle(error ? Object.assign(new Error(String(error.message || error)), { dispatched: error.dispatched !== false }) : null, result);
    return { ok: true };
  }
  claim(helperId, { sessionId, id }) {
    this.admit(helperId, sessionId);
    if (!this.pending.get(id)?.delivered || this.pending.get(id).sessionId !== sessionId) throw fail(409, 'Browser command was cancelled or expired');
    return { ok: true };
  }
  interrupt() {
    for (const entry of [...this.pending.values()]) entry.settle(Object.assign(new Error(entry.delivered ? CONTROL_INTERRUPTED : 'Browser connection interrupted before dispatch'), { dispatched: entry.delivered }));
    this.session = null; this.waiter?.(); this.onChange();
  }
  close() { this.closed = true; this.interrupt(); }
}
