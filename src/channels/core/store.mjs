import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { defaultRegistry } from './registry.mjs';
import { CHANNEL_STORE_VERSION } from './contract.mjs';
import { TELEGRAM_CHANNEL_ID } from '../manifests/telegram.mjs';

const PRIVATE_FILE_MODE = 0o600; // POSIX permission bits: channel settings contain credentials.
const LEGACY_VERSION = 1; // The previous desktop { version, channels: { telegram } } format.
const LEGACY_BACKUP_SUFFIX = '.v1.bak'; // Never replace this recoverable, exact pre-migration copy.

export function writePrivateJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = path.join(path.dirname(file), `.${path.basename(file)}.${randomUUID()}.tmp`);
  try {
    fs.writeFileSync(temp, typeof value === 'string' ? value : JSON.stringify(value, null, 2), { mode: PRIVATE_FILE_MODE, flag: 'wx' });
    fs.renameSync(temp, file);
    try { fs.chmodSync(file, PRIVATE_FILE_MODE); } catch { /* Windows ACLs manage file access. */ }
  } finally { try { fs.unlinkSync(temp); } catch {} }
}

export class ChannelStore {
  constructor(file, { registry = defaultRegistry, env = () => undefined } = {}) {
    Object.assign(this, { file, registry, env });
    this.data = {}; this.error = null; this.migrated = false;
  }
  load() {
    this.error = null; this.migrated = false;
    let original;
    try {
      original = fs.readFileSync(this.file, 'utf8');
      const parsed = JSON.parse(original);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object' || (parsed.version != null && ![LEGACY_VERSION, CHANNEL_STORE_VERSION].includes(parsed.version))) throw new Error('Invalid channel settings format');
      const channels = parsed.channels || (parsed.telegram ? { [TELEGRAM_CHANNEL_ID]: parsed.telegram } : null);
      if (!channels || Array.isArray(channels) || typeof channels !== 'object') throw new Error('Invalid channels map');
      const data = {};
      for (const [id, settings] of Object.entries(channels)) {
        if (['__proto__', 'constructor', 'prototype'].includes(id)) throw new Error('Invalid channel identifier');
        if (!settings || typeof settings !== 'object' || Array.isArray(settings)) throw new Error('Invalid saved channel');
        data[id] = this.registry.manifests.has(id) ? this.registry.validate(id, settings) : structuredClone(settings);
      }
      this.data = data;
      if (parsed.version !== CHANNEL_STORE_VERSION) {
        const backup = this.file + LEGACY_BACKUP_SUFFIX;
        if (!fs.existsSync(backup)) fs.writeFileSync(backup, original, { mode: PRIVATE_FILE_MODE, flag: 'wx' });
        writePrivateJson(this.file, { version: CHANNEL_STORE_VERSION, channels: data });
        this.migrated = true;
      }
    } catch (error) {
      if (error.code !== 'ENOENT') { this.error = 'Channel settings are corrupt or unreadable; repair the file before saving. The original was preserved.'; this.data = {}; }
    }
    return this;
  }
  get(id) { return this.registry.resolve(id, this.data[id] || {}, this.env); }
  telegram() { return this.get(TELEGRAM_CHANNEL_ID); }
  preview(id, patch) {
    if (typeof id !== 'string') { patch = id; id = TELEGRAM_CHANNEL_ID; }
    return { ...this.data, [id]: { ...this.get(id), ...this.registry.validate(id, patch || {}) } };
  }
  save(next) {
    if (this.error) throw new Error(this.error);
    writePrivateJson(this.file, { version: CHANNEL_STORE_VERSION, channels: next });
    this.data = structuredClone(next);
    return this;
  }
  update(id, patch) { return this.save(this.preview(id, patch)); }
  doctor() { return { ok: !this.error, error: this.error, version: CHANNEL_STORE_VERSION, migrated: this.migrated, rollbackAvailable: fs.existsSync(this.file + LEGACY_BACKUP_SUFFIX) }; }
  rollback() {
    if (Object.keys(this.data).some(id => id !== TELEGRAM_CHANNEL_ID && Object.values(this.data[id]).some(Boolean))) throw new Error('Rollback would discard new channel settings; export them first');
    const original = fs.readFileSync(this.file + LEGACY_BACKUP_SUFFIX, 'utf8');
    const saved = JSON.parse(original), channels = saved.channels || { [TELEGRAM_CHANNEL_ID]: saved.telegram };
    const settings = this.registry.validate(TELEGRAM_CHANNEL_ID, channels[TELEGRAM_CHANNEL_ID] || {});
    writePrivateJson(this.file, original);
    this.data = { [TELEGRAM_CHANNEL_ID]: settings }; this.migrated = false; this.error = null;
    return this;
  }
}
