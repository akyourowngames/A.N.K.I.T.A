import { commonFields } from './common.mjs';

export const SLACK_CHANNEL_ID = 'slack'; // Stable registry ID used by queues, settings and receipts.
export const slackManifest = Object.freeze({
  id: SLACK_CHANNEL_ID, label: 'Slack', connect: 'socket-mode', runtime: '../slack.mjs', export: 'SlackAdapter',
  docsUrl: 'https://docs.slack.dev/apis/events-api/using-socket-mode/', description: 'Connect your workspace through a private outbound socket.',
  capabilities: ['react', 'edit', 'upload', 'threads', 'buttons'], required: ['botToken', 'appToken'],
  fields: {
    ...commonFields,
    enabled: { ...commonFields.enabled, env: 'SLACK_ENABLED' },
    botToken: { section: 'connection', kind: 'secret', label: 'Bot token', help: 'The xoxb token from OAuth & Permissions.', env: 'SLACK_BOT_TOKEN', default: '' },
    appToken: { section: 'connection', kind: 'secret', label: 'App token', help: 'The xapp token with connections:write.', env: 'SLACK_APP_TOKEN', default: '' },
    allowedChatIds: { ...commonFields.allowedChatIds, env: 'SLACK_ALLOWED_CHANNEL_IDS', label: 'Allowed conversation IDs' },
    allowFrom: { ...commonFields.allowFrom, env: 'SLACK_ALLOW_FROM', label: 'Allowed people or workspaces' },
    ownerChatId: { ...commonFields.ownerChatId, env: 'SLACK_OWNER_DM_ID' },
    ownerUserId: { ...commonFields.ownerUserId, env: 'SLACK_OWNER_USER_ID' },
  },
});
