import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { CompanionCapture } from '../../desktop/electron/companion-capture.mjs';
import { McpManager } from '../../src/integrations/mcp-manager.mjs';
import { BROWSER_EXTENSION_MCP_ID, BROWSER_EXTENSION_TOOL } from '../../desktop/browser-helper/control-protocol.mjs';
import { BrowserConnection } from '../../desktop/browser-helper/connection.mjs';

const origin = 'chrome-extension://' + 'a'.repeat(32);
const routes = { connect: '/browser/connect', next: '/browser/next', result: '/browser/result' };
async function fixture(t, control = true) {
  const dir = await mkdtemp(join(tmpdir(), 'ankita-browser-control-'));
  const options = { configFile: join(dir, 'bridge.json'), threadExists: () => true, onCapture() {} };
  const services = [];
  const start = async () => { const service = await new CompanionCapture(options).start(); services.push(service); return service; };
  const service = await start();
  t.after(async () => { await Promise.all(services.map(s => s.close())); await rm(dir, { recursive: true, force: true }); });
  const post = async (s, route, body, token, site = origin) => {
    const response = await fetch(s.address + route, { method: 'POST', headers: { Origin: site, 'Content-Type': 'application/json', ...(token ? { Authorization: 'Bearer ' + token } : {}) }, body: JSON.stringify(body) });
    return { status: response.status, body: await response.json() };
  };
  const setup = service.setup({ control });
  const pair = await post(service, '/pair', { code: setup.code, helperId: randomUUID() });
  assert.equal(pair.status, 200);
  return { service, start, post, ...pair.body };
}
test('browser control is a separate opt-in from an existing capture pairing', async t => {
  const f = await fixture(t, false);
  const response = await f.post(f.service, routes.connect, { helperId: f.helperId, clientId: randomUUID() }, f.token);
  assert.equal(response.status, 403, 'capture-only pairing cannot operate the browser');
});
test('one browser pairing reconnects after desktop restart with the same credentials and port', async t => {
  const f = await fixture(t), clientId = randomUUID();
  const first = await f.post(f.service, routes.connect, { helperId: f.helperId, clientId }, f.token);
  assert.equal(first.status, 200);
  const address = f.service.address;
  await f.service.close();
  const restarted = await f.start();
  assert.equal(restarted.address, address);
  const second = await f.post(restarted, routes.connect, { helperId: f.helperId, clientId }, f.token);
  assert.equal(second.status, 200);
  assert.notEqual(second.body.sessionId, first.body.sessionId);
  assert.equal(restarted.browserStatus().paired, true);
  assert.equal(restarted.browserStatus().connected, true);
});
test('commands execute once and results belong to the paired session', async t => {
  const f = await fixture(t);
  const connected = await f.post(f.service, routes.connect, { helperId: f.helperId, clientId: randomUUID() }, f.token);
  assert.equal(connected.status, 200);
  const auth = { helperId: f.helperId, ...connected.body };
  const work = f.service.browser.execute({ action: 'tabs', scope: 'one' });
  const next = await f.post(f.service, routes.next, auth, f.token);
  assert.equal(next.status, 200);
  assert.equal(next.body.command.operation.action, 'tabs');
  const result = { ...auth, id: next.body.command.id, result: [{ id: 'tab-1', title: 'Fixture' }] };
  assert.equal((await f.post(f.service, routes.result, { ...result, sessionId: randomUUID() }, f.token)).status, 409);
  assert.equal((await f.post(f.service, routes.result, result, f.token)).status, 200);
  assert.deepEqual(await work, result.result);
  assert.equal((await f.post(f.service, routes.result, result, f.token)).status, 409);
});
test('a restarted worker never receives a write dispatched by the previous worker', async t => {
  const f = await fixture(t);
  const connect = () => f.post(f.service, routes.connect, { helperId: f.helperId, clientId: randomUUID() }, f.token);
  const first = await connect(), auth = { helperId: f.helperId, ...first.body };
  const work = f.service.browser.execute({ action: 'act', op: 'click', scope: 'one' });
  const failure = assert.rejects(work, /uncertain|interrupted/i);
  const command = await f.post(f.service, routes.next, auth, f.token);
  assert.ok(command.body.command.id);
  assert.equal((await connect()).status, 200);
  await failure;
  assert.equal(f.service.browser.pending.size, 0);
  const late = await f.post(f.service, routes.result, { ...auth, id: command.body.command.id, result: 'Done' }, f.token);
  assert.equal(late.status, 409);
});
test('website requests, incorrect tokens and revoked helpers cannot connect', async t => {
  const f = await fixture(t), body = { helperId: f.helperId, clientId: randomUUID() };
  assert.equal((await f.post(f.service, routes.connect, body, f.token, 'https://example.test')).status, 403);
  assert.equal((await f.post(f.service, routes.connect, body, 'incorrect')).status, 401);
  await f.service.revokeBrowser();
  assert.equal((await f.post(f.service, routes.connect, body, f.token)).status, 403);
  await f.service.close();
  const restarted = await f.start();
  assert.equal((await f.post(restarted, routes.connect, body, f.token)).status, 403);
});
test('real MCP round trip reaches the paired receiver and rejects webpage access', async t => {
  const f = await fixture(t), mcp = new McpManager();
  t.after(() => mcp.closeAll());
  const connected = await f.post(f.service, routes.connect, { helperId: f.helperId, clientId: randomUUID() }, f.token);
  const auth = { helperId: f.helperId, ...connected.body };
  const gateway = await f.service.browserGateway();
  const forbidden = await fetch(gateway.url, { headers: { Origin: 'https://example.test' } });
  assert.equal(forbidden.status, 403);
  await mcp.connect({ id: BROWSER_EXTENSION_MCP_ID, transport: 'http', url: gateway.url, hidden: true });
  const work = mcp.callToolResult(`mcp__${BROWSER_EXTENSION_MCP_ID}__${BROWSER_EXTENSION_TOOL}`, { operation: { action: 'tabs', scope: 'job' } });
  const next = await f.post(f.service, routes.next, auth, f.token);
  const observed = [{ id: '42', url: 'https://example.test/', title: 'Actual receiver reply' }];
  await f.post(f.service, routes.result, { ...auth, id: next.body.command.id, result: observed }, f.token);
  assert.deepEqual(JSON.parse((await work).text).result, observed);
});
test('Stop invalidates a delivered command before deeper input is dispatched', async t => {
  const f = await fixture(t), connected = await f.post(f.service, routes.connect, { helperId: f.helperId, clientId: randomUUID() }, f.token);
  const auth = { helperId: f.helperId, ...connected.body }, controller = new AbortController();
  const work = f.service.browser.execute({ action: 'act', op: 'press', scope: 'job' }, { signal: controller.signal });
  const failure = assert.rejects(work, /uncertain|interrupted/i);
  const next = await f.post(f.service, routes.next, auth, f.token), claim = { ...auth, id: next.body.command.id };
  assert.equal((await f.post(f.service, '/browser/claim', claim, f.token)).status, 200);
  controller.abort(); await failure;
  assert.equal((await f.post(f.service, '/browser/claim', claim, f.token)).status, 409);
});
test('a cancelled real MCP HTTP request invalidates its delivered browser command', async t => {
  const f = await fixture(t), mcp = new McpManager(), controller = new AbortController();
  t.after(() => mcp.closeAll());
  const connected = await f.post(f.service, routes.connect, { helperId: f.helperId, clientId: randomUUID() }, f.token);
  const auth = { helperId: f.helperId, ...connected.body };
  await mcp.connect({ id: BROWSER_EXTENSION_MCP_ID, transport: 'http', url: (await f.service.browserGateway()).url, hidden: true });
  const work = mcp.callToolResult(`mcp__${BROWSER_EXTENSION_MCP_ID}__${BROWSER_EXTENSION_TOOL}`, { operation: { action: 'act', op: 'press', scope: 'job' } }, { signal: controller.signal });
  const cancelled = assert.rejects(work, /abort|cancel/i);
  const next = await f.post(f.service, routes.next, auth, f.token);
  controller.abort(); await cancelled;
  const deadline = Date.now() + 1000;
  while (f.service.browser.pending.size && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal((await f.post(f.service, '/browser/claim', { ...auth, id: next.body.command.id }, f.token)).status, 409);
});
test('a real HTTP receiver exposes pairing recovery immediately after desktop revocation', async t => {
  const f = await fixture(t);
  let session = { address: f.service.address, token: f.token, helperId: f.helperId, control: true };
  const receiver = new BrowserConnection({ load: async () => session, save: async value => { session = value; }, execute: async () => null,
    post: async (saved, route, body, signal) => {
      const response = await fetch(saved.address + route, { method: 'POST', signal, headers: { Origin: origin, 'Content-Type': 'application/json', Authorization: 'Bearer ' + saved.token }, body: JSON.stringify(body) });
      const result = await response.json(); if (!response.ok) throw Object.assign(new Error(result.error), { status: response.status, code: result.code }); return result;
    } });
  t.after(async () => { receiver.stop(); await receiver.running; });
  await receiver.wake();
  let deadline = Date.now() + 2000;
  while (!receiver.status().connected && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(receiver.status().connected, true);
  await f.service.revokeBrowser();
  deadline = Date.now() + 2000;
  while (!receiver.status().needsPairing && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal(receiver.status().needsPairing, true, JSON.stringify(receiver.status()));
});
test('simultaneous settings changes keep a durable pairing file without conflicting temporary writes', async t => {
  const f = await fixture(t);
  await Promise.all([true, false, true, false].map(paused => f.service.pauseBrowser(paused)));
  const saved = JSON.parse(await readFile(f.service.configFile, 'utf8'));
  assert.equal(saved.helpers[f.helperId].paused, false);
  assert.equal(saved.helpers[f.helperId].control, true);
});
test('passive capture setup cannot replace or upgrade the explicit browser-control pairing code', async t => {
  const f = await fixture(t, false);
  const browser = f.service.setup({ control: true }), capture = f.service.setup();
  const pairedBrowser = await f.post(f.service, '/pair', { code: browser.code }, undefined);
  assert.equal(pairedBrowser.status, 200, 'opening capture help must not invalidate browser setup');
  assert.equal(pairedBrowser.body.control, true);
  const pairedCapture = await f.post(f.service, '/pair', { code: capture.code }, undefined);
  assert.equal(pairedCapture.status, 200);
  assert.equal(pairedCapture.body.control, false);
});
