import test from 'node:test';
import assert from 'node:assert/strict';
import { CredentialRequests } from '../../desktop/electron/credential-requests.mjs';
const SECRET = 'test-login-password';
const ctx = { browserCredentialAllowed: true, browserThreadId: 'thread', browserCallId: 'call', signal: new AbortController().signal };

test('background login without a saved account skips instead of opening a password dialog', async () => {
  const { BrowserCredentials } = await import('../../desktop/electron/browser-credentials.mjs');
  const service = new BrowserCredentials({ store: { withCredentials: async () => null }, requests: { request: () => assert.fail('background jobs must never request a password') }, emit() {} });
  await assert.rejects(service.login({ prepareCredentials: async () => ({}) }, { website: 'https://example.com' }, { ...ctx, backgroundJob: true }), error => error.jobStatus === 'skipped-needs-foreground');
});
test('credential requests bind responses to the call and cancel on Stop', async () => {
  const events = [], registry = new CredentialRequests(event => events.push(event));
  const controller = new AbortController();
  const waiting = registry.request({ threadId: 'thread', callId: 'call', website: 'https://example.com' }, controller.signal);
  assert.equal(registry.respond({ ...events[0], callId: 'other', action: 'submit', username: 'user', password: SECRET }), false);
  controller.abort();
  assert.equal((await waiting).action, 'cancel'); assert.equal(registry.pending.size, 0);
  assert.ok(!JSON.stringify(events).includes(SECRET));
});
test('login reuses a scoped saved account, submits once, emits metadata, and denies remote surfaces', async () => {
  const { BrowserCredentials } = await import('../../desktop/electron/browser-credentials.mjs');
  let submits = 0, prepares = 0;
  const adapter = { prepareCredentials: async () => { prepares++; return {}; }, fillCredentials: async (_plan, _args, value) => { assert.equal(value.password, SECRET); submits++; return 'Dashboard'; } };
  const events = [], value = { username: 'user', password: SECRET };
  const service = new BrowserCredentials({ store: { withCredentials: async (_key, fn) => { try { return await fn(value); } finally { value.password = ''; } } }, requests: { request: () => assert.fail('warm sign-in should not prompt') }, emit: event => events.push(event) });
  const result = await service.login(adapter, { website: 'https://example.com/login', credential_fields: [{ ref: '1-0-0', credential: 'password' }] }, ctx);
  assert.equal(result.status, 'filled'); assert.equal(submits, 1); assert.equal(prepares, 1); assert.equal(value.password, ''); assert.ok(!JSON.stringify([events, result]).includes(SECRET));
  await assert.rejects(service.login(adapter, { website: 'https://example.com' }, { ...ctx, browserCredentialAllowed: false }), /desktop|manual/i);
});
test('wrong password waits for explicit retry; cancel and backend errors never leak a secret', async () => {
  const { BrowserCredentials } = await import('../../desktop/electron/browser-credentials.mjs');
  let calls = 0, prompts = 0;
  const service = new BrowserCredentials({ store: { withCredentials: async () => null, available: async () => true }, requests: { request: async () => ++prompts === 1 ? { action: 'submit', username: 'user', password: SECRET, save: false } : { action: 'cancel' } }, emit: () => {} });
  const result = await service.login({ prepareCredentials: async () => ({}), credentialSnapshot: async () => 'fresh refs', fillCredentials: async () => { calls++; throw new Error(SECRET); } }, { website: 'https://example.com', credential_fields: [{ ref: '1-0-0', credential: 'password' }] }, ctx);
  assert.equal(calls, 1); assert.equal(prompts, 1); assert.equal(result.status, 'attention'); assert.ok(!JSON.stringify(result).includes(SECRET));
  service.clear();
});

test('Stop during a credential wait closes the adapter and leaves a stopped session', async t => {
  const fs = await import('node:fs/promises'), os = await import('node:os'), path = await import('node:path');
  const { BrowserPluginStore } = await import('../../src/integrations/browser-plugins.mjs');
  const { BrowserSessionManager } = await import('../../tools/browser/session.mjs');
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'credential-stop-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const store = new BrowserPluginStore(path.join(directory, 'browser.json')).load(); store.setEnabled('isolated', true);
  let begin, closed = 0; const began = new Promise(resolve => { begin = resolve; });
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({ close: async () => { closed++; } }), credentials: { login: async (_adapter, _args, context) => { begin(); await new Promise(resolve => context.signal.addEventListener('abort', resolve, { once: true })); return { status: 'cancelled' }; } } });
  const work = manager.run({ action: 'login', website: 'https://example.com' }, ctx);
  await began; manager.cancel('thread'); assert.match(await work, /cancel/i); await manager.tail;
  assert.equal(manager.last.status, 'stopped'); assert.equal(closed, 1);
});

test('login requires a separate secure card and refuses Chrome and remote surfaces before creating an adapter', async () => {
  const { BrowserSessionManager } = await import('../../tools/browser/session.mjs');
  let constructed = 0;
  const manager = new BrowserSessionManager({ credentials: {}, isolatedFactory: () => { constructed++; return {}; } });
  assert.match(await manager.run({ action: 'login', website: 'https://example.com', mode: 'local' }, ctx), /Playwright only/);
  assert.match(await manager.run({ action: 'login', website: 'https://example.com' }, { ...ctx, browserCredentialAllowed: false }), /desktop/i);
  assert.match(await manager.run({ action: 'batch', steps: [{ action: 'login', website: 'https://example.com' }] }, ctx), /separate.*login/i);
  assert.equal(constructed, 0);
});

test('disabled Playwright login never constructs the Chrome fallback', async () => {
  const { BrowserSessionManager } = await import('../../tools/browser/session.mjs');
  let constructed = 0;
  const store = { load() { return this; }, get(mode) { return { enabled: mode === 'local' }; } };
  const manager = new BrowserSessionManager({ store, credentials: {}, chromeFactory: () => { constructed++; return {}; } });
  assert.match(await manager.run({ action: 'login', website: 'https://example.com' }, ctx), /Enable Playwright Browser/);
  assert.equal(constructed, 0);
});

test('save failures show a sanitized reason and disable saving on the explicit one-time retry', async () => {
  const { BrowserCredentials } = await import('../../desktop/electron/browser-credentials.mjs');
  const requests = [], events = []; let filled = 0;
  const service = new BrowserCredentials({ store: { withCredentials: async () => null, available: async () => true, save: async () => { throw new Error(SECRET); } }, requests: { request: async detail => { requests.push(detail); return requests.length === 1 ? { action: 'submit', username: 'user', password: SECRET, save: true } : { action: 'cancel' }; } }, emit: event => events.push(event) });
  await service.login({ prepareCredentials: async () => ({}), fillCredentials: async () => { filled++; return 'snapshot'; } }, { website: 'https://example.com' }, ctx);
  assert.equal(filled, 0); assert.equal(requests[1].canSave, false); assert.match(requests[1].message, /could not be saved/i);
  assert.ok(!JSON.stringify([events, requests]).includes(SECRET));
});
