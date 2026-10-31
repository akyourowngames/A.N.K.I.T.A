import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/voice-handsfree-ui'; // Local preview with a stubbed desktop bridge; no real process, device or provider.
const PREFERENCES = {
  secretScrubbing: true, secretWarningSeen: true, provider: 'custom', model: 'alpha', customApiBase: 'http://localhost:11434/v1', appearance: 'graphite',
  contextWindow: 64000, maxTokens: 4096, contextCompaction: true, imageApiBase: '', imageModel: 'gpt-image-1', username: '', timeZone: '', profileSetupDone: true,
  hasCustomApiKey: true, hasGroqKey: false, hasKiloKey: false, hasComposioKey: false, hasImageApiKey: false, hasUnsplashAccessKey: false, hasPixabayApiKey: false,
  hasSarvamKey: true, hasBasetenKey: true, micDevice: '', voiceOutputDevice: '',
  voiceWakeWord: true, voiceStopWord: true, voiceIdleMs: 15000, voiceStandbyMs: 600000,
};
const VOICE_STATUS = {
  state: { sessionId: null, threadId: null, active: false, paused: false, phase: 'idle', caption: '', captionRole: 'assistant', update: '', inputLevel: 0, task: null, jobs: [], error: null, microphone: '', wakeCue: 0, revision: 1 },
  ready: true, issues: [], microphones: [{ name: 'Fixture mic' }], microphone: '', outputs: [{ id: 'o', name: 'Fixture speakers' }], defaultOutput: 'Fixture speakers', outputDevice: '',
};

async function openPreview(t, preferences = PREFERENCES) {
  const vite = await createServer({ configFile: false, root: ROOT, define: { __ANKITA_VERSION__: JSON.stringify('0.0.0-test') }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  const server = http.createServer(async (req, res) => {
    if (req.url !== ROUTE) return vite.middlewares(req, res);
    res.setHeader('content-type', 'text/html');
    res.end(await vite.transformIndexHtml(ROUTE, `<!doctype html><html data-theme="graphite"><body class="desktop-workbench"><div id="root"></div><script type="module">
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {VoiceSettings} from '/src/components/voice/VoiceSettings.tsx';
      import '/src/styles.css'; import '/src/workbench.css'; import '/src/components/voice/voice.css';
      window.savedPatches = [];
      window.ankita = {
        onEvent: () => () => {},
        invoke: async (action, payload) => {
          if (action === 'voiceStatus') return ${JSON.stringify(VOICE_STATUS)};
          if (action === 'saveDesktopSettings') {
            window.savedPatches.push(payload);
            return { preferences: {...${JSON.stringify(preferences)}, ...payload}, settings: {username:'', provider:'custom', model:'alpha', tools:[]}, models: [] };
          }
          return [];
        },
      };
      createRoot(document.getElementById('root')).render(React.createElement(VoiceSettings, { preferences: ${JSON.stringify(preferences)}, onSaved: () => {} }));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vite.close(); });
  const page = await browser.newPage({ viewport: { width: 1100, height: 1000 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  await page.getByRole('heading', { name: 'Hands-free', exact: true }).waitFor();
  return { page, errors };
}

test('the Hands-free panel shows the wake and stop words, their timers, and saves only what changed', async t => {
  const { page, errors } = await openPreview(t);
  const wake = page.getByRole('switch', { name: 'Wake word' });
  const stop = page.getByRole('switch', { name: 'Stop word' });
  assert.equal(await wake.isChecked(), true, 'both default on');
  assert.equal(await stop.isChecked(), true);
  assert.equal(await page.locator('#voice-idle').inputValue(), '15', 'the listening window is shown in seconds');
  assert.equal(await page.locator('#voice-standby').inputValue(), '10', 'mic timeout is shown in minutes');
  assert.match(await page.locator('#voice-handsfree-title').locator('..').innerText(), /Hands-free/);

  if (process.env.ANKITA_UI_CAPTURE_DIR) {
    const { mkdirSync } = await import('node:fs');
    const { join } = await import('node:path');
    mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR, { recursive: true });
    await page.locator('[aria-labelledby="voice-handsfree-title"]').scrollIntoViewIfNeeded();
    await page.locator('[aria-labelledby="voice-handsfree-title"]').screenshot({ path: join(process.env.ANKITA_UI_CAPTURE_DIR, 'voice-handsfree.png') });
  }

  await wake.uncheck();
  assert.equal(await page.locator('#voice-idle').isDisabled(), true, 'the sleep delay only matters with a wake word');
  await page.locator('#voice-idle').evaluate(() => {});
  assert.match(await page.locator('[aria-labelledby="voice-handsfree-title"]').innerText(), /listens freely/, 'the copy explains wake-off behaviour');

  await wake.check();
  await page.locator('#voice-idle').fill('45');
  await page.locator('#voice-standby').fill('5');
  await page.getByRole('button', { name: 'Save voice settings' }).click();
  await page.getByText('Voice settings saved.').waitFor();
  const patches = await page.evaluate(() => window.savedPatches);
  assert.deepEqual(patches, [{ voiceIdleMs: 45000, voiceStandbyMs: 300000 }], 'timers are sent as milliseconds, and only when changed');
  assert.deepEqual(errors, []);
});

test('saved off values render off and an untouched panel writes nothing', async t => {
  const { page, errors } = await openPreview(t, { ...PREFERENCES, voiceWakeWord: false, voiceStopWord: false, voiceIdleMs: 30000, voiceStandbyMs: 120000 });
  assert.equal(await page.getByRole('switch', { name: 'Wake word' }).isChecked(), false);
  assert.equal(await page.getByRole('switch', { name: 'Stop word' }).isChecked(), false);
  assert.equal(await page.locator('#voice-standby').inputValue(), '2');
  assert.equal(await page.getByRole('button', { name: 'Save voice settings' }).isDisabled(), true, 'nothing to save');
  assert.deepEqual(await page.evaluate(() => window.savedPatches), []);
  assert.deepEqual(errors, []);
});
