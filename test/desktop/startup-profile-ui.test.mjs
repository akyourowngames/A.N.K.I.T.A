import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';
import { startupProfile } from '../../src/core/startup-profile.mjs';
import { IPC_CONTRACT } from '../../desktop/shared/version.mjs';

const READY_MS = 15_000; // Milliseconds for the real local renderer to mount.

test('real desktop skills page shows and refreshes the engine startup report', async t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'startup-ui-'));
  const engine = new DesktopEngine({ config: {}, teammateFile: path.join(root, 'teammates.json'), settingsFile: path.join(root, 'settings.json'), channelsFile: path.join(root, 'channels.json'), browserFile: path.join(root, 'browser.json'), credentialFile: path.join(root, 'credentials.json'), composioFile: path.join(root, 'composio.json'), composioGrantsFile: path.join(root, 'grants.json'), sessionsDir: path.join(root, 'sessions'), projectsFile: path.join(root, 'projects.json') });
  const version = JSON.parse(fs.readFileSync(new URL('../../package.json', import.meta.url), 'utf8')).version;
  const vite = await createServer({ configFile: fileURLToPath(new URL('../../desktop/vite.config.ts', import.meta.url)), server: { middlewareMode: true, hmr: false } });
  const server = http.createServer((req, res) => vite.middlewares(req, res));
  let browser;
  t.after(async () => { await browser?.close(); await vite.close(); server.closeAllConnections(); if (server.listening) await new Promise(resolve => server.close(resolve)); await engine.mcp.closeAll(); fs.rmSync(root, { recursive: true, force: true }); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage(); page.setDefaultTimeout(READY_MS);
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.exposeFunction('__engine', (action, payload) => {
    if (action === 'getStartupProfile') return engine.getStartupProfile();
    if (action === 'listSkills') return engine.listSkills();
    if (action === 'setSkillEnabled') return engine.setSkillEnabled(payload.name, payload.enabled);
    if (action === 'initialize') return { teammates: [], models: [], settings: { provider: 'fixture', model: '', username: '', tools: [] }, preferences: { provider: 'fixture', model: '', appearance: 'graphite', profileSetupDone: true }, version, contract: IPC_CONTRACT, chrome: 'inline', jobs: [] };
    if (action === 'pluginsOverview') return { mode: 'unavailable', services: {}, live: false };
    if (action === 'browserPluginsOverview') return { isolated: { enabled: false, ready: false, allowedSites: [], blockedSites: [] }, local: { enabled: false, ready: false, allowedSites: [], blockedSites: [] } };
    if (action === 'secureStoreList') return { records: [] };
    return [];
  });
  await page.addInitScript(() => { const off = () => () => {}; window.ankita = { invoke: (...args) => window.__engine(...args), onEvent: off, onMenuCommand: off, onUpdateEvent: off, onCursor: off, appAction: async () => false, openExternal: async () => false }; });
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.getByRole('button', { name: 'Plugins', exact: true }).click();
  await page.getByRole('button', { name: 'Skills', exact: true }).click();
  await page.getByText('Startup timings', { exact: true }).click();
  await page.getByText(/Startup timings \(ms\):.*skill ankita-dev/).waitFor();
  startupProfile.finish('plugin', 'late-fixture', startupProfile.now(), 'ready');
  await page.getByRole('button', { name: 'Refresh timings', exact: true }).click();
  await page.getByText(/Startup timings \(ms\):.*late-fixture/).waitFor();
  await page.getByRole('switch', { name: 'Disable ankita-dev', exact: true }).click();
  await page.getByRole('switch', { name: 'Enable ankita-dev', exact: true }).waitFor();
  assert.deepEqual(errors, []);
  console.log('STARTUP_PROFILE_UI_LIVE report=true refresh=true existingDisable=true rendererErrors=0 transport=fixture engine=real');
});
