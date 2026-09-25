/**
 * Telegram Bot API client (raw HTTPS long-polling — no framework, no webhook).
 *
 * Scope note: a bot only receives messages sent *to it*, plus posts in groups
 * and channels it belongs to. It cannot read your personal DMs with other
 * humans — that needs a user-account (MTProto) client.
 */

export const TG_LIMIT = 4096;

/** Splits text into Telegram-sized chunks on paragraph, line, then word bounds. */
export function splitMessage(text, limit = TG_LIMIT) {
  const src = String(text ?? "");
  if (src.length <= limit) return src ? [src] : [];
  const chunks = [];
  let rest = src;

  while (rest.length > limit) {
    const window = rest.slice(0, limit);
    let cut = window.lastIndexOf("\n\n");
    if (cut < limit * 0.5) cut = window.lastIndexOf("\n");
    if (cut < limit * 0.5) cut = window.lastIndexOf(" ");
    if (cut <= 0) cut = limit;
    chunks.push(rest.slice(0, cut).trimEnd());
    rest = rest.slice(cut).replace(/^\s+/, "");
  }
  if (rest) chunks.push(rest);
  return chunks;
}

/** Normalises a Telegram update into the job the daemon should run. */
export function updateToJob(update) {
  const message = update?.message || update?.edited_message || update?.channel_post;
  if (!message) return null;
  const chatId = message.chat?.id;
  if (chatId === undefined || chatId === null) return null;

  const from = message.from?.username || message.from?.first_name || message.chat?.title || String(chatId);

  if (typeof message.text === "string" && message.text.trim()) {
    return { chatId, from, kind: "text", text: message.text.trim(), messageId: message.message_id };
  }
  const voice = message.voice || message.audio || (message.document?.mime_type || "").startsWith("audio")
    ? message.voice || message.audio || message.document
    : null;
  if (voice?.file_id) {
    return {
      chatId,
      from,
      kind: "voice",
      fileId: voice.file_id,
      durationSec: voice.duration || null,
      mimeType: voice.mime_type || "audio/ogg",
      messageId: message.message_id,
    };
  }
  if (typeof message.caption === "string" && message.caption.trim()) {
    return { chatId, from, kind: "text", text: message.caption.trim(), messageId: message.message_id };
  }
  return null;
}

export function parseChatIds(value) {
  return String(value ?? "")
    .split(/[,\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => (/^-?\d+$/.test(s) ? Number(s) : s));
}

export class TelegramBot {
  constructor({ token = "", allowedChatIds = [], ownerChatId = null, timeoutMs = 45000 } = {}) {
    this.token = String(token || "").trim();
    this.allowed = new Set(allowedChatIds.map((id) => String(id)));
    this.ownerChatId = ownerChatId ? String(ownerChatId) : null;
    this.timeoutMs = timeoutMs;
    this.me = null;
  }

  get enabled() {
    return Boolean(this.token);
  }

  isAllowed(chatId) {
    if (!this.allowed.size) return false;
    return this.allowed.has(String(chatId));
  }

  async call(method, params = {}, { timeoutMs = 30000, signal = null } = {}) {
    if (!this.enabled) throw new Error("TELEGRAM_BOT_TOKEN is not set");
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(new Error("telegram timeout")), timeoutMs);
    const onAbort = () => ctrl.abort(signal.reason || new Error("telegram aborted"));
    if (signal) {
      if (signal.aborted) onAbort();
      else signal.addEventListener("abort", onAbort, { once: true });
    }
    try {
      const res = await fetch(`https://api.telegram.org/bot${this.token}/${method}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(params),
        signal: ctrl.signal,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(`telegram ${method} failed (${res.status}): ${data.description || "unknown error"}`);
      }
      return data.result;
    } finally {
      clearTimeout(timer);
      if (signal) signal.removeEventListener("abort", onAbort);
    }
  }

  async whoami() {
    if (!this.me) this.me = await this.call("getMe", {}, { timeoutMs: 15000 });
    return this.me;
  }

  /** One long-poll round. Returns normalised jobs (never throws on transient errors). */
  async poll(offset, { timeoutSec = 25, signal = null } = {}) {
    let updates;
    try {
      updates = await this.call("getUpdates", { offset, timeout: timeoutSec }, { timeoutMs: (timeoutSec + 15) * 1000, signal });
    } catch (err) {
      return { jobs: [], offset, error: err.message };
    }
    const jobs = [];
    let next = offset;
    const denied = [];
    for (const update of updates || []) {
      next = Math.max(next, (update.update_id || 0) + 1);
      const job = updateToJob(update);
      if (!job) continue;
      if (!this.isAllowed(job.chatId)) {
        denied.push(job);
        continue;
      }
      jobs.push(job);
    }
    return { jobs, denied, offset: next, error: null };
  }

  async send(chatId, text, { replyTo = null } = {}) {
    const parts = splitMessage(text);
    const sent = [];
    for (const part of parts) {
      sent.push(
        await this.call("sendMessage", {
          chat_id: chatId,
          text: part,
          disable_web_page_preview: true,
          ...(replyTo ? { reply_to_message_id: replyTo, allow_sending_without_reply: true } : {}),
        })
      );
    }
    return sent;
  }

  async sendVoice(chatId, oggBuffer, { caption = "" } = {}) {
    const form = new FormData();
    form.append("chat_id", String(chatId));
    if (caption) form.append("caption", caption.slice(0, 1000));
    form.append("voice", new Blob([oggBuffer], { type: "audio/ogg" }), "reply.ogg");
    const res = await fetch(`https://api.telegram.org/bot${this.token}/sendVoice`, {
      method: "POST",
      body: form,
      signal: AbortSignal.timeout(60000),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(`telegram sendVoice failed: ${data.description || res.status}`);
    return data.result;
  }

  async sendTyping(chatId) {
    try {
      await this.call("sendChatAction", { chat_id: chatId, action: "typing" }, { timeoutMs: 10000 });
    } catch {}
  }

  /** Downloads a voice note into a Buffer. */
  async download(fileId) {
    const file = await this.call("getFile", { file_id: fileId }, { timeoutMs: 20000 });
    if (!file?.file_path) throw new Error("telegram getFile returned no file_path");
    const res = await fetch(`https://api.telegram.org/file/bot${this.token}/${file.file_path}`, {
      signal: AbortSignal.timeout(60000),
    });
    if (!res.ok) throw new Error(`telegram download failed (${res.status})`);
    return Buffer.from(await res.arrayBuffer());
  }
}
