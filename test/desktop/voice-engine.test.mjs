import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';
import { DesktopSettingsStore, applyDesktopSettings } from '../../desktop/electron/settings.mjs';
const actions = await import('../../desktop/electron/voice-actions.mjs').catch(() => ({}));

async function fixture(t, send) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-engine-'));
  const events = [];
  class FixtureAgent {
    constructor(options) { this.confirm = options.confirm; this.config = options.config; this.messages = []; this.state = {}; this.client = options.client; this.systemSuffix = 'Original style'; }
    async send(text, callbacks) {
      this.messages.push({ role: 'user', content: text });
      callbacks.onMessageStart();
      await send?.(this, callbacks);
      callbacks.onDelta('Saved.'); callbacks.onMessageEnd();
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
  return { engine, id: engine.listTeammates()[0].id, events };
}

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
