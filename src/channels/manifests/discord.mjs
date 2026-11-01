import { commonFields } from './common.mjs';

export const DISCORD_CHANNEL_ID = 'discord'; // Stable registry ID, used by sessions and delivery receipts.
export const discordManifest = Object.freeze({
  id: DISCORD_CHANNEL_ID, label: 'Discord', connect: 'gateway', runtime: '../discord.mjs', export: 'DiscordAdapter',
  docsUrl: 'https://discord.com/developers/applications', description: 'Talk to a teammate in a private DM or an allowed server channel.',
  capabilities: ['typing', 'react', 'edit', 'upload', 'threads', 'buttons'], required: ['token', 'applicationId'],
  fields: {
    ...commonFields,
    enabled: { ...commonFields.enabled, env: 'DISCORD_ENABLED' },
    token: { section: 'connection', kind: 'secret', label: 'Bot token', env: 'DISCORD_BOT_TOKEN', default: '' },
    applicationId: { section: 'connection', kind: 'string', label: 'Application ID', env: 'DISCORD_APPLICATION_ID', default: '' },
    allowedChatIds: { ...commonFields.allowedChatIds, env: 'DISCORD_ALLOWED_CHANNEL_IDS', label: 'Allowed channel IDs' },
    allowFrom: { ...commonFields.allowFrom, env: 'DISCORD_ALLOW_FROM' },
    ownerChatId: { ...commonFields.ownerChatId, env: 'DISCORD_OWNER_DM_ID' },
    ownerUserId: { ...commonFields.ownerUserId, env: 'DISCORD_OWNER_USER_ID' },
  },
});
