import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DesktopChannelSurface } from '../../desktop/electron/channel-surface.mjs';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';
import { CHATGPT_BROWSER_PROVIDER } from '../../desktop/shared/chatgpt-browser.mjs';
import { ChannelRuntime } from '../../src/channels/core/runtime.mjs';

function fixture(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-channel-surface-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const parent = { cwd: directory, config: { maxToolCalls: 60 }, model: 'fixture-model', messages: [{ role: 'user', content: 'private desktop history' }] };
  class Agent {
    constructor(options) { this.options = options; this.config = options.config; this.cwd = options.workspacePath; this.messages = []; this.state = {}; }
    async send(text) { assert.equal(this.browserCredentialAllowed, false); this.messages.push({ role: 'user', content: text }); return 'reply'; }
    cancel() {}
  }
  const engine = { AgentClass: Agent, client: {}, config: {}, agents: new Map([['chief', parent]]), sessionsDir: directory,
    agentFor: () => parent, emit: () => {}, approvals: { request: async () => false, cancelThread: () => {} },
    secretHistory: { clean: x => x }, schedule: () => ({}), desktopSettings: { data: {} }, respondApproval: () => {},
  };
  return { parent, engine, surface: new DesktopChannelSurface({ engine }) };
}

test('Discord and group sessions use independent agents without desktop transcript or saved credential access', async t => {
  const { surface, parent } = fixture(t);
  const firstRef = { channel: 'discord', chatId: '42', messageId: '1', raw: { isGroup: true } };
  const secondRef = { ...firstRef, channel: 'slack' };
  const first = surface.targetFor('chief', firstRef), second = surface.targetFor('chief', secondRef);
  assert.notEqual(first, second);
  await surface.run(firstRef, first, 'Discord request', {}, { toolBudget: 3 });
  await surface.run(secondRef, second, 'Slack request', {}, { toolBudget: 2 });
  assert.deepEqual(surface.agents.get(first).messages.map(x => x.content), ['Discord request']);
  assert.deepEqual(surface.agents.get(second).messages.map(x => x.content), ['Slack request']);
  assert.equal(surface.agents.get(first).config.maxToolCalls, 3);
  assert.equal(surface.agents.get(first).options.toolContext.selectBrowserUpload, undefined);
  assert.deepEqual(parent.messages.map(x => x.content), ['private desktop history']);
  assert.equal(parent.config.maxToolCalls, 60);
});

test('Telegram private chat keeps its existing teammate route while groups have separate sessions', t => {
  const { surface } = fixture(t);
  assert.equal(surface.targetFor('chief', { channel: 'telegram', chatId: '42', raw: { isGroup: false } }), 'chief');
  assert.notEqual(surface.targetFor('chief', { channel: 'telegram', chatId: '-42', raw: { isGroup: true } }), 'chief');
});

test('isolated channel history survives a host restart only in its own session', async t => {
  const { surface, engine } = fixture(t);
  const ref = { channel: 'discord', chatId: '42', messageId: '1', raw: {} };
  const target = surface.targetFor('chief', ref);
  await surface.run(ref, target, 'saved conversation', {});
  const restarted = new DesktopChannelSurface({ engine });
  const next = restarted.targetFor('chief', ref);
  await restarted.run({ ...ref, messageId: '2' }, next, 'follow-up', {});
  assert.deepEqual(restarted.agents.get(next).messages.map(x => x.content), ['saved conversation', 'follow-up']);
});

test('an owner always-approval grants only its isolated channel agent', t => {
  const { surface, engine, parent } = fixture(t);
  const target = surface.targetFor('chief', { channel: 'discord', chatId: '42', raw: {} });
  const agent = surface.agentForTarget(target);
  engine.channels = { surface }; engine.approvals.pending = new Map([['r', { threadId: target }]]); engine.approvals.respond = () => true;
  assert.equal(DesktopEngine.prototype.respondApproval.call(engine, 'r', 'always'), true);
  assert.equal(agent.autoApprove, true); assert.notEqual(parent.autoApprove, true);
});

test('browser-only setup gives actionable channel guidance before opening a connection or constructing an API agent', async t => {
  const { surface, engine } = fixture(t); engine.config.provider = CHATGPT_BROWSER_PROVIDER; engine.client = null;
  engine.agentFor = () => { throw new Error('Set up a provider in Settings before sending a message'); };
  for (const channel of ['telegram', 'discord', 'slack']) {
    const ref = { channel, chatId: '42', messageId: '1', raw: { isGroup: false } }, target = surface.targetFor('chief', ref);
    await assert.rejects(surface.run(ref, target, 'hello', {}), /API model/);
  }
  let starts = 0;
  const runtime = new ChannelRuntime({ surface, getSettings: () => ({ enabled: true }), adapter: { manifest: { id: 'fixture', capabilities: [] }, start() { starts++; }, stop() {}, send() {} } });
  const status = await runtime.start(); assert.equal(starts, 0); assert.equal(status.running, false); assert.match(status.error, /API model/);
});

function settingsEngine(engine, surface, parent) {
  engine.channels = { surface }; engine.baseConfig = { provider: 'kilo', contextWindow: 32768 }; engine.provider = { name: 'kilo' };
  engine.turns = new Map(); engine.models = [{ id: 'new-model', tools: true }]; engine.teammates = { find: () => ({}) };
  engine.desktopSettings = { data: {}, preview: patch => ({ ...engine.desktopSettings.data, ...patch }), save: next => { engine.desktopSettings.data = next; } };
  engine.connectProvider = async () => ({ client: { id: 'new-client' }, tool: {}, models: engine.models, model: 'new-model', provider: { name: 'groq' } });
  engine.activateBrowserProvider = async () => {}; engine.settingsPayload = () => ({}); engine.config.contextWindow = 32768; parent.contextWindow = 32768;
  return patch => DesktopEngine.prototype.saveDesktopSettings.call(engine, patch);
}

test('provider and model changes invalidate isolated channel agents while preserving their saved conversation', async t => {
  const { surface, engine, parent } = fixture(t), save = settingsEngine(engine, surface, parent);
  const ref = { channel: 'discord', chatId: '42', messageId: '1', raw: {} }, target = surface.targetFor('chief', ref);
  await surface.run(ref, target, 'saved before provider change', {}); const old = surface.agents.get(target);
  await save({ provider: 'groq' }); parent.model = 'new-model';
  const changed = surface.agentForTarget(target); assert.notEqual(changed, old); assert.equal(changed.options.client.id, 'new-client'); assert.equal(changed.model, 'new-model');
  assert.deepEqual(changed.messages.map(message => message.content), ['saved before provider change']);
  engine.agents.set('chief', parent); await save({ model: 'new-model' }); assert.notEqual(surface.agentForTarget(target), changed);
});

test('provider changes wait for active isolated channel turns', async t => {
  const { surface, engine, parent } = fixture(t), save = settingsEngine(engine, surface, parent);
  const target = surface.targetFor('chief', { channel: 'discord', chatId: '42', raw: {} }); surface.privateTurns.set(target, Promise.resolve());
  await assert.rejects(save({ provider: 'groq' }), /Wait for active replies/); surface.privateTurns.delete(target);
});
