import { CONFIRM_DEFAULT_SECONDS, CONFIRM_MIN_SECONDS, CONFIRM_MAX_SECONDS, CHANNEL_TOOL_CALLS, DEFAULT_MENTION_POLICY, MENTION_POLICIES, ID_CHAR_LIMIT } from '../core/contract.mjs';

/** Shared descriptor fields, not per-platform policy implementations. */
export const commonFields = Object.freeze({
  enabled: { section: 'connection', kind: 'bool', label: 'Connect channel', default: false },
  allowedChatIds: { section: 'access', kind: 'list', label: 'Allowed conversations', default: '', help: 'Only these chat or channel IDs may send requests.' },
  allowFrom: { section: 'access', kind: 'list', label: 'Allowed people or servers', default: '', help: 'User IDs, user:ID, or server:ID. An empty access list permits nobody.' },
  ownerChatId: { section: 'access', kind: 'string', label: 'Owner private conversation', default: '', maxLength: ID_CHAR_LIMIT, help: 'Approvals go to this private conversation only.' },
  ownerUserId: { section: 'access', kind: 'string', label: 'Owner user ID', default: '', maxLength: ID_CHAR_LIMIT, help: 'Required for approvals outside Telegram private chats.' },
  teammateId: { section: 'connection', kind: 'string', label: 'Connected teammate', default: null, source: 'teammates', maxLength: ID_CHAR_LIMIT },
  mentionPolicy: { section: 'behaviour', kind: 'enum', label: 'Group replies', values: MENTION_POLICIES, default: DEFAULT_MENTION_POLICY },
  progressBeats: { section: 'behaviour', kind: 'bool', label: 'Show work updates', default: true },
  voiceReply: { section: 'behaviour', requiresCapability: 'voice', kind: 'bool', label: 'Send spoken replies', default: false },
  pairingEnabled: { section: 'advanced', kind: 'bool', label: 'Allow owner-issued pairing codes', default: false },
  confirmTimeout: { section: 'advanced', kind: 'int', label: 'Approval timeout (seconds)', min: CONFIRM_MIN_SECONDS, max: CONFIRM_MAX_SECONDS, default: CONFIRM_DEFAULT_SECONDS },
  toolBudget: { section: 'advanced', kind: 'int', label: 'Tool calls per request', min: 1, max: CHANNEL_TOOL_CALLS, default: CHANNEL_TOOL_CALLS },
});
