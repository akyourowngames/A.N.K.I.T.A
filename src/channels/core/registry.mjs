import { CHANNEL_CAPABILITIES, CHANNEL_ID_PATTERN, FIELD_KINDS, SECRET_CHAR_LIMIT, LIST_CHAR_LIMIT, TEXT_CHAR_LIMIT, assertSerializable, own } from './contract.mjs';
import { telegramManifest } from '../manifests/telegram.mjs';
import { discordManifest } from '../manifests/discord.mjs';
import { slackManifest } from '../manifests/slack.mjs';

export function normalizeList(value, { numericIds = false } = {}) {
  return String(value ?? '').split(/[,\s]+/).filter(Boolean).map(id => numericIds && /^-?\d+$/.test(id) ? String(Number(id)) : id).join(', ');
}

function cleanField(key, value, field) {
  if (field.source === 'teammates' && value == null) return null;
  if (field.kind === 'bool') {
    if (typeof value !== 'boolean') throw new Error(`Invalid ${key} value`);
    return value;
  }
  if (field.kind === 'int' || field.kind === 'float') {
    const n = Number(value);
    if (value === '' || typeof value === 'boolean' || !Number.isFinite(n) || (field.min != null && n < field.min) || (field.max != null && n > field.max)) throw new Error(`${key === 'confirmTimeout' ? 'Approval timeout' : key} must be between ${field.min} and ${field.max}${key === 'confirmTimeout' ? ' seconds' : ''}`);
    return field.kind === 'int' ? Math.floor(n) : n;
  }
  if (typeof value !== 'string') throw new Error(`Invalid ${key} value`);
  const limit = field.maxLength || (field.kind === 'secret' ? SECRET_CHAR_LIMIT : field.kind === 'list' ? LIST_CHAR_LIMIT : TEXT_CHAR_LIMIT);
  if (value.length > limit) throw new Error(`${key} is too long`);
  if (field.kind === 'enum' && !field.values.includes(value)) throw new Error(`Invalid ${key} value`);
  const result = field.kind === 'list' ? normalizeList(value, field) : value.trim();
  return field.source === 'teammates' && !result ? null : result;
}

export class ChannelRegistry {
  constructor(manifests = []) { this.manifests = new Map(); for (const manifest of manifests) this.register(manifest); }
  register(manifest) {
    assertSerializable(manifest);
    if (!CHANNEL_ID_PATTERN.test(manifest?.id) || !manifest.label || !manifest.fields || !Array.isArray(manifest.capabilities)) throw new Error('Invalid channel manifest');
    if (this.manifests.has(manifest.id)) throw new Error(`Channel ${manifest.id} is already registered`);
    for (const capability of manifest.capabilities) if (!CHANNEL_CAPABILITIES.includes(capability)) throw new Error(`Unknown channel capability: ${capability}`);
    for (const [key, field] of Object.entries(manifest.fields)) {
      if (!/^[a-zA-Z][a-zA-Z0-9]*$/.test(key) || !FIELD_KINDS.includes(field.kind) || (field.kind === 'enum' && !Array.isArray(field.values))) throw new Error('Invalid channel field');
      if (own(field, 'default')) cleanField(key, field.default, field);
      if (field.kind === 'secret' && field.default) throw new Error('A secret field default must be empty');
    }
    for (const key of manifest.required || []) if (!own(manifest.fields, key)) throw new Error(`Unknown required channel field: ${key}`);
    const descriptor = structuredClone(manifest);
    this.manifests.set(manifest.id, descriptor);
    return this;
  }
  get(id) { const manifest = this.manifests.get(id); if (!manifest) throw new Error(`Unknown channel: ${id}`); return structuredClone(manifest); }
  list() { return [...this.manifests.keys()].map(id => this.get(id)); }
  validate(id, patch) {
    if (!patch || typeof patch !== 'object' || Array.isArray(patch) || ![Object.prototype, null].includes(Object.getPrototypeOf(patch))) throw new Error('Invalid channel update');
    const manifest = this.get(id), result = {};
    for (const [key, value] of Object.entries(patch)) {
      if (!own(manifest.fields, key)) throw new Error(`Unknown channel setting: ${key}`);
      result[key] = cleanField(key, value, manifest.fields[key]);
    }
    return result;
  }
  defaults(id) { return Object.fromEntries(Object.entries(this.get(id).fields).map(([key, field]) => [key, structuredClone(own(field, 'default') ? field.default : field.kind === 'bool' ? false : '')])); }
  resolve(id, saved = {}, env = () => undefined) {
    const manifest = this.get(id), result = this.defaults(id);
    for (const [key, field] of Object.entries(manifest.fields)) {
      if (own(saved, key)) continue;
      const raw = field.env ? env(field.env) ?? (field.fallbackEnv ? env(field.fallbackEnv) : undefined) : undefined;
      if (raw == null) continue;
      const value = field.kind === 'bool' ? /^(on|true|1|yes)$/i.test(String(raw)) : raw;
      result[key] = cleanField(key, value, field);
    }
    return { ...result, ...this.validate(id, saved) };
  }
  legacyDefaults() {
    const values = {};
    for (const manifest of this.list()) for (const [key, field] of Object.entries(manifest.fields)) if (field.configKey) values[field.configKey] = this.defaults(manifest.id)[key];
    return values;
  }
  environment(pick) {
    const channels = {}, aliases = {}, errors = [];
    for (const manifest of this.list()) {
      const settings = this.defaults(manifest.id);
      for (const [key, field] of Object.entries(manifest.fields)) {
        const raw = field.env ? pick(field.env) ?? (field.fallbackEnv ? pick(field.fallbackEnv) : undefined) : undefined;
        if (raw != null) {
          try { settings[key] = cleanField(key, field.kind === 'bool' ? /^(on|true|1|yes)$/i.test(String(raw)) : raw, field); }
          catch (error) { errors.push({ channel: manifest.id, field: key, error: error.message }); settings.enabled = false; }
        }
        if (field.configKey) aliases[field.configKey] = settings[key];
      }
      channels[manifest.id] = settings;
    }
    return { channels, aliases, errors };
  }
  publicView(id, config, status = {}) {
    const manifest = this.get(id), settings = this.resolve(id, config), view = { manifest, secrets: {} };
    for (const [key, field] of Object.entries(manifest.fields)) {
      if (field.kind === 'secret') view.secrets[key] = Boolean(settings[key]);
      else view[key] = settings[key];
    }
    // Compatibility for the old Telegram store/verification API, never a secret value.
    view.hasToken = Boolean(view.secrets.token);
    view.status = { running: Boolean(status.running), account: status.account || null, error: status.error || null };
    return view;
  }
}

export const defaultRegistry = new ChannelRegistry([telegramManifest, discordManifest, slackManifest]);

export function environmentForConfig(config, registry = defaultRegistry) {
  const values = {};
  for (const manifest of registry.list()) for (const [key, field] of Object.entries(manifest.fields)) {
    if (!field.env) continue;
    const value = config.channels?.[manifest.id]?.[key] ?? (field.configKey ? config[field.configKey] : undefined);
    if (value != null) values[field.env] = value;
  }
  return key => values[key];
}
