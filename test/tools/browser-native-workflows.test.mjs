import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-native-browser-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const { chromium } = await import('playwright');
const { McpManager } = await import('../../src/integrations/mcp-manager.mjs');
const { chromeMcpCommand, CHROME_MCP_ID } = await import('../../src/integrations/browser-plugins.mjs');
const { ChromeBrowserAdapter } = await import('../../tools/browser/chrome.mjs');
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));

test('real approved Chrome handles a prompt once and reads its resulting page', async t => {
  let writes = 0;
  const server = http.createServer((req, res) => {
    if (req.method === 'POST') { writes++; res.end('saved'); return; }
    res.setHeader('content-type', 'text/html');
    res.end('<title>Native prompt</title><button onclick="const note=prompt(\'Write a note?\');if(note!==null)fetch(\'/save\',{method:\'POST\',body:note}).then(()=>document.querySelector(\'main\').textContent=\'Saved note\')">Note</button><main></main>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const mcp = new McpManager();
  const adapter = new ChromeBrowserAdapter(mcp, { ensureConnected: async ctx => {
    const entry = chromeMcpCommand({ connection: 'profile' }).args[0];
    await mcp.connect({ id: CHROME_MCP_ID, command: process.execPath, args: [entry, '--no-usage-statistics', '--no-performance-crux', '--headless', `--executablePath=${chromium.executablePath()}`, `--user-data-dir=${path.join(root, 'chrome')}`], signal: ctx.signal, initTimeoutMs: 25_000, requestTimeoutMs: 15_000, hidden: true });
  } });
  t.after(async () => { await adapter.close(); await mcp.closeAll(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const ctx = { config: { browserRuntimeV2: true, allowPrivateHosts: true } };
  const opened = await adapter.execute({ action: 'open', url: `http://127.0.0.1:${server.address().port}/` }, ctx);
  assert.equal(opened.status, 'executed');
  assert.equal(opened.observation.capabilities.dialogs, true);
  const clicked = await adapter.execute({ action: 'act', op: 'click', ref: opened.observation.controls.find(control => control.name === 'Note').ref }, ctx);
  assert.equal(clicked.status, 'uncertain');
  assert.equal(clicked.attention.dialog.type, 'prompt');
  assert.equal(writes, 0);
  const pending = await adapter.execute({ action: 'snapshot' }, ctx);
  assert.equal(pending.status, 'executed', JSON.stringify(pending.error));
  assert.match(pending.output, /handle_dialog/);
  const accepted = await adapter.execute({ action: 'handle_dialog', decision: 'accept', prompt_text: 'fixture note' }, ctx);
  assert.equal(accepted.status, 'executed');
  const read = await adapter.execute({ action: 'find', query: 'Saved note' }, ctx);
  assert.match(read.output, /Saved note/);
  assert.equal(writes, 1);
  const unsupported = await adapter.execute({ action: 'downloads' }, ctx);
  assert.equal(unsupported.status, 'failed');
  assert.equal(opened.observation.capabilities.downloads, false);
  console.log('CHROME_PROMPT_NATIVE_LIVE', JSON.stringify({ writes, promptDecision: accepted.status, unsupportedTransfers: true }));
});
