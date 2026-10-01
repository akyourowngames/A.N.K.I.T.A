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
import { CREDENTIAL_STORE_FILENAME } from '../src/integrations/browser-credentials.mjs';
import { IPC_CONTRACT } from '../desktop/shared/version.mjs';
const require = createRequire(import.meta.url);
const ROOT = fileURLToPath(new URL('..', import.meta.url));
const HOST = '127.0.0.1'; // Disposable loopback fixture, never a real account.
const MODEL = 'vault-verification-model';
const SECRET = 'disposable-packaged-vault-secret';
const USERNAME = 'fixture-user';
const TIMEOUT_MS = 45_000; // Bounded app launch, server calls and UI waits.
const ACTION_MS = 12_000;
const LOGIN_BUTTON = 'Submit'; // Fixture's accessible JavaScript login action.
const PUBLIC_OPTION = '--public-login'; // Optional external practice-site verification, never a personal account.
const publicOptionIndex = process.argv.indexOf(PUBLIC_OPTION);
const PUBLIC_LOGIN_URL = publicOptionIndex < 0 ? null : new URL(process.argv[publicOptionIndex + 1]).href;
const PUBLIC_USERNAME = 'student', PUBLIC_PASSWORD = 'Password123'; // Public dummy account published by Practice Test Automation.
const LOGIN_HTML = `<title>Disposable sign-in</title><div class="login"><label>Username<input name="username" autocomplete="username"></label><label>Password<input name="password" type="password" autocomplete="current-password"></label><button>${LOGIN_BUTTON}</button><p role="alert"></p></div><script>document.querySelector('.login button').onclick=async event=>{event.preventDefault();const group=event.currentTarget.parentElement;const result=await fetch('/authenticate',{method:'POST',body:JSON.stringify({username:group.querySelector('[name=username]').value,password:group.querySelector('[name=password]').value,mfa:location.pathname==='/mfa'})});const text=await result.text();if(result.ok)document.body.innerHTML=text;else document.querySelector('[role=alert]').textContent=text;}</script>`;
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-packaged-vault-'));
const configDirectory = path.join(directory, 'config'), userData = path.join(directory, 'user-data');
fs.mkdirSync(configDirectory);
let base, authCount = 0;
const modelRequests = [], fixtureErrors = [];
const server = http.createServer(async (request, response) => {
  if (request.url === '/v1/models') { response.setHeader('content-type', 'application/json'); return response.end(JSON.stringify({ data: [{ id: MODEL, context_length: 131072 }] })); }
  if (request.url === '/v1/chat/completions') {
    try {
      const chunks = []; for await (const chunk of request) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks).toString()); modelRequests.push(body);
      const userIndex = body.messages.findLastIndex(message => message.role === 'user');
      const task = String(body.messages[userIndex]?.content || '');
      const results = body.messages.slice(userIndex + 1).filter(message => message.role === 'tool');
      const phase = results.length;
      const page = task.includes('takeover') ? '/mfa' : task.includes('denied page') ? '/denied' : task.includes('blank page') ? '/blank' : '/login';
      const url = task.includes('public sign-in') ? PUBLIC_LOGIN_URL : `${base}${page}`;
      const select = result => {
        let snapshot = '';
        for (const line of String(result?.content || '').split('\n')) { try { const value = JSON.parse(line); if (value.type === 'browser_login') snapshot = value.snapshot || ''; } catch {} }
        const ref = label => snapshot.split('\n').find(line => line.includes(label))?.match(/\[ref=([^\]]+)\]/)?.[1];
        return ['browser', { action: 'login', website: url, credential_fields: [{ ref: ref('Username'), credential: 'username' }, { ref: ref('Password'), credential: 'password' }], submit_ref: ref(LOGIN_BUTTON) }];
      };
      const requestLogin = ['browser', { action: 'login', website: url, ...(task.includes('local denial') ? { mode: 'local' } : {}) }];
      const read = ['browser', { action: 'read' }];
      const steps = [task.includes('external routing') ? ['mcp__external-playwright__browser_navigate', { url }] : ['find_tools', { query: 'browser' }], ['browser', { action: 'open', mode: 'isolated', url }]];
      if (!/(?:denied|blank) page/.test(task)) {
        steps.push(requestLogin);
        let cancelled = false;
        for (const line of String(results[2]?.content || '').split('\n')) { try { if (JSON.parse(line).status === 'cancelled') cancelled = true; } catch {} }
        if (!cancelled && !task.includes('local denial')) {
          steps.push(select(results[2]));
          if (task.includes('retry')) steps.push(read, requestLogin, select(results[5]));
          if (task.includes('takeover')) steps.push(requestLogin);
        }
      }
      steps.push(read);
      const delta = phase < steps.length ? { tool_calls: [{ index: 0, id: `vault-${modelRequests.length}`, type: 'function', function: { name: steps[phase][0], arguments: JSON.stringify(steps[phase][1]) } }] } : { content: `Completed ${task}` };
      response.writeHead(200, { 'content-type': 'text/event-stream' });
      return response.end(`data: ${JSON.stringify({ model: MODEL, choices: [{ index: 0, delta, finish_reason: delta.tool_calls ? 'tool_calls' : 'stop' }] })}\n\ndata: [DONE]\n\n`);
    } catch (error) { fixtureErrors.push(error.message); response.statusCode = 500; return response.end('Fixture failed'); }
  }
  if (request.url === '/denied') { response.statusCode = 403; return response.end(); }
  if (request.url === '/blank') { response.setHeader('content-type', 'text/html'); return response.end('<html><body></body></html>'); }
  if (request.url === '/authenticate') {
    const chunks = []; for await (const chunk of request) chunks.push(chunk);
    const value = JSON.parse(Buffer.concat(chunks).toString()); authCount++;
    response.setHeader('content-type', 'text/html');
    if (value.username !== USERNAME || value.password !== SECRET) { response.statusCode = 401; return response.end('Incorrect login'); }
    return response.end(value.mfa ? '<h1>Extra verification</h1><button style="position:absolute;left:20px;top:80px;width:220px;height:40px" onclick="document.body.innerHTML=\'<h1>Signed in</h1><button>Sign out</button>\'">Complete verification</button>' : '<h1>Signed in</h1><button>Sign out</button>');
  }
  response.setHeader('content-type', 'text/html'); response.end(LOGIN_HTML);
});
await new Promise(resolve => server.listen(0, HOST, resolve));
base = `http://${HOST}:${server.address().port}`;
new DesktopSettingsStore(path.join(configDirectory, 'desktop-settings.json')).update({ provider: 'custom', model: MODEL, customApiBase: `${base}/v1`, username: 'Verification', profileSetupDone: true });
fs.writeFileSync(path.join(configDirectory, 'config.env'), 'ALLOW_PRIVATE_HOSTS=1\nMEMORY_CONSOLIDATION=0\nAUTO_APPROVE=1\n');
let application, output, diagnostics = '';
try {
  const option = process.argv.indexOf('--package-dir');
  if (option >= 0) output = path.resolve(process.argv[option + 1]);
  else await build({ targets: Platform.current().createTarget('dir'), publish: 'never', projectDir: ROOT, config: { extends: path.join(ROOT, 'desktop/packaging/electron-builder.yml'), directories: { output: path.join(directory, 'package') }, electronDist: path.dirname(require('electron')), npmRebuild: false, win: { signAndEditExecutable: false }, afterPack: context => { output = context.appOutDir; } } });
  const executable = fs.readdirSync(output).find(name => process.platform === 'win32' ? name.endsWith('.exe') : !name.includes('.') && fs.statSync(path.join(output, name)).isFile());
  assert.ok(executable);
  const env = { ...process.env, CONFIG_DIR: configDirectory, ALLOW_PRIVATE_HOSTS: '1', PORTABLE_EXECUTABLE_DIR: output, TOOL_PROVIDER: '', TOOL_MODEL: '', TOOL_API_BASE: '', TOOL_API_KEY: '' };
  delete env.ELECTRON_RUN_AS_NODE; delete env.ANKITA_DESKTOP_DEV_URL;
  application = await electron.launch({ executablePath: path.join(output, executable), args: [`--user-data-dir=${userData}`], cwd: configDirectory, env, timeout: TIMEOUT_MS });
  application.process().stderr?.on('data', chunk => { diagnostics = (diagnostics + chunk.toString()).slice(-10_000); });
  const packagedRequire = await application.evaluateHandle(({ app }) => process.getBuiltinModule('node:module').createRequire(process.getBuiltinModule('node:path').join(app.getAppPath(), 'package.json')));
  const runtime = await packagedRequire.evaluate(async (require, { url, timeout, loginButton }) => {
    const { app, safeStorage } = require('electron');
    const path = require('node:path'), { spawn } = require('node:child_process');
    const { chromeMcpCommand, CHROME_MCP_VERSION } = require('./src/integrations/browser-plugins.mjs');
    const { McpClient } = require('./src/integrations/mcp-client.mjs');
    const { chromium } = require('playwright');
    const launch = chromeMcpCommand({ connection: 'profile' });
    // Reproduce the old launch path inside the actual packaged runtime: no Node flag.
    const legacyEnv = { ...process.env }; delete legacyEnv.ELECTRON_RUN_AS_NODE;
    const legacy = await new Promise((resolve, reject) => {
      const child = spawn(process.execPath, [`--user-data-dir=${app.getPath('userData')}`, launch.args[0]], { env: legacyEnv, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
      let stdout = ''; child.stdout.on('data', bytes => { stdout += bytes.toString(); });
      const timer = setTimeout(() => { child.kill(); reject(new Error('Legacy launch did not exit')); }, timeout);
      child.once('error', reject); child.once('exit', code => { clearTimeout(timer); resolve({ code, protocol: stdout.includes('protocolVersion') }); });
    });
    const client = new McpClient({ id: 'packaged-runtime-check', ...launch, args: [...launch.args, '--headless', `--executablePath=${chromium.executablePath()}`, `--user-data-dir=${path.join(app.getPath('userData'), 'chrome-check')}`], env: { PATH: '', npm_config_cache: path.join(app.getPath('userData'), 'empty-npm-cache') }, initTimeoutMs: timeout, requestTimeoutMs: timeout });
    let bridge;
    try {
      await client.connect();
      const opened = await client.callTool('new_page', { url });
      const pageId = Number(opened.text.match(/^(\d+):.*\[selected\]/m)?.[1]);
      const snapshot = await client.callTool('take_snapshot', { pageId });
      if (opened.isError || snapshot.isError || !snapshot.text.includes('Disposable sign-in')) throw new Error(`Packaged Chrome page round trip failed: ${JSON.stringify({ opened, snapshot }).slice(0, 2500)}`);
      bridge = { version: CHROME_MCP_VERSION, tools: client.tools.length, entry: launch.args[0], node: process.versions.node, snapshot: snapshot.text.includes(loginButton) };
    } finally { await client.close(); }
    return { packaged: app.isPackaged, legacy, bridge, encryption: await safeStorage.isAsyncEncryptionAvailable() };
  }, { url: `${base}/login`, timeout: TIMEOUT_MS, loginButton: LOGIN_BUTTON });
  assert.equal(runtime.packaged, true); assert.deepEqual(runtime.legacy, { code: 0, protocol: false }); assert.ok(runtime.bridge.entry.includes('app.asar.unpacked')); assert.ok(runtime.bridge.snapshot); assert.ok(runtime.encryption);
  console.log(`PACKAGED_CHROME_RED_GREEN: legacy exit=${runtime.legacy.code}, no initialize; bundled ${runtime.bridge.version} -> ${runtime.bridge.tools} tools -> CDP page/snapshot; PATH empty, npm cache empty`);
  const page = await application.firstWindow(); page.setDefaultTimeout(ACTION_MS);
  const pageErrors = []; page.on('pageerror', error => pageErrors.push(error.message));
  await page.waitForFunction(() => Boolean(window.ankita));
  const bootstrap = await page.evaluate(() => window.ankita.invoke('initialize')); assert.equal(bootstrap.contract, IPC_CONTRACT);
  const thread = bootstrap.teammates[0]; assert.ok(thread);
  await page.evaluate(() => { window.__vaultEvents = []; window.ankita.onEvent(event => window.__vaultEvents.push(event)); });
  await page.evaluate(() => window.ankita.invoke('browserPluginSetEnabled', { mode: 'isolated', enabled: true }));
  const send = task => page.evaluate(({ id, text }) => window.ankita.invoke('send', { id, text }), { id: thread.id, text: task });
  const waiting = () => page.locator('.secure-store-card').last().getByRole('button', { name: /^(Add|Retry)$/ });
  const complete = task => page.getByText(`Completed ${task}`, { exact: true }).first().waitFor({ timeout: TIMEOUT_MS });
  const enter = async (password = SECRET, save = true, username = USERNAME) => {
    await waiting().click();
    const modal = page.getByRole('dialog', { name: 'Secure credentials store' });
    await modal.getByRole('textbox', { name: 'Username', exact: true }).fill(username);
    await modal.locator('input[name="password"]').fill(password);
    await modal.getByRole('checkbox').setChecked(save);
    await modal.getByRole('button', { name: 'Enter', exact: true }).click();
    await modal.waitFor({ state: 'hidden' });
  };
  await send('cold sign-in'); await waiting().click();
  const modal = page.getByRole('dialog', { name: 'Secure credentials store' });
  assert.equal(await modal.locator('input[name="username"]').evaluate(node => node === document.activeElement), true);
  await modal.getByRole('button', { name: 'Enter', exact: true }).focus(); await page.keyboard.press('Tab');
  assert.equal(await modal.getByRole('button', { name: 'Cancel sign-in' }).evaluate(node => node === document.activeElement), true);
  for (const theme of ['mono', 'slate', 'graphite']) {
    await page.evaluate(value => { document.documentElement.dataset.theme = value; }, theme);
    assert.equal(await modal.evaluate(node => { const probe = document.createElement('span'); probe.style.background = 'var(--surface)'; node.append(probe); const match = getComputedStyle(node).backgroundColor === getComputedStyle(probe).backgroundColor; probe.remove(); return match; }), true);
    await modal.screenshot({ path: path.join(directory, `secure-store-${theme}.png`) });
  }
  await modal.locator('input[name="username"]').fill(USERNAME); await modal.locator('input[name="password"]').fill(SECRET);
  await modal.getByRole('button', { name: 'Show password' }).click(); assert.equal(await modal.locator('input[name="password"]').getAttribute('type'), 'text');
  await modal.getByRole('button', { name: 'Hide password' }).click();
  await modal.getByRole('button', { name: 'Enter', exact: true }).click(); await complete('cold sign-in'); assert.equal(authCount, 1);
  const records = await page.evaluate(() => window.ankita.invoke('secureStoreList')); assert.equal(records.records.length, 1); assert.ok(!JSON.stringify(records).includes(SECRET));
  await send('warm sign-in'); await complete('warm sign-in'); assert.equal(authCount, 2);
  console.log('PACKAGED_VAULT_COLD_WARM_OK: real async OS encryption; secure dialog -> save -> one fill/submit -> confirmed sign-in -> original task resumes; warm has no dialog');
  await page.getByRole('button', { name: 'Show sidebar', exact: true }).click();
  await page.getByRole('button', { name: 'Plugins', exact: true }).click();
  // The vault is a section of Plugins now, not a collapsed disclosure: it loads
  // its rows on mount, so there is nothing to expand.
  await page.getByRole('heading', { name: 'Saved sign-ins' }).waitFor();
  await page.locator('.vault-item').getByText(USERNAME, { exact: true }).waitFor();
  await page.locator('.vault-item').getByRole('button', { name: /^Remove/ }).click();
  await page.locator('.vault-item').waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: /Chief/ }).first().click();
  console.log('PACKAGED_VAULT_MANAGEMENT_OK: Plugins metadata row and Remove update through real IPC');
  await send('cancel sign-in'); await waiting().click(); await page.keyboard.press('Escape'); await complete('cancel sign-in'); assert.equal(authCount, 2);
  await send('stop sign-in'); await waiting().waitFor(); await page.evaluate(id => window.ankita.invoke('cancel', { id }), thread.id);
  await page.waitForFunction(id => window.__vaultEvents.some(event => event.type === 'turn-end' && event.threadId === id && window.__vaultEvents.filter(e => e.type === 'turn-end').length >= 4), thread.id);
  assert.equal(authCount, 2);
  console.log('PACKAGED_VAULT_CANCEL_STOP_OK: Escape/Stop resolve pending requests without fill or save');
  await send('retry sign-in'); await enter('wrong-fixture-password', false); await waiting().waitFor({ timeout: TIMEOUT_MS });
  assert.equal(authCount, 3); await enter(SECRET, false); await complete('retry sign-in'); assert.equal(authCount, 4);
  await send('takeover sign-in'); await enter(SECRET, false);
  await page.locator('.secure-store-card').last().getByRole('button', { name: 'Take control' }).waitFor({ timeout: TIMEOUT_MS });
  await page.locator('.secure-store-card').last().getByRole('button', { name: 'Take control' }).click();
  await page.getByRole('button', { name: 'Hand back', exact: true }).waitFor();
  // Drive a real native click through the stage input IPC, using the fixture's first button position.
  await page.evaluate(() => window.ankita.invoke('browserSessionInput', { kind: 'click', x: 80, y: 90 }));
  await page.getByRole('button', { name: 'Hand back', exact: true }).click(); await complete('takeover sign-in'); assert.equal(authCount, 5);
  console.log('PACKAGED_VAULT_RETRY_TAKEOVER_OK: wrong password submits once; explicit Retry; extra verification via takeover -> hand back -> verified continuation');
  await send('local denial'); await complete('local denial');
  await page.locator('.secure-store-card').last().getByText(/Secure login supports Playwright only/).waitFor();
  assert.equal(authCount, 5);
  fs.writeFileSync(path.join(configDirectory, CREDENTIAL_STORE_FILENAME), '{broken');
  await send('corrupt store'); await enter(SECRET, true);
  await page.locator('.secure-store-card').last().getByText(/Credentials could not be saved/).waitFor();
  await waiting().click();
  const retryModal = page.getByRole('dialog', { name: 'Secure credentials store' });
  assert.equal(await retryModal.getByRole('checkbox').isDisabled(), true);
  await retryModal.locator('input[name="username"]').fill(USERNAME); await retryModal.locator('input[name="password"]').fill(SECRET);
  await retryModal.getByRole('button', { name: 'Enter', exact: true }).click(); await complete('corrupt store'); assert.equal(authCount, 6);
  assert.equal(fs.readFileSync(path.join(configDirectory, CREDENTIAL_STORE_FILENAME), 'utf8'), '{broken');
  console.log('PACKAGED_VAULT_ERRORS_OK: local denial stays visible; corrupt vault preserves file and offers explicit one-time sign-in');
  await send('external routing sign-in'); await enter(SECRET, false); await complete('external routing sign-in');
  assert.equal(authCount, 7);
  assert.ok(!(await page.evaluate(() => window.__vaultEvents)).some(event => event.type === 'browser-state' && event.state.mode === 'external'));
  console.log('PACKAGED_MANAGED_BROWSER_ROUTING_OK: old external MCP call refused; built-in browser activated; native login succeeds; live stage never switches external');
  for (const task of ['denied page', 'blank page']) {
    await send(task); await complete(task);
    const pane = page.getByRole('complementary', { name: 'Live browser' });
    await pane.getByText('Page needs attention', { exact: true }).waitFor();
    assert.equal(await pane.locator('img').count(), 0);
    assert.match(await pane.locator('.browser-stage-status').innerText(), /Needs attention/);
    await pane.screenshot({ path: path.join(directory, `${task.replace(' ', '-')}.png`) });
  }
  console.log('PACKAGED_EMPTY_PAGE_OK: HTTP 403 and unrendered HTTP 200 have a visible load failure; no white frame or Ready status');
  if (PUBLIC_LOGIN_URL) {
    await send('public sign-in'); await waiting().waitFor({ timeout: TIMEOUT_MS }); await enter(PUBLIC_PASSWORD, false, PUBLIC_USERNAME); await complete('public sign-in');
    await page.locator('.secure-store-card').last().getByText('Selected controls filled', { exact: true }).waitFor();
    // The live address list refreshes periodically; await the observed redirect
    // rather than asserting on the preceding tick's cached URL.
    await page.waitForFunction(async () => {
      const session = await window.ankita.invoke('browserSessionView');
      return session.tabs.some(tab => tab.active && new URL(tab.url).pathname.replace(/\/+$/, '') === '/logged-in-successfully');
    }, null, { timeout: TIMEOUT_MS });
    await page.getByRole('complementary', { name: 'Live browser' }).screenshot({ path: path.join(directory, 'public-login-success.png') });
    console.log('PACKAGED_PUBLIC_LOGIN_OK: actual practice-test website -> native secure dialog -> Submit outside form -> visible Log out -> original task resumes');
  }
  const events = await page.evaluate(() => window.__vaultEvents); assert.ok(!JSON.stringify([events, modelRequests]).includes(SECRET));
  for (const name of fs.readdirSync(configDirectory)) if (fs.statSync(path.join(configDirectory, name)).isFile()) assert.ok(!fs.readFileSync(path.join(configDirectory, name), 'utf8').includes(SECRET), name);
  assert.deepEqual(pageErrors, []); assert.deepEqual(fixtureErrors, []);
  console.log('PACKAGED_SECRET_BOUNDARY_OK: IPC public events, model requests, persisted config contain no password; no renderer errors');
  console.log(`BROWSER_VAULT_PACKAGED_OK artifacts=${directory}; package=${output}`);
} catch (error) {
  if (application) {
    const window = await application.firstWindow().catch(() => null);
    console.error('PACKAGED_BROWSER_STATE:', JSON.stringify(await window?.evaluate(async () => { const view = await window.ankita.invoke('browserSessionView'); return { view: { ...view, screenshot: Boolean(view.screenshot) }, text: document.querySelector('.browser-stage')?.innerText }; }).catch(() => null)));
    await window?.screenshot({ path: path.join(directory, 'failure.png') }).catch(() => {});
  }
  console.error(`PACKAGED_VAULT_FAILURE: ${error.stack}\n${diagnostics}\nArtifacts: ${directory}; package: ${output}`); throw error;
}
finally {
  await application?.close().catch(() => {}); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  // Artifacts are retained for review and exact-build reruns; all config/profile data is disposable.
}
