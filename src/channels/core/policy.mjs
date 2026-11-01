import { randomBytes, createHash, timingSafeEqual } from 'node:crypto';
import { PAIRING_TTL_MS, PAIRING_CODE_BYTES, PAIRING_MAX_CODES, DEFAULT_MENTION_POLICY, CONFIRM_MIN_SECONDS, CONFIRM_MAX_SECONDS, CONFIRM_DEFAULT_SECONDS } from './contract.mjs';
import { TELEGRAM_CHANNEL_ID } from '../manifests/telegram.mjs';

const ANSI_PATTERN = /\x1b\[[0-9;]*m/g; // Terminal decoration is not part of an approval description.
const ALWAYS_PATTERN = /^(a|always|all|yes always|y always|yes all|always allow)$/;
const YES_PATTERN = /^(y|ye|yes|yeah|yep|ok|okay|sure|approve|approved|allow|allowed|go|do it|fine|k)$/;
const BARE_APPROVAL_PATTERN = /^(y|ye|yes|yeah|yep|ok|okay|sure|approve|approved|allow|allowed|go|do it|fine|k|a|always|all)$/;
const CANCEL_PATTERN = /^\/cancel(?:@\w+)?$/i; // Universal text fallback, including Telegram bot commands.
const cleanReply = text => String(text || '').trim().toLowerCase().replace(/[.!]+$/, '');
const ids = value => typeof value === 'string' ? value.split(/[,\s]+/).filter(Boolean) : [];
const digest = value => createHash('sha256').update(String(value)).digest();
export const stripAnsi = text => String(text ?? '').replace(ANSI_PATTERN, '');
export const parseApproval = text => ALWAYS_PATTERN.test(cleanReply(text)) ? 'always' : YES_PATTERN.test(cleanReply(text)) ? 'yes' : 'no';
export const isBareApproval = text => BARE_APPROVAL_PATTERN.test(cleanReply(text));
export const isCancelMessage = message => (message.kind == null || message.kind === 'text') && CANCEL_PATTERN.test(String(message.text || '').trim());
export const confirmationSeconds = value => Math.min(CONFIRM_MAX_SECONDS, Math.max(CONFIRM_MIN_SECONDS, Number(value) || CONFIRM_DEFAULT_SECONDS));

export function allows(message, settings) {
  if (!settings || message.raw?.bot || message.raw?.webhook || message.raw?.system) return false;
  const chatAllowed = ids(settings.allowedChatIds).includes(String(message.chatId));
  const senders = ids(settings.allowFrom);
  const senderAllowed = senders.includes(String(message.senderId)) || senders.includes(`user:${message.senderId}`);
  const serverAllowed = message.raw?.serverId != null && senders.includes(`server:${message.raw.serverId}`);
  if (!chatAllowed && !senderAllowed && !serverAllowed) return false;
  if (message.raw?.isGroup && (settings.mentionPolicy || DEFAULT_MENTION_POLICY) === DEFAULT_MENTION_POLICY && !message.raw?.mentioned) return false;
  return true;
}

export function ownerIdentity(channel, settings) {
  let chatId = String(settings.ownerChatId || '');
  if (channel === TELEGRAM_CHANNEL_ID) {
    if (!chatId) chatId = ids(settings.allowedChatIds).find(id => /^[1-9]\d*$/.test(id)) || '';
    if (!/^[1-9]\d*$/.test(chatId)) return null;
    return { chatId, senderId: String(settings.ownerUserId || chatId) };
  }
  if (!chatId || !settings.ownerUserId) return null;
  return { chatId, senderId: String(settings.ownerUserId) };
}

export function isOwner(message, settings) {
  const owner = ownerIdentity(message.channel, settings);
  return Boolean(owner && !message.raw?.isGroup && !message.raw?.bot && !message.raw?.webhook && String(message.chatId) === owner.chatId && String(message.senderId) === owner.senderId);
}

export class PairingCodes {
  constructor({ now = Date.now, ttlMs = PAIRING_TTL_MS } = {}) { this.now = now; this.ttlMs = ttlMs; this.pending = new Map(); }
  prune() { for (const [key, value] of this.pending) if (value.expiresAt <= this.now()) this.pending.delete(key); }
  issue({ channel, senderId }) {
    this.prune();
    if (!channel || !senderId) throw new Error('Choose a channel and sender before creating a pairing code');
    if (this.pending.size >= PAIRING_MAX_CODES) throw new Error('Too many pending pairing codes');
    const code = randomBytes(PAIRING_CODE_BYTES).toString('base64url');
    const expiresAt = this.now() + this.ttlMs;
    this.pending.set(JSON.stringify([channel, String(senderId)]), { hash: digest(code), expiresAt });
    return { code, expiresAt };
  }
  consume({ channel, senderId, code }) {
    this.prune();
    const key = JSON.stringify([channel, String(senderId)]), pending = this.pending.get(key);
    if (!pending) return false;
    this.pending.delete(key); // One attempt; a wrong guess burns this sender's grant.
    return pending.expiresAt > this.now() && timingSafeEqual(pending.hash, digest(code));
  }
}
