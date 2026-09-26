import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { chromium } from 'playwright';
import { BrowserPluginStore } from '../../src/integrations/browser-plugins.mjs';
import { BrowserSessionManager } from '../../tools/browser/session.mjs';
import { PlaywrightBrowserAdapter } from '../../tools/browser/playwright.mjs';
import { ChromeBrowserAdapter } from '../../tools/browser/chrome.mjs';
import { CHROME_MCP_ID } from '../../src/integrations/browser-plugins.mjs';
import * as browser from '../../tools/browser/browser.mjs';

// Synthetic form only: dynamic port and disposable profile; no travel data or bookings.
const FORM = `<title>Automation regression form</title>
  ${'<input hidden>'.repeat(170)}
  <span id="origin-label">Where from?</span><input role="combobox" aria-labelledby="origin-label">
  <button onclick="document.querySelector('main').textContent='Search submitted'">Search</button><main></main>
  <div id="shadow"></div><iframe src="/frame"></iframe>
  <script>document.querySelector('#shadow').attachShadow({mode:'open'}).innerHTML='<label>Destination <input></label>'</script>`;
const FRAME = '<label>Passenger <input></label>';
// Milliseconds/retries: Windows may briefly retain browser profile files after context.close.
const CLEANUP_RETRY_DELAY_MS = 100;
const CLEANUP_RETRIES = 10;
const refFor = (output, label) => output.split('\n').find(line => line.includes(label) && line.includes('[ref='))?.match(/\[ref=([^\]]+)\]/)?.[1];

async function liveSession(t) {
  if (!fs.existsSync(chromium.executablePath())) { t.skip('Chromium has not been downloaded'); return; }
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-automation-'));
  const server = http.createServer((request, response) => {
    response.writeHead(200, { 'content-type': 'text/html' });
    response.end(request.url === '/frame' ? FRAME : FORM);
  });
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile') });
  const store = new BrowserPluginStore(path.join(directory, 'browser.json')).load();
  store.setEnabled('isolated', true);
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter });
  t.after(async () => {
    await manager.close(); await adapter.close(); server.closeAllConnections();
    await new Promise(resolve => server.close(resolve));
    assert.equal(fs.realpathSync(path.dirname(directory)), fs.realpathSync(os.tmpdir()));
    await fs.promises.rm(directory, { recursive: true, force: true, maxRetries: CLEANUP_RETRIES, retryDelay: CLEANUP_RETRY_DELAY_MS });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const ctx = { browserManager: manager, config: { allowPrivateHosts: true }, cwd: directory };
  const url = `http://127.0.0.1:${server.address().port}/`;
  return { adapter, manager, ctx, url };
}

test('live public browser entry accepts auto and returns usable refs with open', async t => {
  const live = await liveSession(t); if (!live) return;
  const output = await browser.run({ action: 'open', mode: 'auto', url: live.url }, live.ctx);
  console.log(`auto/open trace: ${output.slice(0, 400)}`);
  assert.match(output, /Opened tab/);
  assert.ok(refFor(output, 'Where from?'), output);
});

test('missing Chromium preflight returns an install remedy before launching', async t => {
  const live = await liveSession(t); if (!live) return;
  const executablePath = chromium.executablePath;
  const launch = chromium.launchPersistentContext;
  let launches = 0;
  chromium.executablePath = () => path.join(live.ctx.cwd, 'missing-test-browser');
  chromium.launchPersistentContext = async () => { launches++; throw new Error('must not launch a missing binary'); };
  try {
    const result = await browser.run({ action: 'open', url: live.url }, live.ctx);
    assert.match(result, /Chromium is not downloaded/);
    assert.match(result, /npx playwright install chromium/);
    assert.equal(launches, 0);
    console.log('CHROMIUM_PREFLIGHT_OK: missing binary returns install remedy; no launch');
  } finally { chromium.executablePath = executablePath; chromium.launchPersistentContext = launch; }
});

test('present Chromium with a launch failure preserves the underlying diagnostic', async t => {
  const live = await liveSession(t); if (!live) return;
  const launch = chromium.launchPersistentContext;
  chromium.launchPersistentContext = async () => { throw new Error('fixture launch failure: profile unavailable'); };
  try {
    const result = await browser.run({ action: 'open', url: live.url }, live.ctx);
    assert.match(result, /Chromium could not start: fixture launch failure: profile unavailable/);
    assert.doesNotMatch(result, /Chromium is not downloaded/);
  } finally { chromium.launchPersistentContext = launch; }
});

test('live snapshot covers labelled comboboxes, visible controls, shadow DOM and frames', async t => {
  const live = await liveSession(t); if (!live) return;
  await browser.run({ action: 'open', url: live.url }, live.ctx);
  await live.adapter.page.locator('iframe').contentFrame().getByLabel('Passenger').waitFor();
  const output = await browser.run({ action: 'snapshot' }, live.ctx);
  console.log(`form snapshot trace: ${output}`);
  for (const label of ['Where from?', 'Destination', 'Passenger', 'Search']) assert.ok(refFor(output, label), output);
  const result = await browser.run({ action: 'act', op: 'fill', ref: refFor(output, 'Passenger'), text: 'Test passenger' }, live.ctx);
  assert.match(result, /fill complete/);
  assert.equal(await live.adapter.page.locator('iframe').contentFrame().getByLabel('Passenger').inputValue(), 'Test passenger');
});

test('live invalid refs return fresh refs without clicking or needing a separate snapshot', async t => {
  const live = await liveSession(t); if (!live) return;
  await browser.run({ action: 'open', url: live.url }, live.ctx);
  await browser.run({ action: 'snapshot' }, live.ctx);
  const result = await browser.run({ action: 'act', op: 'click', ref: 'combobox Where from?' }, live.ctx);
  console.log(`invalid-ref trace: ${result.slice(0, 650)}`);
  assert.match(result, /Unknown browser ref/);
  assert.match(result, /Copy.*ref.*verbatim/i);
  const ref = refFor(result, 'Search'); assert.ok(ref, result);
  assert.equal(await live.adapter.page.locator('main').innerText(), '');
  assert.match(await browser.run({ action: 'act', op: 'click', ref }, live.ctx), /click complete/);
  assert.equal(await live.adapter.page.locator('main').innerText(), 'Search submitted');
});

test('live action results supply the next snapshot and confirm updated form state', async t => {
  const live = await liveSession(t); if (!live) return;
  await browser.run({ action: 'open', url: live.url }, live.ctx);
  const first = await browser.run({ action: 'snapshot' }, live.ctx);
  const result = await browser.run({ action: 'act', op: 'fill', ref: refFor(first, 'Where from?'), text: 'Test origin' }, live.ctx);
  console.log(`fill trace: ${result.slice(0, 500)}`);
  assert.match(result, /fill complete/);
  assert.match(result, /Test origin/);
  const search = refFor(result, 'Search'); assert.ok(search, result);
  assert.match(await browser.run({ action: 'act', op: 'click', ref: search }, live.ctx), /click complete/);
  assert.equal(await live.adapter.page.locator('main').innerText(), 'Search submitted');
});

test('Chrome invalid refs recover a snapshot without replaying a mutation; action supplies next refs', async () => {
  const mutations = [];
  const adapter = new ChromeBrowserAdapter({ has: id => id === CHROME_MCP_ID,
    callTool: async (name, args) => {
      if (name.endsWith('__list_pages')) return '1: Form (https://example.com/) [selected]';
      if (name.endsWith('__take_snapshot')) return 'uid=1_0 RootWebArea "Form"\n uid=1_8 StaticText "Where from?"\n uid=1_1 combobox "Where from?"\n uid=1_2 button "Search"';
      mutations.push({ name, args }); return 'done';
    } });
  const first = await adapter.run({ action: 'snapshot' });
  assert.doesNotMatch(first, /\[ref=[^\]]+\] StaticText/);
  let recovery;
  try { await adapter.run({ action: 'act', op: 'click', ref: 'combobox Where from?' }); }
  catch (error) { recovery = error.message; }
  assert.match(recovery || '', /Unknown browser ref/);
  assert.equal(mutations.length, 0);
  const ref = refFor(recovery, 'Where from?'); assert.ok(ref, recovery);
  const output = await adapter.run({ action: 'act', op: 'fill', ref, text: 'Test origin' });
  assert.match(output, /fill complete/);
  assert.ok(refFor(output, 'Search'), output);
  assert.equal(mutations.length, 1);
  await assert.rejects(adapter.run({ action: 'act', op: 'click', ref: refFor(first, 'Search') }), /Stale ref/);
  assert.equal(mutations.length, 1);
});

test('Chrome refuses refs from another tab and uses snapshots included in action responses', async () => {
  let snapshots = 0, mutations = 0;
  const snapshot = 'uid=1_0 RootWebArea "Form"\n uid=1_1 textbox "Origin"';
  const adapter = new ChromeBrowserAdapter({ has: () => true, callTool: async (name, args) => {
    if (name.endsWith('__list_pages')) return '1: First (https://example.com/) [selected]\n2: Second (https://example.org/)';
    if (name.endsWith('__take_snapshot')) { snapshots++; return snapshot; }
    assert.equal(args.includeSnapshot, true); mutations++; return snapshot;
  } });
  const first = await adapter.run({ action: 'snapshot', tab: '1' });
  await assert.rejects(adapter.run({ action: 'act', tab: '2', op: 'fill', ref: refFor(first, 'Origin'), text: 'Wrong tab' }), /Stale ref/);
  assert.equal(mutations, 0);
  const current = await adapter.run({ action: 'snapshot', tab: '1' });
  const before = snapshots;
  const output = await adapter.run({ action: 'act', op: 'fill', ref: refFor(current, 'Origin'), text: 'Origin' });
  assert.ok(refFor(output, 'Origin'), output);
  assert.equal(snapshots, before, 'action-supplied snapshot avoids an extra MCP snapshot');
  assert.equal(mutations, 1);
});

test('Chrome key presses focus the registered target without clicking it', async () => {
  const calls = [];
  const snapshot = 'uid=1_0 RootWebArea "Keys"\n uid=1_1 textbox "Alpha"\n uid=1_2 textbox "Beta"';
  const adapter = new ChromeBrowserAdapter({ has: () => true, callTool: async (name, args) => {
    if (name.endsWith('__list_pages')) return '1: Keys (https://example.com/) [selected]';
    if (name.endsWith('__take_snapshot')) return snapshot;
    calls.push({ name, args });
    if (name.endsWith('__evaluate_script')) return 'Script ran on page and returned:\n```json\ntrue\n```';
    return snapshot;
  } });
  const current = await adapter.run({ action: 'snapshot' });
  await adapter.run({ action: 'act', op: 'press', ref: refFor(current, 'Alpha'), text: 'Enter' });
  assert.deepEqual(calls.map(call => call.name.split('__').at(-1)), ['evaluate_script', 'press_key']);
  assert.deepEqual(calls[0].args.args, ['1_1']);
  assert.match(calls[0].args.function, /\.focus\(/);
  assert.equal(calls[1].args.key, 'Enter');
});

test('Chrome refuses a key press when the target cannot receive focus', async () => {
  let presses = 0;
  const adapter = new ChromeBrowserAdapter({ has: () => true, callTool: async name => {
    if (name.endsWith('__list_pages')) return '1: Keys (https://example.com/) [selected]';
    if (name.endsWith('__take_snapshot')) return 'uid=1_1 button "Disabled"';
    if (name.endsWith('__evaluate_script')) return 'Script ran on page and returned:\n```json\nfalse\n```';
    presses++; return 'done';
  } });
  const current = await adapter.run({ action: 'snapshot' });
  await assert.rejects(adapter.run({ action: 'act', op: 'press', ref: refFor(current, 'Disabled'), text: 'Enter' }), /could not receive keyboard focus/i);
  assert.equal(presses, 0);
});

test('Chrome typing sends only supported keyboard arguments and reads next refs afterward', async () => {
  const calls = [];
  const snapshot = 'uid=1_1 textbox "Alpha"';
  const adapter = new ChromeBrowserAdapter({ has: () => true, callTool: async (name, args) => {
    if (name.endsWith('__list_pages')) return '1: Keys (https://example.com/) [selected]';
    if (name.endsWith('__take_snapshot')) return snapshot;
    calls.push({ name, args }); return 'done';
  } });
  const current = await adapter.run({ action: 'snapshot' });
  const output = await adapter.run({ action: 'act', op: 'type', ref: refFor(current, 'Alpha'), text: 'typed' });
  const typed = calls.find(call => call.name.endsWith('__type_text'));
  assert.deepEqual(typed.args, { pageId: 1, text: 'typed' });
  assert.ok(refFor(output, 'Alpha'), output);
});

test('live registered refs follow a unique re-rendered control but reject ambiguous replacements', async t => {
  const live = await liveSession(t); if (!live) return;
  await browser.run({ action: 'open', url: live.url }, live.ctx);
  const first = await browser.run({ action: 'snapshot' }, live.ctx);
  const origin = refFor(first, 'Where from?'); assert.ok(origin, first);
  await live.adapter.page.getByRole('combobox').evaluate(element => { element.outerHTML = element.outerHTML.replace(/ data-ankita-ref="[^"]*"/, ''); });
  assert.match(await browser.run({ action: 'act', op: 'fill', ref: origin, text: 'New origin' }, live.ctx), /fill complete/);
  assert.equal(await live.adapter.page.getByRole('combobox').inputValue(), 'New origin');
  const second = await browser.run({ action: 'snapshot' }, live.ctx);
  const next = refFor(second, 'Where from?');
  await live.adapter.page.getByRole('combobox').evaluate(element => {
    element.removeAttribute('data-ankita-ref'); element.after(element.cloneNode());
  });
  const failed = await browser.run({ action: 'act', op: 'fill', ref: next, text: 'Must not be filled' }, live.ctx);
  assert.match(failed, /Stale ref/);
  assert.deepEqual(await live.adapter.page.getByRole('combobox').evaluateAll(nodes => nodes.map(node => node.value)), ['New origin', 'New origin']);
});

test('live snapshot query finds controls beyond the cap without exposing password values', async t => {
  const live = await liveSession(t); if (!live) return;
  await browser.run({ action: 'open', url: live.url }, live.ctx);
  await live.adapter.page.evaluate(() => {
    const controls = document.createElement('section');
    controls.innerHTML = '<button>Extra</button>'.repeat(170) + '<label>Secret <input type="password" value="test-secret"></label>';
    document.body.prepend(controls);
  });
  const capped = await browser.run({ action: 'snapshot' }, live.ctx);
  assert.match(capped, /Snapshot limit reached/);
  const targeted = await browser.run({ action: 'snapshot', query: 'Secret' }, live.ctx);
  assert.ok(refFor(targeted, 'Secret'), targeted);
  assert.doesNotMatch(targeted, /test-secret/);
  assert.match(targeted, /value=\[hidden\]/);
});

test('live fill_form fills multiple controls from one snapshot and prechecks all refs', async t => {
  const live = await liveSession(t); if (!live) return;
  const opened = await browser.run({ action: 'open', url: live.url }, live.ctx);
  const fields = [{ ref: refFor(opened, 'Where from?'), text: 'Test origin' }, { ref: refFor(opened, 'Destination'), text: 'Test destination' }];
  assert.equal(browser.needsApproval({ action: 'fill_form', fields }), true);
  assert.doesNotMatch(JSON.stringify(browser.display({ action: 'fill_form', fields })), /Test origin|Test destination/);
  assert.match(await browser.run({ action: 'fill_form', fields: [fields[0], { ref: 'missing', text: 'bad' }] }, live.ctx), /Unknown browser ref/);
  assert.equal(await live.adapter.page.getByRole('combobox').inputValue(), '');
  const fresh = await browser.run({ action: 'snapshot' }, live.ctx);
  const output = await browser.run({ action: 'fill_form', fields: fields.map((field, index) => ({ ...field, ref: refFor(fresh, index ? 'Destination' : 'Where from?') })) }, live.ctx);
  assert.match(output, /Filled 2 fields/);
  assert.equal(await live.adapter.page.getByRole('combobox').inputValue(), 'Test origin');
  assert.equal(await live.adapter.page.getByLabel('Destination').inputValue(), 'Test destination');
  assert.ok(refFor(output, 'Search'), output);
});

test('live fill_form supports selects and checkboxes with accurate labels', async t => {
  const live = await liveSession(t); if (!live) return;
  await browser.run({ action: 'open', url: live.url }, live.ctx);
  await live.adapter.page.evaluate(() => {
    document.body.insertAdjacentHTML('beforeend', '<label>Journey <select><option>Round trip</option><option>One way</option></select></label><label>Remember <input type="checkbox"></label><input type="password" value="unlabelled-secret">');
  });
  const first = await browser.run({ action: 'snapshot' }, live.ctx);
  assert.doesNotMatch(first, /unlabelled-secret/);
  assert.match(first, /select Journey \(/);
  const output = await browser.run({ action: 'fill_form', fields: [{ ref: refFor(first, 'Journey'), text: 'One way' }, { ref: refFor(first, 'Remember'), text: 'true' }] }, live.ctx);
  assert.match(output, /Filled 2 fields/);
  assert.equal(await live.adapter.page.getByLabel('Journey').inputValue(), 'One way');
  assert.equal(await live.adapter.page.getByLabel('Remember').isChecked(), true);
});
