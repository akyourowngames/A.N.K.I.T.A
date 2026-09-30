import test from 'node:test';
import assert from 'node:assert/strict';
import { BrowserCredentials } from '../../desktop/electron/browser-credentials.mjs';

const SECRET = 'selected-controls-test-secret';
const WEBSITE = 'https://example.com';
const fields = [{ ref: '1-0-0', credential: 'username' }, { ref: '1-0-1', credential: 'password' }];

test('malformed credential selections return fresh refs before vault access and allow a corrected call', async () => {
  const controller = new AbortController(), events = [];
  const ctx = { backgroundJob: true, browserCredentialAllowed: true, browserThreadId: 'owner', signal: controller.signal, credentialTurnSignal: controller.signal };
  const plan = { page: {}, website: WEBSITE, tab: '1' };
  let reads = 0, fills = 0;
  const adapter = { prepareCredentials: async () => plan, credentialSnapshot: async () => 'Fresh username/password/button refs',
    fillCredentials: async (_plan, _args, value, context) => { assert.equal(value.password, SECRET); fills++; context.onCredentialUsed?.(); return 'Dashboard'; } };
  const service = new BrowserCredentials({ store: { withCredentials: async (_args, callback) => { reads++; callback({ username: 'user', password: SECRET }); } },
    requests: { request: async () => assert.fail('A malformed selection must not open a credential dialog') }, emit: event => events.push(event) });
  for (const credential_fields of ['bad', [], [fields[0], { ref: '1-0-2', credential: 'submit', password: SECRET }], [fields[0], fields[0]]]) {
    const result = await service.login(adapter, { website: WEBSITE, credential_fields }, ctx);
    assert.equal(result.status, 'attention'); assert.match(result.message, /submit_ref/); assert.match(result.snapshot, /Fresh/);
    assert.equal(reads, 0); assert.equal(fills, 0); assert.equal(service.pending.size, 0);
    assert.ok(!JSON.stringify([result, events]).includes(SECRET));
  }
  const corrected = await service.login(adapter, { website: WEBSITE, credential_fields: fields, submit_ref: '1-0-2' }, ctx);
  assert.equal(corrected.status, 'filled'); assert.equal(reads, 1); assert.equal(fills, 1); assert.equal(service.pending.size, 0);
  controller.abort();
});

test('the model can request credentials before a login form exists and continue with its selected refs', async () => {
  const controller = new AbortController(), events = [];
  const ctx = { browserCredentialAllowed: true, browserThreadId: 'owner', signal: controller.signal, credentialTurnSignal: controller.signal };
  const page = {}, plan = { page, website: WEBSITE, tab: '1' };
  let prompts = 0, fills = 0;
  const adapter = {
    prepareCredentials: async () => plan,
    credentialSnapshot: async () => 'Current snapshot: account control refs',
    fillCredentials: async (_plan, args, value) => { assert.deepEqual(args.credential_fields, fields); assert.equal(value.password, SECRET); fills++; return 'Current snapshot: Dashboard'; },
    prepareLogin: () => assert.fail('Form detection must not gate the dialog'),
  };
  const service = new BrowserCredentials({ store: { withCredentials: async () => null, available: async () => false }, requests: { request: async () => { prompts++; return { action: 'submit', username: 'user', password: SECRET, save: false }; } }, emit: event => events.push(event) });
  const requested = await service.login(adapter, { website: WEBSITE }, ctx);
  assert.equal(requested.status, 'available');
  assert.equal(prompts, 1); assert.equal(fills, 0);
  assert.match(requested.snapshot, /refs/);
  const submitted = await service.login(adapter, { website: WEBSITE, credential_fields: fields, submit_ref: '1-0-2' }, ctx);
  assert.equal(submitted.status, 'filled');
  assert.match(submitted.snapshot, /Dashboard/);
  assert.equal(prompts, 1); assert.equal(fills, 1);
  assert.ok(!JSON.stringify([events, requested, submitted]).includes(SECRET));
  assert.equal(service.pending.size, 0, 'password use consumes the transient record');
  controller.abort();
});

test('username-first credentials remain private until the password step; another thread or tab cannot reuse them', async () => {
  const controller = new AbortController();
  const ctx = { browserCredentialAllowed: true, browserThreadId: 'owner', signal: controller.signal, credentialTurnSignal: controller.signal };
  let prompts = 0, tab = '1'; const page = {};
  const adapter = { prepareCredentials: async () => ({ page, website: WEBSITE, tab }), credentialSnapshot: async () => 'snapshot', fillCredentials: async () => 'next step' };
  const service = new BrowserCredentials({ store: { withCredentials: async () => null, available: async () => false }, requests: { request: async () => ++prompts === 1 ? { action: 'submit', username: 'user', password: SECRET } : { action: 'cancel' } }, emit: () => {} });
  const first = await service.login(adapter, { website: WEBSITE, credential_fields: [fields[0]] }, ctx);
  assert.equal(first.status, 'filled'); assert.equal(service.pending.size, 1);
  assert.equal((await service.login(adapter, { website: WEBSITE }, { ...ctx, browserThreadId: 'other' })).status, 'cancelled');
  tab = '2';
  assert.equal((await service.login(adapter, { website: WEBSITE }, ctx)).status, 'cancelled');
  assert.equal(prompts, 3);
  controller.abort(); assert.equal(service.pending.size, 0);
});

test('a missing selected control returns to the model once, without a credential retry loop or secret in errors', async () => {
  const controller = new AbortController(), ctx = { browserCredentialAllowed: true, browserThreadId: 'owner', signal: controller.signal, credentialTurnSignal: controller.signal };
  let prompts = 0;
  const adapter = { prepareCredentials: async () => ({ page: {}, website: WEBSITE, tab: '1' }), credentialSnapshot: async () => 'fresh refs', fillCredentials: async () => { throw new Error(SECRET); } };
  const service = new BrowserCredentials({ store: { withCredentials: async () => null, available: async () => false }, requests: { request: async () => { prompts++; return { action: 'submit', username: 'user', password: SECRET }; } }, emit: () => {} });
  const result = await service.login(adapter, { website: WEBSITE, credential_fields: fields }, ctx);
  assert.equal(prompts, 1); assert.equal(result.status, 'attention');
  assert.equal(result.snapshot, 'fresh refs'); assert.ok(!JSON.stringify(result).includes(SECRET));
  controller.abort();
});

test('password consumption clears the transient credential even if the click or snapshot subsequently fails', async () => {
  const controller = new AbortController(), ctx = { browserCredentialAllowed: true, browserThreadId: 'owner', signal: controller.signal, credentialTurnSignal: controller.signal };
  const adapter = { prepareCredentials: async () => ({ page: {}, website: WEBSITE, tab: '1' }), credentialSnapshot: async () => 'fresh refs', fillCredentials: async (_plan, _args, value, context) => { assert.equal(value.password, SECRET); context.onCredentialUsed?.(); throw new Error('snapshot failed after fill'); } };
  const service = new BrowserCredentials({ store: { withCredentials: async () => null, available: async () => false }, requests: { request: async () => ({ action: 'submit', username: 'user', password: SECRET }) }, emit: () => {} });
  assert.equal((await service.login(adapter, { website: WEBSITE, credential_fields: fields }, ctx)).status, 'attention');
  assert.equal(service.pending.size, 0); controller.abort();
});
