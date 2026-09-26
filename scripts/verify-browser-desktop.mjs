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

// This is a disposable packaged-app check, using installed Electron/dependencies only.
// It uses a local scripted provider and never installs packages or uses personal configuration.
const require = createRequire(import.meta.url);
const ROOT = fileURLToPath(new URL('..', import.meta.url));
const HOST = '127.0.0.1';
const MODEL = 'desktop-verification-model';
// Milliseconds: bounded app launch/UI actions and transient Windows file-lock cleanup.
const APP_TIMEOUT_MS = 45_000;
const ACTION_TIMEOUT_MS = 10_000;
const CLEANUP_RETRIES = 10;
const CLEANUP_RETRY_MS = 100;
const THEMES = ['mono', 'slate', 'graphite'];
// Tokens: ample fixture context so this check measures IPC/packaging rather than shedding.
const MODEL_CONTEXT_TOKENS = 131072;
const TASK = 'Complete the disposable browser form and inspect its screenshot.';
const COMPLETION = 'Packaged form task complete';
const FORM = '<title>Packaged browser form</title><label>Origin <input></label><button onclick="document.querySelector(\'main\').textContent=\'Confirmed packaged form\'">Search</button><main></main>';
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-packaged-browser-'));
const configDirectory = path.join(directory, 'config');
const userData = path.join(directory, 'user-data');
const screenshots = path.join(directory, 'screenshots');
fs.mkdirSync(configDirectory); fs.mkdirSync(screenshots);
const modelRequests = [];
const fixtureErrors = [];
let base;
let resumeRecovery;
const recoveryGate = new Promise(resolve => { resumeRecovery = resolve; });
const server = http.createServer(async (request, response) => {
  if (request.url === '/v1/models') {
    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ data: [{ id: MODEL, name: MODEL, context_length: MODEL_CONTEXT_TOKENS }] }));
    return;
  }
  if (request.url === '/v1/chat/completions') {
    try {
      const chunks = []; for await (const chunk of request) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      modelRequests.push(body);
      const previous = body.messages.findLast(message => message.role === 'tool')?.content || '';
      const ref = name => previous.split('\n').find(line => line.includes(name) && line.includes('[ref='))?.match(/\[ref=([^\]]+)\]/)?.[1];
      const phases = [
        ['find_tools', { query: 'browser' }],
        ['browser', { action: 'open', mode: 'auto', url: `${base}/form` }],
        ['browser', { action: 'act', op: 'click', ref: 'combobox Origin' }],
        ['browser', { action: 'fill_form', fields: [{ ref: ref('Origin'), text: 'Packaged origin' }] }],
        ['browser', { action: 'act', op: 'click', ref: ref('Search') }],
        ['browser', { action: 'read' }],
        ['browser', { action: 'screenshot' }],
      ];
      const phase = modelRequests.length - 1;
      if (phase === 3) await recoveryGate; // Pause only the scripted provider so the recovered UI state is inspectable.
      let delta;
      if (phase < phases.length) {
        const [name, args] = phases[phase];
        delta = { tool_calls: [{ index: 0, id: `packaged-${phase}`, type: 'function', function: { name, arguments: JSON.stringify(args) } }] };
      } else {
        assert.match(previous, /"visionAttached":true/);
        const user = body.messages.findLast(message => message.role === 'user');
        assert.ok(user.content.some(part => part.type === 'image_url' && part.image_url.url.startsWith('data:image/png;base64,')), 'real HTTP request contains screenshot pixels');
        delta = { content: COMPLETION };
      }
      response.writeHead(200, { 'content-type': 'text/event-stream' });
      response.end(`data: ${JSON.stringify({ model: MODEL, choices: [{ index: 0, delta, finish_reason: delta.tool_calls ? 'tool_calls' : 'stop' }] })}\n\ndata: [DONE]\n\n`);
    } catch (error) {
      fixtureErrors.push(error.message);
      response.writeHead(500, { 'content-type': 'application/json' }); response.end(JSON.stringify({ error: { message: error.message } }));
    }
    return;
  }
  response.writeHead(200, { 'content-type': 'text/html' }); response.end(FORM);
});
await new Promise(resolve => server.listen(0, HOST, resolve));
base = `http://${HOST}:${server.address().port}`;
new DesktopSettingsStore(path.join(configDirectory, 'desktop-settings.json')).update({ provider: 'custom', model: MODEL, customApiBase: `${base}/v1`, customApiKey: '', composioApiKey: '', username: 'Verification', profileSetupDone: true, appearance: 'graphite' });
fs.writeFileSync(path.join(configDirectory, 'config.env'), 'ALLOW_PRIVATE_HOSTS=1\nMEMORY_CONSOLIDATION=0\nAUTO_APPROVE=1\n');
let application;
let appOutput;
let diagnostics = '';
try {
  const packageOption = process.argv.indexOf('--package-dir');
  if (packageOption >= 0) appOutput = path.resolve(process.argv[packageOption + 1]);
  else await build({
    targets: Platform.current().createTarget('dir'), publish: 'never',
    projectDir: ROOT,
    config: {
      extends: path.join(ROOT, 'desktop', 'packaging', 'electron-builder.yml'),
      directories: { output: path.join(directory, 'package') },
      electronDist: path.dirname(require('electron')),
      npmRebuild: false,
      win: { signAndEditExecutable: false },
      afterPack: context => { appOutput = context.appOutDir; },
    },
  });
  assert.ok(appOutput, 'builder supplied the unpacked app directory');
  const packagedExecutable = process.platform === 'win32'
    ? fs.readdirSync(appOutput).find(name => name.endsWith('.exe'))
    : fs.readdirSync(appOutput).find(name => !name.includes('.') && fs.statSync(path.join(appOutput, name)).isFile());
  assert.ok(packagedExecutable, 'packaged executable discovered');
  const environment = { ...process.env, CONFIG_DIR: configDirectory, ALLOW_PRIVATE_HOSTS: '1', PORTABLE_EXECUTABLE_DIR: appOutput, TOOL_PROVIDER: '', TOOL_MODEL: '', TOOL_API_BASE: '', TOOL_API_KEY: '' };
  // Playwright must launch Electron as an app, not inherit a parent Node-mode flag.
  delete environment.ELECTRON_RUN_AS_NODE;
  delete environment.ANKITA_DESKTOP_DEV_URL;
  application = await electron.launch({ executablePath: path.join(appOutput, packagedExecutable), args: [`--user-data-dir=${userData}`], cwd: configDirectory, env: environment, timeout: APP_TIMEOUT_MS });
  application.process().stderr?.on('data', chunk => { diagnostics = (diagnostics + chunk.toString()).slice(-10_000); });
  const runtime = await application.evaluate(({ app, BrowserWindow }) => ({ packaged: app.isPackaged, appPath: app.getAppPath(), userData: app.getPath('userData'), ready: app.isReady(), windows: BrowserWindow.getAllWindows().length }));
  assert.equal(runtime.packaged, true);
  assert.ok(runtime.appPath.endsWith('app.asar'), runtime.appPath);
  assert.equal(path.resolve(runtime.userData), path.resolve(userData), 'user data stays in the disposable directory');
  console.log(`PACKAGED_RUNTIME_OK: actual executable, app.asar, isolated config/user-data; ready=${runtime.ready}, windows=${runtime.windows}`);
  const page = await application.firstWindow({ timeout: APP_TIMEOUT_MS });
  page.setDefaultTimeout(ACTION_TIMEOUT_MS);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.waitForFunction(() => Boolean(window.ankita));
  const overview = await page.evaluate(() => window.ankita.invoke('initialize'));
  assert.equal(overview.settings.model, MODEL, JSON.stringify(overview.settings));
  await page.getByRole('button', { name: /plugins/i }).first().click();
  await page.getByRole('heading', { name: 'By Ankita team' }).waitFor();
  for (const theme of THEMES) {
    await page.getByRole('button', { name: /^(Settings|Open settings)$/ }).last().click();
    await page.getByRole('button', { name: 'Appearance', exact: true }).click();
    await page.getByRole('button', { name: new RegExp(`^${theme[0].toUpperCase()}${theme.slice(1)}`) }).click();
    await page.getByRole('button', { name: 'Apply appearance' }).click();
    await page.waitForFunction(value => document.documentElement.dataset.theme === value, theme);
    await page.getByRole('button', { name: 'Close settings' }).click();
    const tokenMatches = await page.evaluate(() => {
      const marker = document.createElement('span'); document.body.append(marker);
      marker.style.color = 'var(--gold-light)';
      const matches = getComputedStyle(marker).color === getComputedStyle(document.querySelector('.browser-mark')).color;
      marker.remove(); return matches;
    });
    assert.equal(tokenMatches, true, `${theme}: browser card uses global appearance token`);
    await page.screenshot({ path: path.join(screenshots, `plugins-${theme}.png`) });
  }
  console.log('PACKAGED_THEME_OK: mono, slate, graphite update real browser plugin cards');
  await page.evaluate(() => window.ankita.invoke('browserPluginSetEnabled', { mode: 'isolated', enabled: true }));
  await page.getByRole('button', { name: /Chief/ }).first().click();
  await page.getByRole('textbox', { name: 'Message Chief', exact: true }).fill(TASK);
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await page.getByRole('complementary', { name: 'Live browser' }).waitFor();
  await page.waitForFunction(() => JSON.parse(localStorage.getItem('ankita.ui')).sidebarOpen === false);
  const browserPane = page.getByRole('complementary', { name: 'Live browser' });
  await browserPane.getByText('The page changed. Ankita can refresh its controls and continue.', { exact: true }).waitFor();
  await browserPane.getByRole('img', { name: /Live browser page/ }).waitFor();
  assert.equal(await browserPane.getByRole('button', { name: 'Take control', exact: true }).isEnabled(), true);
  assert.ok(!(await browserPane.innerText()).includes('[ref='));
  assert.ok(!(await browserPane.innerText()).includes('Connection required'));
  await page.screenshot({ path: path.join(screenshots, 'browser-recovered-ref.png') });
  resumeRecovery();
  await page.getByText(COMPLETION, { exact: true }).first().waitFor({ timeout: APP_TIMEOUT_MS });
  await page.getByRole('img', { name: /Live browser page/ }).waitFor();
  assert.equal(modelRequests.length, 8);
  assert.deepEqual(fixtureErrors, []);
  await page.screenshot({ path: path.join(screenshots, 'browser-stage.png') });
  await page.getByRole('button', { name: 'Take control', exact: true }).click();
  await page.getByRole('button', { name: 'Hand back', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Hand back', exact: true }).click();
  await page.getByRole('button', { name: 'Take control', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('.app-shell').classList.contains('browser-visible'));
  console.log('PACKAGED_AGENT_HTTP_OK: 8 actual HTTP/SSE model rounds; stale-ref recovery, form submitted/read back; PNG pixels serialized');
  console.log('PACKAGED_SIDEBAR_RECOVERY_OK: real stale-ref tool result keeps live pixels and control; snapshot/code excluded from sidebar');
  console.log('PACKAGED_STAGE_OK: live image, automatic sidebar collapse, Take control/Hand back, Stop');
  // Inspector evaluations have no dynamic-import callback. Create the normal
  // packaged require in main and keep it as a handle for shipped ESM modules.
  const packagedRequire = await application.evaluateHandle(({ app }) => {
    const path = process.getBuiltinModule('node:path');
    return process.getBuiltinModule('node:module').createRequire(path.join(app.getAppPath(), 'package.json'));
  });
  // Load the shipped modules in the actual packaged Electron main process.
  // Use a local form; no agent/model-provider decisions are simulated as real LLM work.
  const result = await packagedRequire.evaluate(async (require, { url, cwd }) => {
    const browser = require('./tools/browser/browser.mjs');
    const ctx = { cwd, config: { allowPrivateHosts: true } };
    const ref = (output, name) => output.split('\n').find(line => line.includes(name) && line.includes('[ref='))?.match(/\[ref=([^\]]+)\]/)?.[1];
    const opened = await browser.run({ action: 'open', mode: 'auto', url }, ctx);
    const filled = await browser.run({ action: 'fill_form', fields: [{ ref: ref(opened, 'Origin'), text: 'Packaged origin' }] }, ctx);
    const clicked = await browser.run({ action: 'act', op: 'click', ref: ref(filled, 'Search') }, ctx);
    const read = await browser.run({ action: 'read' }, ctx);
    const shot = JSON.parse(await browser.run({ action: 'screenshot' }, ctx));
    await browser.manager().close();
    return { opened, filled, clicked, read, shot };
  }, { url: `${base}/form`, cwd: configDirectory });
  assert.match(result.opened, /Origin/);
  assert.match(result.filled, /Filled 1 fields/);
  assert.match(result.clicked, /click complete/);
  assert.match(result.read, /Confirmed packaged form/);
  assert.equal(result.shot.type, 'browser_screenshot');
  assert.ok(fs.statSync(result.shot.path).size > 0);
  console.log('PACKAGED_BROWSER_LIVE_OK: shipped open -> fill_form -> click -> confirmed read -> screenshot');
  const jobResult = await packagedRequire.evaluate(async (require, cwd) => {
    const load = file => require(`./tools/${file}`);
    const command = await load('process/run-command.mjs');
    const input = await load('process/job-input.mjs');
    const wait = await load('process/job-wait.mjs');
    const ctx = { cwd, state: {} };
    const waitMs = 10_000; // Milliseconds: bounded shipped command/crash checks.
    const options = { background: true, env: { ELECTRON_RUN_AS_NODE: '1' } };
    const commandFor = source => {
      const argument = Buffer.from(source).toString('base64');
      const invocation = process.platform === 'win32'
        ? `& '${process.execPath.replaceAll("'", "''")}' -e \"eval(Buffer.from('${argument}','base64').toString())\"`
        : `'${process.execPath.replaceAll("'", "'\\''")}' -e \"eval(Buffer.from('${argument}','base64').toString())\"`;
      // A stdout pipeline makes PowerShell wait for the GUI executable and
      // preserve its native exit status while forwarding output.
      return process.platform === 'win32' ? `${invocation} | ForEach-Object { $_ }; exit $LASTEXITCODE` : invocation;
    };
    const source = "console.log('packaged-start');process.stdin.on('data',data=>process.stdout.write(data));process.stdin.on('end',()=>process.exit(7));";
    const started = await command.run({ command: commandFor(source), ...options }, ctx);
    const job = [...ctx.state.jobs.values()][0];
    const inputReceipt = await input.run({ job_id: job.id, text: 'packaged-stdin\n', eof: true }, ctx);
    await wait.run({ job_id: job.id, timeout_ms: waitMs }, ctx);
    const normal = { started, inputReceipt, done: job.done, code: job.code, error: job.error, output: job.out.toString() };
    const crashCtx = { cwd, state: {} };
    const { once } = require('node:events');
    const { processIdentity } = await load('shared/_process.mjs');
    await command.run({ command: commandFor("console.log('crash-leaf:'+process.pid);setInterval(()=>{},1000);"), ...options }, crashCtx);
    const crashJob = [...crashCtx.state.jobs.values()][0];
    await crashJob.child.identityReady;
    if (!/crash-leaf:/.test(crashJob.out.toString())) await once(crashJob.child.stdout, 'data');
    const leaf = Number(crashJob.out.toString().match(/crash-leaf:(\d+)/)?.[1]);
    const pids = [crashJob.child.pid, leaf];
    const identities = await Promise.all(pids.map(pid => processIdentity(pid)));
    const alive = pid => { try { process.kill(pid, 0); return true; } catch { return false; } };
    let crash;
    try {
      await crashJob.child.worker.terminate();
      await wait.run({ job_id: crashJob.id, timeout_ms: waitMs }, crashCtx);
      crash = { done: crashJob.done, error: crashJob.error, rootAlive: alive(pids[0]), leafAlive: alive(leaf) };
    } finally {
      // Fixture-only emergency cleanup never kills a PID whose identity changed.
      for (const [index, pid] of pids.entries()) {
        if (!alive(pid)) continue;
        const current = await processIdentity(pid).catch(() => null);
        if (current?.identity === identities[index].identity && current.name === identities[index].name) {
          await command.killTree({ pid, exitCode: null, signalCode: null });
        }
      }
    }
    return { ...normal, crash };
  }, configDirectory);
  assert.equal(jobResult.done, true, JSON.stringify(jobResult));
  assert.doesNotMatch(jobResult.inputReceipt, /^Error:/, JSON.stringify(jobResult));
  assert.equal(jobResult.code, 7, JSON.stringify(jobResult));
  assert.match(jobResult.output, /packaged-start/);
  assert.match(jobResult.output, /packaged-stdin/);
  console.log('PACKAGED_COMMAND_OK: shipped launcher preserves stdin/EOF, output and shell exit code 7');
  assert.equal(jobResult.crash.done, true, JSON.stringify(jobResult.crash));
  assert.match(jobResult.crash.error, /launcher.*exited unexpectedly/i);
  assert.equal(jobResult.crash.rootAlive, false, JSON.stringify(jobResult.crash));
  assert.equal(jobResult.crash.leafAlive, false, JSON.stringify(jobResult.crash));
  console.log('PACKAGED_WORKER_CRASH_OK: failed launcher cleans its identity-checked shell and owned child');
  const installer = await packagedRequire.evaluate(async require => {
    const path = require('node:path');
    const { spawn } = require('node:child_process');
    const cli = path.join(path.dirname(require.resolve('playwright/package.json')), 'cli.js');
    return new Promise((resolveResult, reject) => {
      let output = '';
      // Exercise the install entry point and executable without downloading.
      const child = spawn(process.execPath, [cli, 'install', '--dry-run', 'chromium'], { env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' }, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
      child.stdout.on('data', chunk => { output += chunk; });
      child.stderr.on('data', chunk => { output += chunk; });
      child.once('error', reject);
      child.once('close', code => resolveResult({ code, output }));
    });
  });
  assert.equal(installer.code, 0, installer.output);
  assert.match(installer.output, /chromium/i);
  console.log('PACKAGED_CHROMIUM_SETUP_OK: shipped Playwright install --dry-run resolves its browser/cache paths (no download)');
  assert.deepEqual(errors, []);
  console.log(`PACKAGED_DESKTOP_VERIFICATION_OK; screenshots=${screenshots}`);
} catch (error) {
  console.error(`PACKAGED_FAILURE: ${error.message}\n${diagnostics}`);
  if (application) {
    const startup = await application.evaluate(async ({ app, BrowserWindow }) => {
      const state = { ready: app.isReady(), windows: BrowserWindow.getAllWindows().length };
      // Diagnostic only after failure: observe an already failed main-module
      // import. This never changes a failed result into a successful check.
      try {
        const path = process.getBuiltinModule('node:path');
        const require = process.getBuiltinModule('node:module').createRequire(path.join(app.getAppPath(), 'package.json'));
        require('./desktop/electron/main.mjs');
      } catch (failure) { state.mainError = failure.message; }
      return state;
    }).catch(failure => ({ diagnosticError: failure.message }));
    console.error(`PACKAGED_STARTUP_DIAGNOSTIC: ${JSON.stringify(startup)}`);
  }
  throw error;
} finally {
  await application?.close();
  server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  assert.equal(fs.realpathSync(path.dirname(directory)), fs.realpathSync(os.tmpdir()));
  if (process.argv.includes('--keep-artifacts')) console.log(`Retained verification artifacts: ${directory}`);
  else await fs.promises.rm(directory, { recursive: true, force: true, maxRetries: CLEANUP_RETRIES, retryDelay: CLEANUP_RETRY_MS });
}
