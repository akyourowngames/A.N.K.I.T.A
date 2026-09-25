import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { TelegramBot, parseChatIds } from '../../src/channels/telegram.mjs';
import { parseApproval, isBareApproval, stripAnsi } from '../../src/automation/daemon.mjs';
import {
  transcribeGroq,
  convertAudio,
  resolveTtsProvider,
  resolveTtsVoice,
  synthesizeGroq,
  synthesizeEdge,
} from '../../src/channels/voice.mjs';

/**
 * Desktop channels: a long-lived bridge between an external chat service and a
 * teammate in the running app. Telegram is the first channel; the store and
 * manager are shaped so a second one can slot in beside it.
 *
 * Unlike the CLI daemon, a channel does not own a conversation: it routes every
 * allowed message to one chosen teammate, so Telegram and the desktop share the
 * same thread and history. Approvals raised during a channel turn are forwarded
 * to the chat that started it and answered from there.
 */

const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

export const TELEGRAM_DEFAULTS = {
  enabled: false,
  token: '',
  allowedChatIds: '',
  ownerChatId: '',
  teammateId: null,
  voiceReply: false,
  confirmTimeout: 300,
};

/** Canonical comma-separated chat list, so "1 2" and "1,2" compare equal. */
export function normalizeChatIds(value) {
  return parseChatIds(value).join(', ');
}

export function validateTelegramPatch(patch) {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) throw new Error('Invalid channel update');
  const clean = {};
  for (const [key, value] of Object.entries(patch)) {
    if (key === 'enabled' || key === 'voiceReply') {
      if (typeof value !== 'boolean') throw new Error(`Invalid ${key} value`);
      clean[key] = value;
    } else if (key === 'token') {
      if (typeof value !== 'string') throw new Error('Invalid bot token');
      const token = value.trim();
      if (token.length > 512) throw new Error('Bot token is too long');
      clean.token = token;
    } else if (key === 'allowedChatIds') {
      if (typeof value !== 'string') throw new Error('Invalid allowed chat ids');
      if (value.length > 1024) throw new Error('Allowed chat ids are too long');
      clean.allowedChatIds = normalizeChatIds(value);
    } else if (key === 'ownerChatId') {
      if (typeof value !== 'string') throw new Error('Invalid owner chat id');
      clean.ownerChatId = value.trim().slice(0, 64);
    } else if (key === 'teammateId') {
      if (value != null && typeof value !== 'string') throw new Error('Invalid teammate');
      clean.teammateId = value ? value.slice(0, 64) : null;
    } else if (key === 'confirmTimeout') {
      const n = Number(value);
      if (!Number.isFinite(n) || n < 30 || n > 3600) throw new Error('Approval timeout must be between 30 and 3600 seconds');
      clean.confirmTimeout = Math.floor(n);
    } else {
      throw new Error(`Unknown channel setting: ${key}`);
    }
  }
  return clean;
}

export function publicTelegram(config = {}, status = {}) {
  return {
    enabled: Boolean(config.enabled),
    hasToken: Boolean(config.token),
    allowedChatIds: config.allowedChatIds || '',
    ownerChatId: config.ownerChatId || '',
    teammateId: config.teammateId || null,
    voiceReply: Boolean(config.voiceReply),
    confirmTimeout: config.confirmTimeout || TELEGRAM_DEFAULTS.confirmTimeout,
    status: { running: Boolean(status.running), account: status.account || null, error: status.error || null },
  };
}

export class ChannelStore {
  constructor(file) {
    this.file = file;
    this.data = { telegram: { ...TELEGRAM_DEFAULTS } };
  }

  load() {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      const saved = parsed?.channels?.telegram || {};
      this.data = { telegram: { ...TELEGRAM_DEFAULTS, ...validateTelegramPatch(saved) } };
    } catch (error) {
      // A corrupt or unreadable file should not stop the app from starting.
      if (error.code !== 'ENOENT') this.data = { telegram: { ...TELEGRAM_DEFAULTS } };
    }
    return this;
  }

  telegram() {
    return { ...TELEGRAM_DEFAULTS, ...this.data.telegram };
  }

  preview(patch) {
    const next = validateTelegramPatch(patch || {});
    return { telegram: { ...this.telegram(), ...next } };
  }

  save(next) {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const temp = path.join(path.dirname(this.file), `.${path.basename(this.file)}.${process.pid}.tmp`);
    try {
      fs.writeFileSync(temp, JSON.stringify({ version: 1, channels: next }, null, 2), { mode: 0o600 });
      fs.renameSync(temp, this.file);
      try { fs.chmodSync(this.file, 0o600); } catch { /* Windows may ignore mode changes. */ }
    } finally {
      try { fs.unlinkSync(temp); } catch {}
    }
    this.data = next;
    return this;
  }

  update(patch) { return this.save(this.preview(patch)); }
}

export class TelegramChannel {
  constructor({ store, engine = null, getConfig = () => ({}), emit = () => {}, log = () => {}, botFactory = (options) => new TelegramBot(options) } = {}) {
    this.store = store;
    this.engine = engine;
    this.getConfig = getConfig;
    this.emit = emit;
    this.log = log;
    this.botFactory = botFactory;
    this.bot = null;
    this.running = false;
    this.account = null;
    this.error = null;
    this.stopping = false;
    this.loopPromise = null;
    this.abort = null;
    this.offset = 0;
    this.offsetReady = false;
    // One pending approval per chat, keyed by the chat that started the turn.
    this.pending = new Map();
    this.chains = new Map();
    this.activeChat = null;
  }

  settings() { return this.store.telegram(); }

  status() { return { running: this.running, account: this.account, error: this.error }; }

  async start() {
    if (this.running) return this.status();
    const settings = this.settings();
    if (!settings.enabled || !settings.token) {
      this.bot = null;
      this.running = false;
      this.account = null;
      this.error = null;
      return this.status();
    }
    const bot = this.botFactory({
      token: settings.token,
      allowedChatIds: parseChatIds(settings.allowedChatIds),
      ownerChatId: settings.ownerChatId || null,
    });
    try {
      const me = await bot.whoami();
      this.bot = bot;
      this.account = me?.username ? `@${me.username}` : null;
      this.error = null;
    } catch (err) {
      this.bot = null;
      this.running = false;
      this.account = null;
      this.error = err.message;
      this.emit();
      return this.status();
    }
    this.running = true;
    this.stopping = false;
    this.offset = 0;
    this.offsetReady = false;
    this.abort = new AbortController();
    this.loopPromise = this.loop(bot);
    this.emit();
    return this.status();
  }

  async stop() {
    if (!this.running && !this.bot && !this.loopPromise) return this.status();
    this.stopping = true;
    this.running = false;
    this.abort?.abort(new Error('channel stopped'));
    for (const entry of this.pending.values()) entry.settle('no');
    this.pending.clear();
    this.chains.clear();
    try { await this.loopPromise; } catch {}
    this.loopPromise = null;
    this.bot = null;
    this.account = null;
    this.emit();
    return this.status();
  }

  async loop(bot) {
    while (!this.stopping && this.bot === bot) {
      let handled = 0;
      try {
        handled = await this.tick(bot);
      } catch (err) {
        if (this.stopping) break;
        this.error = err.message;
        this.emit();
        await this.pause(5000);
        continue;
      }
      // A long-poll already waited; only pause when a round returned empty.
      if (!handled) await this.pause(2000);
    }
  }

  /** Sleeps, but wakes immediately on stop so quit never waits on a backoff. */
  pause(ms) {
    if (this.stopping) return Promise.resolve();
    return new Promise((resolve) => {
      const timer = setTimeout(resolve, ms);
      timer.unref?.();
      const onAbort = () => { clearTimeout(timer); resolve(); };
      if (this.abort?.signal.aborted) onAbort();
      else this.abort?.signal.addEventListener('abort', onAbort, { once: true });
    });
  }

  /** One poll round. Returns the number of routed messages. */
  async tick(bot) {
    if (!this.offsetReady) {
      const drain = await bot.poll(-1, { timeoutSec: 0, signal: this.abort?.signal });
      this.offsetReady = true;
      if (!drain.error && drain.offset > 0) this.offset = drain.offset;
      return 0;
    }
    const { jobs, denied, offset, error } = await bot.poll(this.offset, { signal: this.abort?.signal });
    if (this.stopping) return 0;
    if (error) {
      this.error = error;
      this.emit();
      return 0;
    }
    if (this.error) {
      this.error = null;
      this.emit();
    }
    if (offset !== this.offset && offset > 0) this.offset = offset;
    for (const job of denied || []) {
      bot.send(job.chatId, `This bot is private. Your chat id is ${job.chatId} - add it to Allowed chat ids to allow it.`).catch(() => {});
    }
    for (const job of jobs || []) {
      if (this.resolvePending(job)) continue;
      if (job.kind === 'text' && isBareApproval(job.text)) {
        bot.send(job.chatId, 'Nothing is waiting for approval right now.', { replyTo: job.messageId }).catch(() => {});
        continue;
      }
      this.dispatch(job);
    }
    return (jobs || []).length;
  }

  dispatch(job) {
    const key = String(job.chatId);
    const previous = this.chains.get(key) || Promise.resolve();
    const next = previous
      .then(() => this.handleJob(job))
      .catch((err) => this.log(`telegram chat ${key} failed: ${err.message}`))
      .finally(() => {
        if (this.chains.get(key) === next) this.chains.delete(key);
      });
    this.chains.set(key, next);
    return next;
  }

  async handleJob(job) {
    const bot = this.bot;
    if (!bot) return;
    const teammateId = this.settings().teammateId;
    if (!teammateId) {
      await bot.send(job.chatId, 'No agent is connected to this channel yet. Choose a teammate in Settings, then Channels.').catch(() => {});
      return;
    }
    let text = job.text || '';
    if (job.kind === 'voice') {
      try {
        text = await this.transcribe(job);
      } catch (err) {
        await bot.send(job.chatId, `I could not read that voice note: ${err.message}`).catch(() => {});
        return;
      }
      if (!text) {
        await bot.send(job.chatId, 'I could not make out that voice note.').catch(() => {});
        return;
      }
    }
    const chatId = String(job.chatId);
    try {
      await bot.sendTyping(job.chatId);
      await this.runTurn(teammateId, text, chatId);
      const reply = await this.engine.waitForTurn(teammateId);
      const body = String(reply || '').trim() || '(no reply)';
      await bot.send(job.chatId, body, { replyTo: job.messageId });
      if (this.settings().voiceReply) await this.speak(job.chatId, body);
    } catch (err) {
      await bot.send(job.chatId, `error: ${err.message}`).catch(() => {});
    } finally {
      if (this.activeChat === chatId) this.activeChat = null;
    }
  }

  /**
   * The teammate runs one turn at a time. A message that arrives mid-turn waits
   * for the current reply and retries once rather than surfacing a race. The
   * chat claims the turn only once it actually starts, so an approval from the
   * running turn is never routed to a chat that is still waiting.
   */
  async runTurn(teammateId, text, chatId) {
    try {
      await this.engine.send(teammateId, text);
    } catch (err) {
      if (!/already replying/i.test(String(err.message))) throw err;
      await this.engine.waitForTurn(teammateId);
      await this.engine.send(teammateId, text);
    }
    this.activeChat = chatId;
  }

  async transcribe(job) {
    const config = this.getConfig();
    if (!config.groqApiKey) throw new Error('set a Groq API key to transcribe voice notes');
    const ogg = await this.bot.download(job.fileId);
    const wav = await convertAudio(ogg, { to: 'wav' });
    const wavPath = path.join(os.tmpdir(), `ankita-tg-${Date.now()}.wav`);
    fs.writeFileSync(wavPath, wav);
    try {
      return await transcribeGroq({ apiKey: config.groqApiKey, model: config.sttModel, wavPath });
    } finally {
      try { fs.unlinkSync(wavPath); } catch {}
    }
  }

  async speak(chatId, text) {
    const config = this.getConfig();
    try {
      const provider = resolveTtsProvider(config);
      const audio = provider === 'groq'
        ? await synthesizeGroq({ apiKey: config.groqApiKey, model: config.ttsModel, voice: resolveTtsVoice(config, 'groq'), text })
        : await synthesizeEdge({ voice: resolveTtsVoice(config, 'edge'), rate: config.ttsRate, text });
      const ogg = await convertAudio(audio, { to: 'ogg' });
      await this.bot.sendVoice(chatId, ogg);
    } catch (err) {
      this.log(`telegram voice reply failed: ${err.message}`);
    }
  }

  /** Routes an approval raised by the connected teammate to the chat that asked. */
  handleEngineEvent(event) {
    if (event?.type !== 'approval-request' || !this.running || !this.bot) return;
    if (!this.activeChat) return; // desktop-initiated turn; the dialog handles it
    if (this.settings().teammateId !== event.threadId) return;
    this.askApproval(this.activeChat, event);
  }

  askApproval(chatId, event) {
    const bot = this.bot;
    const body = stripAnsi(event.detail).trim();
    const timeoutSec = this.settings().confirmTimeout || TELEGRAM_DEFAULTS.confirmTimeout;
    bot.send(chatId, `Permission needed: ${event.toolName}\n\n${body}\n\nReply y = allow once, a = always, n = deny`).catch(() => {});
    const entry = {
      settle: (answer) => {
        clearTimeout(entry.timer);
        if (this.pending.get(chatId) === entry) this.pending.delete(chatId);
        this.engine.respondApproval(event.requestId, answer);
        this.emit({ type: 'approval-resolved', requestId: event.requestId });
      },
    };
    entry.timer = setTimeout(() => {
      const stillWaiting = this.pending.get(chatId) === entry;
      entry.settle('no');
      if (stillWaiting) bot.send(chatId, `No reply, so I skipped ${event.toolName}.`).catch(() => {});
    }, timeoutSec * 1000);
    this.pending.set(chatId, entry);
  }

  resolvePending(job) {
    const key = String(job.chatId);
    const waiting = this.pending.get(key);
    if (!waiting) return false;
    if (job.kind !== 'text') {
      this.bot?.send(key, 'Reply with text (y / n / a) to approve.').catch(() => {});
      return true;
    }
    waiting.settle(parseApproval(job.text));
    return true;
  }
}

export class ChannelManager {
  constructor({ store, engine = null, getConfig = () => ({}), emit = () => {}, log = () => {}, botFactory } = {}) {
    this.store = store;
    this.engine = engine;
    this.log = log;
    this._emit = emit;
    this.telegram = new TelegramChannel({ store, engine, getConfig, emit: (event) => this.emit(event), log, ...(botFactory ? { botFactory } : {}) });
  }

  load() { this.store.load(); return this; }

  publicView() {
    return { telegram: publicTelegram(this.store.telegram(), this.telegram.status()) };
  }

  /** Sends an engine event, or the current channels view when none is given. */
  emit(event = null) {
    this._emit(event && event.type ? event : { type: 'channels-updated', channels: this.publicView() });
  }

  async startEnabled() {
    await this.telegram.start();
    return this.publicView();
  }

  async stopAll() {
    await this.telegram.stop();
  }

  async save(patch) {
    this.store.update(patch);
    // Reconnecting is cheap and the only way to pick up a new token or allowlist.
    await this.telegram.stop();
    await this.telegram.start();
    const view = this.publicView();
    this.emit({ type: 'channels-updated', channels: view });
    return view;
  }

  handleEngineEvent(event) { this.telegram.handleEngineEvent(event); }
}
