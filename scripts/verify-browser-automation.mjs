import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import { chromium } from 'playwright';
import { McpManager } from '../src/integrations/mcp-manager.mjs';
import { BrowserPluginStore, CHROME_MCP_ID, CHROME_MCP_VERSION, chromeMcpCommand } from '../src/integrations/browser-plugins.mjs';
import { BrowserSessionManager } from '../tools/browser/session.mjs';
import { PlaywrightBrowserAdapter } from '../tools/browser/playwright.mjs';
import { ChromeBrowserAdapter } from '../tools/browser/chrome.mjs';
import { waitForBrowser } from '../tools/browser/pending.mjs';
import { browserScreenshotImage } from '../tools/browser/screenshots.mjs';

// This script never downloads packages or touches a personal browser profile.
const TEST_HOST = '127.0.0.1';
const TEST_FORM = '<title>Automation live form</title><label>Origin <input></label><label>Destination <input></label><button onclick="document.querySelector(\'main\').textContent=\'Submitted \'+document.querySelector(\'input\').value">Search</button><main></main>';
const ANIMATED_PREVIEW_FORM = `${TEST_FORM}<div id="clock"></div><script>setInterval(()=>document.querySelector("#clock").textContent=Date.now(),25)</script>`; // Dedicated capture fixture; ordinary browser tasks use the static form.
const INTERACTION_FORM = `<title>Advanced browser interactions</title>
<label>Alpha <input onkeydown="if(event.key==='Enter')document.querySelector('main').textContent='Pressed Alpha'"></label>
<label>Beta <input onkeydown="if(event.key==='Enter')document.querySelector('main').textContent='Pressed Beta'"></label>
<label>Journey <select><option>Round trip</option><option>One way</option></select></label>
<label>Remember <input type="checkbox"></label>
<button onmouseenter="document.querySelector('main').textContent='Hovered control'">Hover target</button>
<button draggable="true" ondragstart="event.dataTransfer.setData('text/plain','fixture')">Drag source</button>
<button ondragover="event.preventDefault()" ondrop="event.preventDefault();document.querySelector('main').textContent='Dropped control'">Drop target</button>
<main></main>`;
const STOCK_FORM = '<title>Stock fixture</title><h1>Requested memory</h1><p>Out of stock</p><p>Alternative memory available</p><form method="post" action="/stock-cart"><label>Quantity <input type="number" name="qty" value="1"></label><button>Add alternative to cart</button></form>';
const FRAME_COUNT = 15;
const STATIC_PREVIEW_COUNT = 5; // Consecutive preview refreshes must not invalidate a static page's action refs.
const RUNTIME_V2 = process.argv.includes('--runtime-v2'); // Exercise the same real backends with either receipt contract; rollout defaults stay untouched.
const FRAME_INTERVAL_MS = 100;
const CONNECT_TIMEOUT_MS = 25_000;
const REQUEST_TIMEOUT_MS = 15_000;
const CLEANUP_RETRIES = 10;
const CLEANUP_RETRY_DELAY_MS = 100;
const SLOW_REQUEST_DEADLINE_MS = 20_000;
const STOP_RETURN_DEADLINE_MS = 1000;
const GUIDE_CONTEXT_WINDOW = 131072; // Verification-only model context units: match the 128k-class HTTP fixture; no provider exists to discover capacity.
const GUIDE_OUTPUT_TOKENS = 1000; // Verification-only reply reserve; the scripted form flow returns one short sentence.
const refFor = (output, label) => output.split('\n').find(line => line.includes(label) && line.includes('[ref='))?.match(/\[ref=([^\]]+)\]/)?.[1];
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-automation-live-'));
let notifySlow;
let cartQuantity = 0, cartWrites = 0; // Fixture-only state independently read back after each adapter's mutation.
const server = http.createServer((request, response) => {
  if (request.url === '/slow') { notifySlow?.(); return; }
  if (request.method === 'POST' && request.url === '/stock-cart') {
    let body = ''; request.on('data', chunk => { body += chunk; });
    request.on('end', () => { cartWrites++; cartQuantity += Number(new URLSearchParams(body).get('qty')); response.writeHead(303, { location: '/stock-cart' }); response.end(); }); return;
  }
  response.writeHead(200, { 'content-type': 'text/html' });
  if (request.url === '/stock') { cartQuantity = 0; cartWrites = 0; response.end(STOCK_FORM); return; }
  if (request.url === '/stock-cart') { response.end(`<title>Fixture cart</title><p>Alternative memory quantity ${cartQuantity}</p><label>Quantity <input type="number" value="${cartQuantity}"></label>`); return; }
  response.end(request.url === '/other' ? '<title>Other live page</title><button>Other</button>' : request.url === '/interactions' ? INTERACTION_FORM : request.url === '/preview-animation' ? ANIMATED_PREVIEW_FORM : TEST_FORM);
});
const mcp = new McpManager();
const playwright = new PlaywrightBrowserAdapter({ profile: path.join(directory, 'playwright') });
const store = new BrowserPluginStore(path.join(directory, 'browser.json')).load();
store.setEnabled('isolated', true); store.setEnabled('local', true);
let manager;
await new Promise(resolve => server.listen(0, TEST_HOST, resolve));
const url = `http://${TEST_HOST}:${server.address().port}`;
const ctx = { config: { allowPrivateHosts: true, browserRuntimeV2: RUNTIME_V2 }, cwd: directory };
try {
  const entry = chromeMcpCommand({ connection: 'profile' }).args[0];
  let manifest;
  for (let folder = path.dirname(entry); folder !== path.dirname(folder); folder = path.dirname(folder)) {
    try { const candidate = JSON.parse(fs.readFileSync(path.join(folder, 'package.json'), 'utf8')); if (candidate.name === 'chrome-devtools-mcp') { manifest = candidate; break; } } catch {}
  }
  console.log(`Live Chrome MCP version=${manifest?.version}; configured=${CHROME_MCP_VERSION}; bundled executable only`);
  const chrome = new ChromeBrowserAdapter(mcp, { ensureConnected: async context => {
    if (context.reconnect) await mcp.disconnect(CHROME_MCP_ID);
    await mcp.connect({ id: CHROME_MCP_ID, command: process.execPath, args: [entry, '--no-usage-statistics', '--no-performance-crux', '--headless', `--executablePath=${chromium.executablePath()}`, `--user-data-dir=${path.join(directory, 'chrome')}`], signal: context.signal, initTimeoutMs: CONNECT_TIMEOUT_MS, requestTimeoutMs: REQUEST_TIMEOUT_MS, hidden: true });
  } });
  manager = new BrowserSessionManager({ store, isolatedFactory: () => playwright, chromeFactory: () => chrome });
  const { Agent } = await import('../src/core/agent.mjs');
  const { loadSkills } = await import('../src/core/skills.mjs');
  const browserGuide = loadSkills().find(skill => skill.name === 'browser-use');
  assert.ok(browserGuide, 'browser guide is packaged with the repository skills');
  for (const [mode, adapter] of [['isolated', playwright], ['local', chrome]]) {
    let output = await manager.run({ action: 'open', mode, url }, ctx);
    assert.ok(refFor(output, 'Origin'), output);
    const staticRef = refFor(output, 'Origin');
    for (let index = 0; index < STATIC_PREVIEW_COUNT; index++) {
      const view = await manager.view();
      assert.equal(view.status, 'ready', JSON.stringify({ mode, previewIndex: index, step: view.step, notice: view.notice })); assert.equal(view.notice, null);
      assert.ok(view.screenshot?.startsWith('data:image/jpeg;base64,'));
    }
    output = await manager.run({ action: 'act', op: 'fill', ref: staticRef, text: 'Preview-stable origin' }, ctx);
    assert.match(output, /Preview-stable origin/);
    assert.equal((await manager.view()).notice, null);
    console.log(`${mode}: STATIC_PREVIEW_REFS_OK refreshes=${STATIC_PREVIEW_COUNT} originalRefUsable=true falsePageChange=false runtimeV2=${RUNTIME_V2}`);
    output = await manager.run({ action: 'act', op: 'fill', ref: refFor(output, 'Origin'), text: 'Test origin' }, ctx);
    assert.match(output, /fill complete/);
    output = await manager.run({ action: 'act', op: 'fill', ref: refFor(output, 'Destination'), text: 'Test destination' }, ctx);
    assert.match(output, /fill complete/);
    output = await manager.run({ action: 'act', op: 'click', ref: refFor(output, 'Search') }, ctx);
    assert.match(output, /click complete/);
    assert.match(await manager.run({ action: 'read' }, ctx), /Submitted Test origin/);
    console.log(`${mode}: open -> fill -> fill -> click -> confirmed read; no separate snapshot calls`);
    output = await manager.run({ action: 'snapshot' }, ctx);
    output = await manager.run({ action: 'fill_form', fields: [{ ref: refFor(output, 'Origin'), text: 'Batch origin' }, { ref: refFor(output, 'Destination'), text: 'Batch destination' }] }, ctx);
    assert.match(output, /Filled 2 fields/);
    assert.ok(refFor(output, 'Search'), output);
    console.log(`${mode}: fill_form fills two fields and returns the next refs`);
    output = await manager.run({ action: 'act', ref: 'combobox Origin' }, ctx);
    assert.match(output, /Unknown browser ref/); assert.ok(refFor(output, 'Origin'), output);
    const recoveredView = await manager.view();
    assert.equal(recoveredView.status, 'ready');
    assert.equal(recoveredView.notice.kind, 'reference');
    assert.doesNotMatch(recoveredView.notice.message, /page changed/i);
    assert.ok(recoveredView.screenshot?.startsWith('data:image/jpeg;base64,'));
    assert.ok(!JSON.stringify(recoveredView).includes('[ref='), 'recovery page controls remain out of the live view');
    console.log(`${mode}: invalid ref recovered with fresh refs and no mutation`);
    console.log(`${mode}: recovered-ref view remains ready with pixels; no snapshot/code in sidebar state`);
    const screenshot = JSON.parse(await manager.run({ action: 'screenshot' }, ctx));
    assert.equal(screenshot.type, 'browser_screenshot'); assert.ok(fs.statSync(screenshot.path).size > 0);
    assert.ok(browserScreenshotImage(screenshot, ctx), 'live screenshot can be attached as vision pixels');
    // Pixel changes are tested separately; they never masquerade as changes to the static task page.
    await manager.run({ action: 'navigate', url: `${url}/preview-animation` }, ctx);
    const frames = new Set(); const started = performance.now();
    for (let index = 0; index < FRAME_COUNT; index++) {
      const frameStart = performance.now(); frames.add(await adapter.preview());
      await new Promise(resolve => setTimeout(resolve, Math.max(0, FRAME_INTERVAL_MS - (performance.now() - frameStart))));
    }
    console.log(`${mode}: preview ${(FRAME_COUNT * 1000 / (performance.now() - started)).toFixed(1)} FPS; ${frames.size} distinct frames; screenshot=${screenshot.bytes} bytes`);
    assert.ok(frames.size > 1);
    output = await manager.run({ action: 'navigate', url }, ctx);
    assert.ok(refFor(output, 'Origin'), output);
    const originalTab = (await adapter.tabs()).find(tab => tab.active)?.id;
    output = await manager.run({ action: 'open', url: `${url}/interactions` }, ctx);
    output = await manager.run({ action: 'fill_form', fields: [{ ref: refFor(output, 'Alpha'), text: '' }, { ref: refFor(output, 'Beta'), text: 'Other' }, { ref: refFor(output, 'Journey'), text: 'One way' }, { ref: refFor(output, 'Remember'), text: 'true' }] }, ctx);
    assert.match(output, /Filled 4 fields/);
    output = await manager.run({ action: 'act', op: 'type', ref: refFor(output, 'Alpha'), text: 'Typed Alpha' }, ctx);
    assert.match(output, /Typed Alpha/);
    output = await manager.run({ action: 'act', op: 'fill', ref: refFor(output, 'Beta'), text: 'Focused Beta' }, ctx);
    output = await manager.run({ action: 'act', op: 'press', ref: refFor(output, 'Alpha'), text: 'Enter' }, ctx);
    assert.match(await manager.run({ action: 'read' }, ctx), /Pressed Alpha/, 'press must target its ref even when another field has focus');
    output = await manager.run({ action: 'snapshot' }, ctx);
    output = await manager.run({ action: 'act', op: 'hover', ref: refFor(output, 'Hover target') }, ctx);
    assert.match(await manager.run({ action: 'read' }, ctx), /Hovered control/);
    output = await manager.run({ action: 'snapshot' }, ctx);
    output = await manager.run({ action: 'act', op: 'drag', ref: refFor(output, 'Drag source'), to_ref: refFor(output, 'Drop target') }, ctx);
    assert.match(await manager.run({ action: 'read' }, ctx), /Dropped control/);
    console.log(`${mode}: native select/checkbox batch, typing, ref-targeted key, hover and drag confirmed`);
    await manager.run({ action: 'open', url: `${url}/other` }, ctx);
    assert.match(await manager.run({ action: 'snapshot', tab: originalTab }, ctx), /Origin/);
    console.log(`${mode}: explicit tab targets original form after another tab opens`);
    output = await manager.run({ action: 'open', url: `${url}/stock` }, ctx);
    assert.match(output, /Out of stock/, 'default snapshot must expose non-interactive stock text');
    output = await manager.run({ action: 'fill_form', fields: [{ ref: refFor(output, 'Quantity'), text: '1' }] }, ctx);
    const staleQuantity = refFor(output, 'Quantity');
    output = await manager.run({ action: 'act', op: 'fill', ref: staleQuantity, text: '1' }, ctx);
    output = await manager.run({ action: 'act', op: 'click', ref: refFor(output, 'Add alternative') }, ctx);
    assert.equal(cartWrites, 1); assert.equal(cartQuantity, 1);
    assert.match(await manager.run({ action: 'read' }, ctx), /Alternative memory quantity 1/);
    const staleResult = await manager.run({ action: 'act', op: 'fill', ref: staleQuantity, text: '2' }, ctx);
    assert.match(staleResult, /Stale ref|Unknown browser ref/);
    assert.equal(cartQuantity, 1);
    console.log(`${mode}: stock text visible; repeated quantity fill -> exactly one cart write; stale ref refused`);
    const agent = new Agent({ client: {}, config: { ...ctx.config, contextWindow: GUIDE_CONTEXT_WINDOW, maxTokens: GUIDE_OUTPUT_TOKENS, tools: true, autoApprove: true, memoryConsolidation: false, browserToolFocus: true },
      browserManager: manager, workspacePath: directory, skillsEnabled: true, print: () => {}, write: () => {} });
    let guideRound = 0;
    const guidedCall = args => ({ content: '', toolCalls: [{ id: `guided-${guideRound}`, type: 'function', function: { name: 'browser', arguments: JSON.stringify(args) } }] });
    agent.streamTurn = async () => {
      guideRound++;
      if (guideRound === 1) return { content: '', toolCalls: [{ id: 'guided-discovery', type: 'function', function: { name: 'find_tools', arguments: '{"query":"browser","scope":"focus"}' } }] };
      assert.ok(agent.messages[0].content.includes(browserGuide.body), `${mode}: guide must remain loaded throughout browsing`);
      if (guideRound === 2) return guidedCall({ action: 'open', mode, url });
      const observation = agent.messages.findLast(message => message.role === 'tool').content;
      if (guideRound === 3) return guidedCall({ action: 'fill_form', fields: [{ ref: refFor(observation, 'Origin'), text: 'Guided origin' }, { ref: refFor(observation, 'Destination'), text: 'Guided destination' }] });
      assert.match(observation, /Guided origin/); assert.match(observation, /Guided destination/);
      return { content: 'Observed both fields', toolCalls: [] };
    };
    await agent.send('Fill both fields in the supplied verification page');
    assert.equal(guideRound, 4); assert.equal(agent.totalToolCalls, 3);
    assert.deepEqual(agent.skillAudit.automatic, ['browser-use']);
    assert.ok(!agent.messages[0].content.includes(browserGuide.body));
    console.log(`${mode}: BROWSER_SKILL_ADAPTER_LIVE_OK rounds=4 calls=3 extraSkillCalls=0 fieldReadBack=true turnGuideCleared=true`);
    const enteredSlowRequest = new Promise(resolve => { notifySlow = resolve; });
    const controller = new AbortController();
    const pending = manager.run({ action: 'open', url: `${url}/slow` }, { ...ctx, signal: controller.signal });
    await waitForBrowser(Promise.race([enteredSlowRequest, pending.then(result => { throw new Error(`Slow request ended before Stop: ${result}`); })]), { timeoutMs: SLOW_REQUEST_DEADLINE_MS });
    const stoppedAt = performance.now(); controller.abort();
    assert.match(await pending, /cancel/i);
    const stopReturnMs = Math.round(performance.now() - stoppedAt);
    assert.ok(stopReturnMs < STOP_RETURN_DEADLINE_MS);
    await manager.tail;
    console.log(`${mode}: Stop returned in ${stopReturnMs} ms; queue released in ${Math.round(performance.now() - stoppedAt)} ms`);
  }
  assert.match(await manager.run({ action: 'open', mode: 'local', url }, ctx), /Origin/);
  await mcp.disconnect(CHROME_MCP_ID);
  assert.match(await manager.run({ action: 'open', url }, ctx), /Origin/);
  console.log('local: reconnect on demand after transport disconnect');
  store.setEnabled('local', false);
  assert.match(await manager.run({ action: 'open', mode: 'auto', url }, ctx), /Origin/);
  assert.equal(manager.activeMode, 'isolated');
  console.log('auto: disabled Chrome falls back to enabled Playwright');
  console.log('BROWSER_AUTOMATION_LIVE_OK');
} catch (error) { console.error(`LIVE_FAILURE: ${error.stack}`); throw error; }
finally {
  await manager?.close(); await playwright.close(); await mcp.closeAll();
  server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  // mkdtemp returned this absolute, script-owned directory under the OS temp root.
  assert.equal(path.dirname(directory), fs.realpathSync(os.tmpdir()));
  await fs.promises.rm(directory, { recursive: true, force: true, maxRetries: CLEANUP_RETRIES, retryDelay: CLEANUP_RETRY_DELAY_MS }).catch(error => console.error(`CLEANUP_FAILURE: ${error.message}`));
}
