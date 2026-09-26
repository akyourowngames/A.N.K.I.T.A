import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import http from 'node:http';
import { chromium } from 'playwright';
import { IPC_CONTRACT } from '../desktop/shared/version.mjs';

// The fixture must identify itself as this build when verifying version compatibility.
const APP_VERSION = JSON.parse(fs.readFileSync(new URL('../package.json', import.meta.url), 'utf8')).version;

let builtServer;
let target = process.argv.find(arg => /^https?:\/\//.test(arg)) || 'http://127.0.0.1:5173/';
if (process.argv.includes('--built')) {
  const root = path.resolve('desktop/renderer/dist');
  const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.woff': 'font/woff' };
  builtServer = http.createServer((request, response) => {
    const pathname = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
    const file = path.resolve(root, `.${pathname === '/' ? '/index.html' : pathname}`);
    if (!file.startsWith(`${root}${path.sep}`)) { response.writeHead(403); response.end(); return; }
    try { response.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' }); response.end(fs.readFileSync(file)); }
    catch { response.writeHead(404); response.end(); }
  });
  await new Promise(resolve => builtServer.listen(0, '127.0.0.1', resolve));
  target = `http://127.0.0.1:${builtServer.address().port}/`;
}
const stage = process.argv.includes('--stage');
const sites = process.argv.includes('--sites');
const failed = process.argv.includes('--error');
const themes = process.argv.includes('--themes');
const narrow = process.argv.includes('--narrow');
const stop = process.argv.includes('--stop');
const issues = process.argv.includes('--issues');
const screenshot = path.resolve(`downloaded-images/browser-${stage ? failed ? 'stage-error' : 'stage' : sites ? 'plugin-sites' : 'plugin'}-ui${narrow ? '-narrow' : ''}.png`);
const browser = await chromium.launch({ headless: true });
try {
  let pageImage = null;
  if (stage && !failed) {
    const content = await browser.newPage({ viewport: { width: 1280, height: 800 } });
    await content.setContent('<body style="font:20px Arial;background:white;color:#292929;margin:0;padding:100px 120px"><h1 style="font-size:58px">Example Domain</h1><p>This domain is for use in illustrative examples in documents.</p><a href="#">Learn more</a></body>');
    pageImage = `data:image/jpeg;base64,${(await content.screenshot({ type: 'jpeg', quality: 65 })).toString('base64')}`;
    await content.close();
  }
  const page = await browser.newPage({ viewport: { width: narrow ? 900 : 1420, height: narrow ? 800 : 900 }, deviceScaleFactor: 1 });
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.addInitScript(({ contract, version, stage, pageImage, failed }) => {
    const callbacks = new Set();
    window.__emitBrowserTest = event => { for (const callback of callbacks) callback(event); };
    const browserView = failed ? { mode: 'local', status: 'error', step: 'Chrome is not connected. Open browser settings to start the connection.', tabs: [], screenshot: null } : { mode: 'isolated', status: 'working', step: 'Reading results', tabs: [{ id: '1', url: 'https://example.com/', title: 'Example Domain', active: true }, { id: '2', url: 'https://example.org/', title: 'Example Org', active: false }], screenshot: pageImage };
    window.__browserTestView = browserView;
    window.__browserViewCalls = 0;
    window.__browserViewPending = 0;
    window.__browserViewPeakPending = 0;
    const preferences = { provider: 'kilo', appearance: 'graphite', profileSetupDone: true, hasComposioKey: true };
    const settings = { username: 'User', provider: 'Kilo', model: '', tools: [] };
    const browserOverview = {
      isolated: { id: 'ankita-playwright', name: 'Playwright Browser', description: 'A private Chromium for Ankita', mode: 'isolated', enabled: true, ready: true, reason: '', headless: true, allowedSites: ['example.com'], blockedSites: ['bad.example.com'] },
      local: { id: 'ankita-chrome', name: 'Chrome local', description: 'Browse with your Chrome session', mode: 'local', enabled: false, ready: false, reason: 'Start Chrome DevTools connection', connection: 'active', port: 9222, allowedSites: [], blockedSites: [] },
    };
    window.ankita = {
      invoke: async (action, payload) => {
        if (action === 'initialize') return { teammates: stage ? [{ id: 'chief', name: 'Ankita', color: '#c8b187', emoji: '✦', persona: 'Your teammate', projectId: null, model: null, createdAt: '', updatedAt: '', lastMessage: '', lastMessageAt: null }] : [], models: [], settings, preferences, version, contract, chrome: 'native' };
        if (action === 'listProjects') return [];
        if (action === 'cancel') { window.__lastCancel = payload; window.__emitBrowserTest({ type: 'turn-end', threadId: payload.id, turnId: 'stop-test' }); return true; }
        if (action === 'browserSessionStop') { window.__stageStopped = true; return true; }
        if (action === 'loadThread') return [{ id: 'hello', role: 'user', content: 'Open example.com and read it.' }];
        if (action === 'browserPluginsOverview') return browserOverview;
        if (action === 'pluginsOverview') return { mode: 'direct', live: true, services: { gmail: { connected: true, pending: false, accounts: [], status: 'ACTIVE' } } };
        if (action === 'pluginsCatalog') return { cards: [['gmail', 'Gmail'], ['google_drive', 'Google Drive'], ['github', 'GitHub'], ['slack', 'Slack']].map(([slug, label]) => ({ slug, label, blurb: 'Connect and use this app with Ankita', noAuth: false })), nextCursor: null };
        if (action === 'saveDesktopSettings') { Object.assign(preferences, payload); return { preferences: { ...preferences }, settings, models: [] }; }
        if (action === 'getChannels') return { telegram: { enabled: false, allowedChatIds: [], voiceReply: false } };
        if (action === 'browserSessionView') {
          window.__browserViewCalls++;
          window.__browserViewPending++;
          window.__browserViewPeakPending = Math.max(window.__browserViewPeakPending, window.__browserViewPending);
          await new Promise(resolve => setTimeout(resolve, 25));
          window.__browserViewPending--;
          return stage ? browserView : { mode: null, status: 'idle', tabs: [], screenshot: null, step: '' };
        }
        return null;
      },
      onEvent: callback => { callbacks.add(callback); return () => callbacks.delete(callback); },
      onMenuCommand: () => () => {},
      onUpdateEvent: () => () => {},
      updateAction: async () => false,
      appAction: async () => null,
      windowAction: async () => true,
      openExternal: async () => {},
    };
  }, { contract: IPC_CONTRACT, version: APP_VERSION, stage, pageImage, failed });
  await page.goto(target);
  if (stage) {
    await page.getByRole('heading', { name: 'Ankita' }).first().waitFor();
    await page.evaluate(() => window.__emitBrowserTest({ type: 'browser-state', threadId: 'chief', state: { ...window.__browserTestView, status: 'working' } }));
    await page.getByRole('complementary', { name: 'Live browser' }).waitFor();
    await page.waitForFunction(() => JSON.parse(localStorage.getItem('ankita.ui')).sidebarOpen === false);
    await page.waitForTimeout(1400);
    const framePolling = await page.evaluate(() => ({ calls: window.__browserViewCalls, maxPending: window.__browserViewPeakPending }));
    assert.ok(framePolling.calls >= (failed ? 1 : 10), 'The visible preview refreshes frequently');
    assert.equal(framePolling.maxPending, 1, 'Preview requests never overlap');
    if (failed) assert.equal(await page.getByRole('button', { name: 'Take control', exact: true }).isDisabled(), true);
    if (issues) {
      const pane = page.getByRole('complementary', { name: 'Live browser' });
      const leaks = 'PRIVATE_PAGE_CODE <html> [ref=99-0-1] Call log: \u001b[2m';
      for (const message of [`Stale ref; Fresh snapshot:\n${leaks}`, `page.goto: net::ERR_HTTP2_PROTOCOL_ERROR\n${leaks}`, `locator.click: Timeout exceeded\n${leaks}`]) {
        await page.evaluate(step => {
          Object.assign(window.__browserTestView, { status: 'error', step, screenshot: null });
          window.__emitBrowserTest({ type: 'browser-state', threadId: 'chief', state: { ...window.__browserTestView } });
        }, message);
        await pane.getByRole('alert').waitFor();
        assert.ok(await pane.getByRole('img', { name: /Live browser page/ }).count(), 'recoverable error keeps the last frame');
        assert.equal(await pane.getByRole('button', { name: 'Take control', exact: true }).isEnabled(), true);
        assert.ok(!(await pane.innerText()).includes('PRIVATE_PAGE_CODE'), 'page code, refs and raw logs never enter the sidebar');
        assert.ok(!(await pane.innerText()).includes('Connection required'));
        assert.ok(!(await pane.innerText()).includes('Browser unavailable'));
      }
      console.log('BROWSER_SIDEBAR_ERROR_OK: stale refs, navigation and action errors keep pixels/control; no page code or call logs');
    }
  } else {
    await page.getByRole('button', { name: /plugins/i }).first().click();
    await page.getByRole('heading', { name: 'By Ankita team' }).waitFor();
    const row = await page.locator('.browser-plugins-section .plugin-row').first().boundingBox();
    assert.equal(row.height, 71, 'Browser entries match integration row height');
    if (sites) await page.getByRole('button', { name: 'Configure Playwright Browser' }).click();
  }
  fs.mkdirSync(path.dirname(screenshot), { recursive: true });
  await page.screenshot({ path: screenshot, fullPage: true });
  if (themes) {
    if (sites) await page.getByRole('button', { name: 'Close browser settings' }).click();
    const colors = [];
    for (const theme of ['mono', 'slate', 'graphite']) {
      if (stage) await page.keyboard.press('Control+,');
      else await page.getByRole('button', { name: /^(Settings|Open settings)$/ }).last().click();
      await page.getByRole('button', { name: 'Appearance', exact: true }).click();
      await page.getByRole('button', { name: new RegExp(`^${theme[0].toUpperCase()}${theme.slice(1)}`) }).click();
      await page.getByRole('button', { name: 'Apply appearance' }).click();
      await page.waitForFunction(value => document.documentElement.dataset.theme === value, theme);
      await page.getByRole('button', { name: 'Close settings' }).click();
      if (sites) await page.getByRole('button', { name: 'Configure Playwright Browser' }).click();
      const palette = await page.evaluate(({ isStage, drawer }) => {
        const probe = document.createElement('span');
        document.body.append(probe);
        const resolved = token => { probe.style.color = `var(${token})`; return getComputedStyle(probe).color; };
        const checks = isStage ? [['.browser-stage', 'backgroundColor', '--canvas'], ['.browser-stage-address', 'backgroundColor', '--surface'], ['.browser-stage-footer button', 'color', document.querySelector('.browser-stage-footer button').disabled ? '--text-dim' : '--gold-light']] : [['.plugins-pane', 'backgroundColor', '--canvas'], ['.browser-mark', 'color', '--gold-light'], ['.plugins-header-settings', 'backgroundColor', '--surface'], ...(drawer ? [['.plugins-drawer', 'backgroundColor', '--surface'], ['.skill-toggle.on span', 'backgroundColor', '--gold-light']] : [])];
        const matches = checks.map(([selector, property, token]) => getComputedStyle(document.querySelector(selector))[property] === resolved(token));
        probe.remove();
        return { background: getComputedStyle(document.querySelector(isStage ? '.browser-stage' : '.plugins-pane')).backgroundColor, matches };
      }, { isStage: stage, drawer: sites });
      assert.ok(palette.matches.every(Boolean), `${theme} controls resolve from global theme tokens`);
      colors.push(palette.background);
      await page.screenshot({ path: screenshot.replace('.png', `-${theme}.png`), fullPage: true });
      if (sites) await page.getByRole('button', { name: 'Close browser settings' }).click();
    }
    assert.equal(new Set(colors).size, 3, 'Appearance settings update each surface without remounting');
  }
  assert.deepEqual(pageErrors, [], 'UI has no runtime errors');
  if (narrow) {
    const fits = await page.evaluate(isStage => {
      const pane = document.querySelector(isStage ? '.browser-stage' : '.plugins-pane');
      const rect = pane.getBoundingClientRect();
      return rect.right <= innerWidth + 1 && rect.left >= 0 && pane.scrollWidth <= pane.clientWidth;
    }, stage);
    assert.equal(fits, true, 'Pane fits a smaller desktop window');
  }
  if (stage && stop) {
    await page.evaluate(() => window.__emitBrowserTest({ type: 'turn-start', threadId: 'chief', turnId: 'stop-test', model: 'demo', text: 'Continue' }));
    await page.getByRole('button', { name: 'Stop response', exact: true }).click();
    await page.getByRole('button', { name: 'Send message', exact: true }).waitFor();
    assert.equal(await page.evaluate(() => window.__lastCancel.id), 'chief', 'Composer Stop cancels the selected thread');
    await page.getByRole('button', { name: 'Stop', exact: true }).click();
    await page.waitForFunction(() => window.__stageStopped === true && !document.querySelector('.app-shell').classList.contains('browser-visible'));
  }
  console.log(screenshot);
} finally { await browser.close(); if (builtServer) await new Promise(resolve => builtServer.close(resolve)); }
