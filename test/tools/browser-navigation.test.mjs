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

for (const runtimeV2 of [false, true]) test(`catalogued Chrome settles a new tab before its only target navigation (runtimeV2=${runtimeV2})`, async () => {
  const requested = 'http://127.0.0.1/form'; // Synthetic transport URL: no request is sent to this host.
  const createdId = '8', otherId = '9'; // Synthetic native IDs distinguish the created tab from a concurrent unrelated blank tab.
  const tabs = new Map([['7', 'about:blank']]);
  const calls = [];
  const adapter = new ChromeBrowserAdapter({ has: () => true,
    findTool: name => name.endsWith('__navigate_page') ? {} : null,
    callTool: async (name, args) => {
      calls.push({ name, args });
      const listed = () => [...tabs].map(([id, url]) => `${id}: ${url}${id === createdId ? ' [selected]' : ''}`).join('\n');
      if (name.endsWith('__list_pages')) return listed();
      if (name.endsWith('__new_page')) {
        if (args.url !== 'about:blank') return `Error: net::ERR_ABORTED at ${args.url}`;
        tabs.set(createdId, args.url); tabs.set(otherId, args.url);
        return listed();
      }
      if (name.endsWith('__navigate_page')) {
        assert.equal(args.pageId, Number(createdId));
        tabs.set(createdId, args.url); return 'Successfully navigated.';
      }
      if (name.endsWith('__take_snapshot')) return 'uid=8_1 button "Save once"';
      throw new Error(`Unexpected native call: ${name}`);
    },
  }, { ownedTabs: true });
  const result = await adapter.execute({ action: 'open', url: requested }, { config: { allowPrivateHosts: true, browserRuntimeV2: runtimeV2 } });
  assert.equal(result.status, 'executed', JSON.stringify(result.error));
  assert.equal(result.observation.tabId, createdId);
  assert.equal(result.observation.url, requested);
  assert.equal(tabs.get(otherId), 'about:blank');
  assert.deepEqual([...adapter.ownedTabs], [Number(createdId)]);
  assert.equal(calls.filter(call => call.name.endsWith('__new_page')).length, 1);
  assert.equal(calls.filter(call => call.name.endsWith('__navigate_page')).length, 1);
});

for (const boundary of ['ambiguous', 'stopped', 'refused']) test(`staged Chrome open does not guess or replay at the ${boundary} boundary`, async () => {
  const controller = new AbortController(), calls = [];
  let created = false;
  const adapter = new ChromeBrowserAdapter({ has: () => true,
    findTool: name => name.endsWith('__navigate_page') ? {} : null,
    callTool: async (name, args) => {
      calls.push({ name, args });
      if (name.endsWith('__list_pages')) return created ? '1: about:blank\n2: about:blank\n3: about:blank' : '1: about:blank';
      if (name.endsWith('__new_page')) {
        created = true;
        if (boundary === 'stopped') controller.abort();
        return `1: about:blank\n2: about:blank${boundary === 'ambiguous' ? '' : ' [selected]'}\n3: about:blank`;
      }
      if (name.endsWith('__navigate_page')) return 'Unable to navigate in the selected page: fixture denial.';
      throw new Error(`Unexpected native call: ${name}`);
    },
  }, { ownedTabs: true });
  const result = await adapter.execute({ action: 'open', url: 'http://127.0.0.1/form' }, { signal: controller.signal, config: { allowPrivateHosts: true } });
  assert.equal(result.status, 'uncertain');
  assert.equal(calls.filter(call => call.name.endsWith('__new_page')).length, 1);
  assert.equal(calls.filter(call => call.name.endsWith('__navigate_page')).length, boundary === 'refused' ? 1 : 0);
  if (boundary === 'refused') assert.deepEqual([...adapter.ownedTabs], [2]);
  else assert.match(result.error.message, boundary === 'ambiguous' ? /identify.*tab/ : /cancel|abort/i);
});
