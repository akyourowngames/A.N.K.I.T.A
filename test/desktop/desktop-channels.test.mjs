import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ChannelStore, ChannelManager, TelegramChannel, normalizeChatIds, publicTelegram } from '../../desktop/electron/channels.mjs';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';

class StubBot {
  constructor(options = {}) {
    this.options = options;
    this.sent = [];
    this.typing = [];
    this.voices = [];
    this.reactions = [];
    this.files = [];
    this.script = [];
    this.me = { username: 'test_bot' };
  }
  async whoami() { return this.me; }
  async poll(offset) {
    const round = this.script.shift();
    if (!round) return { jobs: [], offset, error: null };
    return { jobs: round.jobs || [], denied: round.denied || [], offset: round.offset ?? offset, error: round.error || null };
  }
  async send(chatId, text, options = {}) { this.sent.push({ chatId, text, ...options }); return [{ message_id: this.sent.length }]; }
  async sendTyping(chatId) { this.typing.push(chatId); }
  async sendVoice(chatId) { this.voices.push(chatId); }
  async react(chatId, messageId, emoji) { this.reactions.push({ chatId, messageId, emoji }); }
  async sendPhoto(chatId, bytes, options) { this.files.push({ chatId, bytes, options, kind: 'photo', after: this.sent.length }); }
  async sendDocument(chatId, bytes, options) { this.files.push({ chatId, bytes, options, kind: 'document', after: this.sent.length }); }
  async download() { return Buffer.from('audio'); }
}

function tempDir(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-channels-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function tempStore(t, patch = {}) {
  const store = new ChannelStore(path.join(tempDir(t), 'channels.json'));
  store.load();
  if (Object.keys(patch).length) store.update(patch);
  return store;
}

function readyChannel(t, { store, engine, bot, emit = () => {} }) {
  const channel = new TelegramChannel({ store, engine, emit, botFactory: () => bot });
  channel.bot = bot;
  channel.running = true;
  channel.abort = new AbortController();
  channel.offsetReady = true;
  return channel;
}

test('channel store validates input and never returns the token', (t) => {
  const store = tempStore(t, { enabled: true, token: 'secret-token', allowedChatIds: '1 2', teammateId: 'chief', confirmTimeout: 120 });
  const fresh = new ChannelStore(store.file).load();
  assert.equal(fresh.telegram().token, 'secret-token');
  assert.equal(fresh.telegram().allowedChatIds, '1, 2');
  const view = publicTelegram(fresh.telegram(), { running: true, account: '@bot' });
  assert.equal(view.hasToken, true);
  assert.equal(view.confirmTimeout, 120);
  assert.equal(JSON.stringify(view).includes('secret-token'), false);
  assert.throws(() => store.update({ confirmTimeout: 5 }), /between 30 and 3600/);
  assert.throws(() => store.update({ nope: true }), /Unknown channel setting/);
});

test('chat ids are canonicalised before they are stored', () => {
  assert.equal(normalizeChatIds(' 123, 456 789 '), '123, 456, 789');
  assert.equal(normalizeChatIds('@channel'), '@channel');
  assert.equal(normalizeChatIds(''), '');
});

test('a telegram message runs the chosen teammate and posts the reply', async (t) => {
  const store = tempStore(t, { enabled: true, token: 'tok', allowedChatIds: '42', teammateId: 'chief' });
  const bot = new StubBot();
  const calls = [];
  const engine = {
    send: async (id, text) => { calls.push([id, text]); return { turnId: 't' }; },
    waitForTurn: async () => 'Hello from the agent',
    respondApproval: () => true,
  };
  const channel = readyChannel(t, { store, engine, bot });
  bot.script.push({ jobs: [{ chatId: 42, from: 'me', kind: 'text', text: 'hi', messageId: 7 }] });
  await channel.tick(bot);
  await channel.chains.get('42');
  assert.deepEqual(calls, [['chief', 'hi']]);
  assert.equal(bot.sent.at(-1).chatId, 42);
  assert.equal(bot.sent.at(-1).text, 'Hello from the agent');
  assert.equal(bot.sent.at(-1).replyTo, 7);
  assert.deepEqual(bot.typing, [42]);
});

test('a denied chat is told its own id so it can be allowed', async (t) => {
  const store = tempStore(t, { enabled: true, token: 'tok', allowedChatIds: '42', teammateId: 'chief' });
  const bot = new StubBot();
  const channel = readyChannel(t, { store, engine: {}, bot });
  bot.script.push({ denied: [{ chatId: 99, from: 'x', kind: 'text', text: 'hi', messageId: 1 }] });
  await channel.tick(bot);
  assert.match(bot.sent[0].text, /chat id is 99/);
});

test('an approval raised during a channel turn is answered from telegram', async (t) => {
  const store = tempStore(t, { enabled: true, token: 'tok', allowedChatIds: '42', teammateId: 'chief', confirmTimeout: 30 });
  const bot = new StubBot();
  let answered = null;
  const engine = {
    send: async () => ({ turnId: 't' }),
    waitForTurn: () => new Promise(() => {}),
    respondApproval: (requestId, answer) => { answered = { requestId, answer }; return true; },
  };
  const events = [];
  const channel = readyChannel(t, { store, engine, bot, emit: event => events.push(event) });
  channel.activeChat = '42';
  channel.handleEngineEvent({ type: 'approval-request', requestId: 'req-1', threadId: 'chief', toolName: 'run_command', detail: 'rm -rf build' });
  assert.match(bot.sent.at(-1).text, /Permission needed: run_command/);
  bot.script.push({ jobs: [{ chatId: 42, kind: 'text', text: 'y', messageId: 2 }] });
  await channel.tick(bot);
  assert.deepEqual(answered, { requestId: 'req-1', answer: 'yes' });
  assert.equal(events.some(event => event.type === 'approval-resolved' && event.requestId === 'req-1'), true);
});

test('start opens the inbox and stop closes it cleanly', async (t) => {
  const store = tempStore(t, { enabled: true, token: 'tok', allowedChatIds: '42', teammateId: 'chief' });
  const bot = new StubBot();
  const channel = new TelegramChannel({ store, engine: {}, botFactory: () => bot });
  const status = await channel.start();
  assert.equal(status.running, true);
  assert.equal(status.account, '@test_bot');
  await channel.stop();
  assert.equal(channel.status().running, false);
});

test('a bad token reports an error instead of running', async (t) => {
  const store = tempStore(t, { enabled: true, token: 'bad', teammateId: 'chief' });
  const channel = new TelegramChannel({
    store,
    engine: {},
    botFactory: () => ({ whoami: async () => { throw new Error('Unauthorized'); } }),
  });
  const status = await channel.start();
  assert.equal(status.running, false);
  assert.match(status.error, /Unauthorized/);
});

test('saving channel settings reconnects and emits the new view without the token', async (t) => {
  const store = tempStore(t);
  const bot = new StubBot();
  const events = [];
  const manager = new ChannelManager({ store, engine: {}, emit: event => events.push(event), botFactory: () => bot });
  manager.load();
  const view = await manager.save({ enabled: true, token: 'tok', allowedChatIds: '42', teammateId: 'chief' });
  assert.equal(view.telegram.enabled, true);
  assert.equal(view.telegram.status.running, true);
  assert.equal(JSON.stringify(view).includes('tok'), false);
  assert.equal(events.some(event => event.type === 'channels-updated'), true);
  await manager.stopAll();
});

test('the desktop engine starts an enabled channel and rejects an unknown teammate', async (t) => {
  const dir = tempDir(t);
  const bot = new StubBot();
  const events = [];
  const engine = new DesktopEngine({
    teammateFile: path.join(dir, 'teammates.json'),
    settingsFile: path.join(dir, 'settings.json'),
    channelsFile: path.join(dir, 'channels.json'),
    sessionsDir: dir,
    config: { provider: 'custom', apiBase: 'http://localhost:11434/v1', apiKey: 'k', model: 'alpha', tools: true },
    bootstrap: async ({ config }) => ({ client: {}, tool: null, models: [{ id: 'alpha', tools: true }], model: 'alpha', provider: { name: config.provider } }),
    mcp: { connectedIds: [], reconcile: async () => {}, ensureComposio: async () => {}, closeAll: async () => {} },
    telegramBotFactory: () => bot,
    emit: event => events.push(event),
  });
  await engine.init();
  const teammate = engine.createTeammate({ name: 'Chief', persona: '', color: '#22d3ee', emoji: '🧭' });
  await assert.rejects(engine.saveChannelSettings('telegram', { teammateId: 'missing' }), /available teammate/);
  const view = await engine.saveChannelSettings('telegram', { enabled: true, token: 'secret', allowedChatIds: '42', teammateId: teammate.id });
  assert.equal(view.telegram.status.running, true);
  assert.equal(view.telegram.teammateId, teammate.id);
  assert.equal(JSON.stringify(view).includes('secret'), false);
  assert.equal(events.some(event => event.type === 'channels-updated'), true);
  await engine.close();
});

test('channel emits bounded tool progress and reactions, sends current-turn files after final text, and cleans up', async t => {
  const store = tempStore(t, { teammateId: 'chief' }), bot = new StubBot();
  const dir = tempDir(t); fs.mkdirSync(path.join(dir, 'generated-images'));
  const image = path.join(dir, 'generated-images', 'current.png'); fs.writeFileSync(image, Buffer.from('fixture image'));
  const old = { role: 'tool', name: 'image_generate', result: JSON.stringify({ type: 'generated_image', path: image }) };
  const agent = { cwd: dir, messages: [old] };
  let finish; const turn = new Promise(resolve => { finish = resolve; });
  const engine = { agentFor: () => agent, send: async () => { channel.handleEngineEvent({ type: 'turn-start', threadId: 'chief', turnId: 'owned' }); }, waitForTurn: () => turn };
  const channel = readyChannel(t, { store, engine, bot });
  const work = channel.handleJob({ chatId: 42, messageId: 7, kind: 'text', text: 'make image' });
  await new Promise(resolve => setImmediate(resolve));
  for (let i = 0; i < 20; i++) channel.handleEngineEvent({ type: 'tool-call', threadId: 'chief', name: 'image_generate', args: { password: 'never-progress' } });
  channel.handleEngineEvent({ type: 'assistant-delta', threadId: 'chief', text: 'never-progress' });
  channel.handleEngineEvent({ type: 'tool-result', threadId: 'chief', text: old.result });
  agent.messages.push(old); finish('Here is the image'); await work;
  assert.equal(bot.reactions.length, 2);
  assert.equal(bot.reactions[0].messageId, 7);
  assert.equal(bot.sent.filter(item => /Using/.test(item.text)).length, 1);
  assert.ok(!JSON.stringify(bot.sent).includes('never-progress'));
  assert.equal(bot.files.length, 1); assert.equal(bot.files[0].kind, 'photo');
  assert.equal(bot.sent[bot.files[0].after - 1].text, 'Here is the image');
  assert.equal(channel.activeJobs.size, 0);
});

test('/cancel bypasses the chat queue and pending approval, stops only its owned turn, and sends no success reply', async t => {
  const store = tempStore(t, { teammateId: 'chief' }), bot = new StubBot();
  let finish, cancelled = 0; const turn = new Promise(resolve => { finish = resolve; });
  const engine = { send: async () => {}, waitForTurn: () => turn, cancel: id => { assert.equal(id, 'chief'); cancelled++; finish('partial reply'); }, respondApproval: () => {} };
  const channel = readyChannel(t, { store, engine, bot });
  const work = channel.handleJob({ chatId: 42, messageId: 7, kind: 'text', text: 'long task' });
  await new Promise(resolve => setImmediate(resolve));
  channel.handleEngineEvent({ type: 'approval-request', threadId: 'chief', requestId: 'pending', toolName: 'run_command', detail: 'action' });
  bot.script.push({ jobs: [{ chatId: 42, messageId: 8, kind: 'text', text: '/cancel' }] });
  await channel.tick(bot); await work;
  assert.equal(cancelled, 1); assert.equal(channel.pending.size, 0);
  assert.ok(bot.sent.some(item => /stopped/i.test(item.text)));
  assert.ok(!bot.sent.some(item => item.text === 'partial reply'));
});

test('another chat starting during final delivery cannot add its files to the preceding chat turn', async t => {
  const store = tempStore(t, { teammateId: 'chief' }), bot = new StubBot(), dir = tempDir(t);
  fs.mkdirSync(path.join(dir, 'generated-images')); const image = path.join(dir, 'generated-images', 'private.png'); fs.writeFileSync(image, 'private image');
  const agent = { cwd: dir, messages: [] }; let release, began, reply;
  const delivering = new Promise(resolve => { began = resolve; });
  const send = bot.send.bind(bot);
  bot.send = async (chatId, text, options) => { if (chatId === 1 && text === 'final A') { began(); await new Promise(resolve => { release = resolve; }); } return send(chatId, text, options); };
  const engine = { agentFor: () => agent, send: async (_id, text) => {
    reply = `final ${text}`;
    if (text === 'B') {
      const result = JSON.stringify({ type: 'generated_image', path: image });
      channel.handleEngineEvent({ type: 'tool-call', threadId: 'chief', callId: 'image-B', name: 'image_generate', args: {} });
      channel.handleEngineEvent({ type: 'tool-result', threadId: 'chief', callId: 'image-B', text: result });
      agent.messages.push({ role: 'tool', name: 'image_generate', result });
    }
  }, waitForTurn: async () => reply };
  const channel = readyChannel(t, { store, engine, bot });
  const first = channel.handleJob({ chatId: 1, messageId: 7, kind: 'text', text: 'A' }); await delivering;
  await channel.handleJob({ chatId: 2, messageId: 8, kind: 'text', text: 'B' }); release(); await first;
  assert.deepEqual(bot.files.map(file => file.chatId), [2]);
});
