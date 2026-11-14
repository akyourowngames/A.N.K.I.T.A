import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import https from 'node:https';
import os from 'node:os';
import path from 'node:path';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';
import { PhonePairing } from '../../desktop/electron/phone-pairing.mjs';
import { parsePairingUri, formatPairingCode, normalizePairingCode, FINGERPRINT_PATTERN, PHONE_PAIRING_ROOT } from '../../desktop/shared/phone-pairing.mjs';

const LOOPBACK = '127.0.0.1';
const TEST_LAN_ADDRESS = '192.0.2.10'; // TEST-NET-1: advertised, never dialled.
const SAFE_STORAGE = {
  isAsyncEncryptionAvailable: async () => true,
  encryptStringAsync: async value => Buffer.from(`enc:${value}`),
  decryptStringAsync: async buffer => ({ result: buffer.toString().replace(/^enc:/, '') }),
};

function temporaryDirectory(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-phone-pairing-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  return directory;
}

class PhoneAgent {
  constructor(options) {
    this.options = options;
    this.messages = [{ role: 'system', content: 'system' }];
    this.state = {};
    this.model = 'fast';
    this.stopped = false;
    this.release = null;
  }
  async send(text, callbacks) {
    this.messages.push({ role: 'user', content: text });
    callbacks.onMessageStart?.();
    callbacks.onDelta?.('Desktop ');
    if (text.includes('approve')) {
      const allowed = await this.options.confirm('write_file', 'Create notes.txt', {});
      callbacks.onDelta?.(allowed ? 'approved ' : 'denied ');
    }
    if (text.includes('slow')) await new Promise(resolve => { this.release = resolve; });
    if (this.stopped) throw new Error('The reply was stopped');
    callbacks.onDelta?.('reply');
    callbacks.onMessageEnd?.();
    const content = `Desktop reply for ${text}`;
    this.messages.push({ role: 'assistant', content });
    return content;
  }
  cancel() { this.stopped = true; this.release?.(); return true; }
}

async function makeEngine(t) {
  const directory = temporaryDirectory(t);
  const engine = new DesktopEngine({
    teammateFile: path.join(directory, 'teammates.json'),
    settingsFile: path.join(directory, 'settings.json'),
    channelsFile: path.join(directory, 'channels.json'),
    sessionsDir: directory,
    AgentClass: PhoneAgent,
    bootstrap: async () => ({ client: {}, tool: null, models: [{ id: 'fast', tools: true }], model: 'fast', provider: { name: 'test' } }),
    config: { provider: 'test', tools: true, model: '', memoryConsolidation: false },
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, summaries: () => [], alwaysOnIds: () => [], specs: () => [], has: () => false, closeAll: async () => {} },
  });
  await engine.init();
  t.after(() => engine.close());
  return { engine, directory };
}

async function makePairing(t, { engine, directory }, options = {}) {
  const events = [];
  const service = new PhonePairing({
    configFile: path.join(directory, 'phone-pairing.json'),
    devicesFile: path.join(directory, 'phone-devices.json'),
    safeStorage: SAFE_STORAGE,
    engine,
    addresses: options.addresses ?? [TEST_LAN_ADDRESS],
    hostname: 'ankita-test',
    emit: event => events.push(event),
  });
  await service.start();
  t.after(() => service.close());
  return { service, events };
}

function call(service, pathname, { method = 'GET', body, token, secret, ca, signal, headers = {} } = {}) {
  headers = { ...headers };
  if (body !== undefined) headers['content-type'] = 'application/json';
  if (token) headers.authorization = `Bearer ${token}`;
  if (secret) headers['x-pair-secret'] = secret;
  return new Promise((resolve, reject) => {
    const request = https.request(`https://${LOOPBACK}:${service.port}${PHONE_PAIRING_ROOT}${pathname}`, {
      method, headers, ca: ca === null ? undefined : ca ?? service.certificate().pem, rejectUnauthorized: true, servername: 'localhost', signal,
    }, response => {
      const chunks = [];
      response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        resolve({ status: response.statusCode, text, headers: response.headers, json: response.headers['content-type']?.includes('application/json') && text ? JSON.parse(text) : null });
      });
    });
    request.on('error', reject);
    if (body !== undefined) request.write(JSON.stringify(body));
    request.end();
  });
}

async function waitFor(check, { timeoutMs = 8000, intervalMs = 25 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await check();
    if (value) return value;
    await new Promise(resolve => setTimeout(resolve, intervalMs));
  }
  throw new Error('Timed out waiting for the pairing service');
}

async function pair(service, { name = 'Krish phone', platform = 'android' } = {}) {
  const invitation = await service.createInvitation();
  const started = await call(service, '/pair', { method: 'POST', body: { code: invitation.code, deviceName: name, platform } });
  assert.equal(started.status, 202);
  await service.respondPairing(started.json.requestId, true);
  const claimed = await call(service, `/pair/${started.json.requestId}`, { secret: started.json.secret });
  assert.equal(claimed.status, 200);
  assert.equal(claimed.json.status, 'claimed');
  assert.equal(typeof claimed.json.token, 'string');
  return { token: claimed.json.token, requestId: started.json.requestId, secret: started.json.secret, deviceId: claimed.json.device.id, invitation };
}

test('invitation format, local QR generation and LAN-only address', async t => {
  const context = await makeEngine(t);
  const { service, events } = await makePairing(t, context);
  assert.equal(service.state, 'ready');
  assert.equal(service.snapshot().address, `https://${TEST_LAN_ADDRESS}:${service.port}${PHONE_PAIRING_ROOT}`);
  assert.equal(service.snapshot().address.includes('localhost'), false);
  assert.match(service.fingerprint(), FINGERPRINT_PATTERN);

  const invitation = await service.createInvitation();
  assert.match(invitation.code, /^[A-Z2-9]{4}-[A-Z2-9]{4}$/);
  assert.equal(normalizePairingCode(invitation.code), normalizePairingCode(invitation.code.replace('-', '')));
  assert.equal(formatPairingCode(normalizePairingCode(invitation.code)), invitation.code);
  assert.equal(invitation.qr.startsWith('data:image/png;base64,'), true);
  assert.ok(events.some(event => event.type === 'phone-pairing-changed'));
  const parsed = parsePairingUri(invitation.uri);
  assert.deepEqual(parsed, {
    address: service.snapshot().address, origin: `https://${TEST_LAN_ADDRESS}:${service.port}`,
    code: normalizePairingCode(invitation.code), fingerprint: service.fingerprint(), name: 'ankita-test',
  });
  assert.equal(invitation.uri.length < 500, true, 'QR payload stays free of long-lived credentials');
  assert.equal(invitation.uri.includes('Bearer'), false);
});

test('expired, replayed and over-guessed invitations are rejected', async t => {
  const { engine, directory } = await makeEngine(t);
  const { service } = await makePairing(t, { engine, directory });

  const expired = await service.createInvitation();
  service.invitation.expiresAt = Date.now() - 1;
  const late = await call(service, '/pair', { method: 'POST', body: { code: expired.code, deviceName: 'Phone', platform: 'ios' } });
  assert.equal(late.status, 410);

  const guessed = await service.createInvitation();
  for (let attempt = 0; attempt < 5; attempt++) {
    const wrong = await call(service, '/pair', { method: 'POST', body: { code: 'AAAA-AAAA', deviceName: 'Phone', platform: 'ios' } });
    assert.equal(wrong.status, 403);
  }
  assert.equal(service.snapshot().invitation, null, 'the invitation burns after the attempt limit');
  const afterBurn = await call(service, '/pair', { method: 'POST', body: { code: guessed.code, deviceName: 'Phone', platform: 'ios' } });
  assert.equal(afterBurn.status, 410);

  const single = await service.createInvitation();
  const first = await call(service, '/pair', { method: 'POST', body: { code: single.code, deviceName: 'Phone', platform: 'ios' } });
  assert.equal(first.status, 202);
  const replay = await call(service, '/pair', { method: 'POST', body: { code: single.code, deviceName: 'Other', platform: 'ios' } });
  assert.equal(replay.status, 410, 'a successful scan consumes the invitation');
});

test('approval, rejection, expiry and one-time token claim', async t => {
  const { engine, directory } = await makeEngine(t);
  const { service } = await makePairing(t, { engine, directory });
  const invitation = await service.createInvitation();
  const started = await call(service, '/pair', { method: 'POST', body: { code: invitation.code, deviceName: 'Krish phone', platform: 'android' } });
  assert.equal(started.status, 202);

  const waiting = await call(service, `/pair/${started.json.requestId}`, { secret: started.json.secret });
  assert.deepEqual(waiting.json, { status: 'pending' });
  assert.equal(service.snapshot().pending.length, 1);
  assert.equal(service.snapshot().devices.length, 0);

  const rejected = await call(service, '/pair', { method: 'POST', body: { code: (await service.createInvitation()).code, deviceName: 'Other phone', platform: 'ios' } });
  assert.equal(rejected.status, 202);
  const other = service.snapshot().pending.find(item => item.requestId === rejected.json.requestId);
  await service.respondPairing(other.requestId, false);
  const denied = await call(service, `/pair/${rejected.json.requestId}`, { secret: rejected.json.secret });
  assert.deepEqual(denied.json, { status: 'rejected' });

  await service.respondPairing(started.json.requestId, true, engine.listTeammates()[0].id);
  const approved = await call(service, `/pair/${started.json.requestId}`, { secret: started.json.secret });
  assert.equal(approved.json.status, 'claimed');
  assert.match(approved.json.token, /^[A-Za-z0-9_-]{43}$/);
  assert.equal(service.snapshot().devices.length, 1);
  const replayClaim = await call(service, `/pair/${started.json.requestId}`, { secret: started.json.secret });
  assert.deepEqual(replayClaim.json, { status: 'claimed' }, 'the token is returned exactly once');
  assert.equal(JSON.stringify(service.snapshot()).includes(approved.json.token), false);

  const deviceFile = fs.readFileSync(path.join(directory, 'phone-devices.json'), 'utf8');
  assert.equal(deviceFile.includes(approved.json.token), false);
  assert.match(deviceFile, /"tokenHash":"[0-9a-f]{64}"/);

  const expiring = await service.createInvitation();
  const expiringRequest = await call(service, '/pair', { method: 'POST', body: { code: expiring.code, deviceName: 'Late phone', platform: 'ios' } });
  await service.respondPairing(expiringRequest.json.requestId, true);
  service.pending.get(expiringRequest.json.requestId).expiresAt = Date.now() - 1;
  const expiredClaim = await call(service, `/pair/${expiringRequest.json.requestId}`, { secret: expiringRequest.json.secret });
  assert.deepEqual(expiredClaim.json, { status: 'expired' });
  assert.equal(service.snapshot().devices.length, 1);
});

test('a paired phone runs the real desktop engine, owns its runs and can be revoked', async t => {
  const { engine, directory } = await makeEngine(t);
  const teammates = engine.listTeammates();
  engine.createTeammate({ name: 'Research desk' });
  const { service } = await makePairing(t, { engine, directory });
  const first = await pair(service, { name: 'Krish phone' });

  const capabilities = await call(service, '/capabilities', { token: first.token });
  assert.equal(capabilities.status, 200);
  assert.deepEqual(capabilities.json.tools, ['desktop_run']);
  assert.equal(capabilities.json.version, 1);
  assert.equal(capabilities.json.teammate.id, teammates[0].id);

  const started = await call(service, '/runs', { method: 'POST', token: first.token, body: { version: 1, prompt: 'Summarise the notes' } });
  assert.equal(started.status, 202);
  const finished = await waitFor(async () => {
    const poll = await call(service, `/runs/${started.json.id}?after=0`, { token: first.token });
    return poll.json.status === 'completed' ? poll.json : null;
  });
  assert.equal(finished.reply, 'Desktop reply for Summarise the notes');
  assert.ok(finished.events.some(event => event.type === 'message' && event.detail.includes('Desktop ')));
  assert.ok(engine.loadThread(teammates[0].id).some(message => message.content === 'Desktop reply for Summarise the notes'));

  const second = await pair(service, { name: 'Tablet' });
  const foreignRead = await call(service, `/runs/${started.json.id}`, { token: second.token });
  assert.equal(foreignRead.status, 404, 'another phone cannot read the run');
  const foreignApproval = await call(service, `/runs/${started.json.id}/approvals/${'0'.repeat(36)}`, { method: 'POST', token: second.token, body: { allow: true } });
  assert.equal(foreignApproval.status, 404);
  assert.equal((await call(service, '/capabilities')).status, 401);

  const secondRun = await call(service, '/runs', { method: 'POST', token: second.token, body: { version: 1, prompt: 'Its own reply' } });
  assert.equal(secondRun.status, 202, 'the second phone still works after its own isolation checks');
  await waitFor(async () => { const poll = await call(service, `/runs/${secondRun.json.id}`, { token: second.token }); return poll.json.status === 'completed'; });

  const active = await call(service, '/runs', { method: 'POST', token: first.token, body: { version: 1, prompt: 'slow work' } });
  assert.equal(active.status, 202);
  await service.revokeDevice(first.deviceId);
  assert.equal((await call(service, '/capabilities', { token: first.token })).status, 401);
  assert.equal(service.snapshot().devices.some(device => device.id === first.deviceId), false);
  assert.equal([...service.runs.values()].some(run => run.deviceId === first.deviceId && !run.finished), false, 'revocation cancels active work');
});

test('phone approvals and cancellation flow through the desktop engine', async t => {
  const { engine, directory } = await makeEngine(t);
  const { service } = await makePairing(t, { engine, directory });
  const phone = await pair(service);

  const approvalRun = await call(service, '/runs', { method: 'POST', token: phone.token, body: { version: 1, prompt: 'approve this action' } });
  assert.equal(approvalRun.status, 202);
  const waiting = await waitFor(async () => {
    const poll = await call(service, `/runs/${approvalRun.json.id}`, { token: phone.token });
    return poll.json.pending ? poll.json : null;
  });
  assert.equal(waiting.pending.name, 'write_file');
  assert.match(waiting.pending.detail, /notes\.txt/);
  assert.equal(engine.listApprovals().length, 1);
  const decision = await call(service, `/runs/${approvalRun.json.id}/approvals/${waiting.pending.id}`, { method: 'POST', token: phone.token, body: { allow: true } });
  assert.equal(decision.status, 200);
  const completed = await waitFor(async () => {
    const poll = await call(service, `/runs/${approvalRun.json.id}`, { token: phone.token });
    return poll.json.status === 'completed' ? poll.json : null;
  });
  assert.ok(completed.events.some(event => event.type === 'approval' && event.name === 'write_file'));
  assert.ok(completed.events.some(event => event.type === 'message' && event.detail.includes('approved')));
  assert.equal(engine.listApprovals().length, 0);

  const slow = await call(service, '/runs', { method: 'POST', token: phone.token, body: { version: 1, prompt: 'slow work' } });
  assert.equal(slow.status, 202);
  const cancelled = await call(service, `/runs/${slow.json.id}`, { method: 'DELETE', token: phone.token });
  assert.equal(cancelled.status, 200);
  const stopped = await waitFor(async () => {
    const poll = await call(service, `/runs/${slow.json.id}`, { token: phone.token });
    return poll.json.status === 'cancelled' ? poll.json : null;
  });
  assert.ok(stopped.events.some(event => event.type === 'done' && event.detail === 'cancelled'));
});

test('pairing survives restart, keeps the certificate and forgets invitations', async t => {
  const { engine, directory } = await makeEngine(t);
  const first = await makePairing(t, { engine, directory });
  const phone = await pair(first.service);
  const fingerprint = first.service.fingerprint();
  const { port } = first.service;
  await first.service.close();

  const events = [];
  const restored = new PhonePairing({
    configFile: path.join(directory, 'phone-pairing.json'),
    devicesFile: path.join(directory, 'phone-devices.json'),
    safeStorage: SAFE_STORAGE, engine, addresses: [TEST_LAN_ADDRESS], hostname: 'ankita-test',
    emit: event => events.push(event),
  });
  await restored.start();
  t.after(() => restored.close());
  assert.equal(restored.state, 'ready');
  assert.equal(restored.port, port, 'the firewall-friendly port is reused');
  assert.equal(restored.fingerprint(), fingerprint, 'the installed certificate stays valid');
  assert.equal(restored.snapshot().invitation, null);
  assert.equal(restored.snapshot().devices.length, 1);
  assert.equal((await call(restored, '/capabilities', { token: phone.token })).status, 200);
  assert.equal(events.some(event => event.type === 'phone-pairing-changed'), true);

  const config = JSON.parse(fs.readFileSync(path.join(directory, 'phone-pairing.json'), 'utf8'));
  assert.match(config.caKey, /^[A-Za-z0-9+/=]+$/, 'the CA key is encrypted at rest');
  assert.equal(config.caKey.includes('PRIVATE KEY'), false);
});

test('TLS stays strict and browser origins are refused', async t => {
  const { engine, directory } = await makeEngine(t);
  const { service } = await makePairing(t, { engine, directory });
  await assert.rejects(call(service, '/pair', { method: 'POST', body: { code: 'AAAA-AAAA', deviceName: 'x', platform: 'y' }, ca: null }), /self-signed|unable to verify|certificate/i);
  await assert.rejects(new Promise((resolve, reject) => {
    https.get(`https://${LOOPBACK}:${service.port}${PHONE_PAIRING_ROOT}/capabilities`, { ca: service.certificate().pem, rejectUnauthorized: true, servername: 'wrong.example' }, resolve).on('error', reject);
  }), /altnames|IP|hostname|certificate/i);
  const origin = await new Promise((resolve, reject) => {
    const request = https.request(`https://${LOOPBACK}:${service.port}${PHONE_PAIRING_ROOT}/pair`, { method: 'POST', ca: service.certificate().pem, headers: { 'content-type': 'application/json', origin: 'https://evil.example' } }, response => {
      const chunks = []; response.on('data', chunk => chunks.push(chunk));
      response.on('end', () => resolve({ status: response.statusCode, json: JSON.parse(Buffer.concat(chunks).toString('utf8')) }));
    });
    request.on('error', reject); request.end(JSON.stringify({ code: 'AAAA-AAAA', deviceName: 'x', platform: 'y' }));
  });
  assert.equal(origin.status, 403);
});

test('the fixed phone client admits only its served HTTPS origin and certificate hosts', async t => {
  const context = await makeEngine(t);
  const { service } = await makePairing(t, context);
  const page = await call(service, '/phone');
  assert.equal(page.status, 200, 'a phone can open the browser entrypoint');
  assert.match(page.text, /Pair this phone/);
  assert.match(page.headers['content-security-policy'], /connect-src 'self'/);
  assert.equal(page.headers['cache-control'], 'no-store');
  assert.equal((await call(service, '/phone/app.mjs')).status, 200);
  assert.equal((await call(service, '/phone/contract.mjs')).status, 200);
  assert.notEqual((await call(service, '/phone/%2e%2e/%2e%2e/package.json')).status, 200);
  const invitation = await service.createInvitation();
  assert.match(invitation.browserUrl, /^https:\/\/192\.0\.2\.10:\d+\/v1\/ankita-companion\/phone#/);
  assert.ok(invitation.browserQr.startsWith('data:image/png;base64,'));
  const origin = `https://${LOOPBACK}:${service.port}`;
  const started = await call(service, '/pair', { method: 'POST', headers: { origin }, body: { code: invitation.code, deviceName: 'Browser phone', platform: 'browser' } });
  assert.equal(started.status, 202, 'same-origin pairing reaches desktop approval');
  assert.equal((await call(service, `/pair/${started.json.requestId}`, { secret: started.json.secret, headers: { origin } })).json.status, 'pending');
  for (const headers of [
    { origin: 'null' }, { origin: 'https://evil.example' }, { origin: `${origin}0` },
    { host: `rebinding.example:${service.port}`, origin: `https://rebinding.example:${service.port}` },
    { host: `${LOOPBACK}:1` }, { 'sec-fetch-site': 'cross-site' },
  ]) assert.equal((await call(service, '/phone', { headers })).status, 403, JSON.stringify(headers));
  assert.equal((await call(service, '/history', { headers: { origin } })).status, 401, 'origin never replaces bearer authentication');
});

test('history and tasks are assigned-owner only and reviewed context is bounded and single-use', async t => {
  const { engine, directory } = await makeEngine(t);
  const { service } = await makePairing(t, { engine, directory });
  const owner = engine.listTeammates()[0].id;
  const other = engine.createTeammate({ name: 'Private desk' }).id;
  const phone = await pair(service);
  const store = engine.assistant().tasks;
  const mine = store.create({ ownerId: owner, goal: 'Continue the trip plan', surface: 'desktop' });
  store.finish(mine.id, { status: 'interrupted' });
  const foreign = store.create({ ownerId: other, goal: 'PRIVATE_OTHER_OWNER', surface: 'channel' });
  store.finish(foreign.id, { status: 'interrupted' });
  await engine.send(owner, 'My visible history'); await engine.waitForTurn(owner);
  await engine.send(other, 'PRIVATE_OTHER_OWNER'); await engine.waitForTurn(other);
  const history = await call(service, '/history', { token: phone.token });
  assert.equal(history.status, 200);
  assert.ok(history.json.messages.some(message => message.content === 'My visible history'));
  assert.equal(JSON.stringify(history.json).includes('PRIVATE_OTHER_OWNER'), false);
  assert.equal((await call(service, `/history?threadId=${other}`, { token: phone.token })).status, 400);
  const tasks = await call(service, '/tasks', { token: phone.token });
  assert.equal(tasks.status, 200);
  assert.ok(tasks.json.tasks.some(task => task.id === mine.id));
  assert.equal(JSON.stringify(tasks.json).includes('PRIVATE_OTHER_OWNER'), false);
  const deniedResume = await call(service, `/tasks/${foreign.id}/resume`, { method: 'POST', token: phone.token, body: { version: 1 } });
  assert.equal(deniedResume.status, 404);
  assert.equal((await call(service, '/context', { method: 'POST', token: phone.token, body: { title: 'Notes', text: 'x'.repeat(7000) } })).status, 400);
  const preview = await call(service, '/context', { method: 'POST', token: phone.token, body: { title: 'Travel notes', text: 'Take the late train.' } });
  assert.equal(preview.status, 201);
  assert.deepEqual(preview.json.context, { title: 'Travel notes', text: 'Take the late train.' });
  const second = await pair(service, { name: 'Different browser' });
  assert.equal((await call(service, '/runs', { method: 'POST', token: second.token, body: { version: 1, prompt: 'Explain this', contextId: preview.json.id } })).status, 404);
  const run = await call(service, '/runs', { method: 'POST', token: phone.token, body: { version: 1, prompt: 'Explain this', contextId: preview.json.id } });
  assert.equal(run.status, 202);
  await waitFor(async () => (await call(service, `/runs/${run.json.id}`, { token: phone.token })).json.status === 'completed');
  assert.equal((await call(service, '/runs', { method: 'POST', token: phone.token, body: { version: 1, prompt: 'Again', contextId: preview.json.id } })).status, 404, 'reviewed context is used for exactly one accepted request');
  const plain = await call(service, '/runs', { method: 'POST', token: phone.token, body: { version: 1, prompt: 'Without context' } });
  assert.equal(plain.status, 202, 'the native v1 request remains valid');
  await waitFor(async () => (await call(service, `/runs/${plain.json.id}`, { token: phone.token })).json.status === 'completed');
  await service.revokeDevice(phone.deviceId);
  assert.equal((await call(service, '/history', { token: phone.token })).status, 401);
  assert.equal((await call(service, '/tasks', { token: phone.token })).status, 401);
});

test('changing a phone assignment removes access to old run events and pending approvals', async t => {
  const { engine, directory } = await makeEngine(t);
  const other = engine.createTeammate({ name: 'New assignment' }).id;
  const { service } = await makePairing(t, { engine, directory });
  const phone = await pair(service);
  const started = await call(service, '/runs', { method: 'POST', token: phone.token, body: { version: 1, prompt: 'approve this action' } });
  const waiting = await waitFor(async () => { const result = await call(service, `/runs/${started.json.id}`, { token: phone.token }); return result.json.pending ? result.json : null; });
  await service.assignDevice(phone.deviceId, other);
  assert.equal((await call(service, `/runs/${started.json.id}`, { token: phone.token })).status, 404);
  assert.equal((await call(service, `/runs/${started.json.id}/approvals/${waiting.pending.id}`, { method: 'POST', token: phone.token, body: { allow: true } })).status, 404);
  assert.equal((await call(service, '/capabilities', { token: phone.token })).json.teammate.id, other);
  assert.equal(engine.listApprovals().length, 0);
});

test('phone saved-work details have a small total excerpt budget instead of returning every receipt', async t => {
  const { engine, directory } = await makeEngine(t);
  const { service } = await makePairing(t, { engine, directory });
  const phone = await pair(service), ownerId = engine.listTeammates()[0].id, store = engine.assistant().tasks;
  const task = store.create({ ownerId, goal: 'G'.repeat(8000) }); store.start(task.id, { ownerId });
  for (let index = 0; index < 16; index++) {
    const call = { id: `read-${index}`, name: 'read_file', arguments: { path: `file-${index}` } };
    store.requested(task.id, call, { mutation: false }); store.started(task.id, call); store.settled(task.id, call, { content: [{ type: 'text', text: 'R'.repeat(1200) }] });
  }
  store.finish(task.id, { status: 'interrupted' });
  const response = await call(service, '/tasks', { token: phone.token });
  assert.equal(response.status, 200);
  assert.ok(Buffer.byteLength(response.text) < 24000, 'a long task remains a phone-sized preview');
  assert.equal(response.json.tasks[0].detailsOmitted, true);
});
