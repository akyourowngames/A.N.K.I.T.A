import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { chromium } from 'playwright';
import { PlaywrightBrowserAdapter } from '../../tools/browser/playwright.mjs';
import { BrowserSessionManager } from '../../tools/browser/session.mjs';
import { BrowserPluginStore } from '../../src/integrations/browser-plugins.mjs';

const SECRET = 'formless-fixture-password';
const RENDER_MS = 700; // Fixture timeout, milliseconds; real defaults remain longer.
const DELAY_MS = 100; // Fixture async hydration delay, milliseconds.
const RESPONSE_MS = 500; // Milliseconds: a failed navigation must return without awaiting tab metadata.
const FORM = '<div class="login"><label>Username<input name="username"></label><label>Password<input type="password" name="password"></label><button>Submit</button></div>';
const HANDLER = `<script>document.querySelector('.login button').onclick=async()=>{await fetch('/authenticate',{method:'POST',body:JSON.stringify({password:document.querySelector('input[type=password]').value})});document.body.innerHTML='<h1>Logged in successfully</h1><a href="/logout">Log out</a>';}</script>`;

async function fixture(t) {
  if (!await fs.stat(chromium.executablePath()).catch(() => null)) { t.skip('Chromium has not been downloaded'); return; }
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-formless-login-'));
  let submits = 0, leaks = 0;
  const server = http.createServer(async (request, response) => {
    response.setHeader('content-type', 'text/html');
    if (request.url.includes(SECRET)) leaks++;
    if (request.url === '/authenticate') { submits++; response.end('OK'); return; }
    if (request.url === '/denied') { response.statusCode = 403; response.end(); return; }
    if (request.url === '/blank') { response.end('<html><body></body></html>'); return; }
    if (request.url === '/delayed') { response.end(`<script>setTimeout(()=>{document.body.innerHTML=${JSON.stringify(FORM)};${HANDLER.replace('<script>', '').replace('</script>', '')}},${DELAY_MS})</script>`); return; }
    if (request.url === '/ambiguous') { response.end(FORM.replace('</div>', '<button>Submit</button></div>')); return; }
    if (request.url === '/changed') { response.end(FORM + HANDLER); return; }
    if (request.url === '/steps') { response.end('<label>Email<input type="email"></label><button onclick="document.body.innerHTML=\'<label>Access key<input type=password></label><input type=submit value=Go>\'">Next</button>'); return; }
    response.end(FORM + HANDLER);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile'), renderTimeoutMs: RENDER_MS });
  const ctx = { settings: { headless: true }, config: { allowPrivateHosts: true }, signal: new AbortController().signal };
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await fs.rm(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }); });
  return { directory, base, adapter, ctx, counts: () => ({ submits, leaks }) };
}

test('secure sign-in supports one scoped JavaScript login with Submit outside a native form', async t => {
  const live = await fixture(t); if (!live) return;
  const { adapter, base, ctx, counts } = live;
  const plan = await adapter.prepareLogin({ website: `${base}/login` }, ctx);
  assert.equal(await adapter.login(plan, { username: 'student', password: SECRET }, ctx), true);
  assert.deepEqual(counts(), { submits: 1, leaks: 0 });
  await adapter.run({ action: 'open', url: `${base}/ambiguous` }, ctx);
  await assert.rejects(adapter.prepareLogin({ website: base }, ctx), /unambiguous/i);
});

test('a replaced JavaScript login container cannot receive the credential', async t => {
  const live = await fixture(t); if (!live) return;
  const { adapter, base, ctx, counts } = live;
  const plan = await adapter.prepareLogin({ website: `${base}/changed` }, ctx);
  await adapter.page.evaluate(() => { document.querySelector('.login').outerHTML = '<div><input name="username"><input type="password"><button>Submit</button></div>'; });
  await assert.rejects(adapter.login(plan, { username: 'student', password: SECRET }, ctx));
  assert.deepEqual(counts(), { submits: 0, leaks: 0 });
});

test('opening a deferred SPA waits for rendered controls before snapshot and secure sign-in', async t => {
  const live = await fixture(t); if (!live) return;
  const { adapter, base, ctx } = live;
  assert.match(await adapter.run({ action: 'open', url: `${base}/delayed` }, ctx), /Username/);
  const plan = await adapter.prepareLogin({ website: base }, ctx);
  assert.equal(await adapter.login(plan, { username: 'student', password: SECRET }, ctx), true);
});

test('empty HTTP denial and empty success are load failures and cannot become Ready through snapshot or preview', async t => {
  const live = await fixture(t); if (!live) return;
  const { adapter, directory, base, ctx } = live;
  const store = new BrowserPluginStore(path.join(directory, 'browser.json')).load(); store.setEnabled('isolated', true);
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter });
  t.after(() => manager.close());
  const denied = await manager.run({ action: 'open', url: `${base}/denied` }, ctx);
  assert.match(denied, /HTTP 403/);
  assert.equal(manager.last.notice.kind, 'denied');
  assert.equal((await manager.view()).status, 'error');
  assert.match(await manager.run({ action: 'snapshot' }, ctx), /HTTP 403/);
  assert.equal((await manager.view()).status, 'error');
  assert.equal(manager.last.screenshot, null);
  assert.match(await manager.run({ action: 'open', url: `${base}/blank` }, ctx), /did not render/i);
  assert.equal((await manager.view()).status, 'error');
  await adapter.page.evaluate(() => { document.body.innerHTML = '<h1>Delayed render recovered</h1>'; });
  assert.doesNotMatch(await manager.run({ action: 'snapshot' }, ctx), /^Error:/);
  assert.equal((await manager.view()).status, 'ready');
  assert.match(await manager.run({ action: 'open', url: `${base}/login` }, ctx), /Username/);
  assert.equal((await manager.view()).status, 'ready');
});

test('an attention login receipt remains Needs attention in the live session', async t => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-login-attention-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const store = new BrowserPluginStore(path.join(directory, 'browser.json')).load(); store.setEnabled('isolated', true);
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({ tabs: async () => [] }), credentials: { login: async () => ({ type: 'browser_login', status: 'attention', message: 'No login controls' }) } });
  await manager.run({ action: 'login', website: 'https://example.com' }, { browserCredentialAllowed: true });
  assert.equal(manager.last.status, 'error');
  assert.equal(manager.last.notice.kind, 'login');
});

test('a preview started on the preceding tab cannot overwrite a later navigation failure', async t => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-preview-race-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const store = new BrowserPluginStore(path.join(directory, 'browser.json')).load(); store.setEnabled('isolated', true);
  let capture, began;
  const started = new Promise(resolve => { began = resolve; });
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({
    run: async args => { if (args.url?.includes('denied')) throw new Error('Navigation refused: HTTP 403'); return 'Opened'; },
    tabs: async () => [{ id: '1', active: true, url: 'https://example.com' }],
    preview: () => { began(); return new Promise(resolve => { capture = resolve; }); }, close: async () => {},
  }) });
  t.after(() => manager.close());
  await manager.run({ action: 'open', url: 'https://example.com' });
  const view = manager.view(); await started;
  await manager.run({ action: 'open', url: 'https://example.com/denied' });
  capture('data:image/jpeg;base64,b2xk');
  const next = await view;
  assert.equal(next.notice.kind, 'denied');
  assert.equal(next.screenshot, null);
  assert.equal(next.status, 'error');
});

test('a failed navigation returns even when tab metadata never resolves', async t => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-navigation-metadata-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const store = new BrowserPluginStore(path.join(directory, 'browser.json')).load(); store.setEnabled('local', true);
  const manager = new BrowserSessionManager({ store, chromeFactory: () => ({ run: async () => { throw new Error('Navigation refused: HTTP 403'); }, tabs: () => new Promise(() => {}), close: async () => {} }) });
  t.after(() => manager.close());
  const response = await Promise.race([manager.run({ action: 'open', mode: 'local', url: 'https://example.com' }), new Promise((_, reject) => { const timer = setTimeout(() => reject(new Error('navigation waited for tab metadata')), RESPONSE_MS); timer.unref(); })]);
  assert.match(response, /HTTP 403/);
  await manager.tail;
});

test('model-selected refs support username-first and arbitrary submit labels without form detection', async t => {
  const live = await fixture(t); if (!live) return;
  const { adapter, base, ctx } = live;
  const plan = await adapter.prepareCredentials({ website: `${base}/steps` }, ctx);
  const snapshot = await adapter.credentialSnapshot(plan, ctx);
  const ref = (text, label) => text.split('\n').find(line => line.includes(label))?.match(/\[ref=([^\]]+)\]/)?.[1];
  const first = await adapter.fillCredentials(plan, { credential_fields: [{ ref: ref(snapshot, 'Email'), credential: 'username' }], submit_ref: ref(snapshot, 'Next') }, { username: 'student', password: SECRET }, ctx);
  assert.match(first, /Access key/);
  const second = await adapter.fillCredentials(plan, { credential_fields: [{ ref: ref(first, 'Access key'), credential: 'password' }] }, { username: 'student', password: SECRET }, ctx);
  assert.match(second, /value=\[hidden\]/);
  assert.ok(!second.includes(SECRET));
  assert.equal(await adapter.page.locator('input[type=password]').inputValue(), SECRET);
});

test('selected credentials reject stale, non-password and foreign form targets before any fill', async t => {
  const live = await fixture(t); if (!live) return;
  const { adapter, base, ctx } = live;
  const plan = await adapter.prepareCredentials({ website: `${base}/login` }, ctx);
  const snapshot = await adapter.credentialSnapshot(plan, ctx);
  const username = snapshot.match(/\[ref=([^\]]+)\] input Username/)[1];
  await assert.rejects(adapter.fillCredentials(plan, { credential_fields: [{ ref: username, credential: 'password' }] }, { password: SECRET }, ctx));
  assert.equal(await adapter.page.locator('input[name=username]').inputValue(), '');
  await adapter.page.locator('.login').evaluate(node => { node.outerHTML = '<form action="https://other.example/login"><label>Password<input type=password></label></form>'; });
  await assert.rejects(adapter.fillCredentials(plan, { credential_fields: [{ ref: username, credential: 'username' }] }, { username: 'student' }, ctx));
  const fresh = await adapter.credentialSnapshot(plan, ctx);
  const password = fresh.match(/\[ref=([^\]]+)\] input Password/)[1];
  await assert.rejects(adapter.fillCredentials(plan, { credential_fields: [{ ref: password, credential: 'password' }] }, { password: SECRET }, ctx));
  assert.equal(await adapter.page.locator('input[type=password]').inputValue(), '');
});
