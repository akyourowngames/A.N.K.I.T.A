import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/providers-ui'; // Local preview with a stubbed desktop bridge; no real process or provider.
const TEAMMATE = { id: 'fixture', name: 'Fixture', persona: 'Your teammate', color: 'sage', projectId: null };
const PREFERENCES = {
  secretScrubbing: true, secretWarningSeen: true, provider: 'chatgpt-browser', model: '', customApiBase: '', appearance: 'graphite',
  contextWindow: 0, maxTokens: 0, imageApiBase: '', imageModel: 'gpt-image-1', username: '', timeZone: '', profileSetupDone: true,
  hasCustomApiKey: false, hasGroqKey: false, hasKiloKey: false, hasComposioKey: false, hasImageApiKey: false, hasUnsplashAccessKey: false, hasPixabayApiKey: false,
};

test('providers keep one calm column, grouped actions and a single save bar', async t => {
  // This preview is static: no HMR client, so a loaded CI runner cannot surface
  // Vite's "WebSocket closed without opened" as an unhandled page error.
  const vite = await createServer({ configFile: false, root: ROOT, define: { __ANKITA_VERSION__: JSON.stringify('0.0.0-test') }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  const server = http.createServer(async (req, res) => {
    if (req.url !== ROUTE) return vite.middlewares(req, res);
    res.setHeader('content-type', 'text/html');
    res.end(await vite.transformIndexHtml(ROUTE, `<!doctype html><html data-theme="graphite"><body class="desktop-workbench"><div id="root"></div><script type="module">
      import React from 'react'; import {createRoot} from 'react-dom/client';
      import {SettingsDialog} from '/src/components/SettingsDialog.tsx';
      import '/src/styles.css'; import '/src/workbench.css';
      const listeners = new Set();
      let connection = {status:'setup-required', mode:'chrome', threadId:'fixture', selectedModel:null, nativeTools:[]};
      window.showConnection = next => { connection = {...connection, ...next}; listeners.forEach(fn => fn({type:'chatgpt-connection-changed', state:structuredClone(connection)})); };
      window.ankita = {
        onEvent: fn => { listeners.add(fn); return () => listeners.delete(fn); },
        invoke: async (action, payload) => {
          if (action === 'chatgptConnectionOverview') return structuredClone(connection);
          if (action === 'chatgptNativePreferences') return {tunnels:{}, savedKeys:[]};
          if (action === 'chatgptConnectionStart') { connection = {...connection, ...payload, status:'ready'}; return {state:structuredClone(connection)}; }
          if (action === 'saveDesktopSettings') return {preferences:{...payload}, settings:{username:'', provider:'chatgpt-browser', model:'', tools:[]}, models:[]};
          return [];
        },
      };
      createRoot(document.getElementById('root')).render(React.createElement(SettingsDialog, {
        tab:'providers', onTab:()=>{}, onClose:()=>{}, preferences:${JSON.stringify(PREFERENCES)}, models:[], teammates:[${JSON.stringify(TEAMMATE)}],
        jobs:[], version:'0.0.0-test', onSaved:()=>{}, onOpenJobs:()=>{}, selectedThreadId:'fixture',
      }));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vite.close(); });
  const page = await browser.newPage({ viewport: { width: 1200, height: 820 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  await page.getByRole('heading', { name: 'Providers', exact: true }).waitFor();
  // The dialog enters with a 220ms scale animation; measuring before it settles
  // reports scaled sizes (36px buttons read as 35.46) on a slower runner.
  await page.locator('.settings-window').evaluate(element => Promise.all(element.getAnimations().map(animation => animation.finished)));

  const cards = page.locator('.settings-provider-card');
  assert.equal(await cards.count(), 6);
  const boxes = await cards.evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().toJSON()));
  assert.equal(new Set(boxes.map(box => Math.round(box.x))).size, 1, 'provider cards share one left edge');
  assert.ok(boxes.every((box, index) => index === 0 || box.y > boxes[index - 1].y), 'provider cards stack instead of splitting into ragged columns');
  assert.ok(boxes.every(box => box.width > 400), 'provider cards use the reading column');

  const choices = page.getByRole('group', { name: 'Where ChatGPT runs' });
  await choices.waitFor();
  const choiceBoxes = await choices.getByRole('button').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().toJSON()));
  assert.equal(Math.round(choiceBoxes[0].y), Math.round(choiceBoxes[1].y), 'browser choices sit side by side');
  assert.ok((await page.getByLabel('Teammate', { exact: true }).boundingBox()).height >= 36, 'selects share the field height');
  const actions = page.locator('.chatgpt-actions').getByRole('button');
  const actionBoxes = await actions.evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().toJSON()));
  assert.equal(Math.round(actionBoxes[0].y), Math.round(actionBoxes[1].y), 'setup actions stay on one row');
  assert.ok(actionBoxes.every(box => box.height >= 36), `all setup actions keep a comfortable target: ${actionBoxes.map(box => box.height).join(', ')}`);

  const sessionButtons = page.locator('.chatgpt-session-actions').getByRole('button');
  assert.equal(await sessionButtons.count(), 2, 'session controls stay grouped');
  const saveBar = page.locator('.settings-savebar');
  assert.equal(await saveBar.getByRole('button', { name: 'Save provider settings' }).count(), 1);
  assert.equal(await page.evaluate(() => document.querySelector('.settings-scroll').scrollWidth <= document.querySelector('.settings-scroll').clientWidth), true, 'no horizontal overflow');

  if (process.env.ANKITA_UI_CAPTURE_DIR) {
    const capture = path.join(process.env.ANKITA_UI_CAPTURE_DIR, 'providers-setup.png');
    const connected = path.join(process.env.ANKITA_UI_CAPTURE_DIR, 'providers-connected.png');
    const savebar = path.join(process.env.ANKITA_UI_CAPTURE_DIR, 'providers-savebar.png');
    const card = path.join(process.env.ANKITA_UI_CAPTURE_DIR, 'chatgpt-connected-card.png');
    fs.mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR, { recursive: true });
    await page.locator('.chatgpt-connection').scrollIntoViewIfNeeded();
    await page.screenshot({ path: capture });
    await page.locator('.settings-scroll').evaluate(element => element.scrollTo({ top: element.scrollHeight }));
    await page.screenshot({ path: savebar });
    await page.evaluate(() => window.showConnection({ status: 'ready', selectedModel: 'Current ChatGPT model', workspacePath: 'C:\\Users\\fixture\\AppData\\ankita\\chatgpt-workspace' }));
    await page.locator('.chatgpt-connected-summary').waitFor();
    await page.locator('.chatgpt-connection').scrollIntoViewIfNeeded();
    await page.screenshot({ path: connected });
    await page.locator('.chatgpt-connection').screenshot({ path: card });
  }
  assert.deepEqual(errors, []);
});
