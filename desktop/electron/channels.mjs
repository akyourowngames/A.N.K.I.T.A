import path from 'node:path';
import { ChannelStore } from '../../src/channels/core/store.mjs';
import { defaultRegistry, normalizeList } from '../../src/channels/core/registry.mjs';
import { ChannelRuntime } from '../../src/channels/core/runtime.mjs';
import { DesktopChannelSurface } from './channel-surface.mjs';
import { ChannelOutbox } from '../../src/channels/core/outbox.mjs';
import { PairingCodes } from '../../src/channels/core/policy.mjs';
import { transcribeChannelVoice, speakChannelReply } from '../../src/channels/core/voice.mjs';
import { TelegramAdapter, telegramEnvelope } from '../../src/channels/telegram-adapter.mjs';
import { TELEGRAM_CHANNEL_ID } from '../../src/channels/manifests/telegram.mjs';
import { CHANNEL_DELIVERY_FILE } from '../../src/channels/core/contract.mjs';

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

/** Desktop host glue. The registry supplies setup and lazy transport metadata. */
export class ChannelManager {
  constructor({ store, engine = null, surface = new DesktopChannelSurface({ engine }), getConfig = () => ({}), emit = () => {}, log = () => {}, botFactory, adapterFactories = {} } = {}) {
    Object.assign(this, { store, engine, surface, getConfig, log, adapterFactories });
    this.registry = store.registry || defaultRegistry; this._emit = emit;
    this.outbox = new ChannelOutbox({ file: store.file ? path.join(path.dirname(store.file), CHANNEL_DELIVERY_FILE) : null });
    this.pairing = new PairingCodes(); this.runtimes = new Map();
    const common = { store, engine, surface, getConfig, emit: event => this.emit(event), log, outbox: this.outbox, pairing: this.pairing, onPair: ref => this.allowPaired(ref) };
    this.telegram = new TelegramChannel({ ...common, botFactory });
    this.runtimes.set(TELEGRAM_CHANNEL_ID, this.telegram);
  }
  load() { this.store.load(); return this; }
  publicView() { return { telegram: publicTelegram(this.store.telegram(), this.telegram.status()) }; }
  emit(event = null) { this._emit(event?.type ? event : { type: 'channels-updated', channels: this.publicView() }); }
  async runtime(id) {
    if (this.runtimes.has(id)) return this.runtimes.get(id);
    const manifest = this.registry.get(id);
    const create = this.adapterFactories[id];
    const adapter = create ? await create(this.store.get(id)) : new (await import(new URL(manifest.runtime, import.meta.url)))[manifest.export]();
    const runtime = new ChannelRuntime({ adapter, surface: this.surface, getSettings: () => this.store.get(id), outbox: this.outbox,
      emit: event => this.emit(event), log: this.log, pairing: this.pairing, onPair: ref => this.allowPaired(ref),
      transcribe: (ref, options) => transcribeChannelVoice(adapter, ref, this.getConfig(), options),
      speak: (ref, text) => speakChannelReply(adapter, ref, text, this.getConfig(), this.log),
    });
    this.runtimes.set(id, runtime); return runtime;
  }
  async startEnabled() {
    if (this.store.doctor?.().ok === false) return this.publicView();
    for (const manifest of this.registry.list()) if (this.store.get(manifest.id).enabled) await (await this.runtime(manifest.id)).start();
    return this.publicView();
  }
  async stopAll() { await Promise.all([...this.runtimes.values()].map(runtime => runtime.stop())); }
  async save(id, patch) {
    if (typeof id !== 'string') { patch = id; id = TELEGRAM_CHANNEL_ID; }
    this.store.update(id, patch);
    const runtime = await this.runtime(id);
    await runtime.stop(); await runtime.start();
    const view = this.publicView(); this.emit({ type: 'channels-updated', channels: view }); return view;
  }
  allowPaired(ref) {
    const settings = this.store.get(ref.channel), ids = new Set(normalizeList(settings.allowFrom).split(', ').filter(Boolean));
    ids.add(`user:${ref.senderId}`); this.store.update(ref.channel, { allowFrom: [...ids].join(', ') }); this.emit();
  }
  createPairing(id, senderId) {
    if (!this.store.get(id).pairingEnabled) throw new Error('Enable owner-issued pairing codes for this channel first');
    return this.pairing.issue({ channel: id, senderId });
  }
  handleEngineEvent(event) { for (const runtime of this.runtimes.values()) runtime.handleEngineEvent(event); }
}
