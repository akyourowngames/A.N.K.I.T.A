import { randomUUID } from 'node:crypto';

export class ApprovalRegistry {
  constructor(onRequest = () => {}) {
    this.onRequest = onRequest;
    this.pending = new Map();
  }

  request(threadId, toolName, detail) {
    const requestId = randomUUID();
    return new Promise(resolve => {
      this.pending.set(requestId, { threadId, resolve });
      this.onRequest({ requestId, threadId, toolName, detail });
    });
  }

  respond(requestId, answer) {
    const entry = this.pending.get(requestId);
    if (!entry) return false;
    this.pending.delete(requestId);
    entry.resolve(answer === 'yes' || answer === 'always');
    return true;
  }

  cancelThread(threadId) {
    for (const [id, entry] of this.pending) {
      if (entry.threadId !== threadId) continue;
      this.pending.delete(id);
      entry.resolve(false);
    }
  }

  cancelAll() {
    for (const entry of this.pending.values()) entry.resolve(false);
    this.pending.clear();
  }
}
