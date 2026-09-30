import { randomUUID } from 'node:crypto';
import { CREDENTIAL_WAIT_MS } from '../../src/integrations/browser-credentials.mjs';

/** Main-process waiters. Public events never contain submitted secrets. */
export class CredentialRequests {
  constructor(emit = () => {}) { this.emit = emit; this.pending = new Map(); }
  request(detail, signal) {
    if (signal?.aborted) return Promise.resolve({ action: 'cancel' });
    const requestId = randomUUID();
    return new Promise(resolve => {
      const finish = result => {
        if (!this.pending.delete(requestId)) return;
        clearTimeout(timer); signal?.removeEventListener('abort', cancel);
        this.emit({ type: 'secure-store-resolved', requestId, threadId: detail.threadId, callId: detail.callId });
        resolve(result);
      };
      const cancel = () => finish({ action: 'cancel' });
      const timer = setTimeout(cancel, CREDENTIAL_WAIT_MS);
      this.pending.set(requestId, { detail, finish });
      signal?.addEventListener('abort', cancel, { once: true });
      this.emit({ type: 'secure-store-request', ...detail, requestId });
    });
  }
  respond({ requestId, threadId, callId, action, username, password, save }) {
    const entry = this.pending.get(requestId);
    if (!entry || entry.detail.threadId !== threadId || entry.detail.callId !== callId || !['submit', 'cancel', 'takeover'].includes(action)) return false;
    if (action === 'submit' && (!String(username || '').trim() || typeof password !== 'string' || !password)) return false;
    entry.finish(action === 'submit' ? { action, username: String(username).trim(), password, save: save === true } : { action });
    return true;
  }
  cancelThread(threadId) { for (const entry of this.pending.values()) if (entry.detail.threadId === threadId) entry.finish({ action: 'cancel' }); }
  cancelAll() { for (const entry of this.pending.values()) entry.finish({ action: 'cancel' }); }
}
