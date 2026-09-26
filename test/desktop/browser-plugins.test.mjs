import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DesktopBrowserPlugins } from '../../desktop/electron/browser-plugins.mjs';
import { McpStore } from '../../src/integrations/mcp-store.mjs';
import { McpManager } from '../../src/integrations/mcp-manager.mjs';
import { ApprovalRegistry } from '../../desktop/electron/approvals.mjs';

test('Chrome setup records a pinned hidden MCP command and connection mode', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-ui-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const browserFile = path.join(dir, 'browser.json');
  const mcpFile = path.join(dir, 'mcp.json');
  const service = new DesktopBrowserPlugins({ browserFile, mcpFile });
  await service.configureChrome({ connection: 'port', port: 9333 });
  const record = new McpStore(mcpFile).load().find('ankita-chrome');
  assert.equal(record.hidden, true);
  assert.equal(record.manualStart, true);
  assert.ok(record.args.includes('chrome-devtools-mcp@1.10.1'));
  assert.ok(record.args.includes('--no-usage-statistics'));
  assert.equal(record.args.at(-1), '--browserUrl=http://127.0.0.1:9333');
  assert.equal(record.approvedHash, null);
  const overview = await service.overview();
  assert.equal(overview.local.connection, 'port');
});

test('a hidden MCP backing remains callable internally but is not offered to the agent', () => {
  const manager = new McpManager();
  manager.servers.set('ankita-chrome', { id: 'ankita-chrome', hidden: true, tools: [{ name: 'new_page', inputSchema: { type: 'object', properties: {} } }], client: {} });
  assert.equal(manager.has('ankita-chrome'), true);
  assert.deepEqual(manager.specs(), []);
  assert.deepEqual(manager.summaries(), []);
  assert.deepEqual(manager.alwaysOnIds(), []);
});

test('Chrome backing stays off at startup until a browser request or Start connection', async (t) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-manual-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const mcpFile = path.join(dir, 'mcp.json');
  const store = new McpStore(mcpFile).load();
  store.add({ id: 'ankita-chrome', name: 'Chrome local', command: 'npx', args: ['-y', 'chrome-devtools-mcp@1.10.1'], hidden: true, manualStart: true });
  store.markApproved('ankita-chrome');
  const manager = new McpManager();
  await manager.reconcile(new McpStore(mcpFile).load());
  assert.equal(manager.has('ankita-chrome'), false);
});

test('on-demand Chrome startup asks once for the exact command and reuses that approval on reconnect', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-auto-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  let connected = false, connects = 0, requests = 0;
  const mcp = { has: () => connected, disconnect: async () => { connected = false; }, connect: async () => { connects++; connected = true; } };
  const approvals = new ApprovalRegistry(event => { requests++; assert.equal(event.threadId, 'chief'); assert.match(event.detail, /chrome-devtools-mcp@1.10.1/); approvals.respond(event.requestId, 'yes'); });
  const service = new DesktopBrowserPlugins({ browserFile: path.join(dir, 'browser.json'), mcpFile: path.join(dir, 'mcp.json'), mcp, approvals });
  await service.setEnabled({ mode: 'local', enabled: true });
  await Promise.all([service.startChrome({ browserThreadId: 'chief' }), service.startChrome({ browserThreadId: 'chief' })]);
  assert.equal(connects, 1); assert.equal(requests, 1);
  await service.startChrome({ browserThreadId: 'chief', reconnect: true });
  assert.equal(connects, 2); assert.equal(requests, 1);
  await service.setEnabled({ mode: 'local', enabled: false });
  await assert.rejects(service.startChrome(), /Enable Chrome/); assert.equal(connects, 2);
});

test('Stop dismisses the Chrome setup approval and prevents the connection from launching', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-cancel-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  let requested; const request = new Promise(resolve => { requested = resolve; });
  let connects = 0;
  const approvals = new ApprovalRegistry(requested);
  const service = new DesktopBrowserPlugins({ browserFile: path.join(dir, 'browser.json'), mcpFile: path.join(dir, 'mcp.json'), approvals, mcp: { has: () => false, connect: async () => { connects++; } } });
  await service.setEnabled({ mode: 'local', enabled: true });
  const controller = new AbortController();
  const pending = service.startChrome({ signal: controller.signal, browserThreadId: 'chief' });
  await request; controller.abort();
  await assert.rejects(pending, /abort|cancel/i); assert.equal(approvals.pending.size, 0); assert.equal(connects, 0);
});
