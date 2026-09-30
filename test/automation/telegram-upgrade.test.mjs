import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { TelegramBot, updateToJob } from '../../src/channels/telegram.mjs';
import { Daemon } from '../../src/automation/daemon.mjs';
import { TelegramProgress, readTelegramArtifact, sendTurnArtifacts } from '../../src/channels/telegram-progress.mjs';

test('Telegram transport supports reactions, photo/document multipart upload and unsupported incoming media nudges', async t => {
  const requests = [];
  t.mock.method(globalThis, 'fetch', async (url, options) => { requests.push({ url, options }); return new Response(JSON.stringify({ ok: true, result: { message_id: 9 } })); });
  const bot = new TelegramBot({ token: 'fixture-token', allowedChatIds: [42] });
  await bot.react(42, 7, '👀');
  assert.deepEqual(JSON.parse(requests[0].options.body).reaction, [{ type: 'emoji', emoji: '👀' }]);
  await bot.sendPhoto(42, Buffer.from('image'), { filename: 'image.png', caption: 'photo', replyTo: 7 });
  assert.equal(requests[1].options.body.get('photo').name, 'image.png');
  await bot.sendDocument(42, Buffer.from('document'), { filename: 'note.txt', mime: 'text/plain' });
  assert.equal(requests[2].options.body.get('document').name, 'note.txt');
  const update = { update_id: 1, message: { chat: { id: 42 }, message_id: 7, photo: [{ file_id: 'image' }], caption: 'ignored attachment caption' } };
  assert.equal(updateToJob(update), null);
  t.mock.method(bot, 'call', async () => [update]);
  const polled = await bot.poll(0);
  assert.equal(polled.jobs.length, 0); assert.equal(polled.unsupported.length, 1);
});

test('CLI channel mirrors progress, artifact sends and cancel without losing approval polling', async t => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-telegram-upgrade-'));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  await fs.mkdir(path.join(directory, 'downloaded-images'));
  const image = path.join(directory, 'downloaded-images', 'turn.png'); await fs.writeFile(image, 'fixture image');
  const sent = [], reactions = [], files = [];
  const bot = { enabled: true, sendTyping: async () => {}, react: async (...args) => reactions.push(args), send: async (_id, text) => sent.push(text), sendPhoto: async (_id, bytes) => files.push(bytes) };
  const daemon = new Daemon({ store: {}, bot, config: {}, client: {}, runPrompt: async () => '', deliver: async () => {} });
  daemon.saveChat = () => {};
  const agent = { cwd: directory, messages: [], send: async (_prompt, callbacks) => { callbacks.onToolCall({ function: { name: 'browser' } }); agent.messages.push({ role: 'tool', name: 'browser', result: JSON.stringify({ type: 'browser_screenshot', path: image }) }); return 'final'; } };
  daemon.chatAgent = () => agent;
  await daemon.handleJob({ chatId: 42, messageId: 7, kind: 'text', text: 'capture' });
  assert.equal(reactions.length, 2); assert.ok(sent.some(text => /Using browser/.test(text))); assert.equal(sent.at(-1), 'final'); assert.equal(files.length, 1);
  let finish, stopped = 0; agent.send = () => new Promise(resolve => { finish = resolve; }); agent.cancel = () => { stopped++; finish('partial'); };
  const work = daemon.handleJob({ chatId: 42, messageId: 8, kind: 'text', text: 'long' });
  await new Promise(resolve => setImmediate(resolve));
  bot.poll = async () => ({ jobs: [{ chatId: 42, messageId: 9, kind: 'text', text: '/cancel' }], offset: 2 }); daemon.offsetReady = true; daemon.store.setTelegramOffset = () => {};
  await daemon.pollInbox(); await work;
  assert.equal(stopped, 1); assert.ok(sent.some(text => /stopped/i.test(text))); assert.ok(!sent.includes('partial')); daemon.stop();
});

test('typing heartbeats and throttled step replies end with the turn and never include model deltas', async t => {
  t.mock.timers.enable({ apis: ['setInterval'] });
  let clock = 0, typing = 0; const sent = [];
  const progress = new TelegramProgress({ sendTyping: async () => { typing++; }, send: async (_id, text) => sent.push(text) }, { chatId: 42, messageId: 7 }, { heartbeatMs: 40, beatIntervalMs: 50, now: () => clock });
  await progress.start();
  t.mock.timers.tick(40); await new Promise(resolve => setImmediate(resolve)); assert.equal(typing, 2);
  progress.beat({ type: 'tool-call', name: 'browser' });
  progress.beat({ type: 'tool-result', name: 'browser' });
  progress.beat({ type: 'assistant-delta', text: 'private model text' });
  await progress.tail; assert.equal(sent.length, 1);
  clock = 50; progress.beat({ type: 'tool-result', name: 'browser' }); await progress.tail;
  assert.equal(sent.length, 2); await progress.stop();
  t.mock.timers.tick(400); await new Promise(resolve => setImmediate(resolve)); assert.equal(typing, 2);
});

test('artifact reads reject outside files and symlink escapes; delivery is capped and photo failure falls back to a document', async t => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'telegram-contained-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const cwd = path.join(root, 'workspace'); await fs.mkdir(path.join(cwd, 'generated-images'), { recursive: true });
  const outside = path.join(root, 'outside.png'); await fs.writeFile(outside, 'private');
  await assert.rejects(readTelegramArtifact(cwd, outside), /outside/);
  const linked = path.join(cwd, 'generated-images', 'linked');
  await fs.symlink(root, linked, process.platform === 'win32' ? 'junction' : 'dir');
  await assert.rejects(readTelegramArtifact(cwd, path.join(linked, 'outside.png')), /outside/);
  const messages = [];
  for (let index = 0; index < 7; index++) { const image = path.join(cwd, 'generated-images', `${index}.png`); await fs.writeFile(image, 'image'); messages.push({ role: 'tool', name: 'image_generate', result: JSON.stringify({ type: 'generated_image', path: image }) }); }
  let photos = 0, documents = 0;
  await sendTurnArtifacts({ sendTyping: async () => {}, sendPhoto: async () => { photos++; throw new Error('photo rejected'); }, sendDocument: async () => { documents++; }, send: () => assert.fail('fallback should upload') }, { chatId: 42 }, cwd, messages);
  assert.equal(photos, 5); assert.equal(documents, 5);
});

test('CLI cancel during initial typing prevents starting the model after the chat action finishes', async () => {
  let release, began; const starting = new Promise(resolve => { began = resolve; });
  const sent = [], bot = { enabled: true, sendTyping: () => { began(); return new Promise(resolve => { release = resolve; }); }, send: async (_id, text) => sent.push(text) };
  const daemon = new Daemon({ store: {}, bot, config: {}, client: {}, runPrompt: async () => '', deliver: async () => {} });
  let starts = 0; daemon.chatAgent = () => ({ send: async () => { starts++; return 'not allowed'; }, cancel: () => {} }); daemon.saveChat = () => {};
  const work = daemon.handleJob({ chatId: 42, messageId: 7, kind: 'text', text: 'task' }); await starting;
  await daemon.cancelChatJob({ chatId: 42, messageId: 8, kind: 'text', text: '/cancel' }); release(); await work;
  assert.equal(starts, 0); assert.ok(!sent.includes('not allowed')); daemon.stop();
});
