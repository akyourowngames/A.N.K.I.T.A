import { ChannelStore } from '../../src/channels/core/store.mjs';
import { defaultRegistry, normalizeList } from '../../src/channels/core/registry.mjs';
import { ChannelHost } from '../../src/channels/core/host.mjs';
import { ChannelRuntime } from '../../src/channels/core/runtime.mjs';
import { DesktopChannelSurface } from './channel-surface.mjs';
import { transcribeChannelVoice, speakChannelReply } from '../../src/channels/core/voice.mjs';
import { TelegramAdapter, telegramEnvelope } from '../../src/channels/telegram-adapter.mjs';
import { TELEGRAM_CHANNEL_ID } from '../../src/channels/manifests/telegram.mjs';

export { ChannelStore };
export const TELEGRAM_DEFAULTS = Object.freeze(defaultRegistry.defaults(TELEGRAM_CHANNEL_ID));
export const normalizeChatIds = value => normalizeList(value, { numericIds: true });
export const validateTelegramPatch = patch => defaultRegistry.validate(TELEGRAM_CHANNEL_ID, patch);
export const publicTelegram = (config = {}, status = {}) => {
  const { manifest, secrets, ...view } = defaultRegistry.publicView(TELEGRAM_CHANNEL_ID, config, status);
  return view;
};

/** Import-compatible Telegram facade; queues, policy, approvals and delivery live in the core. */
export class TelegramChannel extends ChannelRuntime {
  constructor({ store, engine = null, surface = new DesktopChannelSurface({ engine }), getConfig = () => ({}), emit = () => {}, log = () => {}, botFactory, outbox, pairing, onPair } = {}) {
    const adapter = new TelegramAdapter({ ...(botFactory ? { botFactory } : {}) });
    super({ adapter, surface, getSettings: () => ({ ...TELEGRAM_DEFAULTS, ...store.telegram() }), emit, log, outbox, pairing, onPair, legacy: true,
      transcribe: (ref, options) => transcribeChannelVoice(adapter, ref, getConfig(), options),
      speak: (ref, text) => speakChannelReply(adapter, ref, text, getConfig(), log),
    });
    this.store = store; this.engine = engine;
  }
  get bot() { return this.adapter.bot; }
  set bot(value) { this.adapter.bot = value; }
  get offset() { return this.adapter.offset; }
  set offset(value) { this.adapter.offset = value; }
  get offsetReady() { return this.adapter.offsetReady; }
  set offsetReady(value) { this.adapter.offsetReady = value; }
  tick(bot = this.bot) {
    return this.adapter.tick({ signal: this.abort?.signal, receive: ref => this.receive(ref), status: status => { Object.assign(this, status); } }, bot);
  }
  handleJob(job, options) { return super.handleJob(job.channel ? job : telegramEnvelope(job), options); }
  dispatch(job) { return super.dispatch(job.channel ? job : telegramEnvelope(job)); }
}

/** Desktop keeps its public names; both terminal and desktop use the shared host. */
export class ChannelManager extends ChannelHost {
  constructor({ store, engine = null, surface = new DesktopChannelSurface({ engine }), getConfig = () => ({}), emit = () => {}, log = () => {}, botFactory, ...options } = {}) {
    super({ store, engine, surface, getConfig, emit, log, ...options });
    this.telegram = new TelegramChannel({ store, engine, surface, getConfig, emit: event => this.emit(event), log,
      outbox: this.outbox, pairing: this.pairing, onPair: ref => this.allowPaired(ref), ...(botFactory ? { botFactory } : {}) });
    this.runtimes.set(TELEGRAM_CHANNEL_ID, this.telegram);
  }
}
