import path from 'node:path';
import { defaultRegistry, normalizeList } from './registry.mjs';
import { ChannelRuntime } from './runtime.mjs';
import { ChannelOutbox } from './outbox.mjs';
import { PairingCodes } from './policy.mjs';
import { transcribeChannelVoice, speakChannelReply } from './voice.mjs';
import { TELEGRAM_CHANNEL_ID } from '../manifests/telegram.mjs';
import { CHANNEL_DELIVERY_FILE } from './contract.mjs';
import { loadChannelAdapter } from './loader.mjs';

/** Desktop host glue. The registry supplies setup and lazy transport metadata. */
export class ChannelHost {
  constructor({ store, engine = null, surface, getConfig = () => ({}), emit = () => {}, log = () => {}, adapterFactories = {}, settingsFor = null, onRuntime = null, settled = () => {} } = {}) {
    Object.assign(this, { store, engine, surface, getConfig, log, adapterFactories });
    this.registry = store.registry || defaultRegistry; this._emit = emit;
    this.outbox = new ChannelOutbox({ file: store.file ? path.join(path.dirname(store.file), CHANNEL_DELIVERY_FILE) : null });
    this.pairing = new PairingCodes(); this.runtimes = new Map();
    this.settingsFor = settingsFor || (id => this.store.get(id)); this.onRuntime = onRuntime; this.settled = settled;

  }
  load() { this.store.load(); return this; }
  publicView() {
    return { channels: Object.fromEntries(this.registry.list().map(manifest => [manifest.id, this.registry.publicView(manifest.id, this.store.get(manifest.id), this.runtimes.get(manifest.id)?.status())])), doctor: this.store.doctor?.() };
  }
  emit(event = null) { this._emit(event?.type ? event : { type: 'channels-updated', channels: this.publicView() }); }
  async runtime(id) {
    if (this.runtimes.has(id)) return this.runtimes.get(id);
    const manifest = this.registry.get(id);
    const create = this.adapterFactories[id];
    const adapter = create ? await create(this.store.get(id)) : await loadChannelAdapter(manifest);
    const runtime = new ChannelRuntime({ adapter, surface: this.surface, getSettings: () => this.settingsFor(id), outbox: this.outbox,
      emit: event => this.emit(event), log: this.log, settled: this.settled, pairing: this.pairing, onPair: ref => this.allowPaired(ref),
      transcribe: (ref, options) => transcribeChannelVoice(adapter, ref, this.getConfig(), options),
      speak: (ref, text) => speakChannelReply(adapter, ref, text, this.getConfig(), this.log),
    });
    this.runtimes.set(id, runtime); this.onRuntime?.(id, runtime); return runtime;
  }
  async startEnabled() {
    if (this.store.doctor?.().ok === false) return this.publicView();
    for (const manifest of this.registry.list()) if (this.settingsFor(manifest.id).enabled) await (await this.runtime(manifest.id)).start();
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
  async verify(id, input = {}) {
    const manifest = this.registry.get(id), settings = { ...this.store.get(id), ...this.registry.validate(id, input) };
    for (const field of manifest.required || []) if (!settings[field]) throw new Error(`Enter ${manifest.fields[field].label || field} first`);
    const adapter = (await this.runtime(id)).adapter;
    if (!adapter.verify) throw new Error('This channel does not support connection testing');
    const result = await adapter.verify(settings);
    this.outbox.revive(id);
    return result;
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
