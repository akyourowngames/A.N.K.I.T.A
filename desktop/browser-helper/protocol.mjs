// Shared by the extension, renderer and loopback server; no credentials in drag data.
export const DRAG_MIME = 'application/x-ankita-mascot';
export const PROTOCOL_VERSION = 1; // Wire revision; incompatible drops are rejected.
export const LOOPBACK_HOST = '127.0.0.1'; // IPv4 loopback only; never expose page context on the LAN.
export const ROUTES = Object.freeze({ pair: '/pair', capture: '/capture' });
export const MAX_ATTACHMENTS = 8; // Attachments per teammate draft; matches the existing composer limit.
export const MAX_TEXT_BYTES = 200 * 1024; // UTF-8 bytes; matches existing plain-text uploads.
export const MAX_REQUEST_BYTES = MAX_TEXT_BYTES * 6 + 16 * 1024; // JSON escaping plus bounded metadata.
export const MAX_TITLE_CHARS = 240; // Display characters; bounds attachment labels.
export const MAX_URL_CHARS = 4096; // URL characters; enough for ordinary document locations.
export const TICKET_TTL_MS = 120 * 1000; // Milliseconds; allows a deliberate cross-window drag.
export const PAIR_TTL_MS = 5 * 60 * 1000; // Milliseconds; one-use pairing window.
export const MAX_PENDING_CAPTURES = 64; // Bounds tickets, inbox and concurrent helper clients.
export const REQUEST_TIMEOUT_MS = 10 * 1000; // Milliseconds; failed local delivery is recoverable.
export const RECEIPT_MS = 2400; // Milliseconds; transient desktop/page delivery receipts remain readable.
export const FILE_ACTIVITY_EVENT = 'ankita:companion-file-activity';
export const FILE_DROP_EVENT = 'ankita:companion-file-drop';
export const CAPTURE_EVENT = 'companion-capture-ready';
export const CAPTURE_UI_EVENTS = Object.freeze({ island: 'ankita:island-captured', main: 'ankita:open-captured-thread' });
export const CAPTURE_ACTIONS = Object.freeze({ setup: 'companionCaptureSetup', register: 'companionCaptureRegister', cancel: 'companionCaptureCancel', inbox: 'companionCaptureInbox', ack: 'companionCaptureAck', openHelper: 'companionCaptureOpenHelper' });
export const HELPER_MESSAGE = Object.freeze({ pair: 'ankita-pair', capture: 'ankita-capture' });
export function boundedText(value, maxBytes = MAX_TEXT_BYTES) {
  const bytes = new TextEncoder().encode(String(value ?? ''));
  return new TextDecoder().decode(bytes.subarray(0, maxBytes)).replace(/\uFFFD$/, '');
}
export function isPageUrl(value) {
  try { return ['http:', 'https:'].includes(new URL(value).protocol); } catch { return false; }
}
