// Runs the actual App in a browser with isolated IPC fixtures; no user data is used.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { createServer } from 'vite';
import { IPC_CONTRACT } from '../desktop/shared/version.mjs';

const repo = fileURLToPath(new URL('../', import.meta.url));
const evidence = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-workbench-'));
console.log('Workbench evidence: ' + evidence);
const readyMs = 15_000; // Milliseconds; local development renderer readiness.
const instantMotionSeconds = 0.00001; // Seconds; the existing global reduced-motion rule permits a .01ms settle.
async function settleMotion(page) {
  await page.evaluate(async () => {
    await new Promise(requestAnimationFrame);
    await Promise.all(document.getAnimations().filter(animation => animation.effect.getTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => {})));
  });
}
const server = await createServer({ configFile: path.join(repo, 'desktop/vite.config.ts'), server: { port: 0, strictPort: false } });
let browser;
try {
  await server.listen();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  page.setDefaultTimeout(readyMs);
  const errors = [];
  page.on('pageerror', error => { errors.push(error.message); console.log('Renderer error: ' + error.message); });
  await page.addInitScript(({ contract, version }) => {
    const teammates = [
      { id: 'chief', name: 'Chief', color: '#baa47d', persona: 'Coordinate the work. Keep the next step clear.', lastMessage: '', projectId: 'project', emoji: '✦' },
      { id: 'research', name: 'Research desk with a very long name', color: '#a8c4bc', persona: 'Find evidence and compare options.', lastMessage: 'The reference is ready for review.', projectId: null, emoji: '◎' },
      { id: 'developer', name: 'Development', color: '#aba4ca', persona: 'Build and test.', lastMessage: 'Changes are ready.', projectId: 'project' },
    ];
    const project = { id: 'project', name: 'Desktop companion', summary: 'A calmer workspace for the team.', path: '/fixture/workspace/with-a-long-folder-name', repo: '', client: 'Desktop team', conventions: ['Keep drafts with their teammate'], todos: [{ id: 'task', text: 'Review the layout', done: false, at: new Date().toISOString() }], notes: [{ at: new Date().toISOString(), text: 'Reference notes\n' + 'A detailed reference for the desktop interaction and project history. '.repeat(30) }], decisions: [{ at: new Date().toISOString(), text: 'Use the island palette throughout the workspace.' }], archived: false };
    const projects = [project, { ...project, id: 'other-project', name: 'Research workspace with a long name', summary: 'An independent project.', todos: [], notes: [], decisions: [] }];
    window.__projects = projects;
    window.__jobs = [];
    const preferences = { provider: 'custom', model: 'fixture-model', appearance: 'graphite', customApiBase: '', profileSetupDone: true, username: 'Fixture', timeZone: 'UTC', contextWindow: 0, maxTokens: 0 };
    const listeners = new Set();
    window.__calls = [];
    window.__emit = event => listeners.forEach(listener => listener(event));
    window.ankita = {
      onEvent: fn => { listeners.add(fn); return () => listeners.delete(fn); }, onMenuCommand: () => () => {}, onUpdateEvent: () => () => {},
      openExternal: async () => {}, windowAction: async () => {},
      invoke: async (action, payload) => {
        window.__calls.push({ action, payload });
        if (window.__failAction === action) throw new Error('Fixture action failed');
        if (action === 'initialize') return { teammates, models: [{ id: 'fixture-model', name: 'Fixture model' }], settings: { provider: 'custom', model: 'fixture-model', tools: ['read_file', 'write_file'], username: 'Fixture' }, preferences, chrome: 'custom', contract, version, jobs: [] };
        if (action === 'saveDesktopSettings') { Object.assign(preferences, payload); return { preferences: { ...preferences }, settings: { provider: 'custom', model: 'fixture-model', tools: ['read_file', 'write_file'], username: 'Fixture' }, models: [{ id: 'fixture-model', name: 'Fixture model' }] }; }
        if (action === 'browserSessionView') return window.__browserView;
        if (action === 'listProjects') return structuredClone(projects);
        if (action === 'listTeammates') return teammates;
        if (action === 'assignProject') { teammates.find(item => item.id === payload.id).projectId = payload.projectId; return {}; }
        if (action === 'addProjectTodo') { projects.find(item => item.id === payload.id).todos.push({ id: 'added-task', text: payload.text, done: false, at: new Date().toISOString() }); return {}; }
        if (action === 'completeProjectTodo') { projects.find(item => item.id === payload.id).todos.find(item => item.id === payload.ref).done = true; return {}; }
        if (action === 'addProjectRecord') { projects.find(item => item.id === payload.id)[payload.kind === 'note' ? 'notes' : 'decisions'].push({ text: payload.text, at: new Date().toISOString() }); return {}; }
        if (action === 'updateProject') { const item = projects.find(item => item.id === payload.id); Object.assign(item, payload.patch); return item; }
        if (action === 'createProject') { const item = { ...project, ...payload, id: 'created-project', todos: [], notes: [], decisions: [] }; projects.push(item); return item; }
        if (action === 'scheduleHostSettings') { if (payload) window.__hostSettings = payload; return { supported: window.__startupSupported ?? true, startAtLogin: window.__hostSettings?.startAtLogin ?? false }; }
        if (action === 'getChannels') return { telegram: { enabled: false, hasToken: false, allowedChatIds: '', ownerChatId: '', teammateId: 'chief', voiceReply: false, confirmTimeout: 300, status: { running: false, account: null, error: null } } };
        if (action === 'schedulePauseAll') { window.__jobs.forEach(job => job.enabled = false); window.__emit({ type: 'schedule-changed', jobs: window.__jobs }); return {}; }
        if (action === 'scheduleEnable') { window.__jobs.find(job => job.id === payload.id).enabled = payload.enabled; window.__emit({ type: 'schedule-changed', jobs: window.__jobs }); return {}; }
        if (action === 'scheduleRunNow') { window.__jobs.find(job => job.id === payload.id).running = true; window.__emit({ type: 'schedule-changed', jobs: window.__jobs }); return {}; }
        if (action === 'scheduleStop') { window.__jobs.find(job => job.id === payload.id).running = false; window.__emit({ type: 'schedule-changed', jobs: window.__jobs }); return {}; }
        if (action === 'loadThread') return payload.id === 'developer' ? [{ id: 'user', role: 'user', content: 'Check the workspace.' }, { id: 'answer', role: 'assistant', content: '## Layout review\n\nThe workspace keeps **tools and files** in reach.\n\n| Area | State |\n| --- | --- |\n| Conversation | Ready |' }] : [];
        if (action === 'workspaceSnapshot') return { cwd: '/fixture/workspace', files: [{ path: 'src/layout.ts', status: ' M', untracked: false }], artifacts: [{ path: 'notes.md', name: 'notes.md' }], jobs: [] };
        if (action === 'workspaceDiff') return { diff: '@@ -1 +1 @@\n-old layout\n+new layout', truncated: false };
        if (action === 'pluginsOverview') return { mode: 'unavailable', services: {}, live: false };
        if (action === 'browserPluginsOverview') return { isolated: { mode: 'isolated', name: 'Ankita browser', enabled: false, ready: false, installed: false, allowedSites: [], blockedSites: [] }, local: { mode: 'local', name: 'Chrome connection', enabled: false, ready: false, installed: false, allowedSites: [], blockedSites: [] } };
        if (action === 'secureStoreList') return { records: [] };
        if (action === 'skills:list' || action === 'palette:query') return [];
        if (action === 'companionCaptureSetup') return { paired: false, address: 'http://127.0.0.1:1', code: 'fixture-pairing-code' };
        if (action === 'companionCaptureInbox') return [];
        return {};
      },
    };
  }, { contract: IPC_CONTRACT, version: JSON.parse(await fs.readFile(path.join(repo, 'package.json'), 'utf8')).version });
  await page.goto(server.resolvedUrls.local[0]);
  await page.getByRole('button', { name: 'Open command palette', exact: true }).waitFor();
  if (process.argv.includes('--focus-only')) {
    const checkFocus = async (field, container) => {
      await field.evaluate(element => element.blur());
      const before = await container.evaluate(element => getComputedStyle(element).borderColor);
      await field.focus();
      assert.equal(await field.evaluate(element => getComputedStyle(element).outlineStyle), 'none');
      assert.equal(await container.evaluate(element => getComputedStyle(element).borderColor), before, 'focus must not brighten the surrounding border');
    };
    for (const theme of [{ id: 'mono', name: 'Mono' }, { id: 'slate', name: 'Slate' }, { id: 'graphite', name: 'Graphite' }]) {
      await page.getByRole('button', { name: 'Open settings', exact: true }).click();
      await page.getByRole('button', { name: 'Appearance', exact: true }).click();
      await page.locator('.settings-theme-card').filter({ has: page.getByText(theme.name, { exact: true }) }).click();
      await page.getByRole('button', { name: 'Apply appearance', exact: true }).click();
      await page.waitForFunction(id => document.documentElement.dataset.theme === id, theme.id);
      await page.getByRole('button', { name: 'Close settings', exact: true }).click();
      await page.getByRole('button', { name: 'Conversations', exact: true }).click();
      await checkFocus(page.getByLabel('Message Chief'), page.locator('.composer-shell'));
      await page.screenshot({ path: path.join(evidence, `focus-composer-${theme.id}.png`) });
      await page.getByRole('button', { name: 'Projects', exact: true }).click();
      await page.getByRole('tab', { name: 'Context', exact: true }).click();
      await checkFocus(page.getByLabel('New decision'), page.locator('.project-context-compose'));
      await page.screenshot({ path: path.join(evidence, `focus-context-${theme.id}.png`) });
      await page.getByRole('button', { name: 'Open settings', exact: true }).click();
      const windowField = page.getByLabel('Context window (tokens)', { exact: true });
      await checkFocus(windowField, windowField);
      await windowField.press('Tab');
      assert.equal(await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle), 'none');
      await page.getByRole('button', { name: 'Close settings', exact: true }).click();
    }
    assert.deepEqual(errors, []);
    console.log('PASS focus-only regression: no outlines or brightened focus borders on composer/context/settings, keyboard focus and all three themes');
    console.log('Workbench evidence: ' + evidence);
  } else {
  await page.screenshot({ path: path.join(evidence, 'welcome.png') });
  assert.equal(await page.getByRole('navigation', { name: 'Workspace navigation' }).count(), 1, 'main desktop needs a dedicated compact navigation rail');
  assert.equal(await page.locator('.chat-context-bar').count(), 1, 'project/jobs/review belong in a separate context strip');
  assert.equal(await page.locator('.teammate-row .teammate-face').count(), 3, 'teammates use mascot faces rather than emoji tiles');
  await page.getByRole('button', { name: 'Plan the next step', exact: true }).click();
  assert.ok((await page.getByLabel('Message Chief').inputValue()).length > 0);
  assert.equal(await page.evaluate(() => window.__calls.filter(call => call.action === 'send').length), 0, 'starter actions prepare a draft for review');
  await page.getByLabel('Message Chief').fill('Keep the Chief draft');
  await page.getByRole('button', { name: 'Explore an idea', exact: true }).click();
  assert.ok((await page.getByLabel('Message Chief').inputValue()).startsWith('Keep the Chief draft\n\n'), 'starter actions preserve a draft that is already being written');
  await page.getByLabel('Message Chief').fill('Keep the Chief draft');
  await page.getByRole('button', { name: 'Research desk with a very long name', exact: true }).click();
  await page.getByLabel('Message Research desk with a very long name').fill('Keep the research draft');
  await page.getByRole('button', { name: 'Projects', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: 'Projects', exact: true }).getAttribute('aria-current'), 'page');
  assert.equal(await page.locator('.teammate-row[aria-current="page"]').count(), 0, 'management pages do not show a teammate as the current page');
  await page.getByRole('heading', { name: 'Desktop companion', exact: true }).waitFor();
  assert.equal(await page.getByRole('navigation', { name: 'Projects', exact: true }).getByText('1 open task', { exact: true }).count(), 1, 'task count uses singular copy');
  await page.screenshot({ path: path.join(evidence, 'projects.png') });
  await page.getByRole('button', { name: 'Plugins', exact: true }).click();
  await page.getByRole('heading', { name: 'Connected apps', exact: true }).waitFor();
  await page.screenshot({ path: path.join(evidence, 'plugins.png') });
  await page.getByRole('button', { name: 'Conversations', exact: true }).click();
  assert.equal(await page.getByLabel('Message Research desk with a very long name').inputValue(), 'Keep the research draft');
  await page.getByRole('button', { name: 'Chief', exact: true }).click();
  assert.equal(await page.getByLabel('Message Chief').inputValue(), 'Keep the Chief draft');
  console.log('PASS navigation rail, mascot roster, draft-only starters and preserved teammate drafts across pages');

  await page.getByRole('button', { name: 'Development', exact: true }).click();
  await page.getByRole('heading', { name: 'Layout review' }).waitFor();
  await page.getByRole('button', { name: 'Review changes, artifacts and runs' }).click();
  await page.getByRole('button', { name: 'M src/layout.ts' }).click();
  await page.getByRole('region', { name: 'File diff' }).waitFor();
  await settleMotion(page);
  await page.screenshot({ path: path.join(evidence, 'conversation-review.png') });
  await page.getByRole('button', { name: 'Close work review' }).click();
  await page.getByRole('button', { name: 'Open settings' }).click();
  await page.getByRole('button', { name: 'Close settings' }).waitFor();
  await settleMotion(page);
  await page.screenshot({ path: path.join(evidence, 'settings.png') });
  await page.getByRole('button', { name: 'Close settings' }).click();
  console.log('PASS actual Markdown transcript, work-review diff and settings navigation');

  for (const width of [1440, 1024, 800, 640]) {
    await page.setViewportSize({ width, height: 720 });
    await page.getByRole('button', { name: 'Review changes, artifacts and runs' }).click();
    await page.getByRole('button', { name: 'Close work review' }).waitFor();
    await page.getByRole('button', { name: 'Close work review' }).click();
    await settleMotion(page);
    const layout = await page.evaluate(() => {
      const selectors = ['.chat-header', '.chat-context-bar', '.composer-shell', '.header-actions', '.workspace-rail'];
      return { width: innerWidth, scrollWidth: document.documentElement.scrollWidth, overflow: document.documentElement.scrollWidth > innerWidth, boxes: selectors.map(selector => { const r = document.querySelector(selector).getBoundingClientRect(); return { selector, left: r.left, right: r.right, bottom: r.bottom }; }), outside: [...document.querySelectorAll('body *')].filter(element => element.getBoundingClientRect().right > innerWidth + 1).slice(0,8).map(element => ({ class: element.className, right: element.getBoundingClientRect().right, width: element.getBoundingClientRect().width })) };
    });
    await page.screenshot({ path: path.join(evidence, `width-${width}.png`) });
    assert.equal(layout.overflow, false, `no page overflow at ${width}px: ${JSON.stringify(layout)}`);
    for (const box of layout.boxes) assert.ok(box.left >= 0 && box.right <= layout.width + 1, `controls fit at ${width}px: ${JSON.stringify(box)}`);
  }
  await page.getByRole('button', { name: 'Chief', exact: true }).click();
  assert.equal(await page.getByLabel('Message Chief').inputValue(), 'Keep the Chief draft', 'compact mascot rail changes teammates without losing drafts');
  assert.equal(await page.getByRole('button', { name: 'Close window', exact: true }).count(), 1, 'window controls remain accessible in the compact rail');
  await page.getByRole('button', { name: 'New teammate', exact: true }).click();
  await page.getByRole('heading', { name: 'A new teammate', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await page.getByRole('button', { name: 'Scheduled jobs', exact: true }).click();
  await page.getByRole('button', { name: 'Close scheduled tasks', exact: true }).waitFor();
  await settleMotion(page);
  await page.screenshot({ path: path.join(evidence, 'compact-jobs.png') });
  const jobsBounds = await page.locator('.jobs-panel').boundingBox();
  assert.ok(jobsBounds.x >= 0 && jobsBounds.x + jobsBounds.width <= 640 && jobsBounds.y + jobsBounds.height <= 720);
  await page.getByRole('button', { name: 'Create a task in chat', exact: true }).click();
  assert.equal(await page.getByLabel('Message Chief').inputValue(), 'Schedule a task: ', 'legacy compose actions still prepare their original text');
  await page.getByRole('button', { name: 'Browser helper', exact: true }).click();
  await page.getByRole('button', { name: 'Copy pairing code', exact: true }).click();
  await page.getByLabel('Browser pairing code').waitFor();
  await settleMotion(page);
  const helperBounds = await page.locator('.companion-helper-popover').boundingBox();
  assert.ok(helperBounds.x >= 0 && helperBounds.x + helperBounds.width <= 640 && helperBounds.y + helperBounds.height <= 720);
  await page.screenshot({ path: path.join(evidence, 'compact-helper.png') });
  await page.getByRole('button', { name: 'Browser helper', exact: true }).click();
  console.log('PASS compact teammate switching, window controls, creation dialog, scheduled tasks and helper setup');
  await page.getByRole('button', { name: 'Collapse sidebar' }).click();
  await page.getByRole('button', { name: 'Show sidebar' }).click();
  await page.setViewportSize({ width: 1280, height: 800 });
  await settleMotion(page);
  const colors = [];
  for (const theme of [{ id: 'mono', name: 'Mono' }, { id: 'slate', name: 'Slate' }, { id: 'graphite', name: 'Graphite' }]) {
    await page.getByRole('button', { name: 'Open settings', exact: true }).click();
    await page.getByRole('button', { name: 'Appearance', exact: true }).click();
    await page.locator('.settings-theme-card').filter({ has: page.getByText(theme.name, { exact: true }) }).click();
    await page.getByRole('button', { name: 'Apply appearance', exact: true }).click();
    await page.waitForFunction(id => document.documentElement.dataset.theme === id, theme.id);
    await page.getByRole('button', { name: 'Close settings', exact: true }).click();
    colors.push(await page.locator('.chat-pane').evaluate(element => getComputedStyle(element).backgroundColor));
    await page.screenshot({ path: path.join(evidence, `theme-${theme.id}.png`) });
  }
  assert.equal(new Set(colors).size, 3, 'all existing appearances still change the work surface');
  for (const mode of ['isolated', 'local', 'external']) {
    await page.evaluate(mode => {
      window.__browserView = { mode, status: 'working', step: 'Reading the fixture page', tabs: [{ id: 'fixture-page', url: 'https://fixture.invalid', title: 'Fixture page', active: true }], screenshot: null };
      window.__emit({ type: 'browser-state', threadId: 'chief', state: window.__browserView });
    }, mode);
    await page.getByRole('button', { name: 'Close and stop browser', exact: true }).waitFor();
    await settleMotion(page);
    await page.screenshot({ path: path.join(evidence, `live-browser-${mode}.png`) });
    const browserBounds = await page.locator('.browser-stage').boundingBox();
    assert.ok(browserBounds.x >= 0 && browserBounds.x + browserBounds.width <= 1280 && browserBounds.y + browserBounds.height <= 800);
    await page.getByRole('button', { name: 'Close and stop browser', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.browser-stage').getAttribute('aria-hidden') === 'true');
  }
  console.log('PASS all three appearance settings and isolated/Chrome/external browser preview/stop layouts (fixture IPC)');
  await page.getByRole('button', { name: 'Show sidebar', exact: true }).click();
  await page.getByRole('button', { name: 'Projects', exact: true }).click();
  await page.getByRole('heading', { name: 'Desktop companion', exact: true }).waitFor();
  await settleMotion(page);
  await page.screenshot({ path: path.join(evidence, 'project-sections.png') });
  assert.equal(await page.getByRole('tab', { name: 'Overview', exact: true }).count(), 1, 'projects need distinct overview, tasks and context sections');
  await page.getByRole('tab', { name: 'Tasks', exact: true }).click();
  await page.getByLabel('New project task').fill('Keep this project draft');
  await page.getByRole('navigation', { name: 'Projects', exact: true }).getByRole('button', { name: 'Research workspace with a long name', exact: true }).click();
  assert.equal(await page.getByLabel('New project task').inputValue(), '', 'a project draft cannot leak into another workspace');
  await page.getByLabel('New project task').fill('Independent draft');
  await page.getByRole('navigation', { name: 'Projects', exact: true }).getByRole('button', { name: 'Desktop companion', exact: true }).click();
  assert.equal(await page.getByLabel('New project task').inputValue(), 'Keep this project draft');
  await page.getByLabel('New project task').fill('A task added through the real form');
  await page.getByRole('button', { name: 'Add task', exact: true }).click();
  await page.getByRole('button', { name: 'Complete A task added through the real form', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Complete A task added through the real form', exact: true }).click();
  await page.locator('.project-completed summary').click();
  await page.locator('.project-completed').getByText('A task added through the real form', { exact: true }).waitFor();
  await page.screenshot({ path: path.join(evidence, 'project-tasks.png') });
  await page.getByRole('tab', { name: 'Context', exact: true }).click();
  await page.getByLabel('New decision').fill('Context draft for this project');
  await page.getByRole('navigation', { name: 'Projects', exact: true }).getByRole('button', { name: 'Research workspace with a long name', exact: true }).click();
  assert.equal(await page.getByLabel('New decision').inputValue(), '');
  await page.getByRole('navigation', { name: 'Projects', exact: true }).getByRole('button', { name: 'Desktop companion', exact: true }).click();
  assert.equal(await page.getByLabel('New decision').inputValue(), 'Context draft for this project');
  await page.locator('.project-record-kind').getByRole('button', { name: 'Note', exact: true }).click();
  await page.getByLabel('New note').fill('Saved note from the context editor');
  await page.getByRole('button', { name: 'Save context', exact: true }).click();
  await page.locator('.context-record-copy > span').getByText('Saved note from the context editor', { exact: true }).waitFor();
  await page.locator('.project-context-toolbar').getByRole('button', { name: 'Notes', exact: true }).click();
  assert.equal(await page.locator('.context-record-mark.decision').count(), 0);
  await page.getByLabel('Search project context').fill('Reference notes');
  assert.equal(await page.locator('.project-context-records details').count(), 1);
  const collapsedHeight = await page.locator('.project-context-records details').evaluate(element => element.getBoundingClientRect().height);
  await page.locator('.project-context-records summary').click();
  assert.ok(await page.locator('.project-context-records details').evaluate(element => element.getBoundingClientRect().height) > collapsedHeight, 'long notes expand on demand');
  await page.locator('.project-context-records summary').click();
  await page.getByLabel('Search project context').fill('');
  await page.screenshot({ path: path.join(evidence, 'project-context.png') });
  await page.getByRole('tab', { name: 'Overview', exact: true }).click();
  await page.getByRole('tab', { name: 'Overview', exact: true }).press('ArrowRight');
  assert.equal(await page.getByRole('tab', { name: 'Tasks', exact: true }).getAttribute('aria-selected'), 'true');
  await page.getByRole('tab', { name: 'Tasks', exact: true }).press('Home');
  await page.getByRole('button', { name: 'Edit project', exact: true }).click();
  await page.getByLabel('Client', { exact: true }).fill('Updated desktop team');
  await page.getByRole('button', { name: 'Save changes', exact: true }).click();
  await page.getByText('Updated desktop team', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Unassign', exact: true }).click();
  await page.getByRole('button', { name: 'Assign teammate', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Assign teammate', exact: true }).click();
  await page.getByRole('button', { name: 'Unassign', exact: true }).waitFor();
  console.log('PASS project sections, keyboard tabs, per-project drafts, task completion, context save/search/expand, editing and assignment (fixture IPC)');

  await page.getByRole('button', { name: 'Conversations', exact: true }).click();
  await page.getByRole('button', { name: 'Scheduled jobs', exact: true }).click();
  const createTask = page.getByRole('button', { name: 'Create a task in chat', exact: true });
  await createTask.waitFor();
  assert.equal(await page.getByRole('button', { name: 'Ask Ankita', exact: true }).count(), 0, 'empty tasks has one clear create action');
  assert.ok(await createTask.evaluate(element => parseFloat(getComputedStyle(element).borderRadius)) > 0, 'the create action must have the workbench button styling');
  await settleMotion(page);
  await page.screenshot({ path: path.join(evidence, 'scheduled-empty.png') });
  await createTask.click();
  assert.equal(await page.getByLabel('Message Chief').inputValue(), 'Schedule a task: ');
  await page.evaluate(() => {
    const base = { kind: 'routine', description: 'Read the project activity and bring back a useful summary.', cron: '0 9 * * *', cronLabel: 'Every morning', prompt: 'Summarize the project', threadId: 'chief', deliveryThreadId: 'chief', enabled: true, ownerMissing: false, pausedReason: null, nextRunAt: new Date().toISOString(), timeZone: 'UTC', running: false, step: 0, scope: null, needsApproval: false, lastStatus: null };
    window.__jobs = [{ ...base, id: 'daily', name: 'A daily project summary with a long task name' }, { ...base, id: 'research-job', name: 'Research reminder', threadId: 'research', deliveryThreadId: 'research', enabled: false }];
    window.__emit({ type: 'schedule-changed', jobs: window.__jobs });
  });
  await page.getByRole('button', { name: 'Open settings', exact: true }).click();
  await page.getByLabel('Context window (tokens)', { exact: true }).fill('65536');
  await page.getByLabel('Max output tokens', { exact: true }).fill('4096');
  await page.getByRole('button', { name: 'Save model settings', exact: true }).click();
  await page.getByRole('status').getByText('Changes saved.', { exact: true }).waitFor();
  const modelPatch = await page.evaluate(() => window.__calls.filter(call => call.action === 'saveDesktopSettings').at(-1).payload);
  assert.deepEqual(modelPatch, { contextWindow: 65536, maxTokens: 4096 });
  await page.screenshot({ path: path.join(evidence, 'settings-model.png') });
  await page.getByRole('button', { name: 'Connect or change a provider', exact: true }).click();
  await page.getByRole('heading', { name: 'Providers', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Background jobs', exact: true }).click();
  await page.getByRole('switch', { name: /Start Ankita when I sign in/ }).check();
  await page.waitForFunction(() => window.__calls.some(call => call.action === 'scheduleHostSettings' && call.payload?.startAtLogin === true));
  assert.deepEqual(await page.locator('.settings-job-overview strong').allTextContents(), ['2', '1', '0']);
  assert.equal(await page.locator('.settings-note').filter({ hasText: '--takeover' }).count(), 0, 'scheduler implementation text stays out of the preference flow');
  await page.screenshot({ path: path.join(evidence, 'settings-background.png') });
  await page.locator('.settings-job-list').getByRole('button', { name: /Research reminder/ }).click();
  await page.getByLabel('Message Research desk with a very long name').waitFor();
  await page.locator('.job-detail h3').getByText('Research reminder', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Resume', exact: true }).click();
  await page.getByRole('button', { name: 'Pause', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Run now', exact: true }).click();
  await page.getByRole('button', { name: 'Stop', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await page.getByRole('button', { name: 'Run now', exact: true }).waitFor();
  await page.screenshot({ path: path.join(evidence, 'scheduled-detail.png') });
  await page.getByRole('button', { name: 'Close scheduled tasks', exact: true }).click();
  await page.getByRole('button', { name: 'Open settings', exact: true }).click();
  await page.getByRole('button', { name: 'Background jobs', exact: true }).click();
  await page.getByRole('button', { name: 'Pause all jobs', exact: true }).click();
  await page.waitForFunction(() => [...document.querySelectorAll('.settings-job-overview strong')].map(item => item.textContent).join(',') === '2,0,0');
  assert.equal(await page.getByRole('button', { name: 'Pause all jobs', exact: true }).isDisabled(), true);
  await page.evaluate(() => {
    window.__jobs.push({ ...window.__jobs[0], id: 'orphan', name: 'Task with a removed owner', threadId: null, deliveryThreadId: 'chief', ownerMissing: true }, { ...window.__jobs[0], id: 'unroutable', name: 'Task without a delivery conversation', threadId: null, deliveryThreadId: null, ownerMissing: true });
    window.__emit({ type: 'schedule-changed', jobs: window.__jobs });
  });
  assert.equal(await page.locator('.settings-job-list').getByRole('button', { name: /Task without a delivery conversation/ }).isDisabled(), true);
  await page.locator('.settings-job-list').getByRole('button', { name: /Task with a removed owner/ }).click();
  await page.getByLabel('Message Chief').waitFor();
  await page.locator('.job-detail h3').getByText('Task with a removed owner', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Close scheduled tasks', exact: true }).click();
  await page.getByRole('button', { name: 'Research desk with a very long name', exact: true }).click();
  await page.getByRole('button', { name: 'Open settings', exact: true }).click();
  await page.getByRole('button', { name: 'Close settings', exact: true }).click();
  console.log('PASS styled scheduled empty/detail views, model save, startup switch, live task counts, owner routing, resume/run/stop and pause-all (fixture IPC)');

  for (const width of [1280, 800, 640]) {
    await page.setViewportSize({ width, height: 720 });
    await page.getByRole('button', { name: 'Projects', exact: true }).click();
    await page.getByRole('tab', { name: 'Context', exact: true }).click();
    await settleMotion(page);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `projects fit at ${width}px`);
    const controls = await page.locator('.project-context-compose, .project-tabs, .project-context-toolbar').evaluateAll(elements => elements.every(element => element.getBoundingClientRect().right <= innerWidth));
    assert.equal(controls, true, `project controls fit at ${width}px`);
    await page.screenshot({ path: path.join(evidence, `project-context-${width}.png`) });
    await page.getByRole('button', { name: 'Open settings', exact: true }).click();
    for (const name of ['Model', 'Background jobs', 'Providers', 'Profile', 'Images', 'Channels', 'Privacy', 'Appearance', 'About']) {
      await page.getByRole('button', { name, exact: true }).click();
      await settleMotion(page);
      const overflow = await page.locator('.settings-scroll').evaluate(element => ({ width: element.clientWidth, scroll: element.scrollWidth }));
      assert.ok(overflow.scroll <= overflow.width + 1, `${name} settings fit at ${width}px: ${JSON.stringify(overflow)}`);
      if (name === 'Model' || name === 'Background jobs') await page.screenshot({ path: path.join(evidence, `settings-${name.replaceAll(' ', '-')}-${width}.png`) });
    }
    await page.getByRole('button', { name: 'Close settings', exact: true }).click();
  }
  console.log('PASS populated project/context and settings layouts at three widths; compact settings keep accessible navigation labels');
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.getByLabel('New decision').fill('Keep this text if saving fails');
  await page.evaluate(() => { window.__failAction = 'addProjectRecord'; });
  await page.getByRole('button', { name: 'Save context', exact: true }).click();
  await page.getByRole('alert').getByText('Fixture action failed', { exact: true }).waitFor();
  assert.equal(await page.getByLabel('New decision').inputValue(), 'Keep this text if saving fails');
  await page.evaluate(() => { window.__failAction = undefined; window.__startupSupported = false; });
  await page.getByRole('button', { name: 'Open settings', exact: true }).click();
  await page.getByRole('button', { name: 'Background jobs', exact: true }).click();
  await page.getByText('Startup control is unavailable on this system.', { exact: true }).waitFor();
  assert.equal(await page.getByRole('switch', { name: /Start Ankita when I sign in/ }).isDisabled(), true);
  await page.evaluate(() => { window.__startupSupported = true; });
  await page.getByRole('button', { name: 'Model', exact: true }).click();
  await page.getByRole('button', { name: 'Background jobs', exact: true }).click();
  await page.getByText('Ready for scheduled work after you sign in.', { exact: true }).waitFor();
  await page.evaluate(() => { window.__failAction = 'scheduleHostSettings'; });
  await page.getByRole('switch', { name: /Start Ankita when I sign in/ }).click();
  await page.getByRole('status').getByText('Fixture action failed', { exact: true }).waitFor();
  assert.equal(await page.getByRole('switch', { name: /Start Ankita when I sign in/ }).isChecked(), true, 'startup failures keep the confirmed state');
  await page.evaluate(() => { window.__failAction = undefined; });
  await page.getByRole('button', { name: 'Close settings', exact: true }).click();
  for (const theme of [{ id: 'mono', name: 'Mono' }, { id: 'slate', name: 'Slate' }, { id: 'graphite', name: 'Graphite' }]) {
    await page.getByRole('button', { name: 'Open settings', exact: true }).click();
    await page.getByRole('button', { name: 'Appearance', exact: true }).click();
    await page.locator('.settings-theme-card').filter({ has: page.getByText(theme.name, { exact: true }) }).click();
    await page.getByRole('button', { name: 'Apply appearance', exact: true }).click();
    await page.waitForFunction(id => document.documentElement.dataset.theme === id, theme.id);
    await page.getByRole('button', { name: 'Model', exact: true }).click();
    await page.screenshot({ path: path.join(evidence, `section-model-${theme.id}.png`) });
    await page.getByRole('button', { name: 'Background jobs', exact: true }).click();
    await page.screenshot({ path: path.join(evidence, `section-background-${theme.id}.png`) });
    await page.getByRole('button', { name: 'Close settings', exact: true }).click();
    await page.screenshot({ path: path.join(evidence, `section-context-${theme.id}.png`) });
  }
  assert.ok(await page.locator('.project-tabs button').first().evaluate(element => parseFloat(getComputedStyle(element).transitionDuration)) > 0, 'tabs use the real shared motion token');
  console.log('PASS saved text on context failure, unavailable/failed startup controls and all three themes on the redesigned sections');
  await page.getByLabel('New decision').focus();
  assert.equal(await page.getByLabel('New decision').evaluate(element => getComputedStyle(element).outlineStyle), 'none', 'project textareas have no rectangular focus outline');
  await page.screenshot({ path: path.join(evidence, 'context-focused-no-outline.png') });
  await page.getByRole('button', { name: 'Conversations', exact: true }).click();
  await page.getByLabel('Message Research desk with a very long name').focus();
  assert.equal(await page.getByLabel('Message Research desk with a very long name').evaluate(element => getComputedStyle(element).outlineStyle), 'none', 'the composer has no rectangular focus outline');
  await page.screenshot({ path: path.join(evidence, 'composer-focused-no-outline.png') });
  await page.getByRole('button', { name: 'Open settings', exact: true }).click();
  await page.getByLabel('Context window (tokens)', { exact: true }).focus();
  assert.equal(await page.getByLabel('Context window (tokens)', { exact: true }).evaluate(element => getComputedStyle(element).outlineStyle), 'none');
  await page.getByRole('button', { name: 'Providers', exact: true }).focus();
  assert.equal(await page.getByRole('button', { name: 'Providers', exact: true }).evaluate(element => getComputedStyle(element).outlineStyle), 'none');
  await page.getByRole('button', { name: 'Close settings', exact: true }).click();
  console.log('PASS focused context editor, composer, settings input and navigation controls have no outline rectangles');
  await page.emulateMedia({ reducedMotion: 'reduce' });
  assert.ok(await page.locator('.sidebar').evaluate((element, seconds) => parseFloat(getComputedStyle(element).transitionDuration) <= seconds, instantMotionSeconds));
  assert.deepEqual(errors, []);
  console.log('PASS four responsive widths, inspector dismissal, sidebar restore and reduced motion; no page errors');
  console.log('Workbench evidence: ' + evidence);
  }
} finally {
  await browser?.close();
  await server.close();
}
