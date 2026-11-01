import test from 'node:test';
import assert from 'node:assert/strict';
import { Daemon } from '../../src/automation/daemon.mjs';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ChannelStore } from '../../src/channels/core/store.mjs';

test('daemon approvals for a group are sent only to the private owner and group replies cannot allow them', async t => {
  const sent = [], bot = { enabled: true, send: async (chatId, text) => { sent.push({ chatId: String(chatId), text }); return [{ message_id: sent.length }]; } };
  const daemon = new Daemon({ store: {}, bot, config: { telegramChatId: '42', telegramAllowedChatIds: '-100,42' }, client: {}, runPrompt: async () => '', deliver: async () => {} });
  t.after(() => daemon.stop());
  const decision = daemon.confirmFrom('-100', 'write_file', 'save poem');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(sent[0].chatId, '42');
  assert.equal(daemon.resolvePending({ chatId: -100, kind: 'text', text: 'y' }), false);
  assert.equal(daemon.resolvePending({ chatId: 42, kind: 'text', text: 'y' }), true);
  assert.equal(await decision, true);
});

test('a daemon poll replay does not execute the same request twice', async t => {
  let starts = 0;
  const job = { chatId: 42, messageId: 7, kind: 'text', text: 'do this once' };
  const bot = { enabled: true, poll: async () => ({ jobs: [job], offset: 8 }), send: async () => [{ message_id: 1 }], sendTyping: async () => {} };
  const daemon = new Daemon({ store: { setTelegramOffset() {} }, bot, config: { telegramChatId: '42' }, client: {}, runPrompt: async () => '', deliver: async () => {} });
  t.after(() => daemon.stop());
  daemon.chatAgent = () => ({ messages: [], send: async () => { starts++; return 'done'; } }); daemon.saveChat = () => {};
  daemon.offsetReady = true;
  await daemon.pollInbox(); await daemon.drain(); await daemon.pollInbox(); await daemon.drain();
  assert.equal(starts, 1);
});

test('stopping during channel authentication never starts the next enabled channel', async t => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-daemon-channel-stop-')); t.after(() => fs.rmSync(dir, { force: true, recursive: true }));
  const channelStore = new ChannelStore(path.join(dir, 'channels.json')).load();
  channelStore.update('discord', { enabled: true, token: 'fixture', applicationId: 'bot' }); channelStore.update('slack', { enabled: true, botToken: 'fixture', appToken: 'fixture' });
  let authenticate, started; const gate = new Promise(resolve => { started = resolve; }), auth = new Promise(resolve => { authenticate = resolve; }); const starts = [];
  const adapter = id => ({ manifest: { ...channelStore.registry.get(id), capabilities: [] }, send() {}, stop() {}, start() { starts.push(id); this.ready = id === 'discord' ? auth : Promise.resolve({ account: id }); if (id === 'discord') started(); } });
  const daemon = new Daemon({ store: { routines: [], watches: [] }, channelStore, channelAdapterFactories: { discord: () => adapter('discord'), slack: () => adapter('slack') }, config: {}, client: {}, runPrompt() {}, deliver() {} });
  t.after(() => daemon.stop()); const running = daemon.run(); await gate;
  const stopped = daemon.stop(); authenticate({ account: 'discord' }); await running; await stopped;
  assert.deepEqual(starts, ['discord']); assert.equal(daemon.channelRuntimes.get('slack')?.running || false, false);
});
