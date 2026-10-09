import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-navigation-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
const { ChromeBrowserAdapter } = await import('../../tools/browser/chrome.mjs');
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));

test('live navigate/back/forward keep the same tab and refuse old document refs', async t => {
  const server = http.createServer((req, res) => {
    if (req.url === '/redirect') { res.writeHead(302, { location: '/b' }); res.end(); return; }
    res.setHeader('content-type', 'text/html'); res.end(`<title>${req.url}</title><button>Page ${req.url}</button>`);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'profile') });
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const url = `http://127.0.0.1:${server.address().port}`, ctx = { config: { allowPrivateHosts: true }, settings: { headless: true } };
  const first = await adapter.run({ action: 'open', url: `${url}/a` }, ctx);
  const ref = /\[ref=([^\]]+)\]/.exec(first)[1], tab = (await adapter.tabs())[0].id;
  const next = await adapter.execute({ action: 'navigate', tab, url: `${url}/redirect` }, ctx);
  assert.equal(next.status, 'executed');
  assert.equal(adapter.page.url(), `${url}/b`);
  assert.equal((await adapter.tabs()).length, 1);
  await assert.rejects(adapter.run({ action: 'act', op: 'click', ref }, ctx), /Stale ref/);
  await adapter.run({ action: 'back', tab }, ctx); assert.equal(adapter.page.url(), `${url}/a`);
  await adapter.run({ action: 'forward', tab }, ctx); assert.equal(adapter.page.url(), `${url}/b`);
  await assert.rejects(adapter.run({ action: 'navigate', tab, url: 'file:///unapproved' }, ctx), /HTTP/);
  assert.equal(adapter.page.url(), `${url}/b`);
  console.log('NAVIGATION_HISTORY_LIVE', JSON.stringify({ tabs: (await adapter.tabs()).length, backForward: true, redirect: true, staleRefRefused: true }));
});

test('Chrome uses approved native navigation and refuses failed native receipts', async () => {
  const calls = [];
  let failed = false;
  const adapter = new ChromeBrowserAdapter({ has: () => true, callTool: async (name, args) => {
    calls.push({ name, args });
    if (name.endsWith('__list_pages')) return '1: Page (http://127.0.0.1/) [selected]';
    if (name.endsWith('__navigate_page')) return failed ? 'Unable to navigate in the selected page: fixture failure.' : 'Successfully navigated.';
    return 'uid=1_1 button "Read"';
  } });
  const ctx = { config: { allowPrivateHosts: true } };
  const result = await adapter.execute({ action: 'navigate', url: 'http://127.0.0.1/b' }, ctx);
  assert.equal(result.status, 'executed');
  assert.equal(calls.find(call => call.name.endsWith('__navigate_page')).args.type, 'url');
  failed = true;
  const refused = await adapter.execute({ action: 'back' }, ctx);
  assert.equal(refused.status, 'uncertain');
  assert.match(refused.error.message, /Unable to navigate/);
  assert.equal(calls.filter(call => call.name.endsWith('__new_page')).length, 0);
});
