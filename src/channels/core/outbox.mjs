import fs from 'node:fs';
import path from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { writePrivateJson } from './store.mjs';
import { DELIVERY_LEDGER_VERSION, CHANNEL_RETRY_LIMIT, RETRY_BASE_MS, RETRY_MAX_MS, CHANNEL_PRIVATE_MODE, abortableDelay, sessionKey } from './contract.mjs';

const LEDGER_RECORD_LIMIT = 10_000; // Receipts: fail closed at capacity instead of forgetting dedupe evidence.
const DELIVERY_KINDS = new Set(['rate_limited', 'transient', 'permanent', 'unknown']);
const EMPTY_LEDGER = () => ({ version: DELIVERY_LEDGER_VERSION, records: {}, deadTargets: {}, inbound: {} });
const payloadHash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');

export class DeliveryError extends Error {
  constructor(kind, message, { retryAfterMs = null, deadTarget = false } = {}) {
    super(message); this.name = 'DeliveryError'; this.kind = DELIVERY_KINDS.has(kind) ? kind : 'unknown';
    this.retryAfterMs = retryAfterMs; this.deadTarget = deadTarget;
  }
}

/** Short atomic transactions; network operations never run under the file lock. */
class DeliveryLedger {
  constructor(file) { this.file = file; this.memory = EMPTY_LEDGER(); }
  read() {
    if (!this.file) return structuredClone(this.memory);
    try {
      const value = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      if (value.version !== DELIVERY_LEDGER_VERSION || !value.records || !value.deadTargets || !value.inbound || [value.records, value.deadTargets, value.inbound].some(part => Array.isArray(part) || typeof part !== 'object')) throw new Error('Invalid ledger structure');
      return value;
    } catch (error) {
      if (error.code === 'ENOENT') return EMPTY_LEDGER();
      throw new DeliveryError('permanent', 'Delivery ledger is corrupt or unreadable; preserve and repair it before sending');
    }
  }
  change(fn) {
    if (!this.file) { const value = this.read(), result = fn(value); this.memory = value; return result; }
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const lock = `${this.file}.lock`; let fd;
    try { fd = fs.openSync(lock, 'wx', CHANNEL_PRIVATE_MODE); }
    catch (error) {
      if (error.code === 'EEXIST') throw new DeliveryError('transient', 'Delivery ledger is busy; retry after checking the other host');
      throw error;
    }
    try {
      const value = this.read(), result = fn(value);
      writePrivateJson(this.file, value);
      return result;
    } finally { fs.closeSync(fd); fs.unlinkSync(lock); }
  }
}

export class ChannelOutbox {
  constructor({ file = null, retryLimit = CHANNEL_RETRY_LIMIT, delay = abortableDelay } = {}) {
    this.ledger = new DeliveryLedger(file); this.retryLimit = retryLimit; this.delay = delay; this.chains = new Map();
  }
  inspect() { return this.ledger.read(); }
  revive(channel, chatId = null) {
    this.ledger.change(value => { for (const key of Object.keys(value.deadTargets)) if (chatId == null ? key.startsWith(`${channel}:`) : key === sessionKey({ channel, chatId })) delete value.deadTargets[key]; });
  }
  claimInbound(ref) {
    const key = JSON.stringify([ref.channel, String(ref.chatId), String(ref.messageId)]);
    return this.ledger.change(value => {
      if (value.inbound[key]) return false;
      if (Object.keys(value.inbound).length >= LEDGER_RECORD_LIMIT) throw new DeliveryError('permanent', 'Inbound ledger is full; archive its receipts before accepting new work');
      value.inbound[key] = { state: 'received', at: new Date().toISOString() };
      return true;
    });
  }
  finishInbound(ref, state = 'done') {
    const key = JSON.stringify([ref.channel, String(ref.chatId), String(ref.messageId)]);
    this.ledger.change(value => { if (value.inbound[key]) value.inbound[key].state = state; });
  }
  deliver(envelope, adapter, { signal } = {}) {
    const key = sessionKey(envelope), previous = this.chains.get(key) || Promise.resolve();
    const next = previous.catch(() => {}).then(() => this.sendParts(envelope, adapter, signal)).finally(() => { if (this.chains.get(key) === next) this.chains.delete(key); });
    this.chains.set(key, next);
    return next;
  }
  async sendParts(envelope, adapter, signal) {
    const target = sessionKey(envelope), messageId = envelope.messageId ?? envelope.replyTo;
    if (messageId == null) throw new DeliveryError('permanent', 'A stable inbound message ID is required for delivery dedupe');
    const items = [...(envelope.parts || []).map(text => ({ type: 'text', text })), ...(envelope.files || []).map(file => ({ type: 'file', file }))];
    const accepted = [];
    for (let index = 0; index < items.length; index++) {
      signal?.throwIfAborted();
      const item = items[index], key = JSON.stringify([envelope.channel, String(envelope.chatId), String(messageId), envelope.intent || 'reply', index]);
      const hash = payloadHash({ item, threadId: envelope.threadId ?? null, replyTo: envelope.replyTo ?? null });
      let sent = false;
      for (let attempt = 0; attempt < this.retryLimit; attempt++) {
        signal?.throwIfAborted();
        const claimId = randomUUID();
        const existing = this.ledger.change(value => {
          if (value.deadTargets[target]) throw new DeliveryError('permanent', 'Target is paused; re-verify the connection before sending again');
          const record = value.records[key];
          if (record?.hash && record.hash !== hash) throw new DeliveryError('permanent', 'A delivery key cannot be reused for a different payload');
          if (record?.state === 'sent') return record;
          if (record?.state === 'inflight' || record?.state === 'unknown') throw new DeliveryError('unknown', 'An earlier send has an unknown outcome; check the conversation before retrying');
          if (!record && Object.keys(value.records).length >= LEDGER_RECORD_LIMIT) throw new DeliveryError('permanent', 'Delivery ledger is full; archive receipts before sending');
          value.records[key] = { state: 'inflight', hash, claimId, at: new Date().toISOString() };
          return null;
        });
        if (existing) { accepted.push(existing.receipt); sent = true; break; }
        try {
          const ref = { ...envelope, parts: item.type === 'text' ? [item.text] : [], files: [] };
          const receipt = item.type === 'file'
            ? await adapter.upload(ref, item.file, { signal })
            : await adapter.send(ref, { signal });
          this.ledger.change(value => {
            if (value.records[key]?.claimId !== claimId) throw new DeliveryError('unknown', 'Delivery claim changed before receipt could be recorded');
            value.records[key] = { state: 'sent', hash, receipt: receipt || { messageId: null, parts: [] }, at: new Date().toISOString() };
          });
          accepted.push(receipt); sent = true; break;
        } catch (cause) {
          const error = cause instanceof DeliveryError ? cause : new DeliveryError('unknown', 'The send outcome is unknown; check the conversation before retrying');
          this.ledger.change(value => {
            if (value.records[key]?.claimId === claimId) value.records[key] = { state: error.kind === 'unknown' ? 'unknown' : 'rejected', hash, kind: error.kind, at: new Date().toISOString() };
            if (error.deadTarget) value.deadTargets[target] = { at: new Date().toISOString() };
          });
          if (!['rate_limited', 'transient'].includes(error.kind) || attempt + 1 >= this.retryLimit) throw error;
          const retryMs = error.retryAfterMs ?? Math.min(RETRY_MAX_MS, RETRY_BASE_MS * (2 ** attempt));
          await this.delay(Math.max(0, retryMs), signal);
        }
      }
      if (!sent) throw new DeliveryError('permanent', 'Delivery retry budget exhausted');
    }
    return { messageId: accepted.at(-1)?.messageId || null, parts: accepted.flatMap(receipt => receipt?.parts || []) };
  }
}
