import { randomUUID } from 'node:crypto';

export class ApprovalRegistry {
  constructor(onRequest = () => {}, onResolved = () => {}) {
    this.onRequest = onRequest;
    this.onResolved = onResolved;
    this.pending = new Map();
  }

  request(threadId, toolName, detail, metadata = {}) {
    const requestId = randomUUID();
    return new Promise(resolve => {
      // toolName/detail are stored on the entry (not just the emitted event)
      // so a late subscriber such as the island can list what is still pending.
      this.pending.set(requestId, { ...metadata, threadId, toolName, detail, resolve });
      metadata.onRegistered?.(requestId);
      const { onRegistered, ...publicMetadata } = metadata;
      this.onRequest({ requestId, threadId, toolName, detail, ...publicMetadata });
    });
  }

  respond(requestId, answer) {
    const entry = this.pending.get(requestId);
    if (!entry) return false;
    this.pending.delete(requestId);
    entry.resolve(answer === 'yes' || answer === 'always');
    this.onResolved(requestId);
    return true;
  }

  /** Serializable snapshot of pending tool approvals (resolve fns omitted). */
  list() {
    return [...this.pending.entries()]
      .filter(([, entry]) => !entry.routineId)
      .map(([requestId, entry]) => ({
        type: 'approval-request',
        requestId,
        threadId: entry.threadId,
        toolName: entry.toolName,
        detail: entry.detail,
        routineId: entry.routineId,
        runId: entry.runId,
        expiresAt: entry.expiresAt,
        subagentId: entry.subagentId,
        subagentType: entry.subagentType,
        subagentDescription: entry.subagentDescription,
        voiceTaskId: entry.voiceTaskId,
      }));
  }

  cancelThread(threadId) {
    for (const [id, entry] of this.pending) {
      if (entry.threadId !== threadId || entry.routineId || entry.voiceTaskId) continue;
      this.respond(id, 'no');
    }
  }

  cancelAll() {
    for (const id of [...this.pending.keys()]) this.respond(id, 'no');
  }
}
