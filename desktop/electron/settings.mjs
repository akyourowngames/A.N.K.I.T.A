import fs from 'node:fs';
import path from 'node:path';

const providers = new Set(['copilot', 'groq', 'kilo', 'custom']);
const appearances = new Set(['graphite', 'mono', 'slate']);
const keys = new Set(['provider', 'model', 'customApiBase', 'customApiKey', 'groqApiKey', 'kiloApiKey', 'composioApiKey', 'appearance', 'contextWindow', 'maxTokens']);
const own = (value, key) => Object.prototype.hasOwnProperty.call(value, key);

export function normalizeApiBase(value) {
  const raw = String(value || '').trim().replace(/\/+$/, '');
  if (!raw) return '';
  let url;
  try { url = new URL(raw); } catch { throw new Error('Enter a valid provider URL'); }
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error('Use an HTTP or HTTPS provider URL without credentials or query parameters');
  }
  return url.toString().replace(/\/$/, '');
}

function validatePatch(patch) {
  if (!patch || typeof patch !== 'object' || Array.isArray(patch)) throw new Error('Invalid settings update');
  const clean = {};
  for (const [key, value] of Object.entries(patch)) {
    if (!keys.has(key)) throw new Error(`Unknown desktop setting: ${key}`);
    if (key === 'provider') {
      if (!providers.has(value)) throw new Error('Choose a supported provider');
      clean.provider = value;
    } else if (key === 'appearance') {
      if (!appearances.has(value)) throw new Error('Choose a supported appearance');
      clean.appearance = value;
    } else if (key === 'customApiBase') {
      clean.customApiBase = normalizeApiBase(value);
    } else if (key === 'contextWindow' || key === 'maxTokens') {
      // 0 (or blank) means "leave it to the default / the model". Any positive
      // value is a token count the user typed; cap it so a typo cannot ask for
      // a billion-token window.
      const n = value === '' || value == null ? 0 : Number(value);
      if (!Number.isFinite(n) || n < 0 || n > 10_000_000) throw new Error(`Enter a valid ${key === 'maxTokens' ? 'max output tokens' : 'context window'} value`);
      clean[key] = Math.floor(n);
    } else {
      if (typeof value !== 'string') throw new Error(`Invalid ${key} value`);
      const limit = key === 'model' ? 200 : 4096;
      const text = value.trim();
      if (text.length > limit) throw new Error(`${key} is too long`);
      clean[key] = text;
    }
  }
  return clean;
}

export function applyDesktopSettings(base, saved = {}) {
  const config = { ...base };
  if (own(saved, 'provider')) {
    config.provider = saved.provider;
    // API_BASE from .env otherwise wins over PROVIDER in the shared bootstrap.
    config.apiBase = '';
    config.apiKey = '';
    config.model = '';
  }
  if (own(saved, 'groqApiKey')) config.groqApiKey = saved.groqApiKey;
  if (own(saved, 'composioApiKey')) config.composioApiKey = saved.composioApiKey;
  if (config.provider === 'custom') {
    if (own(saved, 'customApiBase')) config.apiBase = saved.customApiBase;
    if (own(saved, 'customApiKey')) config.apiKey = saved.customApiKey;
  } else if (config.provider === 'kilo' && own(saved, 'kiloApiKey')) {
    config.apiKey = saved.kiloApiKey;
  }
  if (own(saved, 'model')) config.model = saved.model;
  // A compatible endpoint often advertises no context window, so the app falls
  // back to a small default and can run out of room for tools. Let the user
  // declare the real numbers; an explicit value must win over the default.
  if (own(saved, 'contextWindow') && saved.contextWindow > 0) {
    config.contextWindow = saved.contextWindow;
    config.contextWindowExplicit = true;
  }
  if (own(saved, 'maxTokens') && saved.maxTokens > 0) {
    config.maxTokens = saved.maxTokens;
    config.maxTokensExplicit = true;
  }
  return config;
}

export class DesktopSettingsStore {
  constructor(file) { this.file = file; this.data = {}; }

  load() {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      this.data = validatePatch(parsed.settings || {});
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
      this.data = {};
    }
    return this;
  }

  preview(patch) { return { ...this.data, ...validatePatch(patch) }; }

  save(next) {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const temp = path.join(path.dirname(this.file), `.${path.basename(this.file)}.${process.pid}.tmp`);
    try {
      fs.writeFileSync(temp, JSON.stringify({ version: 1, settings: next }, null, 2), { mode: 0o600 });
      fs.renameSync(temp, this.file);
      try { fs.chmodSync(this.file, 0o600); } catch { /* Windows may ignore mode changes. */ }
    } finally {
      try { fs.unlinkSync(temp); } catch {}
    }
    this.data = next;
    return this;
  }

  update(patch) { return this.save(this.preview(patch)); }

  publicView(config) {
    const provider = this.data.provider || (config.apiBase && !['groq', 'kilo'].includes(config.provider) ? 'custom' : config.provider || 'copilot');
    return {
      provider,
      model: this.data.model || config.model || '',
      customApiBase: this.data.customApiBase || (provider === 'custom' ? config.apiBase || '' : ''),
      appearance: this.data.appearance || 'graphite',
      contextWindow: this.data.contextWindow || 0,
      maxTokens: this.data.maxTokens || 0,
      hasCustomApiKey: Boolean(this.data.customApiKey || (provider === 'custom' && config.apiKey)),
      hasGroqKey: Boolean(own(this.data, 'groqApiKey') ? this.data.groqApiKey : config.groqApiKey),
      hasKiloKey: Boolean(this.data.kiloApiKey || (provider === 'kilo' && config.apiKey)),
      hasComposioKey: Boolean(own(this.data, 'composioApiKey') ? this.data.composioApiKey : config.composioApiKey),
    };
  }
}

export async function testCustomProvider({ apiBase, apiKey = '', fetchImpl = fetch }) {
  const base = normalizeApiBase(apiBase);
  if (!base) throw new Error('Enter the provider API URL first');
  let response;
  try {
    response = await fetchImpl(`${base}/models`, {
      headers: { Accept: 'application/json', ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}) },
      signal: AbortSignal.timeout(8000),
    });
  } catch (error) {
    if (error?.name === 'TimeoutError' || error?.name === 'AbortError') throw new Error('Connection timed out after 8 seconds');
    throw new Error('Could not reach the provider. Check the URL and network.');
  }
  if (!response.ok) throw new Error(`Provider returned HTTP ${response.status}. Check the URL and API key.`);
  const body = await response.json().catch(() => null);
  if (!Array.isArray(body?.data)) throw new Error('The endpoint did not return a valid model list');
  return { ok: true, models: body.data.length, status: response.status };
}
