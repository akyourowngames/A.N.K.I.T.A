import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/compaction-ui'; // Local preview with a stubbed desktop bridge; no real process or provider.
const PREFERENCES = {
  secretScrubbing: true, secretWarningSeen: true, provider: 'custom', model: 'alpha', customApiBase: 'http://localhost:11434/v1', appearance: 'graphite',
  contextWindow: 64000, maxTokens: 4096, contextCompaction: false, imageApiBase: '', imageModel: 'gpt-image-1', username: '', timeZone: '', profileSetupDone: true,
  hasCustomApiKey: true, hasGroqKey: false, hasKiloKey: false, hasComposioKey: false, hasImageApiKey: false, hasUnsplashAccessKey: false, hasPixabayApiKey: false,
};
const MODEL = { id: 'alpha', name: 'Alpha', vendor: 'Fixture', context: 64000, tools: true };

async function openPreview(t, preferences = PREFERENCES) {
  const vite = await createServer({ configFile: false, root: ROOT, define: { __ANKITA_VERSION__: JSON.stringify('0.0.0-test') }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  const server = http.createServer(async (req, res) => {
    if (req.url !== ROUTE) return vite.middlewares(req, res);
    res.setHeader('content-type', 'text/html');
    res.end(await vite.transformIndexHtml(ROUTE, `<!doctype html><html data-theme="graphite"><body class="desktop-workbench"><div id="root"></div><script type="module">
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {SettingsDialog} from '/src/components/SettingsDialog.tsx';
      import '/src/styles.css'; import '/src/workbench.css';
      window.savedPatches = [];
      window.ankita = {
        onEvent: () => () => {},
        invoke: async (action, payload) => {
          if (action === 'saveDesktopSettings') {
            window.savedPatches.push(payload);
            return { preferences: {...${JSON.stringify(preferences)}, ...payload}, settings: {username:'', provider:'custom', model:'alpha', tools:[]}, models: [${JSON.stringify(MODEL)}] };
          }
          return [];
        },
      };
      createRoot(document.getElementById('root')).render(React.createElement(SettingsDialog, {
        tab:'model', onTab:()=>{}, onClose:()=>{}, preferences:${JSON.stringify(preferences)}, models:[${JSON.stringify(MODEL)}], teammates:[],
        jobs:[], version:'0.0.0-test', onSaved:()=>{}, onOpenJobs:()=>{}, selectedThreadId:null,
      }));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vite.close(); });
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  await page.getByRole('heading', { name: 'Long conversations', exact: true }).waitFor();
  await page.locator('.settings-window').evaluate(element => Promise.all(element.getAnimations().map(animation => animation.finished)));
  return { page, errors };
}

test('the compaction switch is off by default, explains itself, and saves only the change', async t => {
  const { page, errors } = await openPreview(t);
  const toggle = page.getByRole('switch', { name: 'Summarize older messages' });
  assert.equal(await toggle.isChecked(), false, 'opt-in: off unless the user turns it on');
  const previous = page.locator('.settings-compaction-preview');
  assert.equal(await previous.evaluate(node => node.classList.contains('is-on')), false, 'the preview reflects the off state');
  assert.ok(await page.locator('.settings-compaction-chip').count() === 3, 'the old -> recap -> recent diagram is present');

  await toggle.click();
  assert.equal(await toggle.isChecked(), true);
  assert.equal(await page.locator('.settings-compaction-preview').evaluate(node => node.classList.contains('is-on')), true, 'the preview lights up with the switch');
  assert.equal(await page.locator('.settings-model-compaction .settings-value-tag').innerText(), 'On');

  if (process.env.ANKITA_UI_CAPTURE_DIR) {
    const { mkdirSync } = await import('node:fs');
    const { join } = await import('node:path');
    mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR, { recursive: true });
    await page.locator('.settings-model-compaction').scrollIntoViewIfNeeded();
    await page.locator('.settings-model-compaction').screenshot({ path: join(process.env.ANKITA_UI_CAPTURE_DIR, 'compaction-on.png') });
  }
  await page.getByRole('button', { name: 'Save model settings' }).click();
  await page.getByText('Changes saved.').waitFor();
  const patches = await page.evaluate(() => window.savedPatches);
  assert.deepEqual(patches, [{ contextCompaction: true }], 'only the changed flag is sent, so untouched numbers stay as they are');
  assert.deepEqual(errors, []);
});

test('an on state from the backend renders as on and saving an unchanged form sends nothing', async t => {
  const { page, errors } = await openPreview(t, { ...PREFERENCES, contextCompaction: true });
  const toggle = page.getByRole('switch', { name: 'Summarize older messages' });
  assert.equal(await toggle.isChecked(), true, 'the saved choice is reflected on load');
  assert.equal(await page.locator('.settings-compaction-preview').evaluate(node => node.classList.contains('is-on')), true);
  assert.equal(await page.locator('.settings-model-compaction .settings-value-tag').innerText(), 'On');
  await page.getByRole('button', { name: 'Save model settings' }).click();
  await page.getByText('Everything is up to date.').waitFor();
  assert.deepEqual(await page.evaluate(() => window.savedPatches), [], 'an untouched form does not write settings');
  assert.deepEqual(errors, []);
});
