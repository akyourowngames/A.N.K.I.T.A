export type PairingStatus = 'pending' | 'approved' | 'claimed' | 'rejected' | 'expired';
export type PairingState = 'starting' | 'ready' | 'offline' | 'unsupported' | 'error';
export type ParsedPairingUri = { address: string; origin: string; code: string; fingerprint: string; name: string };

export const PHONE_PAIRING_PROTOCOL_VERSION: number;
export const PHONE_PAIRING_ROOT: string;
export const PAIRING_LINK_SCHEME: string;
export const PAIRING_LINK_HOST: string;

export const INVITATION_TTL_MS: number;
export const INVITATION_CODE_ALPHABET: string;
export const INVITATION_CODE_LENGTH: number;
export const INVITATION_CODE_GROUP_SIZE: number;
export const MAX_INVITATION_ATTEMPTS: number;
export const PENDING_APPROVAL_TTL_MS: number;
export const MAX_PENDING_PAIRINGS: number;
export const DEVICE_TOKEN_BYTES: number;
export const PAIR_SECRET_BYTES: number;
export const MAX_PAIRED_DEVICES: number;
export const DEVICE_ONLINE_WINDOW_MS: number;
export const MAX_DEVICE_NAME_CHARS: number;
export const MAX_PLATFORM_CHARS: number;

export const RUN_TIMEOUT_MS: number;
export const RUN_RETENTION_MS: number;
export const MAX_RUNS: number;
export const MAX_RUN_EVENTS: number;
export const MAX_PROMPT_CHARS: number;
export const MAX_REPLY_CHARS: number;
export const MAX_EVENT_DETAIL_CHARS: number;
export const MAX_REQUEST_BYTES: number;

export const PAIRING_CONFIG_FILE: string;
export const PAIRING_DEVICES_FILE: string;
export const PAIRING_CERTIFICATE_FILE: string;
export const PAIRING_SERVICE_NAME: string;

export const PAIRING_STATUS: Readonly<{ PENDING: 'pending'; APPROVED: 'approved'; CLAIMED: 'claimed'; REJECTED: 'rejected'; EXPIRED: 'expired' }>;
export const PAIRING_STATE: Readonly<{ STARTING: 'starting'; READY: 'ready'; OFFLINE: 'offline'; UNSUPPORTED: 'unsupported'; ERROR: 'error' }>;
export const FINGERPRINT_PATTERN: RegExp;

export const PHONE_PAIRING_ACTIONS: Readonly<{
  status: 'phonePairingStatus';
  restart: 'phonePairingRestart';
  invite: 'phonePairingInvite';
  cancelInvite: 'phonePairingCancelInvite';
  respond: 'phonePairingRespond';
  revoke: 'phonePairingRevoke';
  assign: 'phonePairingAssign';
  selectAddress: 'phonePairingSelectAddress';
  saveCertificate: 'phonePairingSaveCertificate';
}>;

export function normalizePairingCode(value: unknown): string;
export function formatPairingCode(code: unknown): string;
export function pairingUri(input: { address: string; code: string; fingerprint: string; name?: string }): string;
export function parsePairingUri(value: unknown): ParsedPairingUri | null;
