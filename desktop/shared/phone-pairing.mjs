/**
 * Phone pairing protocol shared by the desktop service, its tests and the
 * renderer. Invitation codes are short-lived and single-use; the long-lived
 * device token is only ever returned over the authenticated HTTPS response
 * after the desktop owner approves the request.
 */

export const PHONE_PAIRING_PROTOCOL_VERSION = 1;
export const PHONE_PAIRING_ROOT = '/v1/ankita-companion'; // Same root as the mobile companion client.
export const PAIRING_LINK_SCHEME = 'chief';
export const PAIRING_LINK_HOST = 'pair';

export const INVITATION_TTL_MS = 120000; // Two minutes: long enough to scan, short enough to limit guessing.
export const INVITATION_CODE_ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'; // No 0/1/I/L/O: unambiguous when typed by hand.
export const INVITATION_CODE_LENGTH = 8; // ~39 bits from the alphabet above.
export const INVITATION_CODE_GROUP_SIZE = 4; // Display grouping only; stored code has no separators.
export const MAX_INVITATION_ATTEMPTS = 5; // Wrong guesses before the invitation is burned.
export const PENDING_APPROVAL_TTL_MS = 120000; // How long a scanned invitation waits on the desktop owner.
export const MAX_PENDING_PAIRINGS = 3; // Concurrent phones awaiting approval.
export const DEVICE_TOKEN_BYTES = 32; // 256-bit per-phone credential.
export const PAIR_SECRET_BYTES = 32; // Capability for polling one pairing request.
export const MAX_PAIRED_DEVICES = 10;
export const DEVICE_ONLINE_WINDOW_MS = 60000; // A request within a minute counts as connected.
export const MAX_DEVICE_NAME_CHARS = 64;
export const MAX_PLATFORM_CHARS = 32;

export const RUN_TIMEOUT_MS = 300000; // Overall phone run budget, matching the companion contract.
export const RUN_RETENTION_MS = 600000; // Finished runs stay readable for late polls.
export const MAX_RUNS = 20;
export const MAX_RUN_EVENTS = 128;
export const MAX_PROMPT_CHARS = 8000;
export const MAX_REPLY_CHARS = 24000;
export const MAX_EVENT_DETAIL_CHARS = 2400;
export const MAX_REQUEST_BYTES = 16384;

// Additive browser continuity contract; native v1 {version,prompt} stays valid.
export const PHONE_CLIENT_ROOT = `${PHONE_PAIRING_ROOT}/phone`;
export const PHONE_ROUTES = Object.freeze({ pair: `${PHONE_PAIRING_ROOT}/pair`, revoke: `${PHONE_PAIRING_ROOT}/pair/revoke`, capabilities: `${PHONE_PAIRING_ROOT}/capabilities`, runs: `${PHONE_PAIRING_ROOT}/runs`, history: `${PHONE_PAIRING_ROOT}/history`, tasks: `${PHONE_PAIRING_ROOT}/tasks`, context: `${PHONE_PAIRING_ROOT}/context` });
export const PHONE_HISTORY_LIMIT = 40; // Visible user/assistant messages, never raw tools or hidden history.
export const PHONE_HISTORY_CHARS = 24000; // Total excerpt characters returned per history request.
export const PHONE_TASK_LIMIT = 30; // Most recent tasks in the assigned conversation.
export const PHONE_TASK_DETAIL_BYTES = 12000; // Combined JSON-encoded text bytes per phone task preview.
export const PHONE_TASK_DETAIL_ITEMS = 20; // Per checklist/reference/receipt list; full records remain on desktop.
export const PHONE_CONTEXT_TITLE_CHARS = 120; // Reviewed source label, not a file path.
export const PHONE_CONTEXT_TEXT_CHARS = 4000; // Fits the task store's bounded UTF-8 attachment metadata.
export const PHONE_CONTEXT_BYTES = 6000; // Reject oversized Unicode excerpts before attachment encoding.
export const PHONE_CONTEXT_TTL_MS = 120000; // A reviewed excerpt expires after two minutes without a send.
export const PHONE_CONTEXT_LIMIT = 20; // Maximum unconsumed previews across all devices.
export const PHONE_POLL_MS = 1000; // Browser run and pairing refresh interval in milliseconds.
export const PHONE_REQUEST_TIMEOUT_MS = 15000; // Browser HTTP request budget, independent of assistant run duration.
export const PHONE_SESSION_KEY = 'ankita-phone-session'; // Per-tab sessionStorage only; never localStorage/cookies.

export function phoneBrowserUrl({ address, code, fingerprint }) {
  const url = new URL(address);
  url.pathname = PHONE_CLIENT_ROOT;
  url.search = '';
  url.hash = new URLSearchParams({ code: normalizePairingCode(code), fingerprint }).toString();
  return url.toString();
}

export const PAIRING_CONFIG_FILE = 'phone-pairing.json'; // Port and encrypted TLS material in the config directory.
export const PAIRING_DEVICES_FILE = 'phone-devices.json'; // Device metadata and token hashes only.
export const PAIRING_CERTIFICATE_FILE = 'ankita-desktop-ca.crt'; // Public certificate the phone owner installs.
export const PAIRING_SERVICE_NAME = 'Ankita desktop';

export const PAIRING_STATUS = Object.freeze({
  PENDING: 'pending',
  APPROVED: 'approved',
  CLAIMED: 'claimed',
  REJECTED: 'rejected',
  EXPIRED: 'expired',
});

export const PAIRING_STATE = Object.freeze({
  STARTING: 'starting',
  READY: 'ready',
  OFFLINE: 'offline',
  UNSUPPORTED: 'unsupported',
  ERROR: 'error',
});

export const FINGERPRINT_PATTERN = /^(?:[0-9A-F]{2}:){31}[0-9A-F]{2}$/; // SHA-256 rendered as colon-separated bytes.

// Renderer/main IPC names. Kept here so both sides cannot drift.
export const PHONE_PAIRING_ACTIONS = Object.freeze({
  status: 'phonePairingStatus',
  restart: 'phonePairingRestart',
  invite: 'phonePairingInvite',
  cancelInvite: 'phonePairingCancelInvite',
  respond: 'phonePairingRespond',
  revoke: 'phonePairingRevoke',
  assign: 'phonePairingAssign',
  selectAddress: 'phonePairingSelectAddress',
  saveCertificate: 'phonePairingSaveCertificate',
});

export function normalizePairingCode(value) {
  const raw = String(value || '').toUpperCase().replace(/[^A-Z2-9]/g, '');
  if (raw.length !== INVITATION_CODE_LENGTH) return '';
  for (const character of raw) if (!INVITATION_CODE_ALPHABET.includes(character)) return '';
  return raw;
}

export function formatPairingCode(code) {
  const raw = normalizePairingCode(code);
  if (!raw) return '';
  const groups = [];
  for (let index = 0; index < raw.length; index += INVITATION_CODE_GROUP_SIZE) groups.push(raw.slice(index, index + INVITATION_CODE_GROUP_SIZE));
  return groups.join('-');
}

export function pairingUri({ address, code, fingerprint, name }) {
  const url = new URL('pair', `${PAIRING_LINK_SCHEME}://${PAIRING_LINK_HOST}`);
  url.searchParams.set('u', String(address || ''));
  url.searchParams.set('c', normalizePairingCode(code));
  url.searchParams.set('f', String(fingerprint || '').toUpperCase());
  if (name) url.searchParams.set('n', String(name));
  return url.toString();
}

export function parsePairingUri(value) {
  let url;
  try { url = new URL(String(value || '').trim()); } catch { return null; }
  if (url.protocol !== `${PAIRING_LINK_SCHEME}:` || url.hostname !== PAIRING_LINK_HOST) return null;
  const address = url.searchParams.get('u') || '';
  const code = normalizePairingCode(url.searchParams.get('c') || '');
  const fingerprint = (url.searchParams.get('f') || '').toUpperCase();
  let target;
  try { target = new URL(address); } catch { return null; }
  if (target.protocol !== 'https:' || target.username || target.password || target.search || target.hash) return null;
  if (['localhost', '127.0.0.1', '[::1]', '::1'].includes(target.hostname.toLowerCase())) return null; // A phone cannot reach the desktop's loopback.
  if (target.pathname.replace(/\/+$/, '') !== PHONE_PAIRING_ROOT) return null;
  if (!code || !FINGERPRINT_PATTERN.test(fingerprint)) return null;
  return {
    address: `${target.origin}${PHONE_PAIRING_ROOT}`,
    origin: target.origin,
    code,
    fingerprint,
    name: (url.searchParams.get('n') || '').slice(0, MAX_DEVICE_NAME_CHARS),
  };
}
