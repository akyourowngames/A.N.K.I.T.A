import assert from 'node:assert/strict';

export const jsonResponse = (value, status = 200, headers = {}) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json', ...headers } });
export async function eventually(predicate) {
  for (let i = 0; i < 100; i++) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 5)); }
  assert.ok(predicate(), 'condition must settle within the bounded fixture wait');
}
export function socketFixture() {
  const instances = [];
  class FixtureSocket extends EventTarget {
    constructor(url) { super(); this.url = url; this.readyState = 0; this.sent = []; instances.push(this); }
    open() { this.readyState = 1; this.dispatchEvent(new Event('open')); }
    packet(data) { this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(data) })); }
    send(data) { this.sent.push(JSON.parse(data)); }
    close(code = 1000) { this.closeFromServer(code); }
    closeFromServer(code = 1006) { if (this.readyState === 3) return; this.readyState = 3; const event = new Event('close'); Object.defineProperty(event, 'code', { value: code }); this.dispatchEvent(event); }
  }
  return { WebSocket: FixtureSocket, instances };
}
