import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { McpManager } from '../src/integrations/mcp-manager.mjs';
import { ChromeBrowserAdapter } from '../tools/browser/chrome.mjs';
import { CHROME_MCP_ID, CHROME_MCP_VERSION } from '../src/integrations/browser-plugins.mjs';
import { PlaywrightBrowserAdapter } from '../tools/browser/playwright.mjs';
import { BrowserSessionManager } from '../tools/browser/session.mjs';
import { BrowserPluginStore } from '../src/integrations/browser-plugins.mjs';
import { waitForBrowser } from '../tools/browser/pending.mjs';

const mcp = new McpManager({ log: message => console.log(message) });
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-chrome-live-'));
const connection = { id: CHROME_MCP_ID, command: 'npx', args: ['-y', `chrome-devtools-mcp@${CHROME_MCP_VERSION}`, '--no-usage-statistics', '--no-performance-crux', '--headless', `--user-data-dir=${path.join(directory, 'chrome')}`], hidden: true, initTimeoutMs: 25_000, requestTimeoutMs: 15_000 };
const playwright = new PlaywrightBrowserAdapter({ profile: path.join(directory, 'playwright') });
let notifySlow;
const slowRequested = new Promise(resolve => { notifySlow = resolve; });
const server = http.createServer((request, response) => {
  if (request.url === '/slow') { notifySlow(); return; }
  response.writeHead(200, { 'content-type': 'text/html' });
  response.end('<title>Browser demo</title><label>Name <input></label><button onclick="document.querySelector(\'main\').textContent = \'Hello \' + document.querySelector(\'input\').value">Save</button><main></main><div id="clock" style="font:60px monospace;margin:40px"></div><script>setInterval(()=>document.querySelector("#clock").textContent=Date.now(),25)</script>');
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
try {
  let reconnects = 0;
  const adapter = new ChromeBrowserAdapter(mcp, { ensureConnected: async ctx => {
    reconnects++;
    if (ctx.reconnect) await mcp.disconnect(CHROME_MCP_ID);
    await mcp.connect({ ...connection, signal: ctx.signal });
  } });
  const opened = await adapter.run({ action: 'open', url: 'https://example.com/' }, {});
  console.log(opened.slice(0, 500));
  const snapshot = await adapter.run({ action: 'snapshot' }, {});
  assert.match(snapshot, /Example Domain/);
  assert.match(snapshot, /\[ref=/);
  console.log(snapshot.slice(0, 800));
  const ctx = { config: { allowPrivateHosts: true } };
  await adapter.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}/` }, ctx);
  const form = await adapter.run({ action: 'snapshot' }, ctx);
  const field = /\[ref=([^\]]+)\] textbox/.exec(form)?.[1];
  assert.ok(field, form);
  await adapter.run({ action: 'act', op: 'fill', ref: field, text: 'Ankita' }, ctx);
  const afterFill = await adapter.run({ action: 'snapshot' }, ctx);
  const save = /\[ref=([^\]]+)\] button "Save"/.exec(afterFill)?.[1];
  assert.ok(save, afterFill);
  await adapter.run({ action: 'act', op: 'click', ref: save }, ctx);
  assert.match(await adapter.run({ action: 'snapshot' }, ctx), /Hello Ankita/);
  const preview = await adapter.preview();
  assert.match(preview, /^data:image\/jpeg;base64,/);
  assert.ok(preview.length > 1000, 'Chrome preview has image data');
  await playwright.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}/` }, { ...ctx, settings: { headless: true } });
  for (const [name, backend] of [['Chrome', adapter], ['Playwright', playwright]]) {
    const frames = new Set();
    const started = performance.now();
    for (let index = 0; index < 15; index++) {
      const frameStart = performance.now();
      frames.add(await backend.preview());
      await new Promise(resolve => setTimeout(resolve, Math.max(0, 100 - (performance.now() - frameStart))));
    }
    const fps = 15_000 / (performance.now() - started);
    assert.ok(frames.size >= 10, `${name} preview updates while the page is animating`);
    assert.ok(fps >= 3, `${name} preview is at least 3 FPS on the local demo; measured ${fps.toFixed(1)}`);
    console.log(`${name} measured preview: ${fps.toFixed(1)} FPS, ${frames.size} distinct frames`);
  }
  const saved = await adapter.run({ action: 'screenshot' }, { ...ctx, cwd: process.cwd() });
  assert.equal(saved.type, 'browser_screenshot');
  const file = saved.path;
  assert.ok(fs.existsSync(file), 'Chrome screenshot exists');
  fs.unlinkSync(file);
  await mcp.disconnect(CHROME_MCP_ID);
  const recovered = await adapter.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}/` }, ctx);
  assert.match(recovered, /Browser demo/);
  assert.equal(reconnects, 2, 'Initial connection and later reconnection happen on browser demand');
  const store = new BrowserPluginStore(path.join(directory, 'browser.json')).load();
  store.setEnabled('local', true);
  const manager = new BrowserSessionManager({ store, chromeFactory: () => adapter });
  const controller = new AbortController();
  const pending = manager.run({ action: 'open', mode: 'local', url: `http://127.0.0.1:${server.address().port}/slow` }, { ...ctx, signal: controller.signal, browserThreadId: 'live-test' });
  await waitForBrowser(Promise.race([slowRequested, pending.then(result => { throw new Error(`Slow navigation ended before Stop: ${result}`); })]), { timeoutMs: 20_000 });
  const stoppedAt = performance.now();
  controller.abort();
  assert.match(await pending, /cancel/i);
  assert.ok(performance.now() - stoppedAt < 1000, 'Stop returns within a second during a hanging Chrome navigation');
  await manager.tail;
  assert.equal(mcp.has(CHROME_MCP_ID), false, 'Cancelled Chrome navigation detaches the transport');
  assert.match(await manager.run({ action: 'open', mode: 'local', url: `http://127.0.0.1:${server.address().port}/` }, ctx), /Browser demo/);
  assert.equal(reconnects, 3, 'Chrome reconnects on the next request after Stop');
  await manager.close();
  await adapter.close();
  assert.equal(mcp.has(CHROME_MCP_ID), false, 'Stop detaches the Chrome connection');
  console.log('Chrome MCP browser verified');
} finally { await playwright.close(); await mcp.closeAll(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); fs.rmSync(directory, { recursive: true, force: true }); }
