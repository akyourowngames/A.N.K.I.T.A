import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { Agent } from '../../src/core/agent.mjs';
import { captureVoiceContext, runVoiceWorker, voiceCallResources } from '../../src/core/voice-worker.mjs';

const fixture = t => { const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-worker-')); t.after(() => fs.rmSync(dir, { recursive: true, force: true })); return dir; };
const controlTool = { name: 'voice_jobs', description: 'test control', parameters: { type: 'object' }, needsApproval: false, run: () => '[]' };
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
