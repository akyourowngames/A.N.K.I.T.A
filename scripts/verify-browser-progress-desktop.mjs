import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { build, Platform } from 'electron-builder';
import { _electron as electron } from 'playwright';
import { DesktopSettingsStore } from '../desktop/electron/settings.mjs';
import { BROWSER_PREVIEW_POLL } from '../desktop/shared/browser-progress.mjs';
import { browserNotice } from '../src/integrations/browser-errors.mjs';

// Disposable local fixtures; no provider spend, package downloads or personal configuration.
const ROOT = path.resolve(fileURLToPath(new URL('..', import.meta.url))), require = createRequire(import.meta.url);
const LIMITS = Object.freeze({ launch: 45_000, action: 15_000, close: 10_000, profile: 4000, cleanupRetries: 10, cleanupDelay: 100 }); // Milliseconds except retry count.
const HOST = '127.0.0.1', MODEL = 'browser-progress-fixture', CONTEXT = 131072;
const TASK = 'Complete the disposable browser progress form.', DONE = 'Observed the submitted form.';
const QUESTION = 'Submit this disposable note?', RESPONSE = 'Fixture note';
const FORM = `<title>Browser progress fixture</title><form><label>Note<input></label><button type="button" onclick="const value=prompt('${QUESTION}');if(value!==null)fetch('/save',{method:'POST',body:value}).then(()=>document.querySelector('main').textContent='Saved once')">Save note</button></form><main></main>`;
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-progress-desktop-'));
const configDirectory = path.join(directory, 'config'), userData = path.join(directory, 'user-data');
fs.mkdirSync(configDirectory); fs.mkdirSync(path.join(directory, 'screenshots'));
const developed = process.argv.includes('--developed');
const requests = [], fixtureErrors = []; let writes = 0, saved = '', base, application, launchedProcess;
let resumeRecovery, resumeDialog;
const recoveryGate = new Promise(resolve => { resumeRecovery = resolve; });
const dialogGate = new Promise(resolve => { resumeDialog = resolve; });
const server = http.createServer(async (request, response) => {
  if (request.url === '/save') {
    const chunks = []; for await (const chunk of request) chunks.push(chunk);
    saved = Buffer.concat(chunks).toString(); writes++; response.end('saved'); return;
  }
  if (request.url === '/v1/models') {
    response.setHeader('content-type', 'application/json'); response.end(JSON.stringify({ data: [{ id: MODEL, context_length: CONTEXT }] })); return;
  }
  if (request.url === '/v1/chat/completions') {
    try {
      const chunks = []; for await (const chunk of request) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks).toString()); requests.push(body);
      const previous = body.messages.findLast(message => message.role === 'tool')?.content || '';
      const ref = name => previous.split('\n').find(line => line.includes(name) && line.includes('[ref='))?.match(/\[ref=([^\]]+)\]/)?.[1];
      const phase = requests.length - 1;
      if (phase === 3) await recoveryGate;
      if (phase === 5) await dialogGate;
      const phases = [
        ['find_tools', { query: 'browser' }],
        ['browser', { action: 'open', url: `${base}/form` }],
        ['browser', { action: 'act', op: 'click', ref: 'stale-fixture-ref' }],
        ['browser', { action: 'snapshot' }],
        ['browser', { action: 'sequence', observation_id: /Observation: (\S+)/.exec(previous)?.[1], steps: [
          { action: 'act', op: 'fill', ref: ref('Note'), text: 'Prepared note' },
          { action: 'act', op: 'click', ref: ref('Save note') },
        ] }],
        ['browser', { action: 'read' }],
      ];
      let delta;
      if (phase < phases.length) {
        const [name, args] = phases[phase];
        delta = { tool_calls: [{ index: 0, id: `progress-${phase}`, type: 'function', function: { name, arguments: JSON.stringify(args) } }] };
      } else { assert.match(previous, /Saved once/); delta = { content: DONE }; }
      response.writeHead(200, { 'content-type': 'text/event-stream' });
      response.end(`data: ${JSON.stringify({ model: MODEL, choices: [{ index: 0, delta, finish_reason: delta.tool_calls ? 'tool_calls' : 'stop' }] })}\n\ndata: [DONE]\n\n`);
    } catch (error) { fixtureErrors.push(error.message); response.writeHead(500); response.end(JSON.stringify({ error: { message: error.message } })); }
    return;
  }
  response.setHeader('content-type', 'text/html'); response.end(FORM);
});
await new Promise(resolve => server.listen(0, HOST, resolve)); base = `http://${HOST}:${server.address().port}`;
new DesktopSettingsStore(path.join(configDirectory, 'desktop-settings.json')).update({ provider: 'custom', model: MODEL, customApiBase: `${base}/v1`, customApiKey: '', composioApiKey: '', username: 'Verification', profileSetupDone: true });
fs.writeFileSync(path.join(configDirectory, 'config.env'), 'ALLOW_PRIVATE_HOSTS=1\nMEMORY_CONSOLIDATION=0\nAUTO_APPROVE=1\nBROWSER_RUNTIME_V2=1\n');
try {
  let appOutput, executablePath;
  if (developed) executablePath = require('electron');
  else {
    await build({ targets: Platform.current().createTarget('dir'), publish: 'never', projectDir: ROOT,
      config: { extends: path.join(ROOT, 'desktop/packaging/electron-builder.yml'), directories: { output: path.join(directory, 'package') },
        electronDist: path.dirname(require('electron')), npmRebuild: false, win: { signAndEditExecutable: false }, afterPack: context => { appOutput = context.appOutDir; } } });
    const executable = fs.readdirSync(appOutput).find(name => process.platform === 'win32' ? name.endsWith('.exe') : !name.includes('.') && fs.statSync(path.join(appOutput, name)).isFile());
    assert.ok(executable, 'packaged executable discovered'); executablePath = path.join(appOutput, executable);
  }
  const env = { ...process.env, CONFIG_DIR: configDirectory, ALLOW_PRIVATE_HOSTS: '1', TOOL_PROVIDER: '', TOOL_MODEL: '', TOOL_API_BASE: '', TOOL_API_KEY: '', ...(appOutput ? { PORTABLE_EXECUTABLE_DIR: appOutput } : {}) };
  delete env.ELECTRON_RUN_AS_NODE; delete env.ANKITA_DESKTOP_DEV_URL;
  application = await electron.launch({ executablePath, args: [...(developed ? [ROOT] : []), `--user-data-dir=${userData}`], cwd: configDirectory, env, timeout: LIMITS.launch });
  launchedProcess = application.process(); // Preserve the owned process handle after Playwright disposes its app dispatcher.
  console.log('PROGRESS_CHECK_STARTED', JSON.stringify({ developed }));
  assert.equal(await application.evaluate(({ app }) => app.isPackaged), !developed);
  const page = await application.firstWindow(); page.setDefaultTimeout(LIMITS.action);
  const metrics = await application.evaluateHandle(({ app }) => {
    const path = process.getBuiltinModule('node:path');
    const require = process.getBuiltinModule('node:module').createRequire(path.join(app.getAppPath(), 'package.json'));
    const state = { recording: false, views: [], captures: [], close: [] };
    const recordClose = label => { state.close.push(label); require('node:fs').writeFileSync(path.join(process.env.CONFIG_DIR, 'shutdown-trace.json'), JSON.stringify(state.close)); };
    for (const name of ['before-quit', 'will-quit', 'quit']) app.on(name, () => recordClose(name));
    const measure = (Class, method, key) => {
      const original = Class.prototype[method];
      Class.prototype[method] = async function(...args) {
        const start = performance.now(), recording = state.recording;
        const result = await original.apply(this, args);
        if (recording) state[key].push({ ms: performance.now() - start, bytes: result?.screenshot?.length || (typeof result === 'string' ? result.length : 0) });
        return result;
      };
    };
    measure(require('./tools/browser/session.mjs').BrowserSessionManager, 'view', 'views');
    measure(require('./tools/browser/playwright.mjs').PlaywrightBrowserAdapter, 'preview', 'captures');
    const Engine = require('./desktop/electron/engine.mjs').DesktopEngine, close = Engine.prototype.close;
    Engine.prototype.close = async function(...args) {
      const stages = [[this.scheduler, 'stop'], [this.channels, 'stopAll'], [this.browserManager, 'close'], [this.mcp, 'closeAll']];
      for (const [object, method] of stages) if (object) {
        const original = object[method]; object[method] = async function(...args) { recordClose(`${method}:start`); const value = await original.apply(this, args); recordClose(`${method}:end`); return value; };
      }
      recordClose('engine:start'); const result = await close.apply(this, args); recordClose('engine:end'); return result;
    };
    const Companion = require('./desktop/electron/companion-capture.mjs').CompanionCapture, companionClose = Companion.prototype.close;
    Companion.prototype.close = async function(...args) { recordClose('companion:start'); const result = await companionClose.apply(this, args); recordClose('companion:end'); return result; };
    return state;
  });
  application.progressMetrics = metrics;
  const errors = []; page.on('pageerror', error => errors.push(error.message));
  await page.waitForFunction(() => Boolean(window.ankita));
  const initialized = await page.evaluate(() => window.ankita.invoke('initialize'));
  console.log('PROGRESS_CHECK_INITIALIZED');
  const owner = initialized.teammates[0].id;
  await page.evaluate(() => {
    window.progressEvents = [];
    window.ankita.onEvent(event => { if (event.type === 'browser-state') window.progressEvents.push(event); });
    window.longFrames = [];
    new PerformanceObserver(list => window.longFrames.push(...list.getEntries().map(entry => entry.duration))).observe({ type: 'longtask', buffered: false });
  });
  await page.evaluate(() => window.ankita.invoke('browserPluginSetEnabled', { mode: 'isolated', enabled: true }));
  await page.getByRole('button', { name: /Chief/ }).first().click();
  await page.getByRole('textbox', { name: 'Message Chief', exact: true }).fill(TASK);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  const pane = page.getByRole('complementary', { name: 'Live browser' }); await pane.waitFor();
  await pane.getByText(browserNotice(new Error('Unknown browser ref')).message, { exact: true }).waitFor();
  assert.equal(await pane.locator('.browser-stage-error.is-recovering').getAttribute('role'), 'status');
  assert.equal(await pane.locator('.browser-stage-status.error').count(), 0);
  await pane.getByRole('img', { name: /Live browser page/ }).waitFor();
  await page.screenshot({ path: path.join(directory, 'screenshots/recovery-reference.png') });
  const profiles = {};
  const profile = async name => {
    await metrics.evaluate(state => { state.recording = true; state.views = []; state.captures = []; });
    await page.evaluate(() => { window.longFrames = []; });
    await page.waitForTimeout(LIMITS.profile);
    const backend = await metrics.evaluate(state => { state.recording = false; return { views: state.views, captures: state.captures }; });
    assert.ok(backend.views.length, `${name}: actual preview calls were observed`);
    const summarize = samples => { const sorted = samples.map(sample => sample.ms).sort((a, b) => a - b); return { samples: sorted.length, medianMs: sorted[Math.floor(sorted.length / 2)] || 0, p95Ms: sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * .95))] || 0, frameChars: samples.reduce((sum, sample) => sum + sample.bytes, 0) }; };
    const renderer = await page.evaluate(async () => {
      const start = performance.now(); await window.ankita.invoke('browserSessionView');
      return { visibility: document.visibilityState, ipcRoundTripMs: performance.now() - start, longTasks: window.longFrames.length, longestTaskMs: Math.max(0, ...window.longFrames) };
    });
    profiles[name] = { view: summarize(backend.views), capture: summarize(backend.captures), renderer };
  };
  await profile('visibleAgentRunning');
  const shortcut = process.platform === 'darwin' ? 'Meta+Shift+b' : 'Control+Shift+b';
  await page.keyboard.press(shortcut); await page.waitForFunction(() => document.querySelector('.browser-stage').classList.contains('is-closed'));
  await profile('paneHidden');
  await page.keyboard.press(shortcut);
  const mainWindow = await application.browserWindow(page);
  await mainWindow.evaluate(window => window.minimize());
  const backgroundWindow = await mainWindow.evaluate(window => ({ minimized: window.isMinimized(), visible: window.isVisible(), focused: window.isFocused() }));
  assert.equal(backgroundWindow.visible, false, 'actual app is hidden to its tray after minimize');
  await profile('windowBackgrounded');
  profiles.windowBackgrounded.nativeWindow = backgroundWindow;
  assert.ok(profiles.windowBackgrounded.capture.samples <= Math.ceil(LIMITS.profile / BROWSER_PREVIEW_POLL.hidden) + 1, 'native hidden window uses the bounded background preview cadence');
  console.log('BROWSER_PREVIEW_PROFILE_CAPTURED', JSON.stringify(profiles));
  await mainWindow.evaluate(window => { window.restore(); window.show(); window.focus(); });
  resumeRecovery();
  const dialog = pane.getByRole('region', { name: 'Page dialog' }); await dialog.waitFor();
  await dialog.getByText(QUESTION, { exact: true }).waitFor();
  assert.equal(writes, 0);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  assert.equal(await pane.locator('.browser-stage-progress > i').evaluate(node => getComputedStyle(node).animationName), 'none');
  assert.equal(await pane.locator('.browser-stage-progress small').innerText(), '1 / 2');
  await dialog.getByRole('textbox', { name: 'Reply to page prompt' }).fill(RESPONSE);
  await page.screenshot({ path: path.join(directory, 'screenshots/dialog-attention.png') });
  await dialog.getByRole('button', { name: 'Continue', exact: true }).click();
  await dialog.waitFor({ state: 'hidden' });
  await pane.getByRole('button', { name: 'Hand back', exact: true }).click();
  resumeDialog();
  await page.getByText(DONE, { exact: true }).first().waitFor({ timeout: LIMITS.launch });
  assert.equal(writes, 1); assert.equal(saved, RESPONSE);
  const events = await page.evaluate(() => window.progressEvents);
  assert.ok(events.every(event => event.threadId === owner));
  assert.ok(!JSON.stringify(events).includes(RESPONSE)); assert.ok(!JSON.stringify(events).includes(QUESTION));
  const phases = [...new Set(events.map(event => event.state.progress?.phase).filter(Boolean))];
  for (const phase of ['thinking', 'reading', 'acting', 'checking', 'recovering', 'waiting-for-user', 'finished']) assert.ok(phases.includes(phase), `${phase}: actual runtime event`);
  await pane.getByRole('button', { name: 'Stop', exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('.app-shell').classList.contains('browser-visible'));
  assert.ok(await page.evaluate(() => window.progressEvents.some(event => event.state.progress?.phase === 'stopped')));
  assert.deepEqual(fixtureErrors, []); assert.deepEqual(errors, []);
  fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify({ developed, requests: requests.length, phases, writes, profiles }, null, 2));
  console.log('BROWSER_PROGRESS_DESKTOP_LIVE', JSON.stringify({ developed, requests: requests.length, phases, writes, publicInputLeak: false, reducedMotion: true, stop: true }));
  console.log('BROWSER_PREVIEW_PROFILE', JSON.stringify(profiles));
  console.log(`Artifacts: ${directory}`);
} catch (error) {
  console.error('BROWSER_PROGRESS_DESKTOP_FAILURE', error.stack, JSON.stringify({ requests: requests.length, fixtureErrors }));
  throw error;
} finally {
  resumeRecovery(); resumeDialog();
  if (application) {
    const page = await application.firstWindow().catch(() => null);
    await page?.evaluate(() => window.ankita.invoke('browserSessionStop')).catch(() => {});
    // Keep the inspector attached while the app drains; Playwright otherwise detaches immediately after app.quit.
    await application.evaluate(({ app }) => app.quit()).catch(() => {});
    console.log('DISPOSABLE_SHUTDOWN_REQUESTED');
    await new Promise(resolve => setTimeout(resolve, BROWSER_PREVIEW_POLL.idle));
    console.log('DISPOSABLE_SHUTDOWN_BEFORE_DETACH', JSON.stringify(await application.progressMetrics?.evaluate(state => state.close).catch(() => ['inspector unavailable'])));
    let deadline;
    try { await Promise.race([application.close(), new Promise((_, reject) => { deadline = setTimeout(async () => {
      const stages = JSON.parse(fs.readFileSync(path.join(configDirectory, 'shutdown-trace.json'), 'utf8'));
      console.error('DISPOSABLE_SHUTDOWN_STAGES', JSON.stringify(stages));
      await application.evaluate(({ app }) => app.exit(1)).catch(() => {});
      reject(new Error('Disposable Electron shutdown timed out'));
    }, LIMITS.close); })]); }
    finally { clearTimeout(deadline); if (launchedProcess?.exitCode === null) launchedProcess.kill(); }
    assert.equal(launchedProcess.exitCode, 0, 'normal quit after native minimize closes the resident island and app');
    console.log('DISPOSABLE_SHUTDOWN_OK');
  }
  server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  assert.equal(fs.realpathSync(path.dirname(directory)), fs.realpathSync(os.tmpdir()));
  if (!process.argv.includes('--keep-artifacts')) await fs.promises.rm(directory, { recursive: true, force: true, maxRetries: LIMITS.cleanupRetries, retryDelay: LIMITS.cleanupDelay });
}
