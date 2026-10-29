import { CONFIRM_DEFAULT_SECONDS, CONFIRM_MIN_SECONDS, CONFIRM_MAX_SECONDS, CHANNEL_TOOL_CALLS, DEFAULT_MENTION_POLICY, MENTION_POLICIES, ID_CHAR_LIMIT } from '../core/contract.mjs';

/** Shared descriptor fields, not per-platform policy implementations. */
export const commonFields = Object.freeze({
  enabled: { kind: 'bool', label: 'Connect channel', default: false },
  allowedChatIds: { kind: 'list', label: 'Allowed conversations', default: '', help: 'Only these chat or channel IDs may send requests.' },
  allowFrom: { kind: 'list', label: 'Allowed people or servers', default: '', help: 'User IDs, user:ID, or server:ID. An empty access list permits nobody.' },
  ownerChatId: { kind: 'string', label: 'Owner private conversation', default: '', maxLength: ID_CHAR_LIMIT, help: 'Approvals go to this private conversation only.' },
  ownerUserId: { kind: 'string', label: 'Owner user ID', default: '', maxLength: ID_CHAR_LIMIT, help: 'Required for approvals outside Telegram private chats.' },
  teammateId: { kind: 'string', label: 'Connected teammate', default: null, source: 'teammates', maxLength: ID_CHAR_LIMIT },
  mentionPolicy: { kind: 'enum', label: 'Group replies', values: MENTION_POLICIES, default: DEFAULT_MENTION_POLICY },
  progressBeats: { kind: 'bool', label: 'Show work updates', default: true },
  voiceReply: { kind: 'bool', label: 'Send spoken replies', default: false },
  pairingEnabled: { kind: 'bool', label: 'Allow owner-issued pairing codes', default: false },
  confirmTimeout: { kind: 'int', label: 'Approval timeout (seconds)', min: CONFIRM_MIN_SECONDS, max: CONFIRM_MAX_SECONDS, default: CONFIRM_DEFAULT_SECONDS },
  toolBudget: { kind: 'int', label: 'Tool calls per request', min: 1, max: CHANNEL_TOOL_CALLS, default: CHANNEL_TOOL_CALLS },
});
