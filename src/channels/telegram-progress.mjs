import fs from 'node:fs/promises';
import path from 'node:path';
import { recentArtifacts } from '../../desktop/electron/workspace.mjs';

const HEARTBEAT_MS = 4000; // Milliseconds: Telegram chat actions expire within five seconds.
const BEAT_INTERVAL_MS = 5000; // Milliseconds: at most one interim step label per interval.
const STEP_LABEL_LIMIT = 80; // Characters: no tool arguments or model text in progress replies.
const MAX_ARTIFACTS = 5; // Files per turn; remaining files stay in the workspace.
const MAX_ARTIFACT_BYTES = 15 * 1024 * 1024; // Bytes: bounded workspace artifact reads.
const MAX_PHOTO_BYTES = 10 * 1024 * 1024; // Bytes: Telegram's photo limit; larger images use documents.
const ARTIFACT_FOLDERS = new Set(['generated-images', 'downloaded-images']); // Same containment scope as desktop image previews.
const IMAGE_MIMES = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' };
// Telegram does not support the plan's hourglass/check/cross as reactions.
// These supported bot acknowledgements mean received, completed and failed.
export const TELEGRAM_ACK = { received: '👀', complete: '👍', failed: '👎' };
export const isCancelMessage = job => job.kind === 'text' && /^\/cancel(?:@\w+)?$/i.test(job.text?.trim());

export class TelegramProgress {
  constructor(bot, job, { heartbeatMs = HEARTBEAT_MS, beatIntervalMs = BEAT_INTERVAL_MS, now = Date.now } = {}) {
    this.bot = bot; this.job = job; this.heartbeatMs = heartbeatMs; this.beatIntervalMs = beatIntervalMs; this.now = now;
    this.lastBeat = -Infinity; this.closed = false; this.tail = Promise.resolve(); this.typingPending = false;
  }
  async typing() {
    if (this.closed || this.typingPending) return;
    this.typingPending = true;
    try { await this.bot.sendTyping(this.job.chatId, 'typing', this.job.messageThreadId); } catch {}
    finally { this.typingPending = false; }
  }
  async react(state) { try { await this.bot.react?.(this.job.chatId, this.job.messageId, TELEGRAM_ACK[state]); } catch {} }
  async start() {
    await Promise.all([this.react('received'), this.typing()]);
    if (!this.closed) { this.timer = setInterval(() => { void this.typing(); }, this.heartbeatMs); this.timer.unref?.(); }
  }
  beat(event) {
    if (this.closed || !['tool-call', 'tool-result'].includes(event?.type) || this.now() - this.lastBeat < this.beatIntervalMs) return;
    this.lastBeat = this.now();
    const name = String(event.name || 'tool').replace(/[^\w .-]/g, '').slice(0, STEP_LABEL_LIMIT);
    const text = event.type === 'tool-call' ? `Using ${name}…` : `${name} ${event.isError ? 'needs attention' : 'finished'}.`;
    this.tail = this.tail.then(async () => { if (!this.closed) await this.bot.send(this.job.chatId, text, { replyTo: this.job.messageId, messageThreadId: this.job.messageThreadId }); }).catch(() => {});
  }
  async stop() { this.closed = true; clearInterval(this.timer); await this.tail; }
}

export async function readTelegramArtifact(cwd, requested) {
  const root = await fs.realpath(cwd), candidate = path.resolve(cwd, requested);
  const absolute = await fs.realpath(candidate), relative = path.relative(root, absolute);
  if (!relative || relative === '..' || relative.startsWith(`..${path.sep}`) || path.isAbsolute(relative) || !ARTIFACT_FOLDERS.has(relative.split(path.sep)[0])) throw new Error('Artifact is outside generated/downloaded images');
  const mime = IMAGE_MIMES[path.extname(absolute).toLowerCase()];
  if (!mime) throw new Error('Unsupported artifact format');
  const handle = await fs.open(absolute, 'r');
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || stat.size > MAX_ARTIFACT_BYTES) throw new Error('Artifact exceeds the upload limit');
    const bytes = await handle.readFile();
    if (bytes.length > MAX_ARTIFACT_BYTES) throw new Error('Artifact exceeds the upload limit');
    return { bytes, mime, filename: path.basename(absolute), photo: ['image/png', 'image/jpeg'].includes(mime) && bytes.length <= MAX_PHOTO_BYTES };
  } finally { await handle.close(); }
}

export async function sendTurnArtifacts(bot, job, cwd, messages, cancelled = () => false) {
  const artifacts = recentArtifacts(cwd, messages).slice(0, MAX_ARTIFACTS);
  for (const artifact of artifacts) {
    if (cancelled()) break;
    try {
      const file = await readTelegramArtifact(cwd, artifact.path);
      if (cancelled()) break;
      await bot.sendTyping(job.chatId, file.photo ? 'upload_photo' : 'upload_document', job.messageThreadId);
      const options = { ...file, caption: artifact.name, replyTo: job.messageId, messageThreadId: job.messageThreadId };
      try { await (file.photo ? bot.sendPhoto(job.chatId, file.bytes, options) : bot.sendDocument(job.chatId, file.bytes, options)); }
      catch (error) { if (!file.photo) throw error; await bot.sendDocument(job.chatId, file.bytes, options); }
    } catch { await bot.send(job.chatId, `Could not upload ${artifact.name}. The artifact remains in the workspace.`, { replyTo: job.messageId, messageThreadId: job.messageThreadId }).catch(() => {}); }
  }
}
