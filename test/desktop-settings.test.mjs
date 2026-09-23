import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DesktopSettingsStore, applyDesktopSettings, testCustomProvider } from '../desktop/electron/settings.mjs';
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
      teammateFile: path.join(dir, 'teammates.json'), settingsFile: path.join(dir, 'desktop-settings.json'), sessionsDir: dir,
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
      teammateFile: path.join(dir, 'teammates.json'), settingsFile: path.join(dir, 'settings.json'), sessionsDir: dir,
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
