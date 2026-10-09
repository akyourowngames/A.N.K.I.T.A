import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { fileURLToPath } from 'node:url';
import { createServer as createViteServer, transformWithEsbuild } from 'vite';
import { chromium } from 'playwright';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-desktop-skill-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const { DesktopEngine } = await import('../../desktop/electron/engine.mjs');
const { BrowserSessionManager } = await import('../../tools/browser/session.mjs');
const { BrowserPluginStore } = await import('../../src/integrations/browser-plugins.mjs');
const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
const { loadSkills } = await import('../../src/core/skills.mjs');
const MODEL = 'desktop-fixture-model'; // Test-only local HTTP provider, no remote model or credentials.
const call = (id, name, args) => ({ id, type: 'function', function: { name, arguments: JSON.stringify(args) } });

test.after(async () => {
  assert.equal(fs.realpathSync(path.dirname(root)), fs.realpathSync(os.tmpdir()));
  await fs.promises.rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 });
});

test('desktop sends the whole automatic guide and reports its actual request inclusion', async t => {
  const requests = [], events = [];
  const server = http.createServer((req, res) => {
    if (req.url === '/form') { res.setHeader('content-type', 'text/html'); res.end('<title>Skill fixture</title><label>Test name <input></label>'); return; }
    let text = '';
    req.on('data', chunk => { text += chunk; });
    req.on('end', () => {
      const body = JSON.parse(text); requests.push(body);
      const step = requests.length;
      let next;
      if (step === 1) next = call('discover', 'find_tools', { query: 'browser' });
      if (step === 2) next = call('open', 'browser', { action: 'open', url: `http://127.0.0.1:${server.address().port}/form` });
      if (step === 3) {
        const observation = body.messages.findLast(message => message.role === 'tool').content;
        const ref = observation.split('\n').find(line => line.includes('[ref=') && line.includes('Test name')).match(/\[ref=([^\]]+)\]/)[1];
        next = call('fill', 'browser', { action: 'fill_form', fields: [{ ref, text: 'Synthetic tester' }] });
      }
      res.setHeader('content-type', 'application/json');
      res.end(JSON.stringify({ choices: [{ message: next ? { content: null, tool_calls: [next] } : { content: 'Field read back.' } }] }));
    });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const directory = path.join(root, 'enabled'); fs.mkdirSync(directory);
  const client = { baseUrl: `http://127.0.0.1:${server.address().port}/model`, headers: () => ({ 'content-type': 'application/json' }) };
  const engine = new DesktopEngine({
    teammateFile: path.join(directory, 'teammates.json'), sessionsDir: path.join(directory, 'sessions'),
    settingsFile: path.join(directory, 'settings.json'), channelsFile: path.join(directory, 'channels.json'),
    projectsFile: path.join(directory, 'projects.json'), browserFile: path.join(directory, 'browser.json'),
    credentialFile: path.join(directory, 'credentials.json'), envPath: path.join(directory, 'config.env'),
    config: { provider: 'fixture', model: MODEL, tools: true, autoApprove: true, allowPrivateHosts: true, contextWindow: 131072, memoryConsolidation: false, memoryRecallChars: 0 },
    bootstrap: async () => ({ client, tool: null, models: [{ id: MODEL, tools: true }], model: MODEL, provider: { name: 'fixture' } }),
    mcp: { reconcile: async () => {}, ensureComposio: async () => {}, summaries: () => [], alwaysOnIds: () => [], specs: () => [], has: () => false, closeAll: async () => {} },
    emit: event => events.push(event),
  });
  await engine.init();
  const store = new BrowserPluginStore(path.join(directory, 'browser.json')).load(); store.setEnabled('isolated', true);
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile') });
  engine.browserManager = new BrowserSessionManager({ store, isolatedFactory: () => adapter });
  t.after(async () => { await engine.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const id = engine.listTeammates()[0].id;
  engine.agentFor(id).toolContext.settings = { headless: true };
  await engine.send(id, 'Open the test form and fill Test name with Synthetic tester.');
  await engine.waitForTurn(id);
  const skill = loadSkills().find(item => item.name === 'browser-use');
  assert.equal(requests.length, 4, 'no extra skill or router round');
  assert.ok(requests.slice(1).every(request => request.messages[0].content.includes(skill.body)), 'actual desktop HTTP requests carry the whole guide');
  assert.equal(await adapter.page.locator('input').inputValue(), 'Synthetic tester');
  console.log('DESKTOP_SKILL_DELIVERY_LIVE modelRequests=4 guideRequests=3 realFieldReadBack=true extraSkillCalls=0');
  const receipt = events.filter(event => event.type === 'skills-loaded');
  assert.equal(receipt.length, 1, 'desktop must expose the actual guide inclusion, once per turn');
  assert.deepEqual(receipt[0].names, ['browser-use']);
  assert.equal(receipt[0].threadId, id);
  const guideRequestEvent = events.findIndex(event => event.type === 'skills-loaded');
  assert.ok(guideRequestEvent < events.findIndex(event => event.type === 'tool-call' && event.name === 'browser'));
  assert.ok(!JSON.stringify(receipt).includes(skill.body), 'UI receipts contain names, never duplicated prompt bodies');

  // Render the shipped reducer and ChatPane using this actual engine receipt;
  // only Electron's capture inbox is stubbed. No user desktop/profile is opened.
  const rendererRoot = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
  const vite = await createViteServer({ configFile: false, root: rendererRoot, server: { middlewareMode: true, fs: { allow: [path.dirname(path.dirname(rendererRoot))] } }, appType: 'custom' });
  const ui = http.createServer(async (req, res) => {
    if (req.url !== '/skill-ui') return vite.middlewares(req, res);
    const html = `<!doctype html><html><body><div id="root"></div><script type="module">
      import React from 'react'; import { createRoot } from 'react-dom/client';
      import { ChatPane } from '/src/components/ChatPane.tsx';
      import { initialState, reducer } from '/src/state/store.ts';
      import '/src/styles.css'; import '/src/workbench.css';
      window.ankita = { invoke: async () => [], onEvent: () => () => {} };
      const events = ${JSON.stringify(events.filter(event => ['turn-start', 'skills-loaded', 'turn-end'].includes(event.type)))};
      let state = events.reduce((state, event) => reducer(state, { type: 'event', event }), initialState);
      const root = createRoot(document.getElementById('root'));
      const callbacks = Object.fromEntries(['onToggleSidebar','onToggleReview','onOpenBrowser','onProject','onOpenProjects','onSend','onStop','onModel','onEdit','onCreate','onClear','onDelete','onEditJob','onWatchJob'].map(name => [name, () => {}]));
      const render = () => root.render(React.createElement(ChatPane, { ...callbacks, teammate: ${JSON.stringify(engine.listTeammates()[0])}, messages: [], running: false, models: [], projects: [], jobs: [], defaultModel: '', chrome: 'native', sidebarOpen: true, reviewOpen: false, loadedSkills: state.loadedSkills[${JSON.stringify(id)}] }));
      window.nextTurn = () => { state = reducer(state, { type: 'event', event: { type: 'turn-start', threadId: ${JSON.stringify(id)}, turnId: 'next-ui-turn', text: 'Hello' } }); render(); };
      render();
    </script></body></html>`;
    try { res.setHeader('content-type', 'text/html'); res.end(await vite.transformIndexHtml('/skill-ui', html)); }
    catch (error) { res.statusCode = 500; res.end(error.message); }
  });
  await new Promise(resolve => ui.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true });
  t.after(async () => { await browser.close(); await vite.close(); ui.closeAllConnections(); await new Promise(resolve => ui.close(resolve)); });
  const page = await browser.newPage(), pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.goto(`http://127.0.0.1:${ui.address().port}/skill-ui`);
  const status = page.getByRole('status').filter({ hasText: 'Instructions loaded: browser-use' });
  await status.waitFor({ state: 'visible' });
  assert.equal(await status.textContent(), 'Instructions loaded: browser-use');
  await page.evaluate(() => window.nextTurn());
  await status.waitFor({ state: 'hidden' });
  assert.deepEqual(pageErrors, []);
  console.log('DESKTOP_SKILL_RENDERER_LIVE actualEngineReceipt=true visibleHeader=true clearsOnNextTurn=true pageErrors=0');
});

test('actual desktop reducer scopes guide receipts to the teammate and clears stale status', async () => {
  const source = fs.readFileSync(new URL('../../desktop/renderer/src/state/store.ts', import.meta.url), 'utf8');
  const compiled = await transformWithEsbuild(source, 'store.ts', { loader: 'ts', format: 'esm', target: 'es2022' });
  const { initialState, reducer } = await import(`data:text/javascript;base64,${Buffer.from(compiled.code).toString('base64')}`);
  let state = initialState;
  const emit = event => { state = reducer(state, { type: 'event', event }); };
  emit({ type: 'turn-start', threadId: 'one', turnId: 'first', text: 'Browse' });
  assert.deepEqual(state.loadedSkills.one, []);
  emit({ type: 'skills-loaded', threadId: 'one', turnId: 'first', names: ['browser-use'] });
  emit({ type: 'skills-loaded', threadId: 'one', turnId: 'first', names: ['browser-use'] });
  assert.deepEqual(state.loadedSkills.one, ['browser-use']); assert.equal(state.loadedSkills.two, undefined);
  emit({ type: 'turn-end', threadId: 'one', turnId: 'first' });
  assert.deepEqual(state.loadedSkills.one, ['browser-use']);
  emit({ type: 'turn-start', threadId: 'one', turnId: 'second', text: 'Hello' });
  assert.deepEqual(state.loadedSkills.one, [], 'a new turn is not falsely labelled as already loaded');
  emit({ type: 'skills-loaded', threadId: 'one', turnId: 'second', names: ['browser-use'] });
  emit({ type: 'thread-cleared', threadId: 'one' }); assert.deepEqual(state.loadedSkills.one, []);
});
