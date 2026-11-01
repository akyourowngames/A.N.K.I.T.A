import { SOCKET_OPEN_TIMEOUT_MS, RETRY_BASE_MS, RETRY_MAX_MS, abortableDelay } from './contract.mjs';

const SOCKET_OPEN = 1; // WebSocket readyState defined by the browser/Node standard.
export const SOCKET_RECONNECT_CODE = 4000; // Application close: Discord permits resuming after this code.
const SOCKET_NORMAL_CLOSE = 1000; // Graceful user disconnect, never used for a resumable heartbeat failure.

/** Shared native-socket lifetime. Protocols own packets, heartbeats and resume data. */
export class SocketChannel {
  constructor({ WebSocketImpl = globalThis.WebSocket, delay = abortableDelay, openTimeoutMs = SOCKET_OPEN_TIMEOUT_MS, retryBaseMs = RETRY_BASE_MS } = {}) {
    Object.assign(this, { WebSocketImpl, delay, openTimeoutMs, retryBaseMs });
  }
  start(ctx) {
    this.ctx = ctx; this.settings = ctx.settings; this.stopping = false; this.readySettled = false;
    this.controller = new AbortController(); this.inboundTail = Promise.resolve();
    this.ready = new Promise((resolve, reject) => { this.resolveReady = resolve; this.rejectReady = reject; });
    const abort = () => { this.controller.abort(ctx.signal.reason); this.ws?.close(SOCKET_NORMAL_CLOSE); };
    ctx.signal.addEventListener('abort', abort, { once: true });
    if (ctx.signal.aborted) abort();
    this.lifetime = (async () => {
      try {
        if (typeof this.WebSocketImpl !== 'function') throw new Error(`${this.manifest.label} needs a runtime with native WebSocket support`);
        await this.prepare?.(); let attempts = 0;
        while (!this.controller.signal.aborted) {
          try {
            await this.connect(await this.connectionUrl());
            attempts = 0;
          } catch (error) {
            if (this.controller.signal.aborted) break;
            if (!this.readySettled || error.fatal) throw error;
            this.ctx.status?.({ error: `${this.manifest.label} disconnected; reconnecting` });
          }
          if (!this.controller.signal.aborted) await this.delay(Math.min(RETRY_MAX_MS, this.retryBaseMs * (2 ** attempts++)), this.controller.signal);
        }
      } catch (error) {
        if (!this.readySettled) { this.readySettled = true; this.rejectReady(error); }
        if (!this.controller.signal.aborted) throw error;
      } finally {
        ctx.signal.removeEventListener('abort', abort); this.cleanupConnection?.();
        if (!this.readySettled) { this.readySettled = true; this.rejectReady(new Error(`${this.manifest.label} stopped`)); }
      }
    })();
    return this.lifetime;
  }
  markReady(account) {
    if (this.controller.signal.aborted) return;
    if (!this.readySettled) { this.readySettled = true; this.resolveReady({ account }); }
    this.ctx.status?.({ account, error: null, running: true });
  }
  connect(url) {
    this.controller.signal.throwIfAborted();
    return new Promise((resolve, reject) => {
      let ws;
      try { ws = new this.WebSocketImpl(url); } catch { reject(new Error(`${this.manifest.label} socket could not open`)); return; }
      this.ws = ws; let done = false;
      const finish = error => {
        if (done) return; done = true; clearTimeout(timer);
        this.controller.signal.removeEventListener('abort', abort);
        ws.removeEventListener('message', message); ws.removeEventListener('close', close); ws.removeEventListener('error', failed);
        this.cleanupConnection?.(); if (this.ws === ws) this.ws = null;
        error ? reject(error) : resolve();
      };
      const abort = () => { finish(); try { ws.close(SOCKET_NORMAL_CLOSE); } catch {} };
      const timer = setTimeout(() => { finish(new Error(`${this.manifest.label} socket handshake timed out`)); try { ws.close(SOCKET_RECONNECT_CODE); } catch {} }, this.openTimeoutMs);
      const message = event => {
        if (done || this.controller.signal.aborted) return;
        let packet; try { packet = JSON.parse(event.data); } catch { return; }
        try { this.packet(packet, ws, () => clearTimeout(timer)); }
        catch { finish(new Error(`${this.manifest.label} socket packet could not be processed`)); try { ws.close(SOCKET_RECONNECT_CODE); } catch {} }
      };
      const close = event => finish(this.closeError?.(event.code));
      const failed = () => { finish(new Error(`${this.manifest.label} socket connection failed`)); try { ws.close(SOCKET_RECONNECT_CODE); } catch {} };
      ws.addEventListener('message', message); ws.addEventListener('close', close); ws.addEventListener('error', failed);
      this.controller.signal.addEventListener('abort', abort, { once: true });
      this.inboundTail = Promise.resolve();
    });
  }
  enqueuePacket(ws, work) {
    this.inboundTail = this.inboundTail.then(async () => { if (this.ws === ws && !this.controller.signal.aborted) await work(); }).catch(() => {
      // Do not expose upstream packet/token text, nor advance an unaccepted replay cursor.
      if (this.ws === ws) { this.ctx.status?.({ error: `${this.manifest.label} inbox was not accepted; reconnecting safely` }); ws.close(SOCKET_RECONNECT_CODE); }
    });
  }
  sendPacket(packet, ws = this.ws) { if (ws?.readyState === SOCKET_OPEN) ws.send(JSON.stringify(packet)); }
  async stop() {
    this.stopping = true; this.controller?.abort(new DOMException(`${this.manifest.label} stopped`, 'AbortError'));
    this.cleanupConnection?.();
  }
}

/** Safe Unicode chunks: platform limits count UTF-16 units, never split a surrogate pair. */
export function splitChannelText(text, limit) {
  const parts = []; let chunk = '';
  for (const point of String(text)) { if (chunk.length + point.length > limit) { parts.push(chunk); chunk = ''; } chunk += point; }
  if (chunk) parts.push(chunk); return parts;
}

const APPROVAL_PREFIX = 'ankita'; // Button namespace, not a grant: the runtime still verifies owner and request ID.
export const approvalButtonId = (requestId, answer) => `${APPROVAL_PREFIX}:${requestId}:${answer}`;
export function approvalButton(value) {
  const match = new RegExp(`^${APPROVAL_PREFIX}:([^:]+):(yes|always|no)$`).exec(String(value || ''));
  return match ? { approvalId: match[1], approvalAnswer: match[2] } : null;
}
