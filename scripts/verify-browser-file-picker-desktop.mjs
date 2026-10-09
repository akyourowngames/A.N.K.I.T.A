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

// Interactive native-picker verification: an operator chooses this generated file,
// cancels the dialog, or chooses it after Stop. No personal files/accounts are used.
const ROOT = path.resolve(fileURLToPath(new URL('..', import.meta.url))), require = createRequire(import.meta.url);
const LIMITS = Object.freeze({ launch: 45_000, action: 30_000, operator: 240_000, poll: 200, shutdownGrace: 2000, close: 10_000 }); // Milliseconds; native consent gets a separate bounded operator wait.
const HOST = '127.0.0.1', MODEL = 'native-file-picker-fixture', CONTEXT = 131072;
const SCENARIOS = Object.freeze(['select', 'cancel', 'stop']);
const option = name => { const index = process.argv.indexOf(name); return index < 0 ? null : process.argv[index + 1]; };
const scenario = option('--scenario') || SCENARIOS[0]; assert.ok(SCENARIOS.includes(scenario), 'known native-picker scenario');
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-picker-desktop-'));
const configDirectory = path.join(directory, 'config'), userData = path.join(directory, 'user-data'); fs.mkdirSync(configDirectory);
const filename = 'selected-fixture.txt', content = 'Generated local native-picker verification document.';
const selectedFile = path.join(directory, filename); fs.writeFileSync(selectedFile, content);
const operatorPath = path.join(directory, 'operator.json'), operatorFinished = path.join(directory, 'operator-finished');
const DONE = 'Native file selection inspected.';
const FORM = '<title>Native upload verification</title><label>Document<input type="file" onchange="document.querySelector(\'main\').textContent=this.files[0]?.name||\'No selection\';if(this.files.length)this.files[0].text().then(text=>fetch(\'/selected\',{method:\'POST\',body:text}))"></label><main>No selection</main>';
let base, application, launchedProcess, packageDirectory, writes = 0, received = '';
const requests = [], fixtureErrors = [];
const server = http.createServer(async (request, response) => {
  if (request.url === '/selected') { const chunks = []; for await (const chunk of request) chunks.push(chunk); received = Buffer.concat(chunks).toString(); writes++; response.end('received'); return; }
  if (request.url === '/v1/models') { response.setHeader('content-type', 'application/json'); response.end(JSON.stringify({ data: [{ id: MODEL, context_length: CONTEXT }] })); return; }
  if (request.url === '/v1/chat/completions') {
    try {
      const chunks = []; for await (const chunk of request) chunks.push(chunk);
      const body = JSON.parse(Buffer.concat(chunks).toString()); requests.push(body);
      const previous = body.messages.findLast(message => message.role === 'tool')?.content || '';
      const ref = previous.split('\n').find(line => line.includes('Document') && line.includes('[ref='))?.match(/\[ref=([^\]]+)\]/)?.[1];
      const phases = [['find_tools', { query: 'browser' }], ['browser', { action: 'open', url: `${base}/form` }], ['browser', { action: 'upload', ref }], ['browser', { action: 'read' }]];
      const phase = requests.length - 1;
      if (phase === phases.length) assert.match(previous, scenario === 'select' ? new RegExp(filename.replaceAll('.', '\\.')) : /No selection/);
      const delta = phase < phases.length ? { tool_calls: [{ index: 0, id: `picker-${phase}`, type: 'function', function: { name: phases[phase][0], arguments: JSON.stringify(phases[phase][1]) } }] } : { content: DONE };
      response.writeHead(200, { 'content-type': 'text/event-stream' });
      response.end(`data: ${JSON.stringify({ model: MODEL, choices: [{ index: 0, delta, finish_reason: delta.tool_calls ? 'tool_calls' : 'stop' }] })}\n\ndata: [DONE]\n\n`);
    } catch (error) { fixtureErrors.push(error.message); response.writeHead(500); response.end('Fixture failed'); }
    return;
  }
  response.setHeader('content-type', 'text/html'); response.end(FORM);
});
await new Promise(resolve => server.listen(0, HOST, resolve)); base = `http://${HOST}:${server.address().port}`;
new DesktopSettingsStore(path.join(configDirectory, 'desktop-settings.json')).update({ provider: 'custom', model: MODEL, customApiBase: `${base}/v1`, customApiKey: '', composioApiKey: '', username: 'Verification', profileSetupDone: true });
fs.writeFileSync(path.join(configDirectory, 'config.env'), 'ALLOW_PRIVATE_HOSTS=1\nMEMORY_CONSOLIDATION=0\nAUTO_APPROVE=1\nBROWSER_RUNTIME_V2=1\n');
try {
  packageDirectory = option('--package-dir');
  if (!packageDirectory) await build({ targets: Platform.current().createTarget('dir'), publish: 'never', projectDir: ROOT,
    config: { extends: path.join(ROOT, 'desktop/packaging/electron-builder.yml'), directories: { output: path.join(directory, 'package') }, electronDist: path.dirname(require('electron')), npmRebuild: false,
      win: { signAndEditExecutable: false }, afterPack: context => { packageDirectory = context.appOutDir; } } });
  const executable = fs.readdirSync(packageDirectory).find(name => process.platform === 'win32' ? name.endsWith('.exe') : !name.includes('.') && fs.statSync(path.join(packageDirectory, name)).isFile()); assert.ok(executable);
  const env = { ...process.env, CONFIG_DIR: configDirectory, ALLOW_PRIVATE_HOSTS: '1', PORTABLE_EXECUTABLE_DIR: packageDirectory, TOOL_PROVIDER: '', TOOL_MODEL: '', TOOL_API_BASE: '', TOOL_API_KEY: '' };
  delete env.ELECTRON_RUN_AS_NODE; delete env.ANKITA_DESKTOP_DEV_URL;
  application = await electron.launch({ executablePath: path.join(packageDirectory, executable), args: [`--user-data-dir=${userData}`], cwd: configDirectory, env, timeout: LIMITS.launch });
  launchedProcess = application.process(); assert.equal(await application.evaluate(({ app }) => app.isPackaged), true);
  const native = await application.evaluateHandle(({ dialog, BrowserWindow }) => {
    const state = { requested: 0, completed: 0, canceled: null, events: [] };
    for (const window of BrowserWindow.getAllWindows()) for (const name of ['show', 'hide', 'focus', 'blur', 'close', 'closed']) window.on(name, () => state.events.push({ name, id: window.id, at: Date.now() }));
    const original = dialog.showOpenDialog.bind(dialog);
    dialog.showOpenDialog = async (...args) => { state.requested++; try { const result = await original(...args); state.completed++; state.canceled = result.canceled; return result; } catch (error) { state.error = error.message; throw error; } };
    state.windows = () => BrowserWindow.getAllWindows().map(window => ({ id: window.id, title: window.getTitle(), visible: window.isVisible(), minimized: window.isMinimized(), focused: window.isFocused(), enabled: typeof window.isEnabled === 'function' ? window.isEnabled() : null,
      handle: process.platform === 'win32' ? window.getNativeWindowHandle().readUInt32LE() : null }));
    return state;
  }); // Observe the actual host call; delegate unchanged to the native chooser.
  const page = await application.firstWindow(); page.setDefaultTimeout(LIMITS.action);
  await page.waitForFunction(() => Boolean(window.ankita));
  const bootstrap = await page.evaluate(() => window.ankita.invoke('initialize')); const thread = bootstrap.teammates[0]; assert.ok(thread);
  await page.evaluate(() => { window.__pickerEvents = []; window.ankita.onEvent(event => window.__pickerEvents.push(event)); });
  await page.evaluate(() => window.ankita.invoke('browserPluginSetEnabled', { mode: 'isolated', enabled: true }));
  const sending = page.evaluate(({ id, text }) => window.ankita.invoke('send', { id, text }), { id: thread.id, text: 'Inspect the generated file through the native chooser in this disposable browser test.' });
  // Keep a handled promise while the operator uses the real native dialog.
  const sent = sending.then(value => ({ value }), error => ({ error: error.message }));
  await page.waitForFunction(() => window.__pickerEvents.some(event => event.type === 'browser-state' && event.state.progress?.phase === 'waiting-for-user'), null, { timeout: LIMITS.action });
  assert.equal(await native.evaluate(state => state.requested), 1, 'the actual native chooser was invoked');
  if (scenario === 'stop') await page.evaluate(id => window.ankita.invoke('cancel', { id }), thread.id);
  fs.writeFileSync(operatorPath, JSON.stringify({ scenario, selectedFile, windowTitle: 'Choose a file to upload', operatorFinished, packageDirectory, directory }, null, 2));
  console.log('PICKER_NATIVE_READY', JSON.stringify({ scenario, operatorPath, selectedFile, packageDirectory }));
  console.log('PICKER_NATIVE_WINDOWS', JSON.stringify(await native.evaluate(state => ({ requested: state.requested, completed: state.completed, windows: state.windows() }))));
  const deadline = Date.now() + LIMITS.operator;
  while (!fs.existsSync(operatorFinished)) { if (Date.now() > deadline) throw new Error('Native chooser operator deadline reached');
    fs.writeFileSync(path.join(directory, 'native-trace.json'), JSON.stringify(await native.evaluate(state => ({ requested: state.requested, completed: state.completed, canceled: state.canceled, error: state.error, events: state.events, windows: state.windows() })), null, 2));
    await new Promise(resolve => setTimeout(resolve, LIMITS.poll)); }
  const result = await sent; assert.ok(!result.error, result.error);
  if (scenario !== 'stop') await page.getByText(DONE, { exact: true }).first().waitFor();
  if (scenario === 'select') await page.waitForFunction(async () => (await window.ankita.invoke('browserSessionView')).progress?.phase === 'finished');
  else assert.equal(writes, 0);
  assert.equal(writes, scenario === 'select' ? 1 : 0); assert.equal(received, scenario === 'select' ? content : '');
  const events = await page.evaluate(() => window.__pickerEvents);
  assert.ok(events.some(event => event.type === 'browser-state' && event.threadId === thread.id && event.state.progress?.phase === 'waiting-for-user'));
  if (scenario === 'stop') assert.ok(events.some(event => event.type === 'browser-state' && event.state.progress?.phase === 'stopped'));
  assert.ok(!JSON.stringify(events.filter(event => event.type === 'browser-state')).includes(selectedFile), 'selected path is excluded from public browser progress');
  assert.deepEqual(fixtureErrors, []);
  const report = { packaged: true, scenario, requests: requests.length, writes, bytes: Buffer.byteLength(received), publicPathLeak: false, packageDirectory };
  fs.writeFileSync(path.join(directory, 'report.json'), JSON.stringify(report, null, 2));
  await page.screenshot({ path: path.join(directory, 'result.png') });
  console.log('NATIVE_PICKER_PACKAGED_OK', JSON.stringify(report)); console.log(`Artifacts: ${directory}`);
} finally {
  if (application) {
    const page = await application.firstWindow().catch(() => null);
    await page?.evaluate(() => window.ankita.invoke('browserSessionStop')).catch(() => {});
    await application.evaluate(({ app }) => app.quit()).catch(() => {});
    await new Promise(resolve => setTimeout(resolve, LIMITS.shutdownGrace));
    let deadline;
    try { await Promise.race([application.close(), new Promise((_, reject) => { deadline = setTimeout(() => reject(new Error('Native-picker fixture shutdown timed out')), LIMITS.close); })]); }
    finally { clearTimeout(deadline); }
    assert.equal(launchedProcess.exitCode, 0);
  }
  server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  // Retain this generated, isolated directory for the native operator and exact-archive reruns.
}
