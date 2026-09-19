import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const SANDBOX = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-mcp2-'));
process.env.CONFIG_DIR = SANDBOX;
test.after(() => fs.rmSync(SANDBOX, { recursive: true, force: true }));

const { McpStore, commandHash, describeServer, MCP_VERSION } = await import('../src/mcp-store.mjs');
const { McpManager } = await import('../src/mcp-manager.mjs');
const { Daemon } = await import('../src/daemon.mjs');
const manage = await import('../tools/mcp-manage.mjs');
const { MCP_FILE } = await import('../src/config.mjs');
const { RoutineStore } = await import('../src/routines.mjs');

const newStore = (t) => {
  const file = path.join(SANDBOX, `mcp-${Math.random().toString(36).slice(2)}.json`);
  return new McpStore(file).load();
};

/* ------------------------------ the store ------------------------------- */

test('a missing or malformed store loads empty', () => {
  const p = path.join(SANDBOX, 'broken.json');
  assert.deepEqual(new McpStore(p).load().servers, []);
  fs.writeFileSync(p, 'not json at all');
  const s = new McpStore(p).load();
  assert.deepEqual(s.servers, []);
  assert.equal(s.data.version, MCP_VERSION);
});

test('adding needs a command and ids do not collide', (t) => {
  const s = newStore(t);
  assert.throws(() => s.add({ name: 'nope' }), /command is required/);
  const first = s.add({ name: 'Everything', command: 'npx', args: ['-y', 'pkg'] });
  assert.equal(first.id, 'everything');
  assert.equal(first.enabled, true);
  assert.equal(first.approvedAt, null, 'nothing is approved on arrival');
  assert.throws(() => s.add({ name: 'everything', command: 'npx' }), /already exists/);
});

test('approval is bound to the command, not the server name', (t) => {
  const s = newStore(t);
  const rec = s.add({ name: 'x', command: 'npx', args: ['-y', 'thing@1.2.3'] });
  assert.equal(s.isApproved(rec), false);
  s.markApproved(rec.id);
  assert.equal(s.isApproved(s.find('x')), true);

  // Same name, different version: the old yes must not carry over.
  const changed = s._fresh().find('x');
  changed.args = ['-y', 'thing@9.9.9'];
  changed.commandHash = commandHash(changed.command, changed.args);
  assert.equal(s.isApproved(s.find('x')), false, 'a version bump asks again');

  // And the hash is stable for identical commands.
  const a = s.add({ name: 'a', command: 'python', args: ['s.py'] });
  const b = s.add({ name: 'b', command: 'python', args: ['s.py'] });
  assert.equal(a.commandHash, b.commandHash);
  assert.notEqual(commandHash('python', ['s.py']), commandHash('python', ['other.py']));
});

test('enable, disable and remove persist', (t) => {
  const s = newStore(t);
  s.add({ name: 'one', command: 'python' });
  s.setEnabled('one', false);
  assert.equal(s.enabled.length, 0);
  assert.equal(s._fresh().find('one').enabled, false);
  assert.equal(s.remove('one').id, 'one');
  assert.equal(s.find('one'), null);
  assert.equal(s.remove('ghost'), null);
});

test('the multi-writer pattern holds', (t) => {
  const file = path.join(SANDBOX, 'multi.json');
  const first = new McpStore(file).load();
  first.add({ name: 'one', command: 'python' });
  // Another process writes a second server after the first loaded.
  new McpStore(file).load().add({ name: 'two', command: 'python' });
  first.setEnabled('one', false);
  const final = new McpStore(file).load();
  assert.equal(final.servers.length, 2, 'the other writer was not clobbered');
  assert.equal(final.find('one').enabled, false, 'and ours stuck too');
});

test('describeServer reads its states plainly', (t) => {
  const s = newStore(t);
  const rec = s.add({ name: 'x', command: 'npx', args: ['-y', 'pkg'] });
  assert.match(describeServer(rec, false), /^idle\s+x\s+npx -y pkg\s+\(needs approval\)/);
  s.markApproved(rec.id);
  assert.match(describeServer(s.find('x'), true), /^live/);
  assert.doesNotMatch(describeServer(s.find('x'), true), /needs approval/);
  s.setEnabled('x', false);
  assert.match(describeServer(s.find('x'), false), /^off/);
});

/* ----------------------------- reconcile -------------------------------- */

/**
 * A real McpManager with the two process-touching methods replaced, so
 * connectedIds / has() keep working off the genuine internals instead of a
 * lookalike object.
 */
function fakeManager() {
  const mgr = new McpManager();
  const calls = [];
  mgr.connect = async ({ id, command, args }) => {
    calls.push(`connect:${id}`);
    const record = { id, command, args, client: { close: async () => {} }, tools: [] };
    mgr.servers.set(id, record);
    mgr._clients.add(record.client);
    return record;
  };
  mgr.disconnect = async (id) => {
    calls.push(`disconnect:${id}`);
    const record = mgr.servers.get(String(id));
    if (!record) return false;
    mgr.servers.delete(String(id));
    mgr._clients.delete(record.client);
    return true;
  };
  return { mgr, calls };
}

test('reconcile starts only approved servers and drops the rest', async (t) => {
  const s = newStore(t);
  s.add({ name: 'approved', command: 'python', args: ['a.py'] });
  s.add({ name: 'unapproved', command: 'python', args: ['b.py'] });
  s.markApproved('approved');

  const { mgr, calls } = fakeManager();
  const first = await mgr.reconcile(s);
  assert.deepEqual(first.connected, ['approved']);
  assert.deepEqual(first.skipped, ['unapproved']);

  // Disabling takes it down on the next pass.
  s.setEnabled('approved', false);
  const second = await mgr.reconcile(s);
  assert.deepEqual(second.connected, []);
  assert.equal(calls.includes('disconnect:approved'), true);
});

test('one bad server does not stop the others or the caller', async (t) => {
  const s = newStore(t);
  s.add({ name: 'good', command: 'python', args: ['a.py'] });
  s.add({ name: 'bad', command: 'python', args: ['b.py'] });
  s.markApproved('good');
  s.markApproved('bad');

  const mcp = new McpManager();
  mcp.has = (id) => id === 'good';
  mcp.disconnect = async () => true;
  mcp.connect = async ({ id }) => {
    if (id === 'bad') throw new Error('spawn failed on purpose');
  };
  const out = await mcp.reconcile(s);
  assert.equal(out.connected.includes('bad'), false);
  assert.match(s.find('bad').lastError, /spawn failed on purpose/, 'the failure is recorded');
});

test('a changed command is not restarted until it is re-approved', async (t) => {
  const s = newStore(t);
  s.add({ name: 'x', command: 'npx', args: ['-y', 'pkg@1.0.0'] });
  s.markApproved('x');
  const { mgr: mcp } = fakeManager();
  assert.deepEqual((await mcp.reconcile(s)).connected, ['x']);

  const drifted = s._fresh().find('x');
  drifted.args = ['-y', 'pkg@2.0.0'];
  drifted.commandHash = commandHash(drifted.command, drifted.args);
  const after = await mcp.reconcile(s);
  assert.deepEqual(after.connected, [], 'no silent upgrade');
  assert.deepEqual(after.skipped, ['x']);
});

/* ------------------------------- daemon --------------------------------- */

function daemonWith(t, mcp) {
  const stateFile = path.join(SANDBOX, `state-${Math.random().toString(36).slice(2)}.json`);
  return new Daemon({
    store: new RoutineStore(stateFile).load(),
    config: {},
    client: {},
    runPrompt: async () => '',
    deliver: async () => {},
    mcp,
    log: () => {},
  });
}

test('the daemon reconciles MCP every tick', async (t) => {
  let reconciles = 0;
  const mcp = {
    reconcile: async () => {
      reconciles++;
      return { connected: [], skipped: [], changed: false };
    },
  };
  const daemon = daemonWith(t, mcp);
  daemon.pollInbox = async () => 0;
  await daemon.tickOnce();
  await daemon.tickOnce();
  assert.equal(reconciles, 2, 'picked up config changes without a restart');
});

test('a failing reconcile does not take the tick down', async (t) => {
  const mcp = {
    reconcile: async () => {
      throw new Error('registry exploded');
    },
  };
  const daemon = daemonWith(t, mcp);
  daemon.pollInbox = async () => 0;
  const result = await daemon.tickOnce();
  assert.ok(result, 'the tick completed despite the failure');
});

test('a daemon without MCP still ticks', async (t) => {
  const daemon = daemonWith(t, null);
  daemon.pollInbox = async () => 0;
  const out = await daemon.tickOnce();
  assert.equal(out.messages, 0);
});

/* --------------------------- the manage tool ---------------------------- */

test('mcp_manage only asks for approval when it will run something', () => {
  // Listing, removing, enabling and disabling touch config only.
  for (const action of ['list', 'remove', 'enable', 'disable', 'add']) {
    assert.equal(manage.approval({ action, id: 'x' }), null, `${action} must not prompt`);
  }
  // Reload starts a third-party process, so it shows the command.
  const store = new McpStore(MCP_FILE).load();
  for (const s of [...store.servers]) store.remove(s.id);
  store.add({ name: 'approve-me', command: 'python', args: ['server.py'] });

  const detail = manage.approval({ action: 'reload', id: 'approve-me' });
  assert.match(detail, /Start MCP server "approve-me"/);
  assert.match(detail, /command: python server\.py/, 'the user sees what will execute');
  assert.match(detail, /asks again/, 'and that a version change re-prompts');
  assert.equal(manage.approval({ action: 'reload', id: 'ghost' }), null);
});

test('mcp_manage reports rather than inventing when there is nothing to act on', () => {
  const store = new McpStore(MCP_FILE).load();
  for (const s of [...store.servers]) store.remove(s.id);

  assert.match(manage.run({ action: 'list' }, {}), /No MCP servers configured/);
  assert.match(manage.run({ action: 'add' }, {}), /'command' is required/);
  assert.match(manage.run({ action: 'remove', id: 'ghost' }, {}), /no MCP server/);
  assert.match(manage.run({ action: 'reload', id: 'ghost' }, {}), /no MCP server/);
  assert.match(manage.run({ action: 'wat' }, {}), /unknown action/);
});

test('enabling says it is still not running, disabling says the tools are gone', () => {
  const store = new McpStore(MCP_FILE).load();
  for (const s of [...store.servers]) store.remove(s.id);
  store.add({ name: 'hint', command: 'python' });

  const enable = manage.run({ action: 'enable', id: 'hint' }, {});
  assert.match(enable, /enabled, but not running yet/);
  assert.match(enable, /asks for approval first/, 'unapproved servers say so');

  store.markApproved('hint');
  assert.match(manage.run({ action: 'enable', id: 'hint' }, {}), /Run reload to start it\.$/);

  const disable = manage.run({ action: 'disable', id: 'hint' }, {});
  assert.match(disable, /disabled and its tools are gone/);
});

test('the /mcp command and the mcp_manage tool word things identically', async () => {
  // These were two copies of the same strings and the tool's fix did not reach
  // the command. They now share helpers; this fails if anyone re-forks them.
  const { enableMessage, disableMessage } = await import('../src/mcp-store.mjs');
  const store = new McpStore(MCP_FILE).load();
  for (const s of [...store.servers]) store.remove(s.id);
  const rec = store.add({ name: 'same', command: 'python' });

  assert.equal(manage.run({ action: 'enable', id: 'same' }, {}), enableMessage(store.find('same'), false));
  assert.equal(manage.run({ action: 'disable', id: 'same' }, {}), disableMessage(store.find('same')));

  store.markApproved(rec.id);
  assert.equal(manage.run({ action: 'enable', id: 'same' }, {}), enableMessage(store.find('same'), true));
});

test('the mcp category is discoverable through find_tools', async () => {
  const { CATEGORIES } = await import('../tools/catalog.mjs');
  const findTools = await import('../tools/find-tools.mjs');
  const mcpCat = CATEGORIES.find((c) => c.id === 'mcp');
  assert.ok(mcpCat, 'there is an mcp group');
  assert.deepEqual(mcpCat.tools.map((t) => t.name), ['mcp_manage']);
  assert.deepEqual(findTools.matchCategories('add an mcp server'), ['mcp']);
  assert.deepEqual(findTools.matchCategories('model context protocol'), ['mcp']);
});
