import path from 'node:path';
import { defaultRegistry, normalizeList } from './registry.mjs';
import { ChannelRuntime } from './runtime.mjs';
import { ChannelOutbox } from './outbox.mjs';
import { PairingCodes } from './policy.mjs';
import { transcribeChannelVoice, speakChannelReply } from './voice.mjs';
import { TELEGRAM_CHANNEL_ID } from '../manifests/telegram.mjs';
import { CHANNEL_DELIVERY_FILE } from './contract.mjs';
import { loadChannelAdapter } from './loader.mjs';

/** Shared host glue. The registry supplies setup and lazy transport metadata. */
export class ChannelHost {
  constructor({ store, engine = null, surface, getConfig = () => ({}), emit = () => {}, log = () => {}, adapterFactories = {}, settingsFor = null, onRuntime = null, settled = () => {} } = {}) {
    Object.assign(this, { store, engine, surface, getConfig, log, adapterFactories });
    this.registry = store.registry || defaultRegistry; this._emit = emit;
    this.outbox = new ChannelOutbox({ file: store.file ? path.join(path.dirname(store.file), CHANNEL_DELIVERY_FILE) : null });
    this.pairing = new PairingCodes(); this.runtimes = new Map(); this.loading = new Map(); this.saves = new Map(); this.generation = 0;
    this.settingsFor = settingsFor || (id => this.store.get(id)); this.onRuntime = onRuntime; this.settled = settled;

  }
  load() { this.store.load(); return this; }
  hasWork() { return [...this.runtimes.values()].some(runtime => runtime.activeJobs.size || runtime.inbox.chains.size); }
  doctor() {
    const settings = this.store.doctor(), delivery = this.outbox.doctor();
    return { ...settings, ok: settings.ok && delivery.ok, error: settings.error || delivery.error || null, delivery };
  }
  publicView() {
    return { channels: Object.fromEntries(this.registry.list().map(manifest => [manifest.id, this.registry.publicView(manifest.id, this.store.get(manifest.id), this.runtimes.get(manifest.id)?.status())])), doctor: this.doctor() };
  }
  emit(event = null) { this._emit(event?.type ? event : { type: 'channels-updated', channels: this.publicView() }); }
  async runtime(id) {
    if (this.runtimes.has(id)) return this.runtimes.get(id);
    if (this.loading.has(id)) return this.loading.get(id);
    const work = this.createRuntime(id).finally(() => this.loading.delete(id));
    this.loading.set(id, work); return work;
  }
  async createRuntime(id) {
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
    if (!this.doctor().ok) return this.publicView();
    const generation = this.generation;
    for (const manifest of this.registry.list()) if (this.settingsFor(manifest.id).enabled) {
      const runtime = await this.runtime(manifest.id); if (generation !== this.generation) break; await runtime.start();
    }
    return this.publicView();
  }
  async stopAll() {
    this.generation++; await Promise.allSettled([...this.loading.values()]);
    await Promise.all([...this.runtimes.values()].map(runtime => runtime.stop()));
  }
  async save(id, patch) {
    if (typeof id !== 'string') { patch = id; id = TELEGRAM_CHANNEL_ID; }
    const generation = this.generation;
    const work = (this.saves.get(id) || Promise.resolve()).catch(() => {}).then(async () => {
      this.store.update(id, patch);
      const runtime = await this.runtime(id);
      await runtime.stop(); if (generation === this.generation) await runtime.start();
      const view = this.publicView(); this.emit({ type: 'channels-updated', channels: view }); return view;
    }).finally(() => { if (this.saves.get(id) === work) this.saves.delete(id); });
    this.saves.set(id, work); return work;
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
