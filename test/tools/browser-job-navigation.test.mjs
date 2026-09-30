import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { chromium } from 'playwright';
import { PlaywrightBrowserAdapter } from '../../tools/browser/playwright.mjs';

test('closing an owned browser marks the guard closed before its socket disconnects', async () => {
  const adapter = new PlaywrightBrowserAdapter();
  const guard = { closing: false, async close() { this.closing = true; } };
  adapter.jobGuard = guard;
  adapter.context = { async close() { assert.equal(guard.closing, true, 'An expected socket close must not fail a completed job'); } };
  await adapter.close(); assert.equal(adapter.context, null); assert.equal(adapter.jobGuard, null);
});

test('concurrent error and scheduler cleanup close one owned context exactly once', async () => {
  const adapter = new PlaywrightBrowserAdapter();
  let closeCount = 0, release;
  const gate = new Promise(resolve => { release = resolve; });
  adapter.jobGuard = { close: async () => {} };
  adapter.context = { close: async () => { closeCount++; await gate; } };
  const first = adapter.close(), second = adapter.close();
  await new Promise(resolve => setImmediate(resolve));
  release(); await Promise.all([first, second]);
  assert.equal(closeCount, 1); assert.equal(adapter.context, null);
});
test('background browser denies redirect destinations before either GET or POST reaches them', async t => {
  if (!fs.existsSync(chromium.executablePath())) return t.skip('Chromium has not been downloaded');
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'job-redirect-')), hits = [];
  let base, frameOrigin;
  const server = http.createServer((request, response) => {
    hits.push(request.url);
    if (request.url.startsWith('/safe')) { response.writeHead(request.url === '/safe-post' ? 307 : 302, { location: '/denied' }); response.end(); }
    else { response.setHeader('content-type', 'text/html'); response.end(request.url === '/embedded' ? `<title>Embedded</title><main>Frame probe</main><iframe src="${frameOrigin}/safe-frame"></iframe>` : '<title>Form</title><form method="post" action="/safe-post"><button>Publish</button></form><a href="/safe-popup" target="_blank">Popup</a>'); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  base = `http://127.0.0.1:${server.address().port}`; frameOrigin = `http://localhost:${server.address().port}`;
  const adapter = new PlaywrightBrowserAdapter({ profile: directory });
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); fs.rmSync(directory, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }); });
  const ctx = { backgroundJob: true, settings: { headless: true }, config: { allowPrivateHosts: true }, authorizeNavigation: async url => { if (new URL(url).pathname === '/denied') throw new Error('Denied destination'); } };
  await assert.rejects(adapter.run({ action: 'open', url: `${base}/safe-get` }, ctx));
  assert.equal(hits.includes('/denied'), false, '302 redirect is blocked before network request');
  await adapter.close(); // A denied navigation ends that run; next probe uses a fresh browser.
  const opened = await adapter.run({ action: 'open', url: `${base}/form` }, ctx);
  const ref = /\[ref=([^\]]+)\] button/.exec(opened)?.[1]; assert.ok(ref);
  await adapter.run({ action: 'act', op: 'click', ref }, ctx).catch(() => {});
  assert.ok(hits.includes('/safe-post')); assert.equal(hits.includes('/denied'), false, '307 POST redirect is blocked before network request');
  await adapter.close();
  const form = await adapter.run({ action: 'open', url: `${base}/form` }, ctx);
  const popupRef = /\[ref=([^\]]+)\] (?:link|a) Popup/.exec(form)?.[1]; assert.ok(popupRef, form);
  const popped = adapter.context.waitForEvent('page');
  await adapter.run({ action: 'act', op: 'click', ref: popupRef }, ctx); const popup = await popped;
  await popup.waitForLoadState('domcontentloaded', { timeout: 5000 }).catch(() => {});
  assert.ok(hits.includes('/safe-popup'), `Popup navigation ran; observed ${hits.join(',')}`);
  assert.equal(hits.includes('/denied'), false, 'popup first navigation and redirected destination are guarded');
  await adapter.close();
  await adapter.run({ action: 'open', url: `${base}/embedded` }, ctx);
  assert.ok(hits.includes('/safe-frame'), 'cross-site frame navigation executed');
  assert.equal(hits.includes('/denied'), false, 'embedded frame redirect is guarded');
  let attempted = false;
  adapter.policyContext = { ...ctx, authorizeRequest: async ({ url }) => { if (new URL(url).pathname === '/denied-fetch') { attempted = true; throw new Error('Denied fetch'); } } };
  await adapter.page.evaluate(async () => { await fetch('/denied-fetch', { method: 'POST' }).catch(() => {}); });
  assert.equal(attempted, true, 'Fetch request reached the permission guard');
  assert.equal(hits.includes('/denied-fetch'), false, 'denied Fetch POST never reaches the server');
});
