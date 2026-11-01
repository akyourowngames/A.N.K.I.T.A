import { ChannelProgress } from './core/progress.mjs';
import { readChannelArtifact, sendChannelArtifacts } from './core/artifacts.mjs';
import { TelegramAdapter, telegramEnvelope } from './telegram-adapter.mjs';
export { isCancelMessage } from './core/policy.mjs';
export { ACK_STATES as TELEGRAM_ACK } from './core/contract.mjs';

/** Compatibility exports for existing CLI, verification scripts and integrations. */
export class TelegramProgress extends ChannelProgress {
  constructor(bot, job, options) { super(new TelegramAdapter({ bot }), telegramEnvelope(job), options); }
}
export const readTelegramArtifact = readChannelArtifact;
export function sendTurnArtifacts(bot, job, cwd, messages, cancelled) {
  return sendChannelArtifacts(new TelegramAdapter({ bot }), telegramEnvelope(job), cwd, messages, cancelled);
}
