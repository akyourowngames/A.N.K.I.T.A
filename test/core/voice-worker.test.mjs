import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { ToolHost } from '../../src/core/tool-host.mjs';
import { VoiceResourceBroker } from '../../src/automation/voice-resources.mjs';
import { Agent } from '../../src/core/agent.mjs';
import { captureVoiceContext, runVoiceWorker, voiceCallResources } from '../../src/core/voice-worker.mjs';
import { BrowserSessionManager } from '../../tools/browser/session.mjs';
import { BrowserPluginStore } from '../../src/integrations/browser-plugins.mjs';

const fixture = t => { const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-worker-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true })); return dir; };
const controlTool = { name: 'voice_jobs', description: 'test control', parameters: { type: 'object' }, needsApproval: false, run: () => '[]' };
test('parallel voice workers retain separate extension browser scopes and release them after work', async t => {
  const dir = fixture(t), store = new BrowserPluginStore(path.join(dir, 'browser.json')).load();
  store.setEnabled('local', true); store.setChromeMode('extension');
  const manager = new BrowserSessionManager({ store }), seen = [];
  const parent = new Agent({ client: {}, browserManager: manager, config: { tools: true }, memoryEnabled: false, workspacePath: dir });
  class Fake extends Agent { async send() { seen.push(this.browserManager); await new Promise(resolve => setImmediate(resolve)); return 'Ready'; } }
  await Promise.all(['one', 'two'].map(id => runVoiceWorker({ id, ownerId: 'owner', transcript: 'browse', context: captureVoiceContext(parent) },
    { signal: new AbortController().signal, observer: {}, controlTool }, { AgentClass: Fake })));
  assert.notEqual(seen[0], manager); assert.notEqual(seen[0], seen[1]);
  assert.equal(seen[0].scopeOptions.ownedTabs, true);
  assert.equal(manager.scopes.size, 0);
});
test('fresh workers keep captured history, planner, abort and job state separate from the typed agent', async t => {
  const dir = fixture(t), parent = new Agent({ client: {}, config: { tools: true, model: 'typed' }, memoryEnabled: false, workspacePath: dir });
  parent.messages.push({ role: 'user', content: 'previous' }, { role: 'assistant', content: 'saved findings' });
  const context = captureVoiceContext(parent);
  parent.messages[2].content = 'changed later';
  const workers = [];
  class Fake extends Agent { async send(text) { this.abort = new AbortController(); this.servedModel = this.model; workers.push(this); this.messages.push({ role: 'user', content: text }); return text; } }
  const brain = { client: {}, model: 'voice' };
  const make = id => ({ id, ownerId: 'owner', transcript: id, context, controller: new AbortController() });
  const first = make('first'), second = make('second');
  await Promise.all([first, second].map(entry => runVoiceWorker(entry, { signal: entry.controller.signal, observer: {}, controlTool }, { AgentClass: Fake, brain, acquire: async () => {} })));
  assert.notEqual(workers[0], workers[1]); assert.notEqual(workers[0].state, workers[1].state);
  assert.notEqual(workers[0].messages, workers[1].messages); assert.equal(workers[0].messages[2].content, 'saved findings');
  assert.equal(workers[0].servedModel, 'voice'); assert.equal(parent.model, 'typed');
  await first.cancelWorker(); assert.equal(workers[0].abort.signal.aborted, true); assert.equal(workers[1].abort.signal.aborted, false);
  assert.equal(parent.messages.length, 3);
});
test('reserved control worker cannot call ordinary tools or schedule a background bypass', async t => {
  const dir = fixture(t), parent = new Agent({ client: {}, config: { tools: true }, memoryEnabled: false, workspacePath: dir });
  let seen;
  class Fake extends Agent { async send() { seen = this.currentSpecs().map(spec => spec.function.name); return 'ready'; } }
  const entry = { id: 'control', ownerId: 'owner', transcript: 'status', controlOnly: true, context: captureVoiceContext(parent) };
  await runVoiceWorker(entry, { signal: new AbortController().signal, observer: {}, controlTool }, { AgentClass: Fake, acquire: async () => {} });
  assert.deepEqual(seen, ['voice_jobs']);
  assert.throws(() => captureVoiceContext({ ...parent, config: { ...parent.config, backgroundJob: true } }), /scheduled/i);
});
test('real file tool waits at its gate, then starts after approval and saves the captured workspace', async t => {
  const dir = fixture(t), trace = [];
  const parent = new Agent({ client: {}, config: { tools: true, autoApprove: false }, memoryEnabled: false, workspacePath: dir });
  class FileAgent extends Agent { async send() {
    this.abort = new AbortController();
    const call = { id: 'write', type: 'function', function: { name: 'write_file', arguments: JSON.stringify({ path: 'poem.txt', content: 'real saved poem' }) } };
    return this.runToolCall(call);
  } }
  const entry = { id: 'write', ownerId: 'owner', transcript: 'save poem', context: captureVoiceContext(parent) };
  await runVoiceWorker(entry, { signal: new AbortController().signal, observer: { onToolStart: () => trace.push('start') }, controlTool },
    { AgentClass: FileAgent, acquire: async (_id, leases) => { trace.push('gate'); assert.equal(leases[0].key.endsWith('/poem.txt'), true); }, confirm: async () => { trace.push('approve'); return true; } });
  assert.deepEqual(trace, ['gate', 'approve', 'start']); assert.equal(fs.readFileSync(path.join(dir, 'poem.txt'), 'utf8'), 'real saved poem');
});
test('resource classification keeps file reads precise and opaque commands and UI conservative', async t => {
  const cwd = fixture(t), ctx = { cwd };
  const call = (name, args) => voiceCallResources({ name, arguments: args }, ctx);
  assert.equal((await call('read_file', { path: 'a.txt' }))[0].mode, 'read');
  assert.equal((await call('write_file', { path: 'b.txt' }))[0].mode, 'write');
  const command = await call('run_command', { command: 'opaque' });
  assert.equal(command.some(resource => resource.kind === 'path'), true);
  assert.equal(command.some(resource => resource.kind === 'shared'), true);
  assert.deepEqual(await call('voice_jobs', { action: 'list' }), []);
  const browser = await call('browser', { action: 'snapshot' });
  assert.equal((await call('mcp__computer__click', {})).some(resource => resource.key === browser[0].key), true);
});

test('a real live shell child remains owned after the voice report and is confirmed stopped', async t => {
  const dir = fixture(t), parent = new Agent({ client: {}, config: { tools: true, autoApprove: true }, memoryEnabled: false, workspacePath: dir });
  class ProcessAgent extends Agent { async send() {
    this.abort = new AbortController();
    const command = process.platform === 'win32' ? `& '${process.execPath.replaceAll("'", "''")}' -e 'setInterval(()=>{},1000)'` : `'${process.execPath}' -e 'setInterval(()=>{},1000)'`;
    return this.runToolCall({ id: 'child', type: 'function', function: { name: 'run_command', arguments: JSON.stringify({ command, background: true }) } });
  } }
  const entry = { id: 'process', ownerId: 'owner', transcript: 'run child', context: captureVoiceContext(parent) };
  t.after(() => entry.cancelWorker?.());
  await runVoiceWorker(entry, { signal: new AbortController().signal, observer: {}, controlTool }, { AgentClass: ProcessAgent, acquire: async () => {} });
  assert.ok(entry.resourceHold?.promise);
  await entry.resourceHold.stop(); await entry.resourceHold.promise;
  assert.equal([...entry.worker.state.jobs.values()].every(job => job.done), true);
});

test('structured Git restores from a nested directory wait for another voice file lease', async t => {
  const root = fixture(t), nested = path.join(root, 'nested'); fs.mkdirSync(nested);
  const git = args => { const result = spawnSync('git', args, { cwd: root, encoding: 'utf8', windowsHide: true }); assert.equal(result.status, 0, result.stderr); };
  git(['init']); fs.writeFileSync(path.join(root, 'note.txt'), 'baseline'); git(['add', 'note.txt']);
  git(['-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-m', 'fixture']);
  fs.writeFileSync(path.join(root, 'note.txt'), 'saved by first voice job');
  const broker = new VoiceResourceBroker();
  await broker.acquire('editor', await voiceCallResources({ name: 'write_file', arguments: { path: path.join(root, 'note.txt') } }, { cwd: root }));
  let started = false;
  const call = { id: 'restore', name: 'git', arguments: { action: 'restore', paths: ['../note.txt'] } };
  const ctx = { cwd: nested, workspacePath: nested, config: { autoApprove: true }, state: { activatedTools: new Set() } };
  const pending = (async () => { await broker.acquire('restore', await voiceCallResources(call, ctx)); started = true; return new ToolHost({ context: ctx }).execute(call); })();
  try {
    await new Promise(resolve => setTimeout(resolve, 40));
    assert.equal(started, false, 'Git must not enter execution while another voice job owns a file in its repository');
    assert.equal(fs.readFileSync(path.join(root, 'note.txt'), 'utf8'), 'saved by first voice job');
  } finally { broker.release('editor'); await pending; broker.release('restore'); }
  assert.equal(fs.readFileSync(path.join(root, 'note.txt'), 'utf8'), 'baseline');
});

test('directory creation and generated file effects acquire filesystem leases too', async t => {
  const cwd = fixture(t);
  for (const name of ['create_dir', 'image_generate', 'image_download']) {
    const leases = await voiceCallResources({ name, arguments: { path: 'new-dir' } }, { cwd });
    assert.ok(leases.some(resource => resource.kind === 'path'), name);
  }
});
