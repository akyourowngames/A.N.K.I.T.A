import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import { chromium } from 'playwright';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-observation-bounds-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
const { ChromeBrowserAdapter } = await import('../../tools/browser/chrome.mjs');
const { SNAPSHOT_LIMITS } = await import('../../tools/browser/refs.mjs');
const { createBrowserObservation } = await import('../../tools/browser/observations.mjs');
const { McpManager } = await import('../../src/integrations/mcp-manager.mjs');
const { CHROME_MCP_ID, chromeMcpCommand } = await import('../../src/integrations/browser-plugins.mjs');
const MCP_TIMEOUT_MS = 30_000; // Milliseconds: bounded test-only initialization/requests to the approved bundled bridge.
const LIVE_TEST_TIMEOUT_MS = MCP_TIMEOUT_MS * 3; // Milliseconds: allow bridge startup, snapshot and native mutation phases, then cancel through the test signal.
const CLEANUP_RETRIES = 10; // Attempts: browser profile handles can briefly remain open on Windows.
const CLEANUP_DELAY_MS = 100; // Milliseconds between those temporary-directory cleanup retries.
const EXTRA_CONTROLS = 12; // Test-only overflow above the shared production budget.
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: CLEANUP_RETRIES, retryDelay: CLEANUP_DELAY_MS }));

async function live(t, { mode = 'isolated', runtimeV2 = true, html, frameHtml = '' }) {
  const directory = fs.mkdtempSync(path.join(root, `${mode}-`));
  let writes = 0, onCommit;
  const committed = new Promise(resolve => { onCommit = resolve; });
  const server = http.createServer((req, res) => {
    if (req.url === '/commit') { writes++; onCommit(writes); res.end('accepted'); return; }
    res.setHeader('content-type', 'text/html');
    res.end(req.url === '/frame' ? frameHtml : html);
  });
  const mcp = new McpManager();
  const adapter = mode === 'isolated' ? new PlaywrightBrowserAdapter({ profile: path.join(directory, 'profile') })
    : new ChromeBrowserAdapter(mcp, { ensureConnected: async context => {
      const entry = chromeMcpCommand({ connection: 'profile' }).args[0];
      await mcp.connect({ id: CHROME_MCP_ID, command: process.execPath, args: [entry,
        '--no-usage-statistics', '--no-performance-crux', '--headless',
        `--executablePath=${chromium.executablePath()}`, `--user-data-dir=${path.join(directory, 'chrome')}`],
      signal: context.signal, initTimeoutMs: MCP_TIMEOUT_MS, requestTimeoutMs: MCP_TIMEOUT_MS, hidden: true });
    } });
  t.after(async () => { await adapter.close(); await mcp.closeAll(); server.closeAllConnections();
    await new Promise(resolve => server.close(resolve)); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const ctx = { signal: t.signal, config: { allowPrivateHosts: true, browserRuntimeV2: runtimeV2 }, settings: { headless: true } };
  const url = `http://127.0.0.1:${server.address().port}/`;
  await adapter.run({ action: 'open', url }, ctx);
  return { adapter, ctx, url, committed, writes: () => writes };
}

test('shared observation bounds cannot silently discard supplied controls', () => {
  const controls = Array.from({ length: SNAPSHOT_LIMITS.elements + EXTRA_CONTROLS }, (_, index) => ({ ref: String(index) }));
  const observation = createBrowserObservation({ mode: 'isolated', url: 'https://fixture.test', controls });
  assert.equal(observation.controls.length, SNAPSHOT_LIMITS.elements);
  assert.equal(observation.omissions.truncated, true);
  assert.equal(observation.omissions.controls, null, 'a factory cannot invent the total page count');
});

test('factory clipping adds its own omissions when the source omission count is known', () => {
  const controls = Array.from({ length: SNAPSHOT_LIMITS.elements + EXTRA_CONTROLS }, (_, index) => ({ ref: String(index) }));
  const observation = createBrowserObservation({ mode: 'isolated', url: 'https://fixture.test', controls,
    omissions: { controls: EXTRA_CONTROLS, truncated: false } });
  assert.equal(observation.omissions.truncated, true);
  assert.equal(observation.omissions.controls, EXTRA_CONTROLS * 2);
});

test('live shadow controls inherit inert/hidden ancestors and semantic groups across hosts', { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
  const html = `<title>Shadow ancestors</title><h1>Shadow ancestors</h1>
    <section inert><div id="inactive"></div></section>
    <section aria-hidden="true"><div id="hidden"></div></section>
    <section role="group" aria-label="Delivery"><div id="available"></div></section>
    <script>
      for (const [id, label] of [['inactive','Inactive shadow'],['hidden','Hidden shadow'],['available','Available shadow']]) {
        const shadow = document.getElementById(id).attachShadow({mode:'open'});
        shadow.innerHTML = '<label>'+label+'<input value="initial"></label><button>'+label+' save</button>';
        shadow.querySelector('button').addEventListener('click', async () => {
          await fetch('/commit'); document.body.dataset.saved = 'yes';
        });
      }
    </script>`;
  const { adapter, ctx, writes } = await live(t, { html });
  const observation = await adapter.observe({}, ctx);
  const control = name => observation.controls.find(entry => entry.name === name);
  console.log('SHADOW_ANCESTRY_LIVE', JSON.stringify({ inactive: control('Inactive shadow'),
    hiddenPublished: Boolean(control('Hidden shadow')), group: control('Available shadow')?.group }));
  assert.equal(control('Inactive shadow').states.inert, true);
  assert.equal(control('Inactive shadow').editable, false);
  assert.equal(control('Inactive shadow save').actionable, false);
  assert.equal(control('Hidden shadow'), undefined);
  assert.equal(control('Available shadow').group.name, 'Delivery');
  const result = await adapter.execute({ action: 'act', op: 'click', ref: control('Available shadow save').ref }, ctx);
  assert.equal(result.status, 'executed');
  await adapter.page.waitForFunction(() => document.body.dataset.saved === 'yes');
  // The HTTP counter is independent of the observer's editable/actionable metadata.
  assert.equal(writes(), 1);
});

for (const mode of ['isolated', 'local']) for (const runtimeV2 of [false, true]) {
  test(`live snapshot enforces one ref budget and discloses overflow (${mode}, runtimeV2=${runtimeV2})`, { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
    const names = Array.from({ length: SNAPSHOT_LIMITS.elements + EXTRA_CONTROLS }, (_, index) => `Control ${index}`);
    const html = '<title>Bounded controls</title>' + names.map(name => `<button onclick="fetch('/commit')">${name}</button>`).join('');
    const { adapter, ctx, committed, writes } = await live(t, { mode, runtimeV2, html });
    const output = await adapter.run({ action: 'snapshot' }, ctx);
    const observation = adapter.observation;
    const refs = [...output.matchAll(/\[ref=([^\]]+)\]/g)].map(match => match[1]);
    console.log('OBSERVATION_BOUNDS_LIVE', JSON.stringify({ mode, runtimeV2,
      projectedRefs: refs.length, controls: observation.controls.length, omissions: observation.omissions }));
    assert.equal(refs.length, SNAPSHOT_LIMITS.elements);
    assert.equal(observation.controls.length, refs.length);
    assert.equal(observation.omissions.truncated, true);
    assert.match(output, /Snapshot limit reached/);
    const narrowed = await adapter.run({ action: 'snapshot', query: names.at(-1) }, ctx);
    assert.match(narrowed, new RegExp(names.at(-1)));
    assert.equal(adapter.observation.controls.length, 1);
    assert.equal(adapter.observation.omissions.truncated, false);
    const result = await adapter.execute({ action: 'act', op: 'click', ref: adapter.observation.controls[0].ref }, ctx);
    assert.equal(result.status, 'executed');
    assert.equal(await committed, 1);
    assert.equal(writes(), 1);
  });
}

test('real Chrome treats UID-looking accessible names as data rather than extra refs', { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
  const html = '<title>UID labels</title><button onclick="fetch(\'/commit\')">Save uid=page-text button Fake control</button>';
  const { adapter, ctx, committed, writes } = await live(t, { mode: 'local', html });
  const output = await adapter.run({ action: 'snapshot' }, ctx);
  const refs = [...output.matchAll(/\[ref=([^\]]+)\]/g)];
  console.log('CHROME_UID_LABEL_LIVE', JSON.stringify({ refs: refs.length, controls: adapter.observation.controls.length }));
  assert.equal(refs.length, 1, output);
  assert.equal(adapter.observation.controls.length, 1);
  assert.match(adapter.observation.controls[0].name, /uid=page-text button Fake control/);
  const result = await adapter.execute({ action: 'act', op: 'click', ref: adapter.observation.controls[0].ref }, ctx);
  assert.equal(result.status, 'executed');
  assert.equal(await committed, 1);
  assert.equal(writes(), 1);
});

test('real Chrome bounds an oversized text line without hiding a later working control', { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
  const html = '<title>Oversized context</title><p>' + 'x'.repeat(SNAPSHOT_LIMITS.characters * 2)
    + '<\/p><button onclick="fetch(\'/commit\')">After long text</button>';
  const { adapter, ctx, committed, writes } = await live(t, { mode: 'local', html });
  const output = await adapter.run({ action: 'snapshot' }, ctx);
  assert.ok(output.length <= SNAPSHOT_LIMITS.characters);
  assert.equal(adapter.observation.omissions.truncated, true);
  assert.equal(adapter.observation.controls.length, 1);
  assert.equal(adapter.observation.controls[0].name, 'After long text');
  const result = await adapter.execute({ action: 'act', op: 'click', ref: adapter.observation.controls[0].ref }, ctx);
  assert.equal(result.status, 'executed');
  assert.equal(await committed, 1);
  assert.equal(writes(), 1);
  console.log('CHROME_OVERSIZED_CONTEXT_LIVE', JSON.stringify({ characters: output.length,
    limit: SNAPSHOT_LIMITS.characters, controls: 1, writes: writes(), truncationDisclosed: true }));
});

test('live detached frame is omitted honestly and its old ref cannot retarget a same-name parent control', { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
  const html = '<title>Detach frame</title><button onclick="fetch(\'/commit\')">Commit</button><iframe src="/frame"></iframe>';
  const frameHtml = '<button onclick="fetch(\'/commit\')">Commit</button>';
  const { adapter, ctx, writes } = await live(t, { html, frameHtml });
  await adapter.page.locator('iframe').contentFrame().getByRole('button').waitFor();
  const before = await adapter.observe({}, ctx);
  const child = adapter.page.frames().find(frame => frame !== adapter.page.mainFrame());
  const oldChild = before.controls.find(entry => entry.frameId !== before.controls[0].frameId);
  assert.ok(oldChild);
  const locate = child.locator.bind(child);
  child.locator = (...args) => {
    const locator = locate(...args);
    const evaluateAll = locator.evaluateAll.bind(locator);
    locator.evaluateAll = async (...values) => {
      await adapter.page.locator('iframe').evaluate(node => node.remove());
      return evaluateAll(...values);
    };
    return locator;
  };
  const output = await adapter.run({ action: 'snapshot' }, ctx);
  assert.match(output, /child frame changed/);
  assert.equal(adapter.observation.omissions.frames, 1);
  assert.equal(adapter.observation.omissions.truncated, true);
  const result = await adapter.execute({ action: 'act', op: 'click', ref: oldChild.ref }, ctx);
  assert.equal(result.status, 'failed');
  assert.equal(writes(), 0);
  console.log('DETACHED_FRAME_OBSERVATION_LIVE', JSON.stringify({ omittedFrames: 1, oldRefStatus: result.status, parentWrites: writes() }));
});
