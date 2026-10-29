import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DesktopChannelSurface } from '../../desktop/electron/channel-surface.mjs';

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
