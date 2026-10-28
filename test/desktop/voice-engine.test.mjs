import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { build } from 'esbuild';
import { fileURLToPath } from 'node:url';
import { Agent } from '../../src/core/agent.mjs';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';
import { DesktopSettingsStore, applyDesktopSettings } from '../../desktop/electron/settings.mjs';
import { VoiceJobs } from '../../src/automation/voice-jobs.mjs';
import { VoiceTaskStore } from '../../src/automation/voice-task.mjs';
const actions = await import('../../desktop/electron/voice-actions.mjs').catch(() => ({}));

async function fixture(t, send) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-engine-'));
  const events = [];
  class FixtureAgent {
    constructor(options) { this.confirm = options.confirm; this.config = options.config; this.messages = []; this.state = { jobs: new Map() }; this.client = options.client; this.model = options.config.model; this.cwd = options.workspacePath || directory; this.systemSuffix = 'Original style'; }
    async send(text, callbacks) {
      this.messages.push({ role: 'user', content: text });
      callbacks.onMessageStart?.();
      await send?.(this, callbacks);
      callbacks.onDelta?.('Saved.'); callbacks.onMessageEnd?.();
      this.messages.push({ role: 'assistant', content: 'Saved.' }); return 'Saved.';
    }
    refreshPrompt() {}
  }
  const engine = new DesktopEngine({ teammateFile: path.join(directory, 'teammates.json'), sessionsDir: path.join(directory, 'sessions'),
    settingsFile: path.join(directory, 'settings.json'), channelsFile: path.join(directory, 'channels.json'), projectsFile: path.join(directory, 'projects.json'),
    credentialFile: path.join(directory, 'credentials.json'), composioFile: path.join(directory, 'composio.json'), composioGrantsFile: path.join(directory, 'grants.json'),
    AgentClass: FixtureAgent, config: { provider: 'kilo', model: 'typed-model', tools: true },
    bootstrap: async () => ({ client: { id: 'typed' }, models: [{ id: 'typed-model' }], model: 'typed-model', provider: { name: 'kilo' } }),
    mcp: { reconcile: async () => {}, summaries: () => [], closeAll: async () => {} }, emit: event => events.push(event) });
  await engine.init();
  t.after(async () => { await engine.close(); fs.rmSync(directory, { recursive: true, force: true }); });
  return { engine, id: engine.listTeammates()[0].id, events, directory };
}

test('a passive voice result and a normal typed ending preserve another voice job permission', async () => {
  const { outputFiles } = await build({ entryPoints: [fileURLToPath(new URL('../../desktop/renderer/src/state/store.ts', import.meta.url))], bundle: true, write: false, platform: 'node', format: 'esm' });
  const { reducer, initialState } = await import(`data:text/javascript;base64,${Buffer.from(outputFiles[0].text).toString('base64')}`);
  for (const source of ['voice', undefined]) {
    let state = reducer(initialState, { type: 'event', event: { type: 'approval-request', requestId: 'B', threadId: 'owner', voiceTaskId: 'job-B', toolName: 'write_file', detail: 'Allow B?' } });
    state = reducer(state, { type: 'event', event: { type: 'turn-end', threadId: 'owner', turnId: 'job-A', source } });
    assert.equal(state.approvals.some(item => item.requestId === 'B'), true);
  }
});

test('cancelling one voice permission emits its exact resolution and preserves another request', async t => {
  const h = await fixture(t);
  h.engine.AgentClass = class extends Agent { async send() { this.abort = new AbortController(); await this.confirm('write_file', 'Allow own write?'); return 'Permission resolved.'; } };
  const other = h.engine.approvals.request(h.id, 'write_file', 'Allow other?', { voiceTaskId: 'other-job' });
  const controller = new AbortController();
  const entry = { id: 'own-job', ownerId: h.id, transcript: 'Write', context: h.engine.captureVoiceContext(h.id) };
  const work = h.engine.runVoiceJob(entry, { signal: controller.signal, observer: {}, controlTool: {}, jobs: { acquire: async () => {} } });
  await new Promise(resolve => setTimeout(resolve, 20));
  const ownRequest = h.events.find(event => event.type === 'approval-request' && event.voiceTaskId === entry.id);
  assert.ok(ownRequest);
  controller.abort(); await work;
  assert.equal(h.engine.approvals.pending.has(ownRequest.requestId), false);
  assert.ok(h.events.some(event => event.type === 'approval-resolved' && event.requestId === ownRequest.requestId));
  assert.equal(h.engine.approvals.pending.size, 1);
  h.engine.approvals.cancelAll(); await other;
});

for (const preGranted of [false, true]) test(`voice file actions follow the owner Always grant (existing=${preGranted})`, async t => {
  const h = await fixture(t);
  h.engine.AgentClass = class extends Agent { async send(_text, callbacks) {
    this.abort = new AbortController();
    for (const name of ['one.txt', 'two.txt']) {
      const call = { id: name, type: 'function', function: { name: 'write_file', arguments: JSON.stringify({ path: name, content: 'confirmed' }) } };
      callbacks.onToolCall(call); const result = await this.runToolCall(call); callbacks.onToolResult(call, result);
    }
    return 'Both files saved.';
  } };
  const parent = h.engine.agentFor(h.id); parent.setProject('', null, h.directory); parent.autoApprove = preGranted;
  let requests = 0;
  const off = h.engine.onEvent(event => { if (event.type === 'approval-request') { requests++; h.engine.respondApproval(event.requestId, 'always'); } });
  t.after(off);
  const entry = { id: 'always-job', ownerId: h.id, transcript: 'Save two notes', context: h.engine.captureVoiceContext(h.id) };
  await h.engine.runVoiceJob(entry, { signal: new AbortController().signal, observer: {}, controlTool: {}, jobs: { acquire: async () => {} } });
  assert.equal(requests, preGranted ? 0 : 1);
  assert.equal(fs.readFileSync(path.join(h.directory, 'two.txt'), 'utf8'), 'confirmed');
});

for (const failRoutine of [false, true]) test(`voice mail drains when a scheduled delivery becomes idle (failed=${failRoutine})`, async t => {
  const h = await fixture(t), parent = h.engine.agentFor(h.id);
  let release, started;
  const held = new Promise(resolve => { release = resolve; }), entered = new Promise(resolve => { started = resolve; });
  parent.streamTurn = async () => { started(); await held; if (failRoutine) throw new Error('fixture routine failure'); return { content: 'Routine ready.', toolCalls: [] }; };
  const routine = h.engine.deliverRoutine({ threadId: h.id, routineId: 'routine', runId: `run-${failRoutine}`, name: 'fixture', text: 'Observed evidence', status: 'done' });
  void routine.catch(() => {});
  await entered;
  await h.engine.deliverVoiceJob({ ownerId: h.id, id: 'voice-report', transcript: 'Voice request', status: 'done', summary: 'Voice work ready.', steps: [] });
  assert.equal(h.engine.voiceDeliveries.size, 1);
  release(); await routine.catch(() => {});
  assert.equal(h.engine.voiceDeliveries.size, 0);
  assert.ok(parent.messages.some(message => message.content === 'Voice work ready.'));
});

test('desktop voice uses existing turn/history with voice override and restores typed model/style', async t => {
  const observed = [];
  const brain = { client: { id: 'meta' }, model: 'voice-model' };
  const h = await fixture(t, (agent, callbacks) => {
    assert.equal(agent.client, brain.client); assert.equal(agent.model, brain.model);
    assert.match(agent.systemSuffix, /one or two short sentences/);
    const call = { id: 'fixture', function: { name: 'fixture_tool', arguments: '{}' } };
    callbacks.onToolCall(call); callbacks.onToolResult(call, 'Denied', { ok: false });
  });
  const outcome = await h.engine.runVoiceTurn(h.id, 'Save a note', { onToolResult: (...args) => observed.push(args) }, brain);
  assert.equal(outcome.text, 'Saved.'); assert.equal(observed[0][2].ok, false);
  assert.equal(h.engine.agentFor(h.id).model, 'typed-model');
  assert.equal(h.engine.agentFor(h.id).systemSuffix, 'Original style');
  assert.equal(h.engine.loadThread(h.id).at(-1).content, 'Saved.');
  assert.equal(JSON.parse(fs.readFileSync(h.engine.sessionFile(h.id))).model, 'typed-model');
  assert.ok(h.events.some(event => event.type === 'turn-start' && event.model === 'voice-model'));
});

test('parallel engine uses fresh voice agents and delivers atomic results only when typed history is idle', async t => {
  const observed = [];
  const h = await fixture(t, agent => { observed.push(agent); });
  const parent = h.engine.agentFor(h.id), typedMessages = parent.messages;
  const jobs = new VoiceJobs({ store: new VoiceTaskStore({ directory: path.join(h.engine.sessionsDir, 'voice-fixture') }),
    run: (entry, options) => h.engine.runVoiceJob(entry, { ...options, brain: { client: {}, model: 'voice-model' }, jobs }),
    onComplete: task => h.engine.deliverVoiceJob(task) });
  t.after(() => jobs.close());
  h.engine.turns.set(h.id, Promise.resolve());
  const a = await jobs.submit({ ownerId: h.id, transcript: 'First poem', context: h.engine.captureVoiceContext(h.id) });
  const b = await jobs.submit({ ownerId: h.id, transcript: 'Second note', context: h.engine.captureVoiceContext(h.id) });
  await Promise.all([jobs.waitFor(a.id, { ownerId: h.id }), jobs.waitFor(b.id, { ownerId: h.id })]);
  assert.notEqual(observed[0], observed[1]); assert.ok(observed.every(agent => agent !== parent));
  assert.equal(parent.messages, typedMessages); assert.equal(parent.messages.length, 0);
  h.engine.turns.delete(h.id); h.engine.flushVoiceDeliveries(h.id);
  assert.deepEqual(parent.messages.map(message => message.role), ['user', 'assistant', 'user', 'assistant']);
  assert.equal(parent.model, 'typed-model');
  assert.equal(h.engine.loadThread(h.id).filter(message => message.role === 'assistant').length, 2);
  assert.equal(observed.length, 2, 'delivery needs no additional planner call');
});

test('voice cancel IPC accepts one task or explicit all and refuses ambiguous payloads', async () => {
  const calls = [], engine = { voice: () => ({ cancelWork: payload => { calls.push(payload); return payload; } }) };
  await actions.runVoiceAction({ engine, action: 'voiceCancel', payload: { taskId: 'job-id' } });
  await actions.runVoiceAction({ engine, action: 'voiceCancel', payload: { all: true } });
  assert.deepEqual(calls, [{ taskId: 'job-id' }, { all: true }]);
  for (const payload of [{ taskId: 'x', all: true }, { all: 'yes' }, { taskId: '' }, { taskId: 'x'.repeat(201) }]) {
    await assert.rejects(actions.runVoiceAction({ engine, action: 'voiceCancel', payload }), /payload/);
  }
});

test('voice approvals wrap the normal permission request without bypassing it', async t => {
  let approvalCalls = 0;
  const h = await fixture(t, async agent => assert.equal(await agent.confirm('fixture_tool', 'Allow?'), false));
  h.engine.approvals.request = async () => false;
  await h.engine.runVoiceTurn(h.id, 'Write', { approval: async (_tool, ask) => { approvalCalls++; return ask(); } }, null);
  assert.equal(approvalCalls, 1);
});

test('voice setup saves env overrides privately, including explicitly clearing keys', t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-settings-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const store = new DesktopSettingsStore(path.join(directory, 'settings.json'));
  const base = { sarvamApiKey: 'env-speech', basetenApiKey: 'env-meta', micDevice: 'Env mic' };
  assert.equal(store.publicView(base).hasSarvamKey, true);
  store.update({ sarvamApiKey: 'saved-speech', basetenApiKey: '', micDevice: 'Chosen mic' });
  const config = applyDesktopSettings(base, new DesktopSettingsStore(store.file).load().data);
  assert.equal(config.sarvamApiKey, 'saved-speech'); assert.equal(config.basetenApiKey, ''); assert.equal(config.micDevice, 'Chosen mic');
  const view = store.publicView(config);
  assert.equal(view.hasBasetenKey, false); assert.equal(view.micDevice, 'Chosen mic');
  assert.ok(!JSON.stringify(view).includes('saved-speech'));
  assert.throws(() => store.preview({ micDevice: 'x'.repeat(201) }), /long/);
});

test('voice IPC rejects unknown fields and oversized owner IDs', async () => {
  const engine = { voice: () => ({ start: async value => value }) };
  await assert.rejects(actions.runVoiceAction({ engine, action: 'voiceStart', payload: { threadId: 'owner', apiKey: 'bad' } }), /payload/i);
  await assert.rejects(actions.runVoiceAction({ engine, action: 'voiceStart', payload: { threadId: 'x'.repeat(201) } }), /conversation/i);
  assert.deepEqual(await actions.runVoiceAction({ engine, action: 'voiceStart', payload: { threadId: 'owner' } }), { threadId: 'owner' });
  const focus = [];
  const view = { sessionId: 'session', threadId: 'owner' };
  const focusedEngine = { voice: () => ({ snapshot: () => view }) };
  await assert.rejects(actions.runVoiceAction({ engine: focusedEngine, action: 'voiceShowMain', payload: { settings: 'true' } }), /payload/);
  await actions.runVoiceAction({ engine: focusedEngine, action: 'voiceShowMain', payload: { settings: true }, focus: (...args) => focus.push(args) });
  assert.deepEqual(focus, [[view, { settings: true }]]);
});

test('live voice blocks setup changes that would invalidate the session', async t => {
  const h = await fixture(t);
  h.engine._voice = { snapshot: () => ({ active: true }), close: async () => {} };
  await assert.rejects(h.engine.saveDesktopSettings({ sarvamApiKey: 'replacement' }), /End voice/i);
  await assert.rejects(h.engine.saveDesktopSettings({ provider: 'groq' }), /End voice/i);
  await assert.rejects(h.engine.saveDesktopSettings({ kiloApiKey: 'replacement' }), /End voice/i);
});

test('failed voice turns restore typed settings and keep ordinary sends on the typed provider', async t => {
  let fail = true;
  const h = await fixture(t, agent => {
    if (fail) throw new Error('Planner unavailable');
    assert.equal(agent.model, 'typed-model'); assert.equal(agent.systemSuffix, 'Original style');
  });
  const outcome = await h.engine.runVoiceTurn(h.id, 'Voice request', {}, { client: {}, model: 'voice-model' });
  assert.match(outcome.error, /Planner unavailable/);
  fail = false;
  await h.engine.send(h.id, 'Typed request'); await h.engine.waitForTurn(h.id);
  assert.equal(h.engine.agentFor(h.id).model, 'typed-model');
  h.engine.config.provider = 'chatgpt-browser';
  await assert.rejects(h.engine.runVoiceTurn(h.id, 'Voice', {}, null), /API-backed/);
});

test('shutdown starts native-control cancellation before waiting for voice audio to close', async t => {
  const h = await fixture(t);
  let release; const audioClosing = new Promise(resolve => { release = resolve; });
  let computerClosed = false;
  h.engine._voice = { close: () => audioClosing };
  h.engine.computerUse.close = async () => { computerClosed = true; };
  const closing = h.engine.close();
  await Promise.resolve();
  try { assert.equal(computerClosed, true); }
  finally { release(); await closing; }
});
