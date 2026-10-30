import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// Sandbox before importing anything that reads config.mjs so the default
// MCP_FILE never points at the user's real profile.
const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-desktop-mcp-'));
process.env.CONFIG_DIR = SANDBOX;
test.after(() => fs.rmSync(SANDBOX, { recursive: true, force: true }));

const { DesktopMcp } = await import('../../desktop/electron/mcp.mjs');
const { McpStore, commandHash } = await import('../../src/integrations/mcp-store.mjs');

const json = body => new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });

const npmEntry = (version = '1.2.3', latest = true) => ({
  server: {
    name: 'io.github.example/echo-mcp',
    description: 'Echo tools for MCP',
    version,
    packages: [{ registryType: 'npm', identifier: '@example/echo-mcp', version, transport: { type: 'stdio' } }],
  },
  _meta: {
    'io.modelcontextprotocol.registry/official': { status: 'active', isLatest: latest },
    'io.modelcontextprotocol.registry/publisher-provided': { title: 'Echo' },
  },
});

const remoteEntry = {
  server: {
    name: 'com.example/remote-mcp',
    description: 'Remote-only server',
    version: '1.0.0',
    remotes: [{ type: 'streamable-http', url: 'https://example.com/mcp' }],
  },
  _meta: { 'io.modelcontextprotocol.registry/official': { status: 'active', isLatest: true } },
};

const secretEntry = {
  server: {
    name: 'io.github.example/keyed-mcp',
    description: 'Needs a key',
    version: '0.1.0',
    packages: [{
      registryType: 'npm',
      identifier: '@example/keyed-mcp',
      version: '0.1.0',
      transport: { type: 'stdio' },
      environmentVariables: [{ name: 'API_KEY', description: 'Your key', isRequired: true, isSecret: true }],
    }],
  },
  _meta: { 'io.modelcontextprotocol.registry/official': { status: 'active', isLatest: true } },
};

function registryFetch(entries) {
  return async url => {
    if (String(url).startsWith('https://registry.modelcontextprotocol.io/')) return json({ servers: entries });
    throw new Error(`Unexpected request: ${String(url)}`);
  };
}

function fakeManager({ connect } = {}) {
  const live = new Set();
  return {
    live,
    has: id => live.has(id),
    servers: new Map(),
    connect: connect || (async ({ id }) => { live.add(id); return { id }; }),
    disconnect: async id => { live.delete(id); },
    reconcile: async () => ({ connected: [...live] }),
  };
}

test('an empty store produces an empty server list', () => {
  const mcp = new DesktopMcp({ storeFile: path.join(SANDBOX, 'empty.json') });
  assert.deepEqual(mcp.overview(), { servers: [] });
});

test('servers configured by other sections stay hidden from the MCP page', () => {
  const file = path.join(SANDBOX, 'hidden.json');
  const store = new McpStore(file);
  store.add({ id: 'ankita-chrome', name: 'Chrome', command: 'npx', args: ['x'] });
  store.add({ id: 'user-server', name: 'User', command: 'npx', args: ['y'] });
  const mcp = new DesktopMcp({ storeFile: file });
  assert.deepEqual(mcp.overview().servers.map(server => server.id), ['user-server']);
});

test('manual add validates the command and records no approval until start', () => {
  const file = path.join(SANDBOX, 'manual.json');
  const mcp = new DesktopMcp({ storeFile: file });
  assert.throws(() => mcp.installManual({ name: 'blankspace', command: '   ' }), /command is required/);
  const { record } = mcp.installManual({ name: 'Echo', command: 'npx', args: ['-y', '@example/echo-mcp@1.2.3'] });
  assert.equal(record.id, 'echo');
  assert.equal(record.approved, false);
  assert.equal(record.connected, false);
  assert.deepEqual(record.args, ['-y', '@example/echo-mcp@1.2.3']);
  assert.throws(() => mcp.installManual({ command: 'npx', env: { 'BAD-NAME': 'x' } }), /not a valid environment variable/);
});

test('search returns usable candidates first and explains remote-only entries', async () => {
  const mcp = new DesktopMcp({ storeFile: path.join(SANDBOX, 'search.json'), fetchImpl: registryFetch([remoteEntry, npmEntry()]) });
  const { candidates } = await mcp.search({ query: 'echo' });
  assert.equal(candidates.length, 2);
  assert.equal(candidates[0].registryName, 'io.github.example/echo-mcp');
  assert.equal(candidates[0].usable, true);
  assert.equal(candidates[0].title, 'Echo');
  assert.equal(candidates[0].command, 'npx');
  assert.deepEqual(candidates[0].args, ['@example/echo-mcp@1.2.3']);
  assert.equal(candidates[1].usable, false);
  assert.match(candidates[1].reason, /remote/);
});

test('search rejects an overlong query before touching the network', async () => {
  const mcp = new DesktopMcp({ storeFile: path.join(SANDBOX, 'long.json'), fetchImpl: () => { throw new Error('unexpected network'); } });
  await assert.rejects(mcp.search({ query: 'x'.repeat(101) }), /limited to 100/);
});

test('installing from the registry stores the pinned command and reports missing env', async () => {
  const file = path.join(SANDBOX, 'install.json');
  const mcp = new DesktopMcp({ storeFile: file, fetchImpl: registryFetch([secretEntry]) });
  const result = await mcp.installFromRegistry({ registryName: 'io.github.example/keyed-mcp', env: {} });
  assert.equal(result.record.id, 'keyed-mcp');
  assert.equal(result.record.command, 'npx');
  assert.deepEqual(result.record.args, ['@example/keyed-mcp@0.1.0']);
  assert.deepEqual(result.missingEnv, ['API_KEY']);
  assert.equal(result.record.source, 'io.github.example/keyed-mcp @ 0.1.0');
  const stored = new McpStore(file).load().find('keyed-mcp');
  assert.equal(stored.approvedHash, null, 'installing is configuration, never execution');
  assert.equal(stored.commandHash, commandHash('npx', ['@example/keyed-mcp@0.1.0']));
});

test('install rejects a remote-only server with the registry reason', async () => {
  const mcp = new DesktopMcp({ storeFile: path.join(SANDBOX, 'remote.json'), fetchImpl: registryFetch([remoteEntry]) });
  await assert.rejects(mcp.installFromRegistry({ registryName: 'com.example/remote-mcp' }), /remote/);
});

test('start records approval, connects, and stop disconnects', async () => {
  const file = path.join(SANDBOX, 'start.json');
  const manager = fakeManager();
  const mcp = new DesktopMcp({ storeFile: file, mcp: manager });
  mcp.installManual({ name: 'Echo', command: 'npx', args: ['-y', '@example/echo-mcp@1.2.3'] });

  await mcp.setEnabled({ id: 'echo', enabled: false });
  await assert.rejects(mcp.start({ id: 'echo' }), /Enable this server/, 'disabled servers do not start');
  await mcp.setEnabled({ id: 'echo', enabled: true });

  const started = await mcp.start({ id: 'echo' });
  assert.equal(started.servers[0].connected, true);
  assert.equal(started.servers[0].approved, true);
  assert.equal(manager.live.has('echo'), true);

  const stopped = await mcp.stop({ id: 'echo' });
  assert.equal(stopped.servers[0].connected, false);
  assert.equal(manager.live.has('echo'), false);
});

test('a failed start records the error instead of claiming success', async () => {
  const file = path.join(SANDBOX, 'fail.json');
  const manager = fakeManager({ connect: async () => { throw new Error('spawn npx ENOENT'); } });
  const mcp = new DesktopMcp({ storeFile: file, mcp: manager });
  mcp.installManual({ name: 'Broken', command: 'npx', args: ['@example/broken@1.0.0'] });
  await assert.rejects(mcp.start({ id: 'broken' }), /ENOENT/);
  const view = mcp.overview().servers[0];
  assert.equal(view.connected, false);
  assert.match(view.lastError, /ENOENT/);
});

test('remove disconnects a running server and drops it from the store', async () => {
  const file = path.join(SANDBOX, 'remove.json');
  const manager = fakeManager();
  const mcp = new DesktopMcp({ storeFile: file, mcp: manager });
  mcp.installManual({ name: 'Echo', command: 'npx', args: ['@example/echo-mcp@1.0.0'] });
  await mcp.start({ id: 'echo' });
  const after = await mcp.remove({ id: 'echo' });
  assert.deepEqual(after.servers, []);
  assert.equal(manager.live.has('echo'), false);
  await assert.rejects(mcp.remove({ id: 'echo' }), /no longer configured/);
});
