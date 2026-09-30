import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { chromium } from 'playwright';
import { PlaywrightBrowserAdapter } from '../../tools/browser/playwright.mjs';
import { credentialOrigin } from '../../src/integrations/browser-credentials.mjs';
import * as browser from '../../tools/browser/browser.mjs';
import { normalizeBrowserArgs } from '../../tools/browser/pending.mjs';
import { BrowserSessionManager } from '../../tools/browser/session.mjs';
import { BrowserPluginStore } from '../../src/integrations/browser-plugins.mjs';
const SECRET = 'login-test-only-password';

test('login without a website binds the actual selected tab before vault lookup', async t => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-login-origin-'));
  t.after(async () => { assert.equal(await fs.realpath(path.dirname(directory)), await fs.realpath(os.tmpdir())); await fs.rm(directory, { recursive: true, force: true }); });
  const store = new BrowserPluginStore(path.join(directory, 'plugins.json')).load(); store.setEnabled('isolated', true);
  const seen = [], tabs = [{ id: '1', url: 'https://first.example/sign-in', active: false }, { id: '2', url: 'https://current.example/login', active: true }];
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({ tabs: async () => tabs }), credentials: { login: async (_adapter, args) => { seen.push(args.website); return { status: 'available' }; } } });
  const context = { browserCredentialAllowed: true, authorizeBrowser: async (_args, page) => { assert.equal(page.url, seen.length ? tabs[0].url : tabs[1].url); } };
  assert.doesNotMatch(await manager.run({ action: 'login' }, context), /^Error/);
  assert.doesNotMatch(await manager.run({ action: 'login', tab: '1' }, context), /^Error/);
  assert.deepEqual(seen, [tabs[1].url, tabs[0].url]);
});

test('explicit website login does not need a tab probe before entering its secure wait', async t => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-explicit-login-'));
  t.after(async () => { assert.equal(await fs.realpath(path.dirname(directory)), await fs.realpath(os.tmpdir())); await fs.rm(directory, { recursive: true, force: true }); });
  const store = new BrowserPluginStore(path.join(directory, 'plugins.json')).load(); store.setEnabled('isolated', true);
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({}), credentials: { login: async (_adapter, args) => ({ status: 'available', website: args.website }) } });
  const result = await manager.run({ action: 'login', website: 'https://example.com/sign-in' }, { browserCredentialAllowed: true });
  assert.equal(JSON.parse(result).status, 'available');
});
test('login schema redacts unexpected secret input and exact-origin validation refuses unsafe URLs', () => {
  assert.equal(browser.needsApproval({ action: 'login' }), true);
  assert.equal(normalizeBrowserArgs({ action: 'signin' }).action, 'login');
  assert.ok(!JSON.stringify(browser.display({ action: 'login', website: 'https://example.com', password: SECRET, fields: [{ text: SECRET }] })).includes(SECRET));
  assert.ok(!browser.approval({ action: 'login', password: SECRET }).includes(SECRET));
  for (const website of ['', 'http://example.com', 'https://user:pass@example.com', 'file:///tmp']) assert.throws(() => credentialOrigin(website));
  assert.equal(credentialOrigin('Example.com/login'), 'https://example.com');
  assert.notEqual(credentialOrigin('https://login.example.com'), credentialOrigin('https://example.com'));
});

test('malformed model credential selections remain renderable in live and saved tool displays', () => {
  for (const credential_fields of ['bad', [null], [{ password: SECRET }]]) {
    assert.doesNotThrow(() => browser.display({ action: 'login', credential_fields }));
    assert.ok(!JSON.stringify(browser.display({ action: 'login', credential_fields })).includes(SECRET));
  }
});
test('real Playwright login binds one form, confirms sign-in, rejects unsafe/ambiguous controls, and never submits a GET password', async t => {
  if (!await fs.stat(chromium.executablePath()).catch(() => null)) return t.skip('Chromium is not downloaded');
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-login-live-'));
  let leakedQueries = 0, submits = 0;
  const form = '<form method="post"><label>Username<input name="username"></label><label>Password<input name="password" type="password" autocomplete="current-password"></label><button>Sign in</button></form>';
  const server = http.createServer((request, response) => {
    if (request.url.includes(SECRET)) leakedQueries++;
    if (request.method === 'POST') { submits++; response.end('<h1>Signed in</h1><button>Sign out</button>'); return; }
    response.setHeader('content-type', 'text/html');
    if (request.url === '/ambiguous') return response.end(form + form);
    if (request.url === '/foreign') return response.end(form.replace('<form method="post">', '<form method="post" action="https://other.example/login">'));
    if (request.url === '/signup') return response.end(form.replace('current-password', 'new-password'));
    if (request.url === '/get') return response.end(form.replace('method="post"', 'method="get"'));
    if (request.url === '/override-get') return response.end(form.replace('<button>', '<button formmethod="get">'));
    if (request.url === '/override-foreign') return response.end(form.replace('<button>', '<button formaction="https://other.example/login">'));
    if (request.url === '/spa') return response.end(form.replace('method="post"', '') + '<script>document.querySelector("form").onsubmit=async event=>{event.preventDefault();const response=await fetch("/login",{method:"POST"});document.body.innerHTML=await response.text();}</script>');
    response.end(form);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const base = `http://127.0.0.1:${server.address().port}`;
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile') });
  const ctx = { config: { allowPrivateHosts: true }, settings: { headless: true }, signal: new AbortController().signal };
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await fs.rm(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }); });
  const plan = await adapter.prepareLogin({ website: `${base}/login` }, ctx);
  const value = { username: 'fixture-user', password: SECRET };
  assert.equal(await adapter.login(plan, value, ctx), true); assert.equal(value.password, ''); assert.equal(submits, 1);
  for (const route of ['ambiguous', 'foreign', 'signup']) { await adapter.run({ action: 'open', url: `${base}/${route}` }, ctx); await assert.rejects(adapter.prepareLogin({ website: base }, ctx)); }
  await adapter.run({ action: 'open', url: `${base}/spa` }, ctx);
  assert.equal(await adapter.login(await adapter.prepareLogin({ website: base }, ctx), { username: 'fixture-user', password: SECRET }, ctx), true, 'SPA handlers work without native GET submission');
  await adapter.run({ action: 'open', url: `${base}/get` }, ctx);
  const getPlan = await adapter.prepareLogin({ website: base }, ctx);
  await adapter.login(getPlan, { username: 'fixture-user', password: SECRET }, ctx);
  assert.equal(leakedQueries, 0, 'a default GET must never put a password in the URL');
  assert.ok(!adapter.page.url().includes(SECRET));
  await adapter.run({ action: 'open', url: `${base}/override-get` }, ctx);
  await adapter.login(await adapter.prepareLogin({ website: base }, ctx), { username: 'fixture-user', password: SECRET }, ctx);
  assert.equal(leakedQueries, 0, 'a submitter override must never put a password in a query');
  await adapter.run({ action: 'open', url: `${base}/override-foreign` }, ctx);
  await assert.rejects(adapter.prepareLogin({ website: base }, ctx), /origin/i);
  await adapter.run({ action: 'open', url: `${base}/login` }, ctx);
  const restricted = { ...ctx, settings: { ...ctx.settings, blockedSites: ['127.0.0.1'] } };
  await assert.rejects(adapter.prepareLogin({ website: base }, restricted), /blocked/i, 'an existing page is still subject to current site policy');
});
