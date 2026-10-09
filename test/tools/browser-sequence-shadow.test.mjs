import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-sequence-shadow-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
const { ChromeBrowserAdapter } = await import('../../tools/browser/chrome.mjs');
const { McpManager } = await import('../../src/integrations/mcp-manager.mjs');
const { CHROME_MCP_ID, chromeMcpCommand } = await import('../../src/integrations/browser-plugins.mjs');
const { chromium } = await import('playwright');
const { SEQUENCE_CHANGED, captureSequenceGuard, SEQUENCE_CONTROL_SELECTOR, SEQUENCE_GUARD_NODE_LIMIT } = await import('../../tools/browser/sequence.mjs');
const { BROWSER_GROUP_SELECTOR, SNAPSHOT_LIMITS, inspectFillControl } = await import('../../tools/browser/refs.mjs');
const LIVE_TEST_TIMEOUT_MS = 30_000; // Milliseconds: bound an actual isolated-browser setup, guard and native-action round trip.
const CLEANUP_RETRIES = 10; // Attempts: allow temporary browser profile handles to close.
const CLEANUP_DELAY_MS = 100; // Milliseconds between temporary-profile cleanup retries.
const OVERSIZED_WIDGET_NODES = 5000; // Fixture element count: exceed the proposed bounded guard walk without exceeding the control budget.
const MCP_TEST_TIMEOUT_MS = 30_000; // Milliseconds: bound approved bundled-bridge startup and individual requests.
const ANCESTRY_SCAN_NODES = 2; // Fixture-only ancestor budget: stop before reaching this shadow widget's host/group.
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: CLEANUP_RETRIES, retryDelay: CLEANUP_DELAY_MS }));

async function fixture(t, behavior = '', { crossGroup = false, paddingNodes = 0, hostGroup = false } = {}) {
  let writes = 0;
  const server = http.createServer((request, response) => {
    if (request.url === '/commit') { writes++; response.end('saved'); return; }
    response.setHeader('content-type', 'text/html');
    response.end(`<title>Guarded shadow widget</title><h1>Delivery settings</h1>
      <label>Outside<input id="outside"></label><section role="group" aria-label="Delivery"><div id="host" ${hostGroup ? 'role="group" aria-label="Inner widget"' : ''}></div></section>
      <section role="group" aria-label="Other"><div id="other"></div></section>
      <script>
        const host = document.getElementById('host');
        const shadow = host.attachShadow({mode:'open'});
        shadow.innerHTML = '<label>First<input name="first"></label><label>Second<input name="second"></label><button>Save</button>';
        shadow.innerHTML += '${'<span></span>'.repeat(paddingNodes)}';
        shadow.querySelector('button').addEventListener('click', async () => {
          await fetch('/commit'); document.body.dataset.saved = 'yes';
        });
        shadow.querySelector('[name=first]').addEventListener('input', () => { ${behavior} });
        ${crossGroup ? "const other = document.getElementById('other').attachShadow({mode:'open'}); other.innerHTML='<label>Unrelated<input></label>';" : ''}
        document.body.dataset.fixtureReady = 'yes';
      </script>`);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: fs.mkdtempSync(path.join(root, 'profile-')) });
  t.after(async () => { await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const dispatched = [];
  const ctx = { signal: t.signal, config: { allowPrivateHosts: true, browserRuntimeV2: true },
    settings: { headless: true }, onBrowserDispatch: event => { if (event.phase === 'start') dispatched.push(event.op || event.action); } };
  await adapter.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}/` }, ctx);
  assert.equal(await adapter.page.locator('body').getAttribute('data-fixture-ready'), 'yes', 'fixture JavaScript setup must complete before testing the guard');
  dispatched.length = 0;
  const observation = await adapter.observe({}, ctx);
  const ref = name => observation.controls.find(control => control.name === name)?.ref;
  const args = { action: 'sequence', observation_id: observation.id, steps: [
    { action: 'act', op: 'fill', ref: ref('First'), text: 'one' },
    { action: 'act', op: 'fill', ref: ref(crossGroup ? 'Unrelated' : 'Second'), text: 'two' },
    { action: 'act', op: 'click', ref: ref('Save') },
  ] };
  assert.ok(args.steps.every(step => step.ref), 'the actual snapshot must publish every planned control');
  return { adapter, ctx, args, dispatched, writes: () => writes };
}

function trace(label, result, live) {
  console.log('SEQUENCE_SHADOW_LIVE', JSON.stringify({ label, status: result.status,
    steps: result.steps?.map(step => step.status), dispatched: live.dispatched, writes: live.writes(), error: result.error?.message }));
}

async function stopAfterNativeInspection(t, live, inspect, when) {
  const run = live.adapter.run;
  let nativeWork;
  live.adapter.run = (...args) => {nativeWork = run.apply(live.adapter, args); return nativeWork;};
  const probe = await live.adapter.page.locator('[name=first]').elementHandle();
  const prototype = Object.getPrototypeOf(probe);
  const descriptor = Object.getOwnPropertyDescriptor(prototype, 'evaluate');
  const evaluate = probe.evaluate;
  const controller = new AbortController();
  let stopped = false;
  prototype.evaluate = async function(fn, ...args) {
    const result = await evaluate.call(this, fn, ...args); // Complete the actual native inspection, never stub its answer.
    if (!stopped && fn === inspect && when()) {stopped = true; controller.abort();}
    return result;
  };
  t.after(async () => {
    live.adapter.run = run;
    if (descriptor) Object.defineProperty(prototype, 'evaluate', descriptor);
    else delete prototype.evaluate;
    await probe.dispose().catch(() => {});
  });
  return {signal: AbortSignal.any([t.signal, controller.signal]), stopped: () => stopped,
    settle: async () => {assert.ok(nativeWork, 'the actual native operation must have started'); await nativeWork.catch(() => {});}};
}

test('an unchanged shadow widget completes one guarded sequence and one independent write', { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
  const live = await fixture(t);
  const serial = live.adapter.snapshotId;
  const result = await live.adapter.execute(live.args, live.ctx);
  if (result.status === 'executed') await live.adapter.page.waitForFunction(() => document.body.dataset.saved === 'yes');
  trace('unchanged', result, live);
  assert.equal(result.status, 'executed');
  assert.deepEqual(live.dispatched, ['fill', 'fill', 'click']);
  assert.equal(live.writes(), 1);
  assert.equal(live.adapter.snapshotId, serial + 1);
});

for (const [label, behavior] of [
  ['new-shadow-field', "shadow.append(Object.assign(document.createElement('input'), {name:'dynamic'}));"],
  ['inert-shadow-host', "host.setAttribute('inert','');"],
  ['hidden-shadow-host', "host.setAttribute('aria-hidden','true');"],
  ['reparented-shadow-widget', "document.getElementById('other').append(host);"],
  ['opened-shadow-combobox', "const next = shadow.querySelector('[name=second]'); next.setAttribute('role','combobox'); next.setAttribute('aria-expanded','true');"],
]) {
  test(`a ${label} after the first field stops the suffix before another native dispatch`, { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
    const live = await fixture(t, behavior);
    const result = await live.adapter.execute(live.args, live.ctx);
    trace(label, result, live);
    assert.equal(result.status, 'partial');
    assert.deepEqual(result.steps.map(step => step.status), ['executed', 'failed', 'not_run']);
    assert.deepEqual(live.dispatched, ['fill']);
    assert.match(result.error.message, new RegExp(SEQUENCE_CHANGED.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    assert.equal(await live.adapter.page.locator('[name=first]').inputValue(), 'one');
    assert.equal(await live.adapter.page.locator('[name=second]').inputValue(), '');
    assert.equal(live.writes(), 0);
  });
}

test('a change outside the shadow widget does not strand an unchanged related form', { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
  const live = await fixture(t, "document.getElementById('outside').disabled = true;");
  const result = await live.adapter.execute(live.args, live.ctx);
  if (result.status === 'executed') await live.adapter.page.waitForFunction(() => document.body.dataset.saved === 'yes');
  trace('outside-change', result, live);
  assert.equal(result.status, 'executed');
  assert.equal(live.writes(), 1);
  assert.equal(await live.adapter.page.locator('[name=second]').inputValue(), 'two');
});

test('a sequence crossing separate shadow widget groups is refused before the first field', { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
  const live = await fixture(t, '', { crossGroup: true });
  const result = await live.adapter.execute(live.args, live.ctx);
  trace('cross-group', result, live);
  assert.equal(result.status, 'failed');
  assert.deepEqual(live.dispatched, []);
  assert.equal(await live.adapter.page.locator('[name=first]').inputValue(), '');
  assert.equal(live.writes(), 0);
});

test('an oversized non-control widget refuses the chain and still permits a fresh individual action', { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
  const live = await fixture(t, '', { paddingNodes: OVERSIZED_WIDGET_NODES });
  const result = await live.adapter.execute(live.args, live.ctx);
  trace('bounded-node-walk', result, live);
  assert.equal(result.status, 'failed');
  assert.deepEqual(live.dispatched, []);
  assert.equal(live.writes(), 0);
  assert.match(result.error.message, /inspection limit.*individual actions/);
  const scope = await live.adapter.page.locator('section[aria-label="Delivery"]').elementHandle();
  const guard = await live.adapter.page.locator('[name=first]').evaluate(captureSequenceGuard, { scope,
    selector: BROWSER_GROUP_SELECTOR, controlSelector: SEQUENCE_CONTROL_SELECTOR,
    limit: SNAPSHOT_LIMITS.elements, scanLimit: SEQUENCE_GUARD_NODE_LIMIT });
  await scope.dispose();
  assert.equal(guard.valid, false);
  assert.ok(guard.inspectedNodes <= SEQUENCE_GUARD_NODE_LIMIT + 1, 'stop at the first overflow sentinel instead of scanning the entire widget');
  console.log('SEQUENCE_GUARD_BOUND_LIVE', JSON.stringify({inspectedNodes: guard.inspectedNodes, limit: SEQUENCE_GUARD_NODE_LIMIT}));
  const fresh = await live.adapter.observe({}, live.ctx);
  const ref = fresh.controls.find(control => control.name === 'Save').ref;
  const action = await live.adapter.execute({action: 'act', op: 'click', ref}, live.ctx);
  await live.adapter.page.waitForFunction(() => document.body.dataset.saved === 'yes');
  assert.equal(action.status, 'executed');
  assert.equal(live.writes(), 1);
});

test('a semantic group on the shadow host itself retains its own guarded controls', { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
  const live = await fixture(t, '', {hostGroup: true});
  const result = await live.adapter.execute(live.args, live.ctx);
  assert.equal(result.status, 'executed');
  await live.adapter.page.waitForFunction(() => document.body.dataset.saved === 'yes');
  trace('host-is-group', result, live);
  assert.equal(live.writes(), 1);
});

test('native guard discloses ancestor-budget exhaustion before a composed owner is guessed', { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
  const live = await fixture(t);
  const scope = await live.adapter.page.locator('section[aria-label="Delivery"]').elementHandle();
  const guard = await live.adapter.page.locator('[name=first]').evaluate(captureSequenceGuard, {scope,
    selector: BROWSER_GROUP_SELECTOR, controlSelector: SEQUENCE_CONTROL_SELECTOR,
    limit: SNAPSHOT_LIMITS.elements, scanLimit: ANCESTRY_SCAN_NODES});
  await scope.dispose();
  assert.equal(guard.valid, false);
  assert.equal(guard.truncated, true);
  assert.deepEqual(live.dispatched, []);
  assert.equal(live.writes(), 0);
});

test('Stop after a real sequence guard returns prevents the next field dispatch', { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
  const live = await fixture(t);
  const stop = await stopAfterNativeInspection(t, live, captureSequenceGuard, () => live.dispatched.length === 1);
  const result = await live.adapter.execute(live.args, {...live.ctx, signal: stop.signal});
  await stop.settle();
  trace('stop-after-native-guard', result, live);
  assert.equal(stop.stopped(), true);
  assert.equal(result.status, 'partial');
  assert.deepEqual(result.steps.map(step => step.status), ['executed', 'failed', 'not_run']);
  assert.deepEqual(live.dispatched, ['fill']);
  assert.equal(await live.adapter.page.locator('[name=second]').inputValue(), '');
  assert.equal(live.writes(), 0);
});

for (const runtimeV2 of [false, true]) {
  test(`Stop after native fill validation prevents an individual write (runtimeV2=${runtimeV2})`, { timeout: LIVE_TEST_TIMEOUT_MS }, async t => {
    const live = await fixture(t);
    const stop = await stopAfterNativeInspection(t, live, inspectFillControl, () => true);
    const result = await live.adapter.execute(live.args.steps[0], {...live.ctx, signal: stop.signal,
      config: {...live.ctx.config, browserRuntimeV2: runtimeV2}});
    await stop.settle();
    trace(`stop-after-native-validation-${runtimeV2}`, result, live);
    assert.equal(stop.stopped(), true);
    assert.equal(result.status, 'failed');
    assert.deepEqual(live.dispatched, []);
    assert.equal(await live.adapter.page.locator('[name=first]').inputValue(), '');
    assert.equal(live.writes(), 0);
  });
}

test('actual approved Chrome refuses unsupported chains in both receipt modes and retains individual actions', { timeout: MCP_TEST_TIMEOUT_MS * 3 }, async t => {
  let writes = 0, onWrite;
  const committed = new Promise(resolve => {onWrite = resolve;});
  const server = http.createServer((request, response) => {
    if (request.url === '/commit') {writes++; onWrite(writes); response.end('saved'); return;}
    response.setHeader('content-type', 'text/html');
    response.end('<title>Chrome sequence boundary</title><label>First<input></label><button onclick="fetch(\'/commit\')">Save</button>');
  });
  const mcp = new McpManager();
  const profile = fs.mkdtempSync(path.join(root, 'chrome-'));
  const adapter = new ChromeBrowserAdapter(mcp, {ensureConnected: async context => {
    const entry = chromeMcpCommand({connection: 'profile'}).args[0];
    await mcp.connect({id: CHROME_MCP_ID, command: process.execPath, args: [entry,
      '--no-usage-statistics', '--no-performance-crux', '--headless',
      `--executablePath=${chromium.executablePath()}`, `--user-data-dir=${profile}`],
      signal: context.signal, initTimeoutMs: MCP_TEST_TIMEOUT_MS, requestTimeoutMs: MCP_TEST_TIMEOUT_MS, hidden: true});
  }});
  t.after(async () => {await adapter.close(); await mcp.closeAll(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));});
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let source, ctx;
  for (const runtimeV2 of [false, true]) {
    ctx = {signal: t.signal, config: {allowPrivateHosts: true, browserRuntimeV2: runtimeV2}};
    await adapter.run({action: 'open', url: `http://127.0.0.1:${server.address().port}/`}, ctx);
    source = await adapter.observe({}, ctx);
    assert.equal(source.capabilities.guardedSequences, false);
    const first = source.controls.find(control => control.name === 'First');
    assert.ok(first);
    const result = await adapter.execute({action: 'sequence', observation_id: source.id,
      steps: [{action: 'act', op: 'fill', ref: first.ref, text: 'one'}]}, ctx);
    assert.equal(result.status, 'failed');
    assert.match(result.error.message, /does not support guarded sequences/);
    assert.equal(writes, 0);
    console.log('CHROME_SEQUENCE_BOUNDARY_LIVE', JSON.stringify({runtimeV2, status: result.status, writes, supported: false}));
  }
  const action = await adapter.execute({action: 'act', op: 'click', ref: source.controls.find(control => control.name === 'Save').ref}, ctx);
  assert.equal(action.status, 'executed');
  assert.equal(await committed, 1);
  assert.equal(writes, 1);
});
