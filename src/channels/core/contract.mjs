/** Shared channel limits. Sizes are bytes/characters; timings are milliseconds. */
export const CHANNEL_CAPABILITIES = Object.freeze(['typing', 'react', 'edit', 'upload', 'threads', 'buttons', 'voice']);
export const FIELD_KINDS = Object.freeze(['string', 'secret', 'bool', 'list', 'enum', 'int', 'float']);
export const CHANNEL_ID_PATTERN = /^[a-z][a-z0-9-]*$/; // Stable registry keys, never paths or colon-separated session keys.
export const SECRET_CHAR_LIMIT = 512; // Characters: bounded credentials and accidentally pasted responses.
export const LIST_CHAR_LIMIT = 1024; // Characters: bounded allowlists/settings IPC payloads.
export const ID_CHAR_LIMIT = 128; // Characters: platform identity and teammate identifiers.
export const TEXT_CHAR_LIMIT = 4096; // Characters: bounded general settings strings.
export const CONFIRM_MIN_SECONDS = 30; // Seconds: a typo must not make approval impossible.
export const CONFIRM_MAX_SECONDS = 3600; // Seconds: approvals cannot remain live indefinitely.
export const CONFIRM_DEFAULT_SECONDS = 300; // Seconds: preserve Telegram's five-minute default.
export const CHANNEL_TOOL_CALLS = 24; // Tool calls per channel turn; remote senders have a bounded execution budget.
export const TYPING_INTERVAL_MS = 4000; // Milliseconds: Telegram actions expire after five seconds.
export const PROGRESS_INTERVAL_MS = 5000; // Milliseconds: bound interim message noise across transports.
export const PROGRESS_LABEL_CHARS = 80; // Characters: progress contains tool names, never arguments/model text.
export const MAX_ARTIFACTS = 5; // Files per turn; the rest remain in the workspace.
export const MAX_ARTIFACT_BYTES = 15 * 1024 * 1024; // Bytes: bounded workspace reads for outbound files.
export const TELEGRAM_PHOTO_BYTES = 10 * 1024 * 1024; // Bytes: Bot API photo limit; larger images become documents.
export const CHANNEL_RETRY_LIMIT = 3; // Attempts: safe, explicitly rejected deliveries only.
export const RETRY_BASE_MS = 1000; // Milliseconds: bounded exponential backoff for known transient rejections.
export const RETRY_MAX_MS = 30_000; // Milliseconds: cap platform retry-after and reconnect backoff.
export const REQUEST_TIMEOUT_MS = 30_000; // Milliseconds: bounded platform HTTP calls.
export const UPLOAD_TIMEOUT_MS = 60_000; // Milliseconds: bounded multipart file transfers.
export const SOCKET_OPEN_TIMEOUT_MS = 15_000; // Milliseconds: fail visibly rather than hanging setup.
export const POLL_ERROR_DELAY_MS = 5000; // Milliseconds: preserve Telegram poll error backoff.
export const POLL_EMPTY_DELAY_MS = 2000; // Milliseconds: preserve Telegram empty-round pacing.
export const CHANNEL_STORE_VERSION = 2; // On-disk descriptor-driven settings format.
export const DELIVERY_LEDGER_VERSION = 1; // On-disk per-part accepted/uncertain receipts.
export const PAIRING_TTL_MS = 120_000; // Milliseconds: a short-lived, owner-issued pairing grant.
export const PAIRING_CODE_BYTES = 6; // Random bytes: eight base64url characters, with no predictable counters.
export const PAIRING_MAX_CODES = 32; // Outstanding grants: bounded memory and brute-force exposure.
export const DEFAULT_MENTION_POLICY = 'mention'; // Group messages require an explicit mention unless configured otherwise.
export const MENTION_POLICIES = Object.freeze(['mention', 'open', 'allowlist']);
export const ACK_STATES = Object.freeze({ received: '👀', complete: '👍', failed: '👎' });
export const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

export function assertSerializable(value) {
  try {
    const encoded = JSON.stringify(value, (_key, entry) => {
      if (typeof entry === 'function' || typeof entry === 'symbol' || typeof entry === 'bigint' || (entry && typeof entry === 'object' && !Array.isArray(entry) && ![Object.prototype, null].includes(Object.getPrototypeOf(entry)))) throw new Error('non-JSON value');
      return entry;
    });
    if (encoded === undefined) throw new Error('missing value');
  } catch { throw new Error('Channel envelopes and manifests must be JSON serialisable'); }
  return value;
}

export function sessionKey({ channel, chatId }) {
  if (!CHANNEL_ID_PATTERN.test(channel) || chatId == null || !String(chatId) || String(chatId).length > TEXT_CHAR_LIMIT) throw new Error('Invalid channel session');
  return `${channel}:${String(chatId)}`;
}

export function normalizeInbound(input) {
  assertSerializable(input);
  sessionKey(input);
  if (input.messageId == null) throw new Error('Channel message ID is required');
  return {
    channel: input.channel, chatId: String(input.chatId), messageId: String(input.messageId),
    senderId: String(input.senderId ?? input.chatId), senderName: String(input.senderName || ''),
    text: String(input.text || ''), media: input.media || [], replyTo: input.replyTo ?? null,
    threadId: input.threadId ?? null, raw: input.raw || {},
  };
}

export function assertAdapter(adapter) {
  if (!adapter?.manifest) throw new Error('A channel adapter needs a manifest');
  for (const method of ['start', 'stop', 'send']) if (typeof adapter[method] !== 'function') throw new Error(`Channel adapter requires ${method}`);
  for (const capability of adapter.manifest.capabilities || []) {
    if (['typing', 'react', 'edit', 'upload', 'buttons'].includes(capability) && typeof adapter[capability] !== 'function') throw new Error(`Channel adapter advertises missing ${capability}`);
  }
  return adapter;
}

export function abortableDelay(ms, signal) {
  signal?.throwIfAborted();
  return new Promise((resolve, reject) => {
    const done = () => { signal?.removeEventListener('abort', abort); resolve(); };
    const timer = setTimeout(done, ms);
    const abort = () => { clearTimeout(timer); signal?.removeEventListener('abort', abort); reject(signal.reason || new DOMException('Channel stopped', 'AbortError')); };
    signal?.addEventListener('abort', abort, { once: true });
  });
}
