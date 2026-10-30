import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { _electron } from 'playwright';

const ROOT = path.resolve(fileURLToPath(new URL('../', import.meta.url))); // Test the actual checkout's package entry, preload and IPC; normalize directory separators for Electron args.
const TIMEOUT_MS = 30_000; // Milliseconds: fail a broken native startup without waiting for external providers.
const HOST = '127.0.0.1'; // Local-only fixture; the OS selects its port.
const MODEL = 'channel-startup-fixture'; // Synthetic model identity, used only by this verification script.
const FIXTURE_TOKEN = 'local-channel-startup-fixture'; // Never a real account key; enabled channels remain off.
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
    await fs.writeFile(path.join(config, 'desktop-settings.json'), JSON.stringify({ version: 1, settings: {
      provider: 'custom', model: MODEL, customApiBase: `http://${HOST}:${model.address().port}`, customApiKey: '', profileSetupDone: true,
    } }));
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
    assert.deepEqual(errors, []);
    console.log(`CHANNEL_DESKTOP_STARTUP_OK: ${mode}; actual Electron main/preload; initialize/getChannels IPC; late config; secret-safe view; no renderer errors.`);
    await app.close(); app = null;
  }
} finally {
  await app?.close(); await vite?.close(); model.closeAllConnections();
  if (model.listening) await new Promise(resolve => model.close(resolve));
  await fs.rm(directory, { recursive: true, force: true }); // Only this script's OS-created temporary profile; user profiles remain untouched.
}
