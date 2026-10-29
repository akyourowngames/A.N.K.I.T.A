import test from 'node:test';
import assert from 'node:assert/strict';
import { Daemon } from '../../src/automation/daemon.mjs';

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
