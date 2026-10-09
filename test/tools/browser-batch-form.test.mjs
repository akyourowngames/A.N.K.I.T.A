import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { chromium } from 'playwright';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-batch-form-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
const { ChromeBrowserAdapter } = await import('../../tools/browser/chrome.mjs');
const { BrowserSessionManager } = await import('../../tools/browser/session.mjs');
const { BrowserPluginStore, chromeMcpCommand, CHROME_MCP_ID } = await import('../../src/integrations/browser-plugins.mjs');
const { McpManager } = await import('../../src/integrations/mcp-manager.mjs');
const TIMEOUT_MS = 60_000; // Milliseconds: real bundled MCP startup and actual native interaction, not provider work.
const VIEWPORT = '1280x800'; // Test-only visible fixture fits without unrelated scroll.
const refFor = (snapshot, label) => {
  const line = snapshot.split('\n').find(line => line.includes('[ref=') && line.replace(/"/g, '').includes(label));
  assert.ok(line, `missing current ${label}`); return line.match(/\[ref=([^\]]+)\]/)[1];
};
test.after(async () => {
  assert.equal(fs.realpathSync(path.dirname(root)), fs.realpathSync(os.tmpdir()));
  await fs.promises.rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
});

for (const mode of ['isolated', 'local']) for (const runtimeV2 of [false, true]) {
  test(`mixed form batch preserves original targets in real ${mode}, receipts=${runtimeV2}`, { timeout: TIMEOUT_MS }, async t => {
    const writes = [];
    const server = http.createServer((req, res) => {
      if (req.method === 'POST') {
        let body = ''; req.on('data', chunk => { body += chunk; });
        req.on('end', () => { writes.push(JSON.parse(body)); res.end('saved'); }); return;
      }
      res.setHeader('content-type', 'text/html');
      const blocked = req.url.includes('blocked'), replaced = req.url.includes('replaced');
      res.end(`<title>Batch fixture</title><form><label>Test first <input name="first"></label><label>Test second <input name="second"></label><label>Test note <input name="note"></label><label>Test class <select name="travelClass"><option>Economy</option><option>Business</option></select></label><label><input name="black" type="checkbox">Black medium</label><label><input name="blue" type="checkbox" ${blocked ? 'disabled' : ''}>Blue large</label><label><input name="quantity" type="radio" value="3">Three items</label><button>Save test</button></form><p id="state"></p><script>if(${replaced})document.querySelector('input[name="first"]').oninput=()=>{const blue=document.querySelector('input[name="blue"]');blue.replaceWith(blue.cloneNode(true));};document.querySelector("form").onsubmit=async event=>{event.preventDefault();const f=event.target;await fetch("/save",{method:"POST",body:JSON.stringify({first:f.first.value,second:f.second.value,note:f.note.value,travelClass:f.travelClass.value,black:f.black.checked,blue:f.blue.checked,quantity:f.quantity.value})});document.querySelector("#state").textContent="Saved test";}</script>`);
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const directory = path.join(root, `${mode}-${runtimeV2}`); fs.mkdirSync(directory);
    const mcp = new McpManager();
    const adapter = mode === 'isolated' ? new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile') }) : new ChromeBrowserAdapter(mcp, {
      ensureConnected: async ctx => {
        const entry = chromeMcpCommand({ connection: 'profile' }).args[0];
        await mcp.connect({ id: CHROME_MCP_ID, command: process.execPath, args: [entry, '--no-usage-statistics', '--no-performance-crux', '--headless', `--viewport=${VIEWPORT}`, `--executablePath=${chromium.executablePath()}`, `--user-data-dir=${path.join(directory, 'profile')}`], signal: ctx.signal, hidden: true, initTimeoutMs: TIMEOUT_MS, requestTimeoutMs: TIMEOUT_MS });
      },
    });
    const store = new BrowserPluginStore(path.join(directory, 'browser.json')).load(); store.setEnabled(mode, true);
    const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter, chromeFactory: () => adapter });
    t.after(async () => { await manager.close(); await mcp.closeAll(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
    const ctx = { settings: { headless: true }, config: { allowPrivateHosts: true, browserRuntimeV2: runtimeV2 } };
    const snapshot = await manager.run({ action: 'open', mode, url: `http://127.0.0.1:${server.address().port}/form` }, ctx);
    const result = await manager.run({ action: 'batch', mode, steps: [
      { action: 'fill_form', fields: [{ ref: refFor(snapshot, 'Test first'), text: 'Synthetic first' }, { ref: refFor(snapshot, 'Test second'), text: 'Synthetic second' }] },
      { action: 'act', op: 'fill', ref: refFor(snapshot, 'Test note'), text: 'Synthetic note' },
      { action: 'act', op: 'select', ref: refFor(snapshot, 'Test class'), text: 'Business' },
      ...['Black medium', 'Blue large', 'Three items', 'Save test'].map(label => ({ action: 'act', op: 'click', ref: refFor(snapshot, label) })),
    ] }, ctx);
    assert.doesNotMatch(result, /Error:|Batch stopped/);
    assert.deepEqual(writes, [{ first: 'Synthetic first', second: 'Synthetic second', note: 'Synthetic note', travelClass: 'Business', black: true, blue: true, quantity: '3' }]);
    console.log(`MIXED_BATCH_FORM_LIVE mode=${mode} runtimeV2=${runtimeV2} writes=1 originalTargets=true`);
    const base = `http://127.0.0.1:${server.address().port}`;
    for (const variant of ['blocked', 'replaced']) {
      const beforeWrites = writes.length;
      const current = await manager.run({ action: 'open', mode, url: `${base}/form?${variant}` }, ctx);
      const refusal = await manager.run({ action: 'batch', mode, steps: [
        { action: 'fill_form', fields: [{ ref: refFor(current, 'Test first'), text: 'Attempted edit' }] },
        { action: 'act', op: 'click', ref: refFor(current, 'Blue large') },
        { action: 'act', op: 'click', ref: refFor(current, 'Save test') },
      ] }, ctx);
      assert.match(refusal, /Error:.*[\s\S]*Batch stopped/); assert.equal(writes.length, beforeWrites, 'no submission or automatic replay after a changed/blocked target');
      assert.match(refusal, /Fresh snapshot:/, 'native preflight refusal provides fresh observed refs');
      if (variant === 'blocked') {
        assert.doesNotMatch(refusal, /Filled 1 fields/);
        const read = await manager.run({ action: 'snapshot', mode, query: 'Test first' }, ctx);
        assert.ok(!read.includes('Attempted edit'), 'a blocked later control prevents the initial edit');
      } else {
        assert.match(refusal, /Filled 1 fields/); assert.doesNotMatch(refusal, /No fields changed/, 'a partial batch must not imply earlier edits disappeared');
      }
      console.log(`BATCH_PREFLIGHT_REFUSAL_LIVE mode=${mode} runtimeV2=${runtimeV2} variant=${variant} extraWrites=0`);
    }
  });
}
