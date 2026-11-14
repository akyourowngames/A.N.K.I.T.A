import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DesktopComputerUse, discoverComputerDriver } from '../../desktop/electron/computer-use.mjs';
import { McpStore } from '../../src/integrations/mcp-store.mjs';
import { COMPUTER_MCP_ID, COMPUTER_DIRECT_CONFIG, COMPUTER_TOOLS } from '../../src/integrations/computer-use.mjs';
test('discovery uses the installed manifest and supports an explicit executable without a shell', async () => {
  const calls = [];
  const result = await discoverComputerDriver({ command: '/chosen/cua-driver', env: {}, run: async (...args) => {
    calls.push(args); return { stdout: JSON.stringify({ binary_version: 'fixture', mcp_invocation: { command: '/resolved/cua-driver', args: ['mcp', '--direct'] } }) };
  } });
  assert.equal(calls[0][0], '/chosen/cua-driver'); assert.equal(calls[0][2].windowsHide, true);
  assert.deepEqual(result, { command: '/resolved/cua-driver', args: ['mcp', '--direct'], version: 'fixture' });
  await assert.rejects(discoverComputerDriver({ env: {}, run: async () => ({ stdout: '{}' }) }), /valid MCP launch manifest/);
});

function service(t, overrides = {}) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-computer-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  let connected = false; const calls = [];
  const mcp = { has: () => connected, servers: new Map(), connect: async options => { calls.push(options); connected = true; }, disconnect: async () => { connected = false; }, callToolResult: async () => ({ text: 'healthy', content: [], isError: false }) };
  const s = new DesktopComputerUse({ mcpFile: path.join(dir, 'mcp.json'), mcp,
    platform: 'win32', discover: async () => ({ command: '/installed/driver', args: ['mcp'], version: 'test-version' }), ...overrides });
  return { s, mcp, calls };
}
test('connect uses discovered command, persists a manual native-only connection, and reuses it', async t => {
  const { s, calls } = service(t);
  await Promise.all([s.connect(), s.connect()]); await s.connect();
  assert.equal(calls.length, 1); assert.deepEqual(calls[0].allowedTools, COMPUTER_TOOLS);
  assert.equal(calls[0].terminateTree, false, 'ending computer control must preserve launched desktop apps');
  const record = new McpStore(s.mcpFile).load().find(COMPUTER_MCP_ID);
  assert.equal(record.manualStart, true); assert.equal(record.command, '/installed/driver');
  assert.deepEqual(record.allowedTools, COMPUTER_TOOLS);
  assert.equal(record.terminateTree, false);
  assert.equal((await s.overview()).connected, true);
  await s.stop(); assert.equal((await s.overview()).connected, false);
  assert.equal(new McpStore(s.mcpFile).load().find(COMPUTER_MCP_ID).enabled, false);
});
test('missing driver and unsupported platform do not start or approve anything', async t => {
  const { s, calls } = service(t, { discover: async () => { throw new Error('driver not found'); } });
  assert.match((await s.overview()).error, /not found/);
  await assert.rejects(s.connect(), /not found/); assert.equal(calls.length, 0);
  const other = service(t, { platform: 'linux' }); await assert.rejects(other.s.connect(), /Windows/);
});
test('Stop cancels pending startup and leaves the service disabled', async t => {
  let release; const { s, calls } = service(t, { discover: () => new Promise(resolve => { release = resolve; }) });
  const pending = s.connect(); const rejected = assert.rejects(pending, /abort|cancel/i);
  await new Promise(resolve => setImmediate(resolve)); const stopping = s.stop();
  release({ command: '/installed/driver', args: ['mcp'], version: 'test' }); await stopping; await rejected;
  assert.equal(calls.length, 0);
});
test('health checks surface MCP isError responses', async t => {
  const { s, mcp } = service(t); await s.connect();
  mcp.callToolResult = async () => ({ text: 'capture denied', isError: true });
  await assert.rejects(s.check(), /capture denied/);
});

test('shutdown leaves an inactive minimal MCP host alone', async t => {
  const { s } = service(t, { mcp: { has: () => false } });
  await s.close();
  assert.equal(s.closed, true);
  const hostWithoutDiscovery = service(t, { mcp: {} });
  const store = new McpStore(hostWithoutDiscovery.s.mcpFile).load();
  store.add({ id: COMPUTER_MCP_ID, name: 'Fixture computer', command: '/fixture/driver', manualStart: true });
  await hostWithoutDiscovery.s.close();
  assert.equal(hostWithoutDiscovery.s.closed, true);
  assert.equal(new McpStore(hostWithoutDiscovery.s.mcpFile).load().find(COMPUTER_MCP_ID).enabled, true, 'an inert host must not change another connection configuration');
});
test('desktop shutdown cancels a connection still discovering its executable', async t => {
  const { DesktopEngine } = await import('../../desktop/electron/engine.mjs');
  let release;
  const { s, mcp, calls } = service(t, { discover: () => new Promise(resolve => { release = resolve; }) });
  const pending = s.connect(); const rejected = assert.rejects(pending, /abort|cancel/i);
  await new Promise(resolve => setImmediate(resolve));
  const engine = { computerUse: s, mcp: { closeAll: async () => {} }, browserManager: { close: async () => {} },
    channels: { stopAll: async () => {} }, credentialRequests: { cancelAll: () => {} }, agents: new Map(), approvals: { cancelAll: () => {} }, scheduler: null,
    projectFileWatcher: null, turns: new Map() };
  const closing = DesktopEngine.prototype.close.call(engine);
  release({ command: '/installed/driver', args: ['mcp'], version: 'test' });
  await closing; await rejected;
  assert.equal(calls.length, 0); assert.equal(mcp.has(), false);
});

test('desktop agents authorize connected native computer actions without enabling global automatic approval', async () => {
  const { DesktopEngine } = await import('../../desktop/electron/engine.mjs');
  const item = { id: 'fixture-desktop', name: 'Fixture', persona: '' };
  const engine = { client: {}, config: { autoApprove: false }, teammates: { find: () => item }, agents: new Map(), models: [], model: 'fixture',
    AgentClass: class { constructor(options) { this.config = options.config; this.messages = []; this.state = {}; } },
    assistant: () => ({ context: () => ({}) }),
    desktopSettings: { data: {} }, schedule: () => null, _savedThread: () => ({ messages: [], todos: [] }) };
  const agent = DesktopEngine.prototype.agentFor.call(engine, item.id);
  assert.equal(agent.config[COMPUTER_DIRECT_CONFIG], true);
  assert.equal(agent.config.autoApprove, false);
});
