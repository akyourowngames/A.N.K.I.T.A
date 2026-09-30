import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { CONFIG_DIR, loadConfig } from '../src/core/config.mjs';
import { TelegramBot } from '../src/channels/telegram.mjs';
import { ChannelStore, TelegramChannel } from '../desktop/electron/channels.mjs';
import { Daemon } from '../src/automation/daemon.mjs';

const CHANNEL_FILE = 'desktop-channels.json'; // Shared desktop channel settings file.
const BEAT_DELAY_MS = 5200; // Milliseconds: cross the production five-second progress throttle and four-second heartbeat.
const CANCEL_DELAY_MS = 100; // Milliseconds: allow the scripted CLI turn to start before cancelling.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l7sAAAAASUVORK5CYII=', 'base64'); // Disposable test image.
const chatId = process.argv[2];
if (!chatId || !/^-?\d+$/.test(chatId)) throw new Error('Supply the explicitly approved test chat ID');
const store = new ChannelStore(path.join(CONFIG_DIR, CHANNEL_FILE)).load();
const token = store.telegram().token || loadConfig().telegramBotToken;
if (!token) throw new Error('No configured bot token; configure it in Ankita settings');
const bot = new TelegramBot({ token, allowedChatIds: [chatId] });
const counts = { actions: 0, progress: 0, reactions: 0, files: 0 };
const call = bot.call.bind(bot);
bot.call = async (method, params, options) => {
  const result = await call(method, params, options);
  if (method === 'sendChatAction') counts.actions++;
  if (method === 'setMessageReaction') counts.reactions++;
  if (method === 'sendPhoto' || method === 'sendDocument') counts.files++;
  if (method === 'sendMessage' && /^Using /.test(params.text)) counts.progress++;
  return result;
};
const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-telegram-live-'));
try {
  await bot.whoami();
  const message = (await bot.send(chatId, 'Ankita upgrade verification: progress, typing, reactions and one sample image.'))[0];
  await fs.mkdir(path.join(directory, 'generated-images'));
  const image = path.join(directory, 'generated-images', 'verification.png'); await fs.writeFile(image, PNG);
  const agent = { cwd: directory, messages: [] }; let work;
  const engine = { agentFor: () => agent, send: async () => {
    work = (async () => {
      channel.handleEngineEvent({ type: 'tool-call', threadId: 'verification', name: 'browser' });
      await delay(BEAT_DELAY_MS);
      channel.handleEngineEvent({ type: 'tool-call', threadId: 'verification', callId: 'image', name: 'image_generate' });
      agent.messages.push({ role: 'tool', name: 'image_generate', result: JSON.stringify({ type: 'generated_image', path: image }) });
      channel.handleEngineEvent({ type: 'tool-result', threadId: 'verification', callId: 'image', text: agent.messages.at(-1).result });
      return 'Desktop channel verification completed; the sample image follows.';
    })();
  }, waitForTurn: () => work };
  const settings = { telegram: () => ({ teammateId: 'verification', voiceReply: false }) };
  const channel = new TelegramChannel({ store: settings, engine }); channel.bot = bot; channel.running = true;
  await channel.handleJob({ kind: 'text', text: 'verification', chatId, messageId: message.message_id });
  assert.equal(channel.activeJobs.size, 0); assert.equal(counts.files, 1); assert.equal(counts.progress, 2); assert.ok(counts.actions >= 3); assert.equal(counts.reactions, 2);
  console.log('TELEGRAM_DESKTOP_LIVE_OK: real Bot API typing heartbeat, two throttled step replies, final reply, one multipart image, received/completed reactions');
  const cancelMessage = (await bot.send(chatId, 'Ankita verification: checking CLI cancellation next.'))[0];
  const daemon = new Daemon({ store: {}, bot, config: {}, client: {}, runPrompt: async () => '', deliver: async () => {} });
  let finish, cancelCount = 0;
  const cli = { cwd: directory, messages: [], send: async () => new Promise(resolve => { finish = resolve; }), cancel: () => { cancelCount++; finish('partial'); } };
  daemon.chatAgent = () => cli; daemon.saveChat = () => {};
  const pending = daemon.handleJob({ kind: 'text', text: 'verification', chatId, messageId: cancelMessage.message_id });
  while (!finish) await delay(CANCEL_DELAY_MS);
  await daemon.cancelChatJob({ kind: 'text', text: '/cancel', chatId, messageId: cancelMessage.message_id }); await pending; daemon.stop();
  assert.equal(cancelCount, 1); assert.equal(daemon.chatTurns.size, 0); assert.equal(counts.reactions, 4);
  console.log('TELEGRAM_CLI_CANCEL_LIVE_OK: real received/failed reactions and stopped reply; partial answer suppressed');
  console.log(`TELEGRAM_UPGRADE_LIVE_OK ${JSON.stringify(counts)}; scripted engine/CLI agent, real Telegram transport; no inbound poll cursor modified`);
} finally { await fs.rm(directory, { recursive: true, force: true }); }
