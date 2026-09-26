import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { BrowserPluginStore } from '../../src/integrations/browser-plugins.mjs';
import { BrowserSessionManager } from '../../tools/browser/session.mjs';
import { ChromeBrowserAdapter } from '../../tools/browser/chrome.mjs';
import { McpClient } from '../../src/integrations/mcp-client.mjs';
import { PlaywrightBrowserAdapter } from '../../tools/browser/playwright.mjs';
import { BrowserReferenceError, ISOLATED_REF_PATTERN } from '../../tools/browser/refs.mjs';

function storeFor(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'browser-lifecycle-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return new BrowserPluginStore(path.join(dir, 'browser.json')).load();
}

for (const mode of ['isolated', 'local']) {
  test(`${mode}: stale refs keep the browser usable without leaking the recovered snapshot into its view`, async t => {
    const store = storeFor(t); store.setEnabled(mode, true);
    let failed = false, invalidated = 0;
    const adapter = {
      run: async () => {
        if (!failed) return 'opened';
        const error = new BrowserReferenceError('1-0-0', ISOLATED_REF_PATTERN);
        error.preserveRefs = true;
        error.message += '\nFresh snapshot:\n[ref=2-0-0] button Secret page content';
        throw error;
      },
      tabs: async () => [{ id: '1', active: true, title: 'Form', url: 'https://example.com/' }],
      preview: async () => 'data:image/jpeg;base64,aW1hZ2U=',
      invalidate: () => { invalidated++; }, close: async () => {},
    };
    const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter, chromeFactory: () => adapter });
    t.after(() => manager.close());
    await manager.run({ action: 'open', mode }); await manager.view(); failed = true;
    assert.match(await manager.run({ action: 'act', ref: '1-0-0' }), /Fresh snapshot:\n\[ref=2-0-0\]/, 'the agent keeps its recovery refs');
    const view = await manager.view();
    assert.equal(view.status, 'ready');
    assert.equal(view.notice.kind, 'reference');
    assert.ok(!JSON.stringify(view).includes('Secret page content'));
    assert.match(view.screenshot, /^data:image\/jpeg/);
    assert.equal(invalidated, 0, 'fresh recovery refs remain valid');
    failed = false; await manager.run({ action: 'snapshot' });
    assert.equal((await manager.view()).notice, null);
  });
}

test('navigation failure exposes a concise notice, keeps the tab and never becomes a lost connection', async t => {
  const store = storeFor(t); store.setEnabled('isolated', true);
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({
    run: async () => { throw new Error('page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at https://example.com/\nCall log:\n\u001b[2m - navigating to private-page-code\u001b[22m'); },
    tabs: async () => [{ id: '1', active: true, url: 'https://example.com/', title: '' }],
    preview: async () => 'data:image/jpeg;base64,aW1hZ2U=', close: async () => {},
  }) });
  t.after(() => manager.close());
  assert.match(await manager.run({ action: 'open' }), /ERR_HTTP2_PROTOCOL_ERROR/);
  const view = await manager.view();
  assert.equal(view.status, 'ready');
  assert.equal(view.notice.kind, 'navigation');
  assert.ok(!JSON.stringify(view).includes('private-page-code'));
  assert.equal(view.tabs.length, 1);
  assert.match(view.screenshot, /^data:image\/jpeg/);
});
const deadline = promise => Promise.race([promise, new Promise((_, reject) => {
  const timer = setTimeout(() => reject(new Error('did not settle within 500ms')), 500); timer.unref();
})]);

test('disabling the active Chrome backend routes the next open to Playwright', async t => {
  const store = storeFor(t);
  store.setEnabled('isolated', true); store.setEnabled('local', true);
  const calls = [];
  const adapter = mode => ({ run: async () => { calls.push(mode); return mode; }, close: async () => {} });
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter('isolated'), chromeFactory: () => adapter('local') });
  await manager.run({ action: 'open', mode: 'local' });
  store.setEnabled('local', false);
  assert.equal(await manager.run({ action: 'open' }), 'isolated');
  assert.equal(await manager.run({ action: 'open', mode: 'local' }), 'isolated');
  assert.deepEqual(calls, ['local', 'isolated', 'isolated']);
  await manager.close();
});

test('Stop cancels an in-flight browser operation and releases the serial queue', async t => {
  const store = storeFor(t); store.setEnabled('isolated', true);
  let started; const ready = new Promise(resolve => { started = resolve; });
  let closes = 0;
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({
    run: args => args.action === 'open' ? (started(), new Promise(() => {})) : Promise.resolve('next'),
    close: async () => { closes++; },
  }) });
  const controller = new AbortController();
  const pending = manager.run({ action: 'open' }, { signal: controller.signal, browserThreadId: 'one' });
  await ready; controller.abort();
  assert.match(await deadline(pending), /cancel/i);
  assert.equal(await deadline(manager.run({ action: 'tabs' })), 'next');
  assert.ok(closes > 0, 'cancel tears down the adapter so the abandoned action cannot execute later');
  await manager.close();
});

test('Stop cancels a queued browser operation while the user has control', async t => {
  const store = storeFor(t); store.setEnabled('isolated', true);
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({ run: async () => 'ok', close: async () => {} }) });
  await manager.run({ action: 'tabs' }, { browserThreadId: 'chief' }); await manager.takeover(true);
  const controller = new AbortController();
  const pending = manager.run({ action: 'tabs' }, { signal: controller.signal, browserThreadId: 'chief' });
  manager.cancel('chief'); controller.abort();
  assert.match(await deadline(pending), /cancel/i);
  assert.equal(manager.paused, false);
  assert.equal(await deadline(manager.run({ action: 'tabs' }, { browserThreadId: 'chief' })), 'ok');
  await manager.close();
});

test('MCP cancellation rejects immediately, sends a cancellation notification, and clears pending requests', async () => {
  const writes = [];
  const client = new McpClient(); client.child = { stdin: { write: line => writes.push(JSON.parse(line)) } };
  const controller = new AbortController();
  const pending = client.callTool('take_snapshot', {}, { signal: controller.signal });
  controller.abort();
  await assert.rejects(deadline(pending), /abort|cancel/i);
  assert.equal(client.pending.size, 0);
  assert.ok(writes.some(message => message.method === 'notifications/cancelled' && message.params.requestId === 1));
});

test('closing an MCP connection rejects its pending calls instead of abandoning them', async () => {
  const client = new McpClient(); client.child = { stdin: { write() {}, end() {} } };
  const pending = client.callTool('take_snapshot');
  client.child = null;
  await client.close();
  await assert.rejects(deadline(pending), /closed|disconnect/i);
});

test('MCP close observes asynchronous process teardown failures without an unhandled rejection', async () => {
  let terminated = false;
  const diagnostics = [];
  const secret = 'opaque-teardown-credential';
  const client = new McpClient({ env: { API_KEY: secret }, terminateProcess: async () => { terminated = true; throw new Error(`process lookup timed out: ${secret}`); }, onStderr: text => diagnostics.push(text) });
  client.child = { stdin: { end() {} } };
  await client.close();
  assert.equal(terminated, true);
  assert.equal(client.child, null);
  assert.match(diagnostics.join('\n'), /process lookup timed out/);
  assert.ok(!diagnostics.join('\n').includes(secret), 'teardown diagnostics redact configured credentials');
});

test('Chrome connects on demand and reconnects once before a read after losing the browser', async () => {
  let connected = false, connects = 0, fail = false;
  const mcp = {
    has: () => connected,
    disconnect: async () => { connected = false; },
    callTool: async name => {
      if (fail) { fail = false; throw new Error('Protocol error: Connection closed'); }
      return name.endsWith('list_pages') ? '1: https://example.com/ [selected]' : 'uid=1_0 RootWebArea "Example"';
    },
  };
  const adapter = new ChromeBrowserAdapter(mcp, { ensureConnected: async () => { connects++; connected = true; } });
  assert.match(await adapter.run({ action: 'snapshot' }, {}), /Example/);
  fail = true;
  assert.match(await adapter.run({ action: 'snapshot' }, {}), /Example/);
  assert.equal(connects, 2);
  await adapter.close();
});

test('Chrome preview receives JPEG data directly without writing a temporary screenshot', async () => {
  let args;
  const adapter = new ChromeBrowserAdapter({ has: () => true,
    callTool: async name => name.endsWith('__list_pages') ? '1: Example (https://example.com/) [selected]' : 'ok',
    callToolResult: async (_name, value) => {
      args = value; return { raw: { content: [{ type: 'image', mimeType: 'image/jpeg', data: 'aW1hZ2U=' }] } };
    } });
  adapter.pageId = 1;
  assert.equal(await adapter.preview(), 'data:image/jpeg;base64,aW1hZ2U=');
  assert.equal(args.filePath, undefined);
});

test('a failed preview keeps the last good frame while reporting the error', async t => {
  const store = storeFor(t); store.setEnabled('isolated', true);
  let failed = false;
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({
    run: async () => 'ok', tabs: async () => [{ id: '1', active: true }],
    preview: async () => { if (failed) throw new Error('Temporary screenshot failure'); return 'data:image/jpeg;base64,aW1hZ2U='; }, close: async () => {},
  }) });
  await manager.run({ action: 'open' });
  assert.match((await manager.view()).screenshot, /^data:image\/jpeg;base64,/);
  failed = true;
  const view = await manager.view();
  assert.equal(view.status, 'error');
  assert.match(view.screenshot, /^data:image\/jpeg;base64,/, 'one slow tick must not blank the preview');
  await manager.close();
});

test('a failed preview recovers its ready state and never leaves a sticky error', async t => {
  const store = storeFor(t); store.setEnabled('isolated', true);
  let failed = true;
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({
    run: async () => 'ok', tabs: async () => [{ id: '1', active: true }],
    preview: async () => { if (failed) throw new Error('Temporary screenshot failure'); return 'data:image/jpeg;base64,aW1hZ2U='; }, close: async () => {},
  }) });
  await manager.run({ action: 'open' });
  assert.equal((await manager.view()).status, 'error');
  failed = false;
  assert.equal((await manager.view()).status, 'ready');
  await manager.close();
});

test('disabled browser refs are rejected before any fallback interaction can execute', async t => {
  const store = storeFor(t); store.setEnabled('local', true); store.setEnabled('isolated', true);
  let interactions = 0;
  const manager = new BrowserSessionManager({ store, chromeFactory: () => ({ run: async () => 'local', close: async () => {} }), isolatedFactory: () => ({ run: async () => { interactions++; return 'isolated'; }, close: async () => {} }) });
  await manager.run({ action: 'tabs', mode: 'local' });
  store.setEnabled('local', false);
  assert.match(await manager.run({ action: 'act', mode: 'local', op: 'click', ref: '1-1' }), /fresh snapshot/);
  assert.equal(interactions, 0);
  await manager.close();
});

test('slow Playwright previews share one capture until it settles', async () => {
  let calls = 0, finish;
  const image = new Promise(resolve => { finish = resolve; });
  const page = { isClosed: () => false, screenshot: () => { calls++; return image; } };
  const adapter = new PlaywrightBrowserAdapter(); adapter.context = { pages: () => [page] }; adapter.page = page;
  const previews = [adapter.preview(), adapter.preview(), adapter.preview()];
  await Promise.resolve(); assert.equal(calls, 1);
  finish(Buffer.from('image'));
  assert.deepEqual(await Promise.all(previews), Array(3).fill('data:image/jpeg;base64,aW1hZ2U='));
});

test('forgiving spellings reach the adapter in canonical form on the right backend', async t => {
  const store = storeFor(t); store.setEnabled('isolated', true);
  let seen = null, chromeBuilt = 0;
  const manager = new BrowserSessionManager({
    store,
    isolatedFactory: () => ({ run: async args => { seen = args; return 'ok'; }, close: async () => {} }),
    chromeFactory: () => { chromeBuilt++; return { run: async () => 'chrome', close: async () => {} }; },
  });
  assert.equal(await manager.run({ action: 'click', target: '1-0-0', mode: 'headless' }, {}), 'ok');
  assert.equal(seen.action, 'act');
  assert.equal(seen.op, 'click');
  assert.equal(seen.ref, '1-0-0');
  assert.equal(chromeBuilt, 0);
  await manager.close();
});

test('a timed-out call keeps the adapter and its connection instead of tearing them down', async t => {
  const store = storeFor(t); store.setEnabled('local', true);
  let disconnects = 0;
  const mcp = {
    has: () => true,
    disconnect: async () => { disconnects++; },
    callTool: async name => {
      if (name.endsWith('__list_pages')) return '1: Demo (https://example.com/) [selected]';
      if (name.endsWith('__take_snapshot')) { await new Promise(resolve => setTimeout(resolve, 5000)); return 'late'; }
      return 'ok';
    },
  };
  const manager = new BrowserSessionManager({ store, chromeFactory: () => new ChromeBrowserAdapter(mcp) });
  assert.match(await manager.run({ action: 'snapshot', mode: 'local' }, { timeoutMs: 100 }), /timed out/);
  assert.equal(disconnects, 0);
  assert.equal(manager.adapters.has('local'), true);
  await manager.close();
});

test('Stop still detaches the Chrome transport while clearing the adapter', async t => {
  const store = storeFor(t); store.setEnabled('local', true);
  let disconnects = 0;
  const mcp = {
    has: () => true,
    disconnect: async () => { disconnects++; },
    callTool: async (name, _args, opts) => {
      if (name.endsWith('__list_pages')) return '1: Demo (https://example.com/) [selected]';
      if (name.endsWith('__new_page')) {
        await new Promise((_resolve, reject) => {
          const timer = setTimeout(() => reject(new Error('should have been cancelled')), 5000);
          opts?.signal?.addEventListener('abort', () => { clearTimeout(timer); reject(new Error('MCP request cancelled')); });
        });
      }
      return 'ok';
    },
  };
  const manager = new BrowserSessionManager({ store, chromeFactory: () => new ChromeBrowserAdapter(mcp) });
  const controller = new AbortController();
  const pending = manager.run({ action: 'open', mode: 'local', url: 'https://example.com/' }, { signal: controller.signal });
  setTimeout(() => controller.abort(), 50);
  assert.match(await pending, /cancel/i);
  // pending settles when the outer wait releases; the background chain that
  // detaches the transport finishes just behind it.
  await manager.tail;
  assert.equal(disconnects, 1);
  assert.equal(manager.adapters.has('local'), false);
  await manager.close();
});
