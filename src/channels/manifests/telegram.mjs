import { commonFields } from './common.mjs';

export const TELEGRAM_CHANNEL_ID = 'telegram'; // Registry ID, preserving the existing config and imported transport.
export const telegramManifest = Object.freeze({
  id: TELEGRAM_CHANNEL_ID, label: 'Telegram', connect: 'long-poll',
  runtime: '../telegram-adapter.mjs', export: 'TelegramAdapter',
  docsUrl: 'https://core.telegram.org/bots#how-do-i-create-a-bot',
  description: 'Message a teammate from your private Telegram bot.',
  capabilities: ['typing', 'react', 'upload', 'threads', 'voice'], required: ['token'],
  fields: {
    ...commonFields,
    enabled: { ...commonFields.enabled, env: 'TELEGRAM_ENABLED' },
    token: { kind: 'secret', label: 'Bot token', env: 'TELEGRAM_BOT_TOKEN', configKey: 'telegramBotToken', default: '' },
    allowedChatIds: { ...commonFields.allowedChatIds, label: 'Allowed chat ids', env: 'TELEGRAM_ALLOWED_CHAT_IDS', fallbackEnv: 'TELEGRAM_CHAT_ID', configKey: 'telegramAllowedChatIds', numericIds: true },
    ownerChatId: { ...commonFields.ownerChatId, env: 'TELEGRAM_CHAT_ID', configKey: 'telegramChatId' },
    voiceReply: { ...commonFields.voiceReply, env: 'TELEGRAM_VOICE_REPLY', configKey: 'telegramVoiceReply' },
    confirmTimeout: { ...commonFields.confirmTimeout, env: 'TELEGRAM_CONFIRM_TIMEOUT', configKey: 'telegramConfirmTimeout' },
  },
});
