import { PERSONALITY_ACTIONS, PERSONALITY_FILENAME } from '../src/core/personality.mjs';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { _electron } from 'playwright';
import { CONFIG_DIR } from '../src/core/config.mjs';
import { normalizeApiBase } from '../desktop/electron/settings.mjs';

const ROOT = path.resolve(fileURLToPath(new URL('../', import.meta.url))); // Test the actual checkout's package entry, preload and IPC; normalize directory separators for Electron args.
const TIMEOUT_MS = 30_000; // Milliseconds: fail a broken native startup without waiting for external providers.
const HOST = '127.0.0.1'; // Local-only fixture; the OS selects its port.
const MODEL = 'channel-startup-fixture'; // Synthetic model identity, used only by this verification script.
const FIXTURE_TOKEN = 'local-channel-startup-fixture'; // Never a real account key; enabled channels remain off.
const CHECK_PERSONALITY = process.argv.includes('--personality'); // Explicit opt-in to exercise the integrated editor over real native IPC.
const EDITOR_TIMEOUT_MS = 5000; // Milliseconds: fail a missing screen promptly.
const SETTINGS_FILE = 'desktop-settings.json'; // Existing desktop profile filename; only copied into owned temporary profiles.
const sourceSettings = process.argv.includes('--saved-settings') ? path.join(CONFIG_DIR, SETTINGS_FILE) : null; // Explicit opt-in to test the user's existing profile, read-only.
const originalSettings = sourceSettings ? await fs.readFile(sourceSettings) : null;
const expectedSettings = originalSettings ? JSON.parse(originalSettings.toString('utf8')).settings : null;
const require = createRequire(import.meta.url);
const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-channel-startup-'));
const model = http.createServer((request, response) => {
  response.setHeader('Content-Type', 'application/json');
  response.end(JSON.stringify(request.url === '/models' ? { data: [{ id: MODEL }] } : {}));
});
let vite, app;
try {
  await new Promise(resolve => model.listen(0, HOST, resolve));
  vite = await createServer({ configFile: path.join(ROOT, 'desktop/vite.config.ts'), server: { strictPort: false }, logLevel: 'error' });
  await vite.listen();
  for (const mode of ['dev', 'built']) {
    const config = path.join(directory, mode, 'config'); await fs.mkdir(config, { recursive: true });
    const saved = expectedSettings || {
      provider: 'future-compatible-fixture', model: MODEL, customApiBase: `http://${HOST}:${model.address().port}`, customApiKey: '', profileSetupDone: true,
    };
    await fs.writeFile(path.join(config, SETTINGS_FILE), originalSettings || JSON.stringify({ version: 1, settings: saved }), { mode: 0o600 });
    const env = { ...process.env, CONFIG_DIR: config, COMPOSIO_API_KEY: '', TOOL_PROVIDER: '', TOOL_MODEL: '', TOOL_API_BASE: '', TOOL_API_KEY: '',
      TELEGRAM_BOT_TOKEN: FIXTURE_TOKEN, TELEGRAM_ENABLED: 'off', DISCORD_ENABLED: 'off', SLACK_ENABLED: 'off',
      MEMORY_CONSOLIDATION: 'off', ALLOW_PRIVATE_HOSTS: '1' };
    delete env.ELECTRON_RUN_AS_NODE; delete env.ANKITA_DESKTOP_DEV_URL;
    if (mode === 'dev') env.ANKITA_DESKTOP_DEV_URL = vite.resolvedUrls.local[0];
    app = await _electron.launch({ executablePath: require('electron'), args: [ROOT, `--user-data-dir=${path.join(directory, mode, 'user-data')}`], cwd: config, env, timeout: TIMEOUT_MS });
    const page = await app.firstWindow(), errors = []; page.setDefaultTimeout(TIMEOUT_MS);
    page.on('pageerror', error => errors.push(error.message));
    await page.waitForFunction(() => Boolean(window.ankita));
    const ready = await page.evaluate(() => window.ankita.invoke('initialize'));
    const view = await page.evaluate(() => window.ankita.invoke('getChannels'));
    assert.ok(ready.teammates.length); assert.deepEqual(Object.keys(view.channels).sort(), ['discord', 'slack', 'telegram']);
    assert.equal(view.channels.telegram.secrets.token, true, 'Native startup must read the late-loaded environment');
    assert.equal(JSON.stringify(view).includes(FIXTURE_TOKEN), false); assert.equal(view.channels.telegram.status.running, false);
    assert.equal(ready.preferences.provider, 'custom');
    assert.ok(ready.preferences.providerNotice, 'A newer saved provider must explain its compatible route');
    assert.ok(ready.preferences.customApiBase === normalizeApiBase(saved.customApiBase), 'Saved compatible endpoint retained');
    assert.ok(ready.preferences.model === saved.model, 'Saved model retained');
    assert.ok(ready.preferences.hasCustomApiKey === Boolean(saved.customApiKey?.trim()), 'Saved credential remains available without returning its value');
    assert.ok(ready.models.length, 'Provider model discovery succeeds');
    await page.getByRole('button', { name: 'Open settings', exact: true }).click();
    await page.getByRole('button', { name: 'Providers', exact: true }).click();
    await page.getByRole('status').filter({ hasText: ready.preferences.providerNotice }).waitFor();
    if (CHECK_PERSONALITY) {
      await page.getByRole('button', { name: 'Personality', exact: true }).click();
      await page.getByLabel('Character', { exact: true }).waitFor({ timeout: EDITOR_TIMEOUT_MS });
      const description = 'Native editor fixture with caring attitude';
      await page.getByLabel('Character', { exact: true }).fill(description);
      await page.getByLabel('Teasing', { exact: true }).selectOption('off');
      await page.getByRole('button', { name: 'Save personality', exact: true }).click();
      await page.getByRole('status').filter({ hasText: 'Personality saved' }).waitFor();
      const card = await page.evaluate(action => window.ankita.invoke(action), PERSONALITY_ACTIONS.get);
      assert.equal(card.profile.description, description);
      assert.equal(card.profile.teasing, 'off');
      const savedCard = JSON.parse(await fs.readFile(path.join(config, PERSONALITY_FILENAME), 'utf8'));
      assert.deepEqual(savedCard.profile, card.profile);
      console.log(`PERSONALITY_DESKTOP_OK: ${mode}; actual Settings tab; edit/save/read-back; native IPC; isolated disk persistence.`);
    }
    assert.deepEqual(errors, []);
    console.log(`CHANNEL_DESKTOP_STARTUP_OK: ${mode}; actual Electron main/preload; initialize/getChannels IPC; late config; secret-safe view; no renderer errors.`);
    console.log(`SAVED_PROVIDER_STARTUP_OK: ${mode}; ${sourceSettings ? 'exact saved-profile copy' : 'future-provider fixture'}; compatible endpoint/model/credential retained; model discovery; Settings notice visible.`);
    await app.close(); app = null;
  }
} finally {
  await app?.close(); await vite?.close(); model.closeAllConnections();
  if (model.listening) await new Promise(resolve => model.close(resolve));
  try {
    if (sourceSettings) {
      assert.ok(originalSettings.equals(await fs.readFile(sourceSettings)), 'The original saved profile must remain byte-for-byte unchanged');
      console.log('SAVED_PROFILE_UNCHANGED: original settings are byte-for-byte intact.');
    }
  } finally {
    await fs.rm(directory, { recursive: true, force: true }); // Only this script's OS-created temporary profile; user profiles remain untouched.
  }
}
