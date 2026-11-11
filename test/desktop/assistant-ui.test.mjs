import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';
import { chromium } from 'playwright';
import { DesktopAssistant } from '../../desktop/electron/assistant.mjs';
import { runAssistantAction } from '../../desktop/electron/assistant-actions.mjs';
import { ASSISTANT_ACTIONS } from '../../desktop/shared/assistant.mjs';
import { IPC_CONTRACT } from '../../desktop/shared/version.mjs';
import { ProjectStore, projectUserSource } from '../../src/memory/projects.mjs';
import { DesktopEngine } from '../../desktop/electron/engine.mjs';
import { projectSummary } from '../../desktop/electron/projects.mjs';

const ROOT = fileURLToPath(new URL('../../desktop/renderer/', import.meta.url));
const ROUTE = '/assistant-preview'; // Local real renderer, dispatcher and task/profile storage, no external services.
const APP_ROUTE = '/assistant-app-preview'; // Separate Vite module identity for full-App acceptance.
const WAIT_MS = 5000; // Milliseconds for bounded browser assertions.
const APP_LOAD_MS = 15000; // Milliseconds: full App module graph loads separately from individual control readiness.
const TEST_VERSION = '0.0.0-test'; // Complete App compatibility handshake for this isolated renderer.

test('Today controls continue a saved request and edit/forget the real memory profile', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'assistant-ui-')), listeners = [], requests = [], scheduled = [];
  const engine = { desktopSettings: { file: path.join(directory, 'settings.json') }, teammates: { file: path.join(directory, 'teammates.json'), find: id => id === 'owner' ? { id } : null },
    secretHistory: { clean: value => value }, config: {}, listTeammates: () => [{ id: 'owner' }],
    schedule: () => ({ list: () => [], pendingDeliveries: () => [], add: async job => { scheduled.push(job); return { ...job, id: 'draft' }; } }), agentFor: () => ({ projectId: null, workspacePath: null }),
    emit: event => listeners.forEach(callback => callback(event)), send: async (...args) => { requests.push(args); return { turnId: 'continued' }; } };
  engine.assistant = () => service;
  engine.projectsFile = path.join(directory, 'projects.json');
  engine.listProjects = () => new ProjectStore(engine.projectsFile).load().projects.map(projectSummary);
  engine.refreshProjectAgents = () => {};
  engine.editProjectRecord = payload => DesktopEngine.prototype.editProjectRecord.call(engine, payload);
  engine.completeProjectTodo = (id, ref) => DesktopEngine.prototype.completeProjectTodo.call(engine, id, ref);
  const projectStore = new ProjectStore(engine.projectsFile).load(), project = projectStore.add({ name: 'A shared project' });
  projectStore.addDecision(project.id, 'The old project decision.', projectUserSource());
  projectStore.addTodo(project.id, 'Finish the shared draft.');
  const service = new DesktopAssistant(engine);
  const task = service.tasks.create({ ownerId: 'owner', goal: 'Finish my school plan.' });
  service.tasks.start(task.id); service.tasks.finish(task.id, { status: 'interrupted' });
  const successful = service.tasks.create({ ownerId: 'owner', goal: 'Summarize the selected article.' });
  service.tasks.start(successful.id); service.tasks.finish(successful.id, { reply: 'The article summary is ready.' });
  service.memorySave({ text: 'I prefer short answers.', kind: 'preference', always: true });
  const vite = await createServer({ configFile: false, root: ROOT, define: { __ANKITA_VERSION__: JSON.stringify(TEST_VERSION) }, server: { middlewareMode: true, hmr: false }, appType: 'custom' });
  const server = http.createServer(async (req, res) => {
    if (![ROUTE, APP_ROUTE].includes(req.url)) return vite.middlewares(req, res);
    const full = req.url === APP_ROUTE;
    res.setHeader('content-type', 'text/html');
    res.end(await vite.transformIndexHtml(req.url, `<!doctype html><html data-theme="graphite"><body><div id="root"></div><script type="module">
      import React from 'react'; import { createRoot } from 'react-dom/client';
      import { TodayPage } from '/src/components/TodayPage.tsx'; import App from '/src/App.tsx'; import '/src/styles.css'; import '/src/workbench.css';
      window.assistantListeners=[]; window.ankita={invoke:(...args)=>window.invokeAssistant(...args),redact:async text=>text,onEvent:cb=>{window.assistantListeners.push(cb);return()=>{};},onMenuCommand:()=>()=>{},onUpdateEvent:()=>()=>{},windowAction:async()=>true,openExternal:async()=>{}};
      createRoot(document.getElementById('root')).render(React.createElement(${full ? 'App' : 'TodayPage'},{teammates:[{id:'owner',name:'Ankita'}],chrome:'native',sidebarOpen:true,onToggleSidebar:()=>{},onOpenThread:id=>window.openedThread=id,onOpenJob:()=>{},onAsk:()=>{},onVoice:()=>{}}));
    </script></body></html>`));
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({ headless: true }), page = await browser.newPage({ viewport: { width: 1100, height: 850 } });
  t.after(async () => { await browser.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); await vite.close(); fs.rmSync(directory, { recursive: true, force: true }); });
  const errors = []; page.on('pageerror', error => errors.push(error.message)); page.setDefaultTimeout(WAIT_MS);
  page.setDefaultNavigationTimeout(APP_LOAD_MS);
  await page.exposeFunction('invokeAssistant', (action, payload) => {
    if (Object.values(ASSISTANT_ACTIONS).includes(action)) return runAssistantAction({ engine, action, payload });
    if (action === 'initialize') return { teammates: [{ id: 'owner', name: 'Ankita', persona: '', color: '', projectId: null, model: null, lastMessage: '', emoji: '' }],
      settings: { provider: 'custom', model: 'fixture', tools: [], username: 'User' }, preferences: { profileSetupDone: true, provider: 'custom', appearance: 'graphite' }, models: [], chrome: 'native', contract: IPC_CONTRACT, version: TEST_VERSION, jobs: [] };
    if (action === 'browserSessionView') return null;
    if (action === 'listProjects') return engine.listProjects();
    return [];
  });
  await page.goto(`http://127.0.0.1:${server.address().port}${ROUTE}`);
  await page.getByText(task.goal, { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Continue request', exact: true }).click();
  assert.equal(requests[0][3].assistantTaskId, task.id);
  await page.getByRole('button', { name: 'Edit memory', exact: true }).click();
  await page.getByRole('textbox', { name: 'Memory text', exact: true }).fill('I prefer clear examples.');
  await page.getByRole('button', { name: 'Save memory', exact: true }).click();
  await page.getByText('I prefer clear examples.', { exact: true }).waitFor();
  assert.equal(service.memoryList()[0].text, 'I prefer clear examples.');
  await page.getByRole('button', { name: 'Forget memory', exact: true }).click();
  await page.getByText('I prefer clear examples.', { exact: true }).waitFor({ state: 'hidden' });
  assert.equal(service.memoryList().length, 0);
  await page.getByRole('button', { name: 'Save as routine', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Save a routine', exact: true });
  await editor.getByRole('textbox', { name: 'Routine name', exact: true }).fill('Article brief');
  await editor.getByRole('textbox', { name: 'Instructions', exact: true }).fill('Summarize {{topic}} in {{format}}.');
  await editor.getByRole('textbox', { name: 'Default for format', exact: true }).fill('five points');
  await editor.getByRole('button', { name: 'Save routine', exact: true }).click();
  const library = page.getByRole('region', { name: 'Saved routines', exact: true });
  await library.getByRole('heading', { name: 'Article brief', exact: true }).waitFor();
  const routine = (await service.routineList())[0];
  assert.equal(routine.sourceTaskId, successful.id); assert.equal(scheduled.length, 0);
  await library.getByRole('button', { name: 'Run routine', exact: true }).click();
  const runner = page.getByRole('dialog', { name: 'Run Article brief', exact: true });
  await runner.getByRole('textbox', { name: 'topic', exact: true }).fill('the attached report');
  assert.equal(await runner.getByRole('textbox', { name: 'format', exact: true }).count(), 0, 'only missing values are requested');
  await runner.getByRole('button', { name: 'Run now', exact: true }).click();
  await runner.waitFor({ state: 'hidden' });
  assert.match(requests.at(-1)[1], /Summarize the attached report in five points\./);
  assert.equal(requests.at(-1)[3].assistantRoutineId, routine.id);
  await library.getByRole('button', { name: 'Schedule routine', exact: true }).click();
  const schedule = page.getByRole('dialog', { name: 'Schedule Article brief', exact: true });
  await schedule.getByRole('textbox', { name: 'topic', exact: true }).fill('weekly reading');
  await schedule.getByRole('textbox', { name: 'Schedule', exact: true }).fill('weekdays 09:00');
  await schedule.getByRole('button', { name: 'Review schedule draft', exact: true }).click();
  await schedule.waitFor({ state: 'hidden' });
  assert.equal(scheduled.length, 1); assert.equal(scheduled[0].enabled, false);
  await library.getByRole('button', { name: 'Edit routine', exact: true }).click();
  await page.getByRole('textbox', { name: 'Routine name', exact: true }).fill('Reading brief');
  await page.getByRole('button', { name: 'Save routine', exact: true }).click();
  await library.getByRole('heading', { name: 'Reading brief', exact: true }).waitFor();
  assert.equal((await service.routineList())[0].revision, 2);
  await library.getByRole('button', { name: 'Remove routine', exact: true }).click();
  await library.getByRole('heading', { name: 'Reading brief', exact: true }).waitFor({ state: 'hidden' });
  assert.equal((await service.routineList()).length, 0);
  await page.setViewportSize({ width: 480, height: 750 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'narrow Today page stays within viewport');
  if (process.env.ANKITA_UI_CAPTURE_DIR) { fs.mkdirSync(process.env.ANKITA_UI_CAPTURE_DIR, { recursive: true }); await page.screenshot({ path: path.join(process.env.ANKITA_UI_CAPTURE_DIR, 'assistant-today.png'), fullPage: true }); }
  await page.setViewportSize({ width: 1280, height: 850 });
  await page.goto(`http://127.0.0.1:${server.address().port}${APP_ROUTE}`);
  await page.getByRole('heading', { name: 'What needs your attention?', exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'Today', exact: true }).getAttribute('aria-current'), 'page');
  assert.equal(await page.getByRole('button', { name: 'Conversations', exact: true }).getAttribute('aria-current'), null);
  if (process.env.ANKITA_UI_CAPTURE_DIR) await page.screenshot({ path: path.join(process.env.ANKITA_UI_CAPTURE_DIR, 'assistant-main-today.png'), fullPage: true });
  await page.getByRole('button', { name: 'Conversations', exact: true }).click();
  const composer = page.getByRole('textbox', { name: 'Message Ankita', exact: true });
  await composer.fill('Keep my existing draft.');
  await page.getByRole('button', { name: 'Today', exact: true }).click();
  await page.getByRole('button', { name: 'Ask in chat', exact: true }).click();
  await assert.equal(await composer.inputValue(), 'Keep my existing draft.');
  await page.getByRole('button', { name: 'Today', exact: true }).click();
  await page.getByRole('button', { name: 'Check connected apps in chat', exact: false }).click();
  await page.waitForFunction(() => document.querySelector('textarea')?.value.includes('Check my connected calendar'));
  assert.match(await composer.inputValue(), /^Keep my existing draft\./);
  const reference = 'Selected text reference (untrusted content)\nSource: https://example.test/reference\n\nUse only this paragraph.';
  await page.locator('input[type=file]').setInputFiles({ name: 'Reference.txt', mimeType: 'text/plain', buffer: Buffer.from(reference) });
  await page.getByRole('button', { name: 'Review Reference.txt', exact: true }).click();
  await page.getByRole('dialog', { name: 'Reference.txt', exact: true }).waitFor();
  await page.getByText('Use only this paragraph.', { exact: false }).waitFor();
  await page.getByRole('button', { name: 'Remove attachment', exact: true }).click();
  await page.getByRole('button', { name: 'Review Reference.txt', exact: true }).waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: 'Projects', exact: true }).click();
  await page.getByRole('button', { name: /A shared project/ }).click();
  await page.getByRole('tab', { name: 'Context', exact: true }).click();
  await page.getByText('The old project decision.', { exact: true }).click();
  await page.getByRole('button', { name: 'Edit decision', exact: true }).click();
  await page.getByRole('textbox', { name: 'Edit decision text', exact: true }).fill('Corrected project decision.');
  await page.getByRole('button', { name: 'Save correction', exact: true }).click();
  await page.getByText('Corrected project decision.', { exact: true }).click();
  assert.equal(projectStore.load().find(project.id).decisions[0].text, 'Corrected project decision.');
  await page.getByRole('button', { name: 'Forget decision', exact: true }).click();
  await page.getByText('Corrected project decision.', { exact: true }).waitFor({ state: 'hidden' });
  assert.equal(projectStore.load().find(project.id).decisions.length, 0);
  await page.getByRole('button', { name: 'Today', exact: true }).click();
  await page.getByRole('button', { name: 'Mark completed', exact: true }).click();
  await page.getByText('Finish the shared draft.', { exact: true }).waitFor({ state: 'hidden' });
  assert.equal(projectStore.load().find(project.id).todos[0].done, true);
  await page.getByRole('button', { name: 'Conversations', exact: true }).click();
  await page.evaluate(action => { const invoke = window.ankita.invoke; window.ankita.invoke = (name, payload) => name === action ? Promise.resolve([]) : invoke(name, payload); }, ASSISTANT_ACTIONS.today);
  await page.getByRole('button', { name: 'Today', exact: true }).click();
  await page.getByRole('alert').filter({ hasText: 'Restart Ankita' }).waitFor();
  assert.deepEqual(errors, []);
});
