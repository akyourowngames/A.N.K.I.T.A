import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DesktopSettingsStore, applyDesktopSettings, seedFreshDesktopProvider, testCustomProvider } from '../desktop/electron/settings.mjs';

test('fresh desktop installs select Kilo while existing users and explicit settings keep their provider', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-fresh-provider-'));
  try {
    const settingsFile = path.join(dir, 'desktop-settings.json');
    const teammatesFile = path.join(dir, 'desktop-teammates.json');
    const fresh = new DesktopSettingsStore(settingsFile).load();
    assert.equal(seedFreshDesktopProvider(fresh, teammatesFile, { provider: '', apiBase: '', apiKey: '', model: '' }), true);
    assert.equal(new DesktopSettingsStore(settingsFile).load().data.provider, 'kilo');
    assert.equal(seedFreshDesktopProvider(fresh, teammatesFile, { provider: '', apiBase: '', apiKey: '', model: '' }), false);

    const existing = new DesktopSettingsStore(path.join(dir, 'existing-settings.json')).load();
    fs.writeFileSync(teammatesFile, '{}');
    assert.equal(seedFreshDesktopProvider(existing, teammatesFile, { provider: '', apiBase: '', apiKey: '', model: '' }), false);
    assert.equal(existing.data.provider, undefined);
    fs.rmSync(teammatesFile);
    assert.equal(seedFreshDesktopProvider(existing, teammatesFile, { provider: 'copilot', apiBase: '', apiKey: '', model: '' }), false);
    assert.equal(seedFreshDesktopProvider(existing, teammatesFile, { provider: '', apiBase: '', apiKey: '', model: 'gpt-4o' }), false);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
import { createSession } from '../src/bootstrap.mjs';
import { DesktopEngine } from '../desktop/electron/engine.mjs';

test('desktop settings persist credentials without returning them to the renderer', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-settings-'));
  try {
    const store = new DesktopSettingsStore(path.join(dir, 'settings.json'));
    store.update({ provider: 'custom', customApiBase: 'http://localhost:11434/v1/', customApiKey: 'private-token', composioApiKey: 'composio-secret', appearance: 'mono' });
    const fresh = new DesktopSettingsStore(store.file).load();
    assert.equal(fresh.data.customApiBase, 'http://localhost:11434/v1');
    const view = fresh.publicView(applyDesktopSettings({}, fresh.data));
    assert.equal(view.hasCustomApiKey, true);
    assert.equal(view.hasComposioKey, true);
    assert.equal(view.appearance, 'mono');
    assert.equal(JSON.stringify(view).includes('private-token'), false);
    assert.equal(JSON.stringify(view).includes('composio-secret'), false);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('desktop provider override replaces an incompatible project API base', () => {
  const base = { provider: 'groq', apiBase: 'https://api.groq.com/openai/v1', apiKey: 'old', model: 'old-model', groqApiKey: 'from-env', composioApiKey: '' };
  const custom = applyDesktopSettings(base, { provider: 'custom', customApiBase: 'http://localhost:11434/v1', customApiKey: 'local-key', model: 'local-model' });
  assert.equal(custom.provider, 'custom');
  assert.equal(custom.apiBase, 'http://localhost:11434/v1');
  assert.equal(custom.apiKey, 'local-key');
  assert.equal(custom.model, 'local-model');
  const copilot = applyDesktopSettings(base, { provider: 'copilot' });
  assert.equal(copilot.apiBase, '');
  assert.equal(copilot.apiKey, '');
  assert.equal(copilot.model, '');
  const inherited = applyDesktopSettings({ provider: 'custom', apiBase: 'http://localhost:1234/v1', apiKey: 'from-env' }, {});
  assert.equal(inherited.apiBase, 'http://localhost:1234/v1');
  assert.equal(inherited.apiKey, 'from-env');
});

test('desktop image settings override env config without exposing API keys', () => {
  const base = {
    provider: 'custom', apiBase: 'https://chat.example/v1', apiKey: 'chat-secret',
    imageApiBase: '', imageApiKey: '', imageModel: 'gpt-image-1', unsplashAccessKey: '', pixabayApiKey: '',
  };
  const configured = applyDesktopSettings(base, {
    imageApiBase: 'https://images.example/v1', imageApiKey: 'image-secret', imageModel: 'image-model',
    unsplashAccessKey: 'unsplash-secret', pixabayApiKey: 'pixabay-secret',
  });
  assert.equal(configured.imageApiBase, 'https://images.example/v1');
  assert.equal(configured.imageApiKey, 'image-secret');
  assert.equal(configured.imageModel, 'image-model');
  const view = new DesktopSettingsStore(path.join(os.tmpdir(), 'not-loaded-image-settings.json'));
  view.data = { imageApiBase: configured.imageApiBase, imageModel: configured.imageModel, imageApiKey: configured.imageApiKey, unsplashAccessKey: configured.unsplashAccessKey, pixabayApiKey: configured.pixabayApiKey };
  const safe = view.publicView(configured);
  assert.equal(safe.hasImageApiKey, true);
  assert.equal(safe.hasUnsplashAccessKey, true);
  assert.equal(safe.hasPixabayApiKey, true);
  assert.equal(JSON.stringify(safe).includes('image-secret'), false);
  assert.equal(JSON.stringify(safe).includes('unsplash-secret'), false);
  assert.equal(JSON.stringify(safe).includes('pixabay-secret'), false);
});

test('context window and output cap are configurable and marked explicit', () => {
  const base = { provider: 'custom', apiBase: 'http://localhost:11434/v1', apiKey: 'k', contextWindow: 32768, maxTokens: 4096, contextWindowExplicit: false, maxTokensExplicit: false };
  const tuned = applyDesktopSettings(base, { contextWindow: 200000, maxTokens: 8192 });
  assert.equal(tuned.contextWindow, 200000);
  assert.equal(tuned.contextWindowExplicit, true, 'a declared window must win over the default');
  assert.equal(tuned.maxTokens, 8192);
  assert.equal(tuned.maxTokensExplicit, true);
  const cleared = applyDesktopSettings(base, { contextWindow: 0, maxTokens: 0 });
  assert.equal(cleared.contextWindow, 32768, 'blank restores the base default');
  assert.equal(cleared.contextWindowExplicit, false);
});

test('desktop settings reject a bad window value instead of persisting it', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-settings-window-'));
  try {
    const store = new DesktopSettingsStore(path.join(dir, 'settings.json'));
    assert.throws(() => store.update({ contextWindow: 'lots' }), /valid context window/);
    assert.throws(() => store.update({ maxTokens: -5 }), /valid max output tokens/);
    store.update({ contextWindow: 128000, maxTokens: 4096 });
    const view = new DesktopSettingsStore(store.file).load().publicView({});
    assert.equal(view.contextWindow, 128000);
    assert.equal(view.maxTokens, 4096);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('an unknown settings key is ignored so a newer window can still save', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-settings-unknown-'));
  try {
    const store = new DesktopSettingsStore(path.join(dir, 'settings.json'));
    // A newer renderer talking to this build would send a key it does not know.
    // It must not block the save or persist the field.
    store.update({ model: 'alpha', somethingFromTheFuture: true });
    const fresh = new DesktopSettingsStore(store.file).load();
    assert.equal(fresh.data.model, 'alpha');
    assert.equal(Object.hasOwn(fresh.data, 'somethingFromTheFuture'), false);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('changing the window updates live agents without reconnecting', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-settings-window-engine-'));
  const client = { id: 'client' };
  const bootstrap = async ({ config }) => ({ client, tool: null, models: [{ id: 'alpha', name: 'Alpha', tools: true }], model: 'alpha', provider: { name: config.provider } });
  const mcp = { connectedIds: [], reconcile: async () => {}, ensureComposio: async () => {}, closeAll: async () => {} };
  try {
    const engine = new DesktopEngine({
      teammateFile: path.join(dir, 'teammates.json'), settingsFile: path.join(dir, 'desktop-settings.json'), channelsFile: path.join(dir, 'channels.json'), sessionsDir: dir,
      config: { provider: 'custom', apiBase: 'http://localhost:11434/v1', apiKey: 'k', model: 'alpha', tools: true, contextWindow: 32768, maxTokens: 4096 },
      bootstrap, mcp, emit: () => {},
    });
    await engine.init();
    const agent = { config: { ...engine.config }, contextWindow: 32768 };
    engine.agents.set('thread', agent);
    await engine.saveDesktopSettings({ contextWindow: 200000, maxTokens: 8192 });
    assert.equal(engine.client, client, 'the provider connection is reused');
    assert.equal(engine.config.contextWindow, 200000);
    assert.equal(engine.config.contextWindowExplicit, true);
    assert.equal(agent.contextWindow, 200000, 'live agents pick up the new window');
    assert.equal(agent.config.contextWindow, 200000);
    assert.equal(agent.config.maxTokensExplicit, true);
    await engine.close();
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('custom provider connection checks models with a bounded request and never echoes the key', async () => {
  let seen;
  const result = await testCustomProvider({ apiBase: 'https://models.example/v1', apiKey: 'private-token', fetchImpl: async (url, options) => {
    seen = { url, auth: options.headers.Authorization, signal: options.signal };
    return { ok: true, status: 200, json: async () => ({ data: [{ id: 'alpha' }, { id: 'beta' }] }) };
  } });
  assert.equal(seen.url, 'https://models.example/v1/models');
  assert.equal(seen.auth, 'Bearer private-token');
  assert.ok(seen.signal);
  assert.deepEqual(result, { ok: true, models: 2, status: 200 });
  assert.equal(JSON.stringify(result).includes('private-token'), false);
  await assert.rejects(testCustomProvider({ apiBase: 'https://models.example/v1', fetchImpl: async () => ({ ok: true, status: 200, json: async () => ({}) }) }), /valid model list/);
});

test('shared bootstrap accepts a configured custom provider', async () => {
  class Client {
    constructor(options) { this.options = options; }
    async models() { return [{ id: 'local', tools: true, default: true }]; }
  }
  const session = await createSession({
    config: { provider: 'custom', apiBase: 'http://localhost:11434/v1', apiKey: 'secret', model: '', tools: true, contextWindow: 32768 },
    CompatibleClientClass: Client,
  });
  assert.equal(session.provider.name, 'custom');
  assert.equal(session.client.options.apiKey, 'secret');
  assert.equal(session.model, 'local');
});

test('desktop engine applies provider changes and leaves failed changes unsaved', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-settings-engine-'));
  const events = [];
  const connected = [];
  const mcp = { connectedIds: [], reconcile: async () => {}, ensureComposio: async config => { connected.push(config.composioApiKey); }, closeAll: async () => {} };
  const bootstrap = async ({ config }) => {
    if (config.apiKey === 'bad-key') throw new Error('Invalid API key');
    return { client: {}, tool: null, models: [{ id: 'alpha', name: 'Alpha', tools: true }], model: 'alpha', provider: { name: config.provider } };
  };
  try {
    const engine = new DesktopEngine({
      teammateFile: path.join(dir, 'teammates.json'), settingsFile: path.join(dir, 'desktop-settings.json'), channelsFile: path.join(dir, 'channels.json'), sessionsDir: dir,
      config: { provider: 'groq', apiBase: 'https://api.groq.com/openai/v1', apiKey: 'from-env', model: '', groqApiKey: 'from-env', composioApiKey: '', tools: true },
      bootstrap, mcp, emit: event => events.push(event),
    });
    await engine.init();
    const result = await engine.saveDesktopSettings({ provider: 'custom', customApiBase: 'http://localhost:11434/v1', customApiKey: 'local-secret', composioApiKey: 'composio-secret', appearance: 'slate' });
    assert.equal(engine.config.apiBase, 'http://localhost:11434/v1');
    assert.equal(engine.config.apiKey, 'local-secret');
    assert.equal(result.preferences.appearance, 'slate');
    assert.equal(result.preferences.hasComposioKey, true);
    assert.equal(JSON.stringify(result).includes('local-secret'), false);
    assert.equal(JSON.stringify(events.filter(event => event.type === 'settings-updated')).includes('composio-secret'), false);
    const originalFetch = globalThis.fetch;
    let sentAuthorization;
    try {
      globalThis.fetch = async (_url, options) => {
        sentAuthorization = options.headers.Authorization;
        return { ok: true, status: 200, json: async () => ({ data: [] }) };
      };
      await engine.testCustomProvider({ apiBase: 'http://different-host.example/v1' });
      assert.equal(sentAuthorization, undefined);
    } finally { globalThis.fetch = originalFetch; }
    await assert.rejects(engine.saveDesktopSettings({ customApiKey: 'bad-key' }), /Invalid API key/);
    assert.equal(engine.config.apiKey, 'local-secret');
    assert.equal(new DesktopSettingsStore(path.join(dir, 'desktop-settings.json')).load().data.customApiKey, 'local-secret');
    await engine.close();
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('appearance can be saved while a custom provider is unconfigured', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-settings-appearance-'));
  try {
    const engine = new DesktopEngine({
      teammateFile: path.join(dir, 'teammates.json'), settingsFile: path.join(dir, 'settings.json'), channelsFile: path.join(dir, 'channels.json'), sessionsDir: dir,
      config: { provider: 'custom', apiBase: '', apiKey: '', model: '', composioApiKey: '' },
      mcp: { connectedIds: [], reconcile: async () => {}, ensureComposio: async () => {}, closeAll: async () => {} },
    });
    await engine.init();
    assert.equal(engine.client, null);
    const result = await engine.saveDesktopSettings({ appearance: 'slate' });
    assert.equal(result.preferences.appearance, 'slate');
    assert.equal(engine.client, null);
    await engine.close();
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('profile name, timezone and setup flag persist and reach the renderer', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-settings-profile-'));
  try {
    const store = new DesktopSettingsStore(path.join(dir, 'settings.json'));
    store.update({ username: '  Krish  ', timeZone: 'Asia/Kolkata', profileSetupDone: true });
    const fresh = new DesktopSettingsStore(store.file).load();
    assert.equal(fresh.data.username, 'Krish', 'names are trimmed');
    assert.equal(fresh.data.timeZone, 'Asia/Kolkata');
    assert.equal(fresh.data.profileSetupDone, true);
    const view = fresh.publicView({ username: 'user', timeZone: '' });
    assert.equal(view.username, 'Krish');
    assert.equal(view.timeZone, 'Asia/Kolkata');
    assert.equal(view.profileSetupDone, true);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('profile settings reject bad values instead of persisting them', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-settings-profile-bad-'));
  try {
    const store = new DesktopSettingsStore(path.join(dir, 'settings.json'));
    assert.throws(() => store.update({ username: 42 }), /Invalid name/);
    assert.throws(() => store.update({ username: 'x'.repeat(101) }), /under 100 characters/);
    assert.throws(() => store.update({ timeZone: 'Mars/Olympus' }), /valid timezone/);
    store.update({ timeZone: '' });
    assert.equal(new DesktopSettingsStore(store.file).load().data.timeZone, '', 'blank stays system-local');
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('profile settings override env config without a reconnect', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-settings-profile-engine-'));
  const client = { id: 'client' };
  const bootstrap = async ({ config }) => ({ client, tool: null, models: [{ id: 'alpha', name: 'Alpha', tools: true }], model: 'alpha', provider: { name: config.provider } });
  const mcp = { connectedIds: [], reconcile: async () => {}, ensureComposio: async () => {}, closeAll: async () => {} };
  try {
    const base = { provider: 'copilot', username: 'user', timeZone: '', tools: true, contextWindow: 32768 };
    const converted = applyDesktopSettings(base, { username: 'Krish', timeZone: 'Asia/Kolkata' });
    assert.equal(converted.username, 'Krish', 'the app value wins over env');
    assert.equal(converted.timeZone, 'Asia/Kolkata');
    assert.equal(applyDesktopSettings(base, {}).username, 'user', 'env survives when the app has nothing saved');
    const engine = new DesktopEngine({
      teammateFile: path.join(dir, 'teammates.json'), settingsFile: path.join(dir, 'desktop-settings.json'), channelsFile: path.join(dir, 'channels.json'), sessionsDir: dir,
      config: { ...base }, bootstrap, mcp, emit: () => {},
    });
    await engine.init();
    const agent = { config: { ...engine.config }, contextWindow: 32768 };
    engine.agents.set('thread', agent);
    const result = await engine.saveDesktopSettings({ username: 'Krish', timeZone: 'Asia/Kolkata', profileSetupDone: true });
    assert.equal(engine.client, client, 'the provider connection is reused');
    assert.equal(engine.config.username, 'Krish');
    assert.equal(agent.config.timeZone, 'Asia/Kolkata', 'live agents pick up the profile');
    assert.equal(result.preferences.username, 'Krish');
    assert.equal(result.preferences.profileSetupDone, true);
    await engine.close();
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});
