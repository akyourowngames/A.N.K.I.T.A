import { TelegramBot, parseChatIds, splitMessage, updateToJob, unsupportedMediaJob, UNSUPPORTED_MEDIA_MESSAGE } from './telegram.mjs';
import { telegramManifest, TELEGRAM_CHANNEL_ID } from './manifests/telegram.mjs';
import { ACK_STATES, POLL_ERROR_DELAY_MS, POLL_EMPTY_DELAY_MS, REQUEST_TIMEOUT_MS, SOCKET_OPEN_TIMEOUT_MS, abortableDelay } from './core/contract.mjs';
import { DeliveryError } from './core/outbox.mjs';
import { requestJson, httpFailure } from './core/http.mjs';

const TELEGRAM_POLL_SECONDS = 25; // Seconds: retain the established long-poll window.
const TELEGRAM_POLL_GRACE_SECONDS = 15; // Seconds: Bot API round trip may outlast its server wait.
const SECONDS_TO_MS = 1000; // Milliseconds per API retry-after/poll second.

/** Existing raw transport remains import-compatible; add policy metadata at its edge. */
export class ChannelTelegramBot extends TelegramBot {
  async whoami({ signal } = {}) {
    if (!this.me) this.me = await this.call('getMe', {}, { signal, timeoutMs: SOCKET_OPEN_TIMEOUT_MS });
    return this.me;
  }
  async call(method, params = {}, { timeoutMs = REQUEST_TIMEOUT_MS, signal } = {}) {
    if (!this.enabled) throw new DeliveryError('permanent', 'Telegram bot token is not set');
    const multipart = params instanceof FormData;
    const { data, status, headers } = await requestJson(`${this.apiBase}/bot${this.token}/${method}`, {
      platform: 'Telegram', method: 'POST', timeoutMs, signal,
      ...(multipart ? {} : { headers: { 'Content-Type': 'application/json' } }),
      body: multipart ? params : JSON.stringify(params),
    });
    if (data.ok === false) throw httpFailure('Telegram', status, data, headers);
    return data.result;
  }
  async poll(offset, { timeoutSec = TELEGRAM_POLL_SECONDS, signal = null } = {}) {
    let updates;
    try { updates = await this.call('getUpdates', { offset, timeout: timeoutSec }, { timeoutMs: (timeoutSec + TELEGRAM_POLL_GRACE_SECONDS) * SECONDS_TO_MS, signal }); }
    catch (error) { return { jobs: [], offset, error: error.message }; }
    const jobs = [], unsupported = []; let next = offset;
    for (const update of updates || []) {
      next = Math.max(next, (update.update_id || 0) + 1);
      const source = update.message || update.edited_message || update.channel_post;
      const job = updateToJob(update), media = job ? null : unsupportedMediaJob(update);
      if (!source || (!job && !media)) continue;
      const value = job || { ...media, kind: 'unsupported' };
      const text = String(source.text || source.caption || '');
      value.channelMetadata = {
        senderId: String(source.from?.id ?? source.chat.id), senderName: value.from || '',
        isGroup: source.chat.type ? source.chat.type !== 'private' : Number(source.chat.id) < 0,
        bot: Boolean(source.from?.is_bot),
        mentioned: Boolean(this.me?.username && text.toLowerCase().includes(`@${this.me.username.toLowerCase()}`)),
      };
      if (source.message_thread_id) value.messageThreadId = source.message_thread_id;
      (job ? jobs : unsupported).push(value);
    }
    return { jobs, unsupported, denied: [], offset: next, error: null };
  }
}

export function telegramEnvelope(job) {
  const chatId = String(job.chatId), metadata = job.channelMetadata || {};
  return {
    channel: TELEGRAM_CHANNEL_ID, chatId, messageId: String(job.messageId),
    senderId: metadata.senderId || chatId, senderName: metadata.senderName || job.from || '', text: job.text || '',
    media: job.kind === 'voice' ? [{ kind: 'voice', fileId: job.fileId, mimeType: job.mimeType || 'audio/ogg' }] : job.kind === 'unsupported' ? [{ kind: 'unsupported' }] : [],
    threadId: job.messageThreadId ?? null, raw: { ...metadata, isGroup: metadata.isGroup ?? Number(job.chatId) < 0, job },
  };
}

const platformId = id => id == null ? null : parseChatIds(String(id))[0];
const optionsFor = ref => ({ replyTo: platformId(ref.replyTo), messageThreadId: platformId(ref.threadId) });
const receiptFor = result => {
  const parts = (Array.isArray(result) ? result : result ? [result] : []).map(part => String(part.message_id));
  return { messageId: parts.at(-1) || null, parts };
};

function telegramFailure(error) {
  if (error instanceof DeliveryError) return error;
  const match = /failed \((\d+)\)/.exec(String(error.message));
  if (!match) return new DeliveryError('unknown', 'Telegram send outcome is unknown; check the chat before retrying');
  const status = Number(match[1]);
  if (status === 429) return new DeliveryError('rate_limited', 'Telegram rate limit; retrying safely');
  if (status >= 400 && status < 500) return new DeliveryError('permanent', `Telegram rejected this delivery (HTTP ${status})`, { deadTarget: [403, 404].includes(status) });
  return new DeliveryError('unknown', 'Telegram send outcome is unknown; check the chat before retrying');
}

export class TelegramAdapter {
  constructor({ bot = null, botFactory = options => new ChannelTelegramBot(options), cursor = null } = {}) {
    this.manifest = telegramManifest; this.bot = bot; this.botFactory = botFactory; this.cursor = cursor;
    this.offset = cursor?.get?.() || 0; this.offsetReady = this.offset > 0; this.stopping = false;
  }
  split(text) { return splitMessage(text); }
  async verify(settings) {
    const bot = this.botFactory({ token: settings.token });
    const me = await bot.whoami();
    return { account: me?.username ? `@${me.username}` : null, username: me?.username || null, name: [me?.first_name, me?.last_name].filter(Boolean).join(' ') || null };
  }
  start(ctx) {
    this.ctx = ctx; this.stopping = false; this.controller = new AbortController();
    this.onAbort = () => this.controller.abort(ctx.signal.reason);
    ctx.signal.addEventListener('abort', this.onAbort, { once: true });
    let resolve, reject; this.ready = new Promise((yes, no) => { resolve = yes; reject = no; });
    return (async () => {
      try {
        this.bot ||= this.botFactory({ token: ctx.settings.token, allowedChatIds: parseChatIds(ctx.settings.allowedChatIds), ownerChatId: ctx.settings.ownerChatId || null });
        const me = await this.bot.whoami({ signal: this.controller.signal });
        resolve({ account: me?.username ? `@${me.username}` : null });
        while (!this.stopping && !this.controller.signal.aborted) {
          try { const count = await this.tick(ctx); if (!count) await abortableDelay(POLL_EMPTY_DELAY_MS, this.controller.signal); }
          catch (error) { if (this.controller.signal.aborted) break; ctx.status?.({ error: error.message }); await abortableDelay(POLL_ERROR_DELAY_MS, this.controller.signal); }
        }
      } catch (error) { reject(error); if (!this.stopping && !ctx.signal.aborted) throw error; }
      finally { ctx.signal.removeEventListener('abort', this.onAbort); }
    })();
  }
  async stop() { this.stopping = true; this.controller?.abort(new DOMException('Telegram stopped', 'AbortError')); this.bot = null; }
  async tick(ctx = this.ctx, bot = this.bot) {
    if (!this.offsetReady) {
      const drain = await bot.poll(-1, { timeoutSec: 0, signal: this.controller?.signal || ctx.signal });
      this.offsetReady = true;
      if (!drain.error && drain.offset > 0) { this.offset = drain.offset; this.cursor?.set?.(this.offset); }
      return 0;
    }
    const { jobs = [], denied = [], unsupported = [], offset, error } = await bot.poll(this.offset, { signal: this.controller?.signal || ctx.signal });
    if (this.stopping || ctx.signal?.aborted) return 0;
    if (error) { ctx.status?.({ error }); return 0; }
    ctx.status?.({ error: null });
    for (const job of denied) if (!job.channelMetadata?.bot) await this.send({ ...telegramEnvelope(job), parts: [`This bot is private. Your chat id is ${job.chatId} - add it to Allowed chat ids to allow it.`] }).catch(() => {});
    let routed = 0;
    for (const job of jobs) routed += Number(await ctx.receive(telegramEnvelope(job))) || 0;
    for (const job of unsupported) await ctx.receive(telegramEnvelope({ ...job, kind: 'unsupported' }));
    // Commit after acceptance. On a partial failure, replayed earlier inputs hit the durable dedupe ledger.
    if (offset > 0 && offset !== this.offset) { this.offset = offset; this.cursor?.set?.(offset); }
    return routed;
  }
  async send(ref) {
    try { return receiptFor(await this.bot.send(platformId(ref.chatId), ref.parts.join('\n'), optionsFor(ref))); }
    catch (error) { throw telegramFailure(error); }
  }
  typing(ref, action = 'typing') { return this.bot.sendTyping(platformId(ref.chatId), action, platformId(ref.threadId)); }
  react(ref, state) { return this.bot.react?.(platformId(ref.chatId), platformId(ref.messageId), ACK_STATES[state] || state); }
  download(ref) { return this.bot.download(ref.media[0].fileId); }
  voice(ref, file) { return this.bot.sendVoice(platformId(ref.chatId), Buffer.from(file.base64, 'base64'), optionsFor(ref)); }
  async upload(ref, file) {
    const bytes = Buffer.from(file.base64, 'base64'), options = { filename: file.filename, mime: file.mime, caption: file.caption, ...optionsFor(ref) };
    try {
      if (!file.photo) return receiptFor(await this.bot.sendDocument(platformId(ref.chatId), bytes, options));
      try { return receiptFor(await this.bot.sendPhoto(platformId(ref.chatId), bytes, options)); }
      catch (error) {
        const failure = telegramFailure(error);
        if (failure.kind !== 'permanent' || failure.deadTarget) throw failure;
        return receiptFor(await this.bot.sendDocument(platformId(ref.chatId), bytes, options));
      }
    } catch (error) { throw telegramFailure(error); }
  }
  get unsupportedMediaMessage() { return UNSUPPORTED_MEDIA_MESSAGE; }
}
