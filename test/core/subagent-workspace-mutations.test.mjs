import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-subagent-mutations-'));
process.env.CONFIG_DIR = sandbox;
test.after(() => fs.rmSync(sandbox, { recursive: true, force: true }));
const { Agent } = await import('../../src/core/agent.mjs');
const { createSubagentRuntime } = await import('../../src/core/subagents/runtime.mjs');
const { names } = await import('../../tools/index.mjs');

const tick = () => new Promise(resolve => setImmediate(resolve));
const call = (name, args) => ({ id: name, type: 'function', function: { name, arguments: JSON.stringify(args) } });
function agent(workspacePath, extra = {}) {
  return new Agent({ client: {}, config: { tools: true, autoApprove: true, memoryConsolidation: false },
    workspacePath, memoryEnabled: false, skillsEnabled: false, print: () => {}, write: () => {}, ...extra });
}

async function workerHarness(t) {
  const workspace = fs.mkdtempSync(path.join(sandbox, 'workspace-'));
  const file = path.join(workspace, 'shared.txt');
  const parent = agent(workspace);
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let started;
  const ready = new Promise(resolve => { started = resolve; });
  const runtime = createSubagentRuntime({ parent, toolNames: names(), createAgent(options) {
    const child = new Agent(options);
    let stopped = false;
    child.cancel = async () => { stopped = true; release(); };
    child.send = async () => {
      assert.doesNotMatch(await child.runToolCall(call('write_file', { path: file, content: 'child started' })), /Error/);
      started();
      await gate;
      if (!stopped) assert.doesNotMatch(await child.runToolCall(call('write_file', { path: file, content: 'child finished' })), /Error/);
      return 'worker finished';
    };
    return child;
  } });
  parent._subagents = runtime;
  const receipt = JSON.parse(await parent.runToolCall(call('delegate_task', {
    subagent_type: 'worker', description: 'edit shared file', prompt: 'edit shared file', background: true,
  })));
  t.after(async () => { release(); await runtime.control({ action: 'wait', subagent_id: receipt.subagentId }); });
  await ready;
  return { parent, runtime, workspace, file, release, receipt };
}

test('parent API writes wait for a background worker while reads and messages stay responsive', { timeout: 10_000 }, async t => {
  const h = await workerHarness(t);
  let wrote = false;
  const writing = h.parent.runToolCall(call('write_file', { path: h.file, content: 'parent finished' })).then(result => {
    wrote = true;
    return result;
  });
  await tick();
  const wroteDuringWorker = wrote;
  const reading = await h.parent.runToolCall(call('read_file', { path: h.file }));
  const sending = JSON.parse(await h.parent.runToolCall(call('subagent_control', {
    action: 'send', subagent_id: h.receipt.subagentId, message: 'Please finish',
  })));
  h.release();
  const result = await writing;
  await h.runtime.control({ action: 'wait', subagent_id: h.receipt.subagentId });
  console.log(`WORKSPACE_MUTATION_API parent_during_worker=${wroteDuringWorker} final=${fs.readFileSync(h.file, 'utf8')}`);
  assert.equal(wroteDuringWorker, false, 'the parent must not write while the worker owns the workspace');
  assert.match(reading, /child started/);
  assert.equal(sending.status, 'queued');
  assert.doesNotMatch(result, /Error/);
  assert.equal(fs.readFileSync(h.file, 'utf8'), 'parent finished');
});

test('native writes in another parent share aliases and cancelled queued writes do not release a running worker', { timeout: 10_000 }, async t => {
  const h = await workerHarness(t);
  const alias = path.join(sandbox, `alias-${path.basename(h.workspace)}`);
  fs.symlinkSync(h.workspace, alias, process.platform === 'win32' ? 'junction' : 'dir');
  const other = agent(alias);
  const controller = new AbortController();
  const cancelledFile = path.join(alias, 'cancelled.txt');
  const cancelled = other.executionHost().execute({ id: 'cancelled', name: 'write_file', arguments: { path: cancelledFile, content: 'cancelled' } }, { signal: controller.signal });
  await tick();
  controller.abort();
  const cancelledResult = await cancelled;
  let wrote = false;
  const writing = other.executionHost().execute({ id: 'native', name: 'write_file', arguments: { path: path.join(alias, 'shared.txt'), content: 'native parent finished' } }).then(result => {
    wrote = true;
    return result;
  });
  await tick();
  const wroteDuringWorker = wrote;
  h.release();
  const result = await writing;
  await h.runtime.control({ action: 'wait', subagent_id: h.receipt.subagentId });
  assert.match(cancelledResult.content[0].text, /cancelled/i);
  assert.equal(fs.existsSync(cancelledFile), false);
  assert.equal(wroteDuringWorker, false, 'a cancelled waiter must not let the next parent overtake the worker');
  assert.equal(result.isError, false);
  assert.equal(fs.readFileSync(h.file, 'utf8'), 'native parent finished');
  console.log('WORKSPACE_MUTATION_NATIVE alias=shared cancelled_write=absent final=native-parent');
});

test('cancelling a background worker releases its workspace for a queued parent mutation', { timeout: 10_000 }, async t => {
  const h = await workerHarness(t);
  const writing = h.parent.runToolCall(call('write_file', { path: h.file, content: 'parent after cancellation' }));
  await tick();
  const cancelled = JSON.parse(await h.parent.runToolCall(call('subagent_control', {
    action: 'cancel', subagent_id: h.receipt.subagentId,
  })));
  assert.equal(cancelled.status, 'cancelled');
  assert.doesNotMatch(await writing, /Error/);
  assert.equal(fs.readFileSync(h.file, 'utf8'), 'parent after cancellation');
});

test('MCP mutation calls wait for workers while MCP reads and unrelated workspaces remain free', { timeout: 10_000 }, async t => {
  const h = await workerHarness(t);
  const readName = 'mcp__fixture__read';
  const writeName = 'mcp__fixture__write';
  h.parent.mcp = {
    findTool: name => ({ tool: { annotations: { readOnlyHint: name === readName } } }),
    needsApproval: () => false,
    async callTool(name) {
      if (name === writeName) fs.writeFileSync(h.file, 'MCP parent finished');
      return fs.readFileSync(h.file, 'utf8');
    },
  };
  let wrote = false;
  const writing = h.parent.runToolCall(call(writeName, {})).then(result => { wrote = true; return result; });
  await tick();
  const wroteDuringWorker = wrote;
  const reading = await h.parent.runToolCall(call(readName, {}));
  const elsewhere = fs.mkdtempSync(path.join(sandbox, 'independent-'));
  const unrelatedFile = path.join(elsewhere, 'independent.txt');
  const unrelated = await agent(elsewhere).runToolCall(call('write_file', { path: unrelatedFile, content: 'independent parent' }));
  h.release();
  await writing;
  await h.runtime.control({ action: 'wait', subagent_id: h.receipt.subagentId });
  assert.equal(wroteDuringWorker, false);
  assert.match(reading, /child started/);
  assert.doesNotMatch(unrelated, /Error/);
  assert.equal(fs.readFileSync(unrelatedFile, 'utf8'), 'independent parent');
  assert.equal(fs.readFileSync(h.file, 'utf8'), 'MCP parent finished');
  console.log('WORKSPACE_MUTATION_MCP write=queued read=responsive independent_root=responsive');
});

test('runtime capability read-only flags preserve the same parent mutation barrier', { timeout: 10_000 }, async t => {
  const h = await workerHarness(t);
  const readName = 'voice_fixture_read';
  const writeName = 'voice_fixture_write';
  h.parent.toolContext.runtimeTools = new Map([readName, writeName].map(name => [name, {
    name, parameters: { type: 'object' }, needsApproval: false,
    readOnly: () => name === readName,
    run: () => {
      if (name === writeName) fs.writeFileSync(h.file, 'runtime parent finished');
      return fs.readFileSync(h.file, 'utf8');
    },
  }]));
  let wrote = false;
  const writing = h.parent.runToolCall(call(writeName, {})).then(result => { wrote = true; return result; });
  await tick();
  const wroteDuringWorker = wrote;
  const reading = await h.parent.runToolCall(call(readName, {}));
  h.release();
  await writing;
  await h.runtime.control({ action: 'wait', subagent_id: h.receipt.subagentId });
  assert.equal(wroteDuringWorker, false);
  assert.match(reading, /child started/);
  assert.equal(fs.readFileSync(h.file, 'utf8'), 'runtime parent finished');
});
