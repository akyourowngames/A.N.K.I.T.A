import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { BrowserPluginStore, chromeInstallNeeded, chromeMcpCommand } from '../../src/integrations/browser-plugins.mjs';
import { BrowserSessionManager } from '../../tools/browser/session.mjs';
import * as browser from '../../tools/browser/browser.mjs';
import { PlaywrightBrowserAdapter, guardBrowserUrl, screenshotFile } from '../../tools/browser/playwright.mjs';
import { ChromeBrowserAdapter } from '../../tools/browser/chrome.mjs';
import { normalizeBrowserArgs } from '../../tools/browser/pending.mjs';

test('browser plugin choices persist without enabling either backend by default', (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'browser.json');
  const store = new BrowserPluginStore(file).load();
  assert.equal(store.get('isolated').enabled, false);
  assert.equal(store.get('local').enabled, false);
  store.setEnabled('isolated', true);
  store.setChromeMode('active');
  store.changeSiteRule('isolated', 'allow', '*.example.com', true);
  store.changeSiteRule('isolated', 'block', 'bad.example.com', true);
  const loaded = new BrowserPluginStore(file).load();
  assert.equal(loaded.get('isolated').enabled, true);
  assert.equal(loaded.get('local').connection, 'active');
  assert.deepEqual(loaded.get('isolated').allowedSites, ['*.example.com']);
  assert.deepEqual(loaded.get('isolated').blockedSites, ['bad.example.com']);
  assert.throws(() => loaded.changeSiteRule('isolated', 'allow', 'https://example.com/path', true), /Enter a domain/);
  assert.throws(() => loaded.setChromeMode('unknown'), /connection mode/i);
});

test('screenshot paths are unique and old captures are pruned without touching other files', t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-shot-names-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const folder = path.join(dir, 'downloaded-images');
  fs.mkdirSync(folder, { recursive: true });
  for (let i = 0; i < 55; i++) {
    const f = path.join(folder, `browser-old-${i}.png`);
    fs.writeFileSync(f, 'x');
    fs.utimesSync(f, new Date(Date.now() - (60 - i) * 1000), new Date(Date.now() - (60 - i) * 1000));
  }
  fs.writeFileSync(path.join(folder, 'notes.txt'), 'keep');
  fs.writeFileSync(path.join(folder, 'other.png'), 'keep');
  const a = screenshotFile(dir), b = screenshotFile(dir);
  assert.notEqual(a, b, 'parallel captures must not share a filename');
  const captures = fs.readdirSync(folder).filter(name => /^browser-.*\.png$/.test(name));
  assert.ok(captures.length <= 50, `captures pruned to the cap, found ${captures.length}`);
  assert.ok(fs.existsSync(path.join(folder, 'notes.txt')));
  assert.ok(fs.existsSync(path.join(folder, 'other.png')));
});

test('takeover clicks are bounded by the capture viewport', async () => {
  const seen = [];
  const adapter = new PlaywrightBrowserAdapter();
  const fake = { isClosed: () => false, mouse: { click: async (x, y) => { seen.push([x, y]); }, wheel: async () => {} }, keyboard: { type: async () => {}, press: async () => {} } };
  adapter.context = { pages: () => [fake] };
  adapter.page = fake;
  await assert.rejects(adapter.userInput({ kind: 'click', x: 2000, y: 10 }), /Invalid browser coordinates/);
  await adapter.userInput({ kind: 'click', x: 100, y: 100 });
  assert.deepEqual(seen, [[100, 100]]);
});

test('forgiving browser spellings normalize to the canonical form', () => {
  assert.deepEqual(normalizeBrowserArgs({ action: 'click', target: '1-0-0' }), { action: 'act', op: 'click', target: '1-0-0', ref: '1-0-0' });
  assert.deepEqual(normalizeBrowserArgs({ action: 'act', op: 'fill', ref: 'r', target: 'ignored' }), { action: 'act', op: 'fill', ref: 'r', target: 'ignored' });
  assert.deepEqual(normalizeBrowserArgs({ action: 'open', mode: 'headless' }), { action: 'open', mode: 'isolated' });
  assert.deepEqual(normalizeBrowserArgs({ action: 'batch', steps: [{ action: 'click', target: 'r' }] }), { action: 'batch', steps: [{ action: 'act', op: 'click', target: 'r', ref: 'r' }] });
  assert.deepEqual(normalizeBrowserArgs({ action: 'snapshot' }), { action: 'snapshot' });
  assert.equal(browser.needsApproval({ action: 'click', op: 'click', ref: 'r' }), true, 'alias must not bypass approval');
  assert.equal(browser.readOnly({ action: 'click' }), false);
});

test('act falls back to the marked element when the page changed since the snapshot', async () => {
  let clicked = false;
  const fake = {
    isClosed: () => false,
    isDetached: () => false,
    url: () => 'about:blank',
    evaluate: async () => 99,
    locator: sel => sel === '[data-ankita-ref="1-0-0"]'
      ? { count: async () => 1, click: async () => { clicked = true; } }
      : { count: async () => 0 },
  };
  const adapter = new PlaywrightBrowserAdapter();
  adapter.context = { pages: () => [fake] };
  adapter.page = fake;
  adapter.refState = { serial: 1, page: fake, refs: new Map([['1-0-0', { frame: fake, url: fake.url() }]]) };
  assert.match(await adapter.run({ action: 'act', op: 'click', ref: '1-0-0' }, {}), /click complete/);
  assert.equal(clicked, true);
  await assert.rejects(adapter.run({ action: 'act', op: 'click', ref: 'gone' }, {}), /Unknown browser ref/);
});

test('uncached Chrome MCP package means a cold install on connect', () => {
  const { args } = chromeMcpCommand({ connection: 'profile', port: 9222 });
  assert.equal(chromeInstallNeeded(args, () => null), true, 'nothing cached: budget the download');
  assert.equal(chromeInstallNeeded(args, () => '/cache/entry.js'), false, 'cached: warm handshake only');
  assert.equal(chromeInstallNeeded([]), true, 'no spec: assume cold');
});

test('site rules block navigation before a network request', async () => {
  await assert.rejects(guardBrowserUrl('https://bad.example.com/', { settings: { blockedSites: ['bad.example.com'] } }), /blocked by a browser site rule/);
  await assert.rejects(guardBrowserUrl('https://other.example/', { settings: { allowedSites: ['example.com'] } }), /outside this browser's allowed sites/);
});

test('browser tool is deferred and approval is limited to page-changing operations', () => {
  assert.equal(browser.name, 'browser');
  assert.equal(browser.needsApproval({ action: 'snapshot' }), false);
  assert.equal(browser.needsApproval({ action: 'open' }), false);
  assert.equal(browser.needsApproval({ action: 'act', op: 'fill' }), true);
  assert.equal(browser.needsApproval({ action: 'act', op: 'click' }), true);
  assert.match(browser.approval({ action: 'act', op: 'fill', ref: '3-1', text: 'secret' }), /fill/i);
  assert.doesNotMatch(browser.approval({ action: 'act', op: 'fill', ref: '3-1', text: 'secret' }), /secret/);
  assert.doesNotMatch(JSON.stringify(browser.display({ action: 'act', op: 'fill', ref: '3-1', text: 'secret' })), /secret/);
});

test('manager refuses a disabled mode before constructing its browser', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const store = new BrowserPluginStore(path.join(dir, 'browser.json')).load();
  let constructed = 0;
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => { constructed++; return {}; } });
  const result = await manager.run({ action: 'open', url: 'https://example.com', mode: 'isolated' }, {});
  assert.match(result, /Enable Playwright Browser/i);
  assert.equal(constructed, 0);
});

test('manager keeps one backend alive, serializes actions, and halts a batch at its first error', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const store = new BrowserPluginStore(path.join(dir, 'browser.json')).load();
  store.setEnabled('isolated', true);
  const calls = [];
  let builds = 0;
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => {
    builds++;
    return { run: async (args) => { calls.push(args.action); if (args.action === 'act') throw new Error('stale ref; re-read the page'); return `${args.action} ok`; }, close: async () => {} };
  } });
  const result = await manager.run({ action: 'batch', steps: [{ action: 'open', url: 'https://example.com' }, { action: 'act', op: 'click', ref: 'old' }, { action: 'tabs' }] }, {});
  assert.match(result, /stale ref; re-read the page/);
  assert.deepEqual(calls, ['open', 'act']);
  assert.equal(builds, 1);
  assert.equal(await manager.run({ action: 'tabs' }, {}), 'tabs ok');
  assert.equal(builds, 1);
  await manager.close();
});

test('takeover pauses agent browser actions until hand back', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const store = new BrowserPluginStore(path.join(dir, 'browser.json')).load();
  store.setEnabled('isolated', true);
  let actions = 0;
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({ run: async () => { actions++; return 'done'; }, tabs: async () => [], close: async () => {} }) });
  await manager.run({ action: 'tabs' });
  await manager.takeover(true);
  const pending = manager.run({ action: 'tabs' });
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(actions, 1);
  await manager.takeover(false);
  assert.equal(await pending, 'done');
  assert.equal(actions, 2);
  await manager.close();
});

test('Chrome adapter without a connection says so instead of reporting no tab', async () => {
  const adapter = new ChromeBrowserAdapter(null);
  await assert.rejects(adapter.run({ action: 'screenshot' }, {}), /Chrome is not connected/);
  await assert.rejects(adapter.preview(), /Chrome is not connected/);
});

test('Chrome preview drops a closed tab and uses the fresh active one', async () => {
  let lists = 0;
  const mcp = {
    has: () => true,
    callTool: async name => {
      if (name.endsWith('__list_pages')) { lists++; return '1: Fresh (https://example.com/) [selected]'; }
      return 'ok';
    },
    callToolResult: async (_full, args) => args.pageId !== 1
      ? { isError: true, text: 'Error: no such page' }
      : { raw: { content: [{ type: 'image', mimeType: 'image/jpeg', data: 'aW1hZ2U=' }] } },
  };
  const adapter = new ChromeBrowserAdapter(mcp);
  adapter.cachedTabs = [{ id: '9', url: 'https://old.example/', title: 'Old', active: true }];
  adapter.pageId = 9;
  assert.equal(await adapter.preview(), 'data:image/jpeg;base64,aW1hZ2U=');
  assert.ok(lists >= 1);
  assert.equal(adapter.pageId, 1);
});

test('Chrome read-only actions retry once after a stale tab instead of failing', async () => {
  let lists = 0, snaps = 0;
  const mcp = {
    has: () => true,
    callTool: async name => {
      if (name.endsWith('__list_pages')) { lists++; return '1: Demo (https://example.com/) [selected]'; }
      if (name.endsWith('__take_snapshot')) { snaps++; if (snaps === 1) throw new Error('No such page 1'); return 'uid=1_0 RootWebArea "Demo"'; }
      return 'ok';
    },
  };
  const adapter = new ChromeBrowserAdapter(mcp);
  assert.match(await adapter.run({ action: 'snapshot' }, {}), /RootWebArea "Demo"/);
  assert.equal(lists, 2);
  assert.equal(snaps, 2);
});

test('Chrome adapter maps MCP snapshot UIDs to expiring browser refs', async () => {
  const calls = [];
  let disconnected = false;
  const mcp = {
    has: id => id === 'ankita-chrome',
    disconnect: async id => { if (id === 'ankita-chrome') disconnected = true; },
    callTool: async (name, args) => {
      calls.push({ name, args });
      if (name.endsWith('__new_page') || name.endsWith('__list_pages')) return '## Pages\n1: about:blank\n2: Example Domain (https://example.com/) [selected]';
      if (name.endsWith('__take_snapshot')) return 'uid=1_0 RootWebArea "Example"\n  uid=1_1 textbox "Name"';
      return 'ok';
    },
  };
  const adapter = new ChromeBrowserAdapter(mcp);
  await adapter.run({ action: 'open', url: 'https://example.com/' }, {});
  const snapshot = await adapter.run({ action: 'snapshot' }, {});
  const ref = /\[ref=([^\]]+)\] textbox/.exec(snapshot)?.[1];
  assert.ok(ref, snapshot);
  assert.match(await adapter.run({ action: 'act', op: 'fill', ref, text: 'Ankita' }, {}), /fill complete/);
  await assert.rejects(adapter.run({ action: 'act', op: 'fill', ref, text: 'again' }, {}), /Stale ref/);
  assert.ok(calls.some(call => call.name.endsWith('__fill') && call.args.uid === '1_1'));
  await adapter.close();
  assert.equal(disconnected, true);
});

test('real Chromium opens a page, fills a form, and rejects stale refs', async (t) => {
  const { chromium } = await import('playwright');
  if (!fs.existsSync(chromium.executablePath())) return t.skip('Chromium has not been downloaded');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-live-'));
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { 'content-type': 'text/html' });
    response.end('<title>Demo form</title><label>Name <input id="name"></label><button onclick="document.querySelector(\'main\').textContent = document.querySelector(\'#name\').value">Save</button><main></main>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const store = new BrowserPluginStore(path.join(dir, 'browser.json')).load();
  store.setEnabled('isolated', true);
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => new PlaywrightBrowserAdapter({ profile: path.join(dir, 'profile') }) });
  t.after(async () => { await manager.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); fs.rmSync(dir, { recursive: true, force: true }); });
  const ctx = { config: { allowPrivateHosts: true }, cwd: dir };
  const opened = await manager.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}` }, ctx);
  assert.match(opened, /Demo form/);
  const first = await manager.run({ action: 'snapshot' }, ctx);
  const input = /\[ref=([^\]]+)\] input/.exec(first)?.[1];
  assert.ok(input, first);
  assert.match(await manager.run({ action: 'act', op: 'fill', ref: input, text: 'Ankita' }, ctx), /fill complete/);
  assert.match(await manager.run({ action: 'act', op: 'click', ref: input }, ctx), /Stale ref/);
  const second = await manager.run({ action: 'snapshot' }, ctx);
  const button = /\[ref=([^\]]+)\] button Save/.exec(second)?.[1];
  assert.ok(button, second);
  assert.match(await manager.run({ action: 'act', op: 'click', ref: button }, ctx), /click complete/);
  assert.equal((await manager.run({ action: 'read' }, ctx)).trim(), 'Name Save\nAnkita');
  assert.match((await manager.view()).screenshot, /^data:image\/jpeg;base64,/);
  const shot = JSON.parse(await manager.run({ action: 'screenshot' }, ctx));
  assert.equal(shot.type, 'browser_screenshot');
  assert.ok(fs.existsSync(shot.path));
  assert.ok(shot.bytes > 0);
  assert.match(shot.note, /do not open it with read_file/);
  await manager.close();
});
