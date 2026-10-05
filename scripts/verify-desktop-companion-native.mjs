// Native round trip against the production Electron app and ANKITA tools.
// The provider is a loopback fixture; configuration, sessions and files are isolated.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import electronPath from 'electron';
import { _electron } from 'playwright';
import { islandSizeFor } from '../desktop/electron/island.mjs';
import { CAPTURE_ACTIONS, ROUTES } from '../desktop/browser-helper/protocol.mjs';
import { randomUUID } from 'node:crypto';

const repo = fileURLToPath(new URL('../', import.meta.url));
const fixture = await fs.mkdtemp(path.join(os.tmpdir(), 'ankita-companion-native-'));
const timeoutMs = 30_000; // Milliseconds; native startup and local tool execution.
const config = path.join(fixture, 'config');
const runtime = path.join(fixture, 'runtime');
const packageOption = process.argv.indexOf('--package-dir');
const packageDirectory = packageOption >= 0 ? path.resolve(process.argv[packageOption + 1]) : null;
// Copy the production modules unchanged so the checkout's .env cannot override the fixture.
for (const relative of ['desktop/electron', 'desktop/shared', 'desktop/browser-helper', 'desktop/renderer/dist', 'desktop/build', 'src', 'tools', 'skills', 'package.json']) {
  await fs.cp(path.join(repo, relative), path.join(runtime, relative), { recursive: true });
}
await fs.symlink(path.join(repo, 'node_modules'), path.join(runtime, 'node_modules'), process.platform === 'win32' ? 'junction' : 'dir');
await fs.mkdir(config);
await fs.mkdir(path.join(fixture, 'app-data'));
await fs.writeFile(path.join(fixture, 'fixture.txt'), 'companion round-trip proof\n');
const requests = [];
const provider = http.createServer(async (request, response) => {
  if (request.url.endsWith('/models')) {
    response.writeHead(200, { 'content-type': 'application/json' });
    response.end(JSON.stringify({ data: [{ id: 'fixture-model', name: 'Fixture model', context_length: 262144, tools: true }] }));
    return;
  }
  if (!request.url.endsWith('/chat/completions')) { response.writeHead(404); response.end(); return; }
  let raw = '';
  for await (const chunk of request) raw += chunk;
  const body = JSON.parse(raw);
  requests.push(body);
  const results = body.messages.filter(message => message.role === 'tool');
  const delta = results.length === 0
    ? { tool_calls: [{ index: 0, id: 'fixture-read', type: 'function', function: { name: 'read_file', arguments: JSON.stringify({ path: 'fixture.txt' }) } }] }
    : results.length === 1
      ? { tool_calls: [{ index: 0, id: 'fixture-write', type: 'function', function: { name: 'write_file', arguments: JSON.stringify({ path: 'created.txt', content: 'created by companion\n' }) } }] }
      : { content: 'Read and wrote the fixture files.' };
  response.writeHead(200, { 'content-type': 'text/event-stream' });
  response.end('data: ' + JSON.stringify({ choices: [{ index: 0, delta, finish_reason: delta.tool_calls ? 'tool_calls' : 'stop' }] }) + '\n\ndata: [DONE]\n\n');
});
await new Promise(resolve => provider.listen(0, '127.0.0.1', resolve));
const apiBase = 'http://127.0.0.1:' + provider.address().port + '/v1';
await fs.writeFile(path.join(config, 'config.env'), 'PROVIDER=custom\nAPI_BASE=' + apiBase + '\nMODEL=fixture-model\nAUTO_APPROVE=off\nTOOLS=on\nMEMORY_CONSOLIDATION=off\n');
await fs.writeFile(path.join(config, 'desktop-settings.json'), JSON.stringify({ version: 1, settings: { provider: 'custom', customApiBase: apiBase, model: 'fixture-model', profileSetupDone: true, username: 'Fixture', timeZone: 'UTC' } }));
const entry = path.join(fixture, 'entry.mjs');
await fs.writeFile(entry, "import { app } from 'electron';\napp.setPath('userData', process.env.ANKITA_NATIVE_DATA);\napp.setVersion(process.env.ANKITA_NATIVE_VERSION);\nawait import(process.env.ANKITA_NATIVE_MAIN);\n");
let app;
try {
  const executable = packageDirectory ? path.join(packageDirectory, (await fs.readdir(packageDirectory)).find(name => name.endsWith('.exe'))) : electronPath;
  app = await _electron.launch({ executablePath: executable, args: packageDirectory ? ['--user-data-dir=' + path.join(fixture, 'app-data')] : [entry], cwd: fixture, timeout: timeoutMs,
    env: { ...process.env, CONFIG_DIR: config, ANKITA_NATIVE_DATA: path.join(fixture, 'app-data'), ANKITA_NATIVE_VERSION: JSON.parse(await fs.readFile(path.join(repo, 'package.json'), 'utf8')).version,
      ANKITA_NATIVE_MAIN: pathToFileURL(path.join(runtime, 'desktop/electron/main.mjs')).href, ANKITA_DESKTOP_DEV_URL: '' } });
  console.log('Native application started');
  const main = await app.firstWindow();
  main.setDefaultTimeout(timeoutMs);
  await main.getByRole('button', { name: 'Open command palette', exact: true }).waitFor();
  console.log('Native desktop ready');
  if (packageDirectory) {
    const packaged = await app.evaluate(({ app }) => ({ packaged: app.isPackaged, resources: process.resourcesPath, version: app.getVersion() }));
    assert.equal(packaged.packaged, true);
    assert.equal(packaged.version, JSON.parse(await fs.readFile(path.join(repo, 'package.json'), 'utf8')).version);
    const helper = path.join(packaged.resources, 'browser-helper');
    for (const file of ['manifest.json', 'background.mjs', 'content.js', 'content.mjs', 'popup.html', 'popup.mjs', 'protocol.mjs']) await fs.access(path.join(helper, file));
    console.log('PASS packaged runtime/version and unpacked Chrome/Edge capture helper resources');
  }
  await main.screenshot({ path: path.join(fixture, 'desktop.png') });
  const islandCreated = app.waitForEvent('window', { timeout: timeoutMs });
  await main.evaluate(() => window.ankita.windowAction('minimize'));
  const island = await islandCreated;
  console.log('Native island created');
  island.setDefaultTimeout(timeoutMs);
  await island.getByRole('button', { name: 'Open Ankita island', exact: true }).click();
  await island.getByLabel('Ask', { exact: true }).click();
  await island.getByLabel('Message', { exact: true }).fill('Read fixture.txt, then write created.txt.');
  await island.getByRole('button', { name: 'Send', exact: true }).click();
  await island.getByRole('button', { name: 'Allow', exact: true }).waitFor();
  // Wait for the native resize, then check the real diff does not hide its answer controls.
  await island.waitForFunction(height => innerHeight === height, islandSizeFor('home-expanded', 1).height);
  const allowBounds = await island.getByRole('button', { name: 'Allow', exact: true }).boundingBox();
  assert.ok(allowBounds.y + allowBounds.height <= await island.evaluate(() => innerHeight));
  console.log('Native write approval ready');
  assert.equal(await fs.access(path.join(fixture, 'created.txt')).then(() => true, () => false), false);
  await island.screenshot({ path: path.join(fixture, 'native-approval.png') });
  await island.getByRole('button', { name: 'Allow', exact: true }).click();
  await island.getByRole('button', { name: 'Open Ankita island', exact: true }).click();
  await island.getByLabel('Ask', { exact: true }).click();
  await island.getByText('Read and wrote the fixture files.', { exact: true }).waitFor();
  assert.equal(await fs.readFile(path.join(fixture, 'created.txt'), 'utf8'), 'created by companion\n');
  assert.equal(requests.length, 3);
  assert.match(requests[1].messages.find(message => message.role === 'tool').content, /1: companion round-trip proof/);
  const snapshot = await island.evaluate(() => window.ankita.invoke('islandSnapshot'));
  const thread = snapshot.state.threads[snapshot.teammates[0].id];
  assert.equal(thread.running, false);
  assert.equal(thread.log.filter(row => row.kind === 'tool' && row.state === 'ok').length, 2);
  console.log('PASS native renderer → preload → DesktopEngine → real read_file/write_file → streamed answer (3 provider requests, 2 tools)');
  await island.screenshot({ path: path.join(fixture, 'native-chat.png') });
  for (const name of ['Research desk with a very long name', 'Development and implementation team', 'Quality assurance and release agent', 'Additional teammate']) {
    await island.evaluate(name => window.ankita.invoke('createTeammate', { name }), name);
  }
  await island.getByLabel('Overview', { exact: true }).click();
  await island.waitForFunction(() => document.querySelectorAll('.island-pill').length === 4);
  await island.waitForFunction(height => innerHeight === height, islandSizeFor('home-expanded', 1).height);
  await island.waitForFunction(() => document.querySelector('.ticker-row-current .ticker-text')?.textContent.includes('write_file'));
  const nativeLayout = await island.evaluate(() => {
    const avatars = [...document.querySelectorAll('.island-pill')];
    const boxes = avatars.map(el => el.getBoundingClientRect());
    const feed = document.querySelector('.island-activity-steps');
    const footer = document.querySelector('.island-activity-actions').getBoundingClientRect();
    return {
      count: avatars.length,
      teammateCard: document.querySelector('.island-overview-right').classList.contains('island-card'),
      twoColumns: Math.abs(boxes[0].y - boxes[1].y) < 1 && Math.abs(boxes[2].y - boxes[3].y) < 1 && boxes[0].x !== boxes[1].x,
      clipped: boxes.some(box => box.bottom > innerHeight),
      overflow: getComputedStyle(feed).overflowY,
      overlaps: feed.lastElementChild.getBoundingClientRect().bottom > footer.top,
      footerClipped: footer.bottom > innerHeight,
      toolState: document.querySelector('.ticker-row-current').dataset.state,
    };
  });
  assert.deepEqual(nativeLayout, { count: 4, teammateCard: false, twoColumns: true, clipped: false, overflow: 'hidden', overlaps: false, footerClipped: false, toolState: 'ok' });
  await island.screenshot({ path: path.join(fixture, 'native-overview.png') });
  console.log('PASS native overview keeps four avatars in two columns without a teammates card, scrollbar or clipped actions');
  const captureSetup = await island.evaluate(action => window.ankita.invoke(action), CAPTURE_ACTIONS.setup);
  const origin = 'chrome-extension://' + 'b'.repeat(32);
  const postCapture = async (route, body, token) => {
    const response = await fetch(captureSetup.address + route, {method:'POST', headers:{Origin:origin,'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:JSON.stringify(body)});
    assert.equal(response.status,200); return response.json();
  };
  const paired = await postCapture(ROUTES.pair, {code:captureSetup.code});
  const recipient = (await island.evaluate(()=>window.ankita.invoke('listTeammates')))[1];
  const ticket = await island.evaluate(({action,threadId,ticketId})=>window.ankita.invoke(action,{threadId,ticketId}), {action:CAPTURE_ACTIONS.register,threadId:recipient.id,ticketId:randomUUID()});
  await postCapture(ROUTES.capture,{...ticket,title:'Native captured page',url:'https://example.test/native',text:'Native capture attachment proof'},paired.token);
  await island.getByRole('button',{name:'Remove Native captured page.txt',exact:true}).waitFor();
  assert.equal(await island.getByLabel('Chat teammate').inputValue(),recipient.id);
  assert.equal(requests.length,3);
  assert.equal((await island.evaluate(action=>window.ankita.invoke(action),CAPTURE_ACTIONS.inbox)).length,0);
  console.log('PASS native gated ticket IPC → paired HTTP bridge → capture event → original teammate draft → inbox acknowledgement; no provider request');
  await island.screenshot({path:path.join(fixture,'native-captured-page.png')});
  await island.getByLabel('Overview',{exact:true}).click();
  await island.getByRole('button', { name: 'Open conversation', exact: true }).click();
  await island.getByLabel('Message', { exact: true }).fill('Preserve this native draft');
  await island.evaluate(() => window.ankita.islandAction('show-main'));
  await main.getByRole('button', { name: 'Open command palette', exact: true }).waitFor();
  await main.evaluate(()=>{
    const data=new DataTransfer();data.items.add(new File(['Native real file context'],'native-context.md',{type:'text/markdown'}));window.__nativeDrop=data;
    document.querySelector('.header-companion').dispatchEvent(new DragEvent('dragenter',{bubbles:true,cancelable:true,dataTransfer:data}));
  });
  await main.locator('canvas[data-interaction="anticipate"]').waitFor();
  await main.screenshot({path:path.join(fixture,'native-hungry-mouth.png')});
  await main.evaluate(()=>document.querySelector('.header-companion').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:window.__nativeDrop})));
  await main.getByRole('button',{name:'Remove native-context.md',exact:true}).waitFor();
  await main.locator('canvas[data-interaction="success"]').waitFor();
  assert.equal(requests.length,3);
  console.log('PASS native desktop mascot opens its mouth and delivers a real file through Composer without sending');
  await main.evaluate(() => window.ankita.windowAction('minimize'));
  assert.equal(await island.getByLabel('Message', { exact: true }).inputValue(), 'Preserve this native draft');
  assert.equal(app.windows().filter(page => page.url().endsWith('island.html')).length, 1);
  const bounds = await app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().find(window => window.getTitle().endsWith('island')).getBounds());
  assert.ok(Number.isInteger(bounds.x) && Number.isInteger(bounds.y));
  console.log('PASS production hide/show keeps one island, the same chat draft, and integer native bounds');
  await island.getByLabel('Settings',{exact:true}).click();
  await island.evaluate(()=>{navigator.clipboard.writeText=async value=>{window.__fixturePairingCode=value;};});
  await island.getByRole('button',{name:'Copy pairing code',exact:true}).click();
  assert.equal(await island.getByRole('button', { name: 'Copy pairing code', exact: true }).evaluate(element => getComputedStyle(element).outlineStyle), 'none', 'island buttons have no rectangular focus outline');
  await island.getByLabel('Browser pairing code',{exact:true}).waitFor();
  const setupBounds=await island.getByLabel('Browser pairing code',{exact:true}).boundingBox();
  assert.ok(setupBounds.y+setupBounds.height<=await island.evaluate(()=>innerHeight),'the native helper pairing code must remain visible');
  await island.screenshot({path:path.join(fixture,'native-helper-setup.png')});
  console.log('PASS native helper setup keeps the real pairing code and controls visible without changing the system clipboard');
  await island.evaluate(() => window.ankita.islandAction('show-main'));
  await main.getByRole('button', { name: 'Projects', exact: true }).click();
  await main.getByRole('button', { name: 'New project', exact: true }).click();
  await main.getByLabel('Project name', { exact: true }).fill('Native project workspace');
  await main.getByLabel('What is it?', { exact: true }).fill('A production IPC round trip for the redesigned project sections.');
  await main.getByLabel(/^Working folder/).fill(fixture);
  await main.getByLabel(/^Conventions/).fill('Keep the workspace context with the team.');
  await main.getByRole('button', { name: 'Create project', exact: true }).click();
  await main.getByRole('heading', { name: 'Native project workspace', exact: true }).waitFor();
  await main.getByRole('button', { name: 'Assign teammate', exact: true }).click();
  await main.getByRole('button', { name: 'Unassign', exact: true }).waitFor();
  await main.getByRole('tab', { name: 'Tasks', exact: true }).click();
  await main.getByLabel('New project task').fill('Complete the native UI round trip');
  await main.getByRole('button', { name: 'Add task', exact: true }).click();
  await main.getByRole('button', { name: 'Complete Complete the native UI round trip', exact: true }).click();
  await main.locator('.project-completed summary').waitFor();
  await main.getByRole('tab', { name: 'Context', exact: true }).click();
  await main.getByLabel('New decision').fill('Keep project decisions searchable in the context view.');
  await main.getByRole('button', { name: 'Save context', exact: true }).click();
  await main.locator('.context-record-copy > span').getByText('Keep project decisions searchable in the context view.', { exact: true }).waitFor();
  await main.getByLabel('New decision').focus();
  assert.equal(await main.getByLabel('New decision').evaluate(element => getComputedStyle(element).outlineStyle), 'none');
  const nativeProjects = await main.evaluate(() => window.ankita.invoke('listProjects'));
  const nativeProject = nativeProjects.find(project => project.name === 'Native project workspace');
  assert.equal(nativeProject.path, fixture);
  assert.equal(nativeProject.todos[0].done, true);
  assert.equal(nativeProject.decisions[0].text, 'Keep project decisions searchable in the context view.');
  await main.screenshot({ path: path.join(fixture, 'native-project-context.png') });
  console.log('PASS native project create/assign → task add/complete → context save → persisted production IPC data');
  await main.getByRole('button', { name: 'Open settings', exact: true }).click();
  await main.getByLabel('Context window (tokens)', { exact: true }).fill('65536');
  await main.getByLabel('Max output tokens', { exact: true }).fill('4096');
  await main.getByRole('button', { name: 'Save model settings', exact: true }).click();
  await main.getByRole('status').getByText('Changes saved.', { exact: true }).waitFor();
  const savedModel = await main.evaluate(() => window.ankita.invoke('initialize'));
  assert.equal(savedModel.preferences.contextWindow, 65536);
  assert.equal(savedModel.preferences.maxTokens, 4096);
  await main.screenshot({ path: path.join(fixture, 'native-model-settings.png') });
  await main.getByRole('button', { name: 'Background jobs', exact: true }).click();
  await main.getByRole('heading', { name: 'Background jobs', exact: true }).waitFor();
  // Do not toggle OS startup in a fixture. The renderer switch is exercised with fixture IPC.
  const startup = await main.evaluate(() => window.ankita.invoke('scheduleHostSettings'));
  assert.equal(typeof startup.supported, 'boolean');
  assert.deepEqual(await main.locator('.settings-job-overview strong').allTextContents(), ['0', '0', '0']);
  await main.screenshot({ path: path.join(fixture, 'native-background-settings.png') });
  await main.getByRole('button', { name: 'Open tasks', exact: true }).click();
  await main.getByRole('button', { name: 'Create a task in chat', exact: true }).waitFor();
  await main.locator('.composer-shell textarea').focus();
  assert.equal(await main.locator('.composer-shell textarea').evaluate(element => getComputedStyle(element).outlineStyle), 'none');
  await main.screenshot({ path: path.join(fixture, 'native-scheduled-empty.png') });
  assert.equal(requests.length, 3, 'management screens must not send model requests');
  console.log('PASS native model-limit persistence, startup capability read and background-settings → scheduled-task navigation without provider requests');
  console.log('Native evidence: ' + fixture);
} catch (error) {
  console.error(error);
  console.error('Fixture provider calls: ' + requests.length + '; evidence: ' + fixture);
  console.error(JSON.stringify(requests.map(body => ({ stream: body.stream, roles: body.messages.map(message => message.role) }))));
  console.error(await fs.readFile(path.join(config, 'logs/desktop-errors.jsonl'), 'utf8').catch(() => 'No engine errors recorded'));
  throw error;
} finally {
  if (app) {
    const deadline = setTimeout(() => app.process().kill(), timeoutMs);
    // The fixture owns this entire application; bypass the tray's interactive quit policy.
    await app.evaluate(({ app }) => app.exit()).catch(() => {});
    await app.close().catch(() => {});
    clearTimeout(deadline);
  }
  provider.closeAllConnections();
  await new Promise(resolve => provider.close(resolve));
}
