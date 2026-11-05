import test from 'node:test';
import assert from 'node:assert/strict';
import { CompatibleClient } from '../../src/core/provider.mjs';
import { CopilotClient } from '../../src/core/auth.mjs';
import { createSession } from '../../src/core/bootstrap.mjs';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';
import { createVoiceBrain, withVoiceBrain } from '../../src/core/voice-session.mjs';
import { declaredContext, modelContextWindow } from '../../src/core/model-capabilities.mjs';

const MODELS = [
  { id: 'large', context: 128000, tools: true },
  { id: 'small', context: 16000, tools: true },
];
const FALLBACK_WINDOW = 32768;

function desktop() {
  const engine = Object.create(DesktopEngine.prototype);
  Object.assign(engine, {
    config: { provider: 'custom', model: 'large', tools: true, contextWindow: MODELS[0].context },
    baseConfig: { provider: 'custom', model: 'large', contextWindow: FALLBACK_WINDOW },
    client: {}, models: MODELS, model: 'large', provider: { name: 'custom' },
    agents: new Map(), turns: new Map(), emit: () => {}, secretHistory: {},
    desktopSettings: { data: {}, preview: patch => ({ ...patch }), save: () => {} },
    settingsPayload: () => ({}),
    teammates: { find: id => ({ id, model: id === 'pinned' ? 'small' : '' }), update: (id, patch) => ({ id, name: id, ...patch }) },
  });
  return engine;
}

test('both provider catalogues retain each advertised model window in runtime capabilities', async t => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({ data: MODELS.map(model => ({
    id: model.id, context_length: model.context, capabilities: { limits: { max_context_window_tokens: model.context } },
  })) }));
  const compatible = new CompatibleClient({ apiBase: 'https://fixture.invalid' });
  const copilot = new CopilotClient('fixture-token');
  copilot.token = { token: 'fixture-token' };
  for (const client of [compatible, copilot]) {
    await client.models();
    for (const model of MODELS) assert.equal(client.modelCapabilities.get(model.id).context, model.context);
  }
});

test('malformed catalogue limits retain fallback budgets and manual tuning wins over discovery', () => {
  for (const context of [null, '', 0, -1, 'unknown', Infinity, 1.5]) assert.equal(declaredContext({ context_length: context }), null);
  assert.equal(declaredContext({ context_length: '16000' }), MODELS[1].context);
  assert.equal(modelContextWindow({ model: 'small', models: MODELS, contextWindow: 48000, contextWindowExplicit: true }), 48000);
  assert.equal(modelContextWindow({ model: 'unknown', models: MODELS, contextWindow: FALLBACK_WINDOW }), FALLBACK_WINDOW);
});

test('compatible model discovery accepts Groq context_window metadata', async t => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({ data: [
    { id: 'groq-model', context_window: MODELS[1].context },
    { id: 'invalid-first', context_length: 0, context_window: MODELS[1].context },
    { id: 'nested-valid', context_length: 'invalid', context_window: -1, capabilities: { limits: { max_context_window_tokens: MODELS[1].context } } },
  ] }));
  const client = new CompatibleClient({ apiBase: 'https://fixture.invalid' });
  for (const model of await client.models()) {
    assert.equal(model.context, MODELS[1].context);
    assert.equal(modelContextWindow({ client, model: model.id, contextWindow: FALLBACK_WINDOW }), MODELS[1].context);
  }
});

test('bootstrap discovers tool-model limits separately and preserves the manual primary window', async () => {
  const discovery = [];
  class Client {
    constructor(options) { Object.assign(this, options); }
    async models() { discovery.push(this.model); return MODELS; }
  }
  const config = { provider: 'kilo', apiBase: 'https://fixture.invalid', model: 'large',
    toolProvider: 'kilo', toolModel: 'small', tools: true, contextWindow: 48000, contextWindowExplicit: true };
  const session = await createSession({ config, CompatibleClientClass: Client });
  assert.deepEqual(discovery, ['large', 'small']);
  assert.equal(session.tool.contextWindow, MODELS[1].context);
  assert.equal(config.contextWindow, 48000);
});

test('desktop model switches update both live and future budgets without resetting pinned teammates', async () => {
  const engine = desktop();
  const inherited = { model: 'large', contextWindow: MODELS[0].context, config: { ...engine.config } };
  const pinned = { model: 'small', contextWindow: MODELS[1].context, config: { ...engine.config, model: 'small', contextWindow: MODELS[1].context } };
  engine.agents.set('inherited', inherited);
  engine.agents.set('pinned', pinned);
  await engine.saveDesktopSettings({ model: 'small' });
  assert.equal(engine.config.contextWindow, MODELS[1].context);
  assert.equal(inherited.contextWindow, MODELS[1].context);
  assert.equal(inherited.config.model, 'small');
  assert.equal(inherited.config.contextWindow, MODELS[1].context);
  assert.equal(pinned.contextWindow, MODELS[1].context);
  await engine.saveDesktopSettings({ contextCompaction: true });
  assert.equal(engine.config.contextWindow, MODELS[1].context, 'unrelated tuning must retain the selected model window');
  await engine.saveDesktopSettings({ contextWindow: 48000 });
  assert.equal(inherited.contextWindow, 48000);
  assert.equal(pinned.contextWindow, 48000);
  await engine.saveDesktopSettings({ model: 'large', contextWindow: 0 });
  assert.equal(inherited.contextWindow, MODELS[0].context);
  assert.equal(pinned.contextWindow, MODELS[1].context, 'clearing manual tuning restores each teammate own window');
});

test('teammate model switches replace stale live model windows and clearing a pin uses the default', () => {
  const engine = desktop();
  const agent = { model: 'large', contextWindow: MODELS[0].context, config: { ...engine.config } };
  engine.agents.set('inherited', agent);
  engine.updateTeammate('inherited', { model: 'small' });
  assert.equal(agent.model, 'small');
  assert.equal(agent.contextWindow, MODELS[1].context);
  assert.equal(agent.config.contextWindow, MODELS[1].context);
  engine.updateTeammate('inherited', { model: '' });
  assert.equal(agent.model, 'large');
  assert.equal(agent.contextWindow, MODELS[0].context);
});

test('new desktop teammates begin with their pinned model budget and forward compaction progress', () => {
  const engine = desktop();
  let options;
  const events = [];
  engine.AgentClass = class { constructor(input) { options = input; Object.assign(this, { config: input.config, messages: [] }); } };
  engine.desktopSettings.data.disabledSkills = [];
  engine._savedThread = () => ({ messages: [], todos: [] });
  engine.schedule = () => ({});
  engine.secretHistory.clean = value => value;
  engine.emit = event => events.push(event);
  const agent = engine.agentFor('pinned');
  assert.equal(agent.model, 'small');
  assert.equal(agent.config.model, 'small');
  assert.equal(agent.config.contextWindow, MODELS[1].context);
  options.onCompaction({ phase: 'started' });
  assert.deepEqual(events, [{ phase: 'started', type: 'context-compaction', threadId: 'pinned' }]);
});

test('voice discovers its own model window once, pins the matching budget, and restores typed state', async () => {
  let discoveries = 0;
  const client = { async models() {
    discoveries++;
    this.modelCapabilities = new Map(MODELS.map(model => [model.id, { context: model.context }]));
    return MODELS;
  } };
  const config = { model: 'large', contextWindow: MODELS[0].context };
  const agent = { client, model: 'large', contextWindow: config.contextWindow, config };
  const brain = createVoiceBrain({ ...config, voiceModel: 'small' }, agent);
  for (const failed of [false, true]) {
    const run = withVoiceBrain(agent, brain, async () => {
      assert.equal(agent.contextWindow, MODELS[1].context);
      assert.equal(agent.config.contextWindow, MODELS[1].context);
      assert.equal(agent.config.model, 'small');
      if (failed) throw new Error('fixture failure');
    });
    if (failed) await assert.rejects(run, /fixture failure/);
    else await run;
    assert.equal(agent.config, config);
    assert.equal(agent.contextWindow, MODELS[0].context);
  }
  assert.equal(discoveries, 1);
});

test('voice preserves manual tuning and shares one discovery when its model is absent from the catalogue', async () => {
  let discoveries = 0;
  const client = { async models() { discoveries++; return []; } };
  const config = { contextWindow: 48000, contextWindowExplicit: true };
  const brain = createVoiceBrain({ ...config, voiceModel: 'private-model' }, { client });
  const agents = [0, 1].map(() => ({ config, contextWindow: config.contextWindow }));
  await Promise.all(agents.map(agent => withVoiceBrain(agent, brain, async () => {
    assert.equal(agent.contextWindow, config.contextWindow);
    assert.equal(agent.config.contextWindowExplicit, true);
  })));
  assert.equal(discoveries, 1);
  for (const agent of agents) assert.equal(agent.config, config);
});
