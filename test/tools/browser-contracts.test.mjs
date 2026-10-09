import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-contract-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
const { ChromeBrowserAdapter } = await import('../../tools/browser/chrome.mjs');
const { BrowserSessionManager } = await import('../../tools/browser/session.mjs');
const { isToolFailure, verdictFor } = await import('../../src/core/verify.mjs');
const contracts = await import('../../tools/browser/contracts.mjs').catch(() => ({}));
const SLOW_PREPARATION_MS = 500; // Milliseconds: fixture preparation exceeds the former 250ms pre-dispatch assertion; browser work remains real.
const LIVE_STOP_TEST_TIMEOUT_MS = 30_000; // Milliseconds: bound real browser startup, cancellation, response and cleanup.
test.after(() => fs.rmSync(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));

test('numbered partial browser batches are failures without misclassifying page prose', () => {
  const result = '1. fill complete.\n2. Error: stale target. Batch stopped.';
  console.log('PARTIAL_BATCH_CLASSIFICATION', JSON.stringify({ failure: isToolFailure(result), verdict: verdictFor('browser', { action: 'batch', steps: [{ action: 'act' }] }, result)?.ok }));
  assert.equal(isToolFailure(result), true);
  assert.equal(verdictFor('browser', { action: 'batch', steps: [{ action: 'act' }] }, result)?.ok, false);
  assert.equal(isToolFailure('Article\n2. Error: examples in a tutorial'), false);
});

test('contract formats screenshot objects unchanged and dispatch errors as uncertain', () => {
  assert.equal(typeof contracts.browserActionResult, 'function');
  const shot = { type: 'browser_screenshot', path: 'owned-shot.png', bytes: 3 };
  const result = contracts.browserActionResult({ action: 'screenshot', output: shot });
  assert.deepEqual(contracts.formatBrowserResult(result), shot);
  const uncertain = contracts.browserActionResult({ action: 'act', dispatched: true, error: new Error('Transport timed out') });
  assert.equal(uncertain.status, 'uncertain');
  assert.equal(uncertain.steps[0].retrySafe, false);
  assert.match(uncertain.error.recovery, /inspect|snapshot/i);
});

test('aggregate batch receipts retain native dialog attention without exposing input', () => {
  const attention = { dialog: { type: 'confirm', message: 'Proceed?', tabId: '1' } };
  const child = { ...contracts.browserActionResult({ action: 'act', error: new Error('Dialog'), dispatched: true }), attention };
  const result = contracts.browserBatchResult({ steps: [{ action: 'act' }, { action: 'act' }] }, [child], null);
  assert.deepEqual(result.attention, attention);
  assert.deepEqual(result.steps.map(step => step.status), ['uncertain', 'not_run']);
});

test('page prose cannot become an execution error in the structured contract', () => {
  const result = contracts.browserActionResult({ action: 'read', output: 'Error: an example quoted by the page' });
  assert.equal(result.status, 'executed');
  assert.equal(result.error, null);
  assert.equal(isToolFailure(contracts.formatBrowserResult(result)), false);
});

test('both native adapters expose detailed execution and observation contracts', () => {
  for (const Adapter of [PlaywrightBrowserAdapter, ChromeBrowserAdapter]) {
    assert.equal(typeof Adapter.prototype.execute, 'function');
    assert.equal(typeof Adapter.prototype.observe, 'function');
  }
});

test('already cancelled detailed work never invokes the adapter operation', async () => {
  const controller = new AbortController();
  controller.abort();
  let calls = 0;
  const result = await contracts.executeBrowserOperation({}, { action: 'act' }, { signal: controller.signal }, 'isolated', async () => { calls += 1; return 'click complete.'; });
  assert.equal(calls, 0);
  assert.equal(result.status, 'failed');
  assert.equal(result.steps[0].retrySafe, true);
});

test('Chrome detailed result marks a dispatch timeout uncertain and never replays the write', async () => {
  let writes = 0;
  const adapter = new ChromeBrowserAdapter({ has: () => true, callTool: async name => {
    if (name.endsWith('__list_pages')) return '1: Form (https://example.com/) [selected]';
    if (name.endsWith('__take_snapshot')) return 'uid=1_0 RootWebArea "Form" url="https://example.com/"\nuid=1_1 button "Save"';
    if (name.endsWith('__click')) { writes += 1; throw new Error('Transport timed out after dispatch'); }
    return 'ok';
  } });
  const snapshot = await adapter.run({ action: 'snapshot' });
  const ref = /\[ref=([^\]]+)\]/.exec(snapshot)[1];
  const result = await adapter.execute({ action: 'act', op: 'click', ref });
  assert.equal(result.status, 'uncertain');
  assert.equal(result.steps[0].retrySafe, false);
  assert.equal(result.observation, null, 'a prior snapshot must not masquerade as a post-write observation');
  assert.equal(writes, 1);
  console.log('CHROME_DISPATCH_CONTRACT', JSON.stringify({ status: result.status, writes, retrySafe: result.steps[0].retrySafe }));
});

test('detailed execution bounds receipts even when a malformed form contains too many fields', async () => {
  const adapter = new PlaywrightBrowserAdapter();
  const result = await adapter.execute({ action: 'fill_form', fields: Array.from({ length: 1000 }, () => ({ ref: 'bad', text: 'x' })) }, {});
  assert.ok(result.steps.length <= 10);
  assert.equal(result.status, 'failed');
});

test('live batch executes one write, stops after stale target, and classifies the partial receipt', async t => {
  let writes = 0;
  const server = http.createServer((req, res) => {
    if (req.method === 'POST') writes += 1;
    res.setHeader('content-type', 'text/html');
    res.end('<title>Contract fixture</title><form method="post"><button>Write once</button></form>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'live') });
  const store = { load() { return this; }, get(mode) { return { enabled: mode === 'isolated', headless: true }; } };
  const details = [];
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter, onResult: result => details.push(result) });
  t.after(async () => { await manager.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const ctx = { cwd: root, config: { allowPrivateHosts: true, browserRuntimeV2: true } };
  const opened = await manager.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}` }, ctx);
  const ref = /\[ref=([^\]]+)\] button Write once/.exec(opened)?.[1];
  assert.ok(ref, opened);
  const result = await manager.run({ action: 'batch', steps: [
    { action: 'act', op: 'click', ref }, { action: 'act', op: 'click', ref }, { action: 'read' },
  ] }, ctx);
  console.log('PARTIAL_BATCH_LIVE', JSON.stringify({ writes, failure: isToolFailure(result), receipt: result.slice(-240) }));
  assert.equal(writes, 1);
  assert.equal(isToolFailure(result), true);
  const aggregate = details.filter(detail => detail.action === 'batch');
  assert.equal(aggregate.length, 1);
  assert.deepEqual(aggregate[0].steps.map(step => step.status), ['executed', 'failed', 'not_run']);
});

for (const preparationDelayMs of [0, SLOW_PREPARATION_MS]) test(`live Stop after server write returns uncertainty before a delayed response, without replay (preparation ${preparationDelayMs}ms)`, { timeout: LIVE_STOP_TEST_TIMEOUT_MS }, async t => {
  const controller = new AbortController();
  let writes = 0;
  let pendingResponse, nativeWork;
  const server = http.createServer((req, res) => {
    res.setHeader('content-type', 'text/html');
    if (req.method === 'POST') { writes++; pendingResponse = res; controller.abort(); } // Hold the response until Stop returns: no race against browser preparation or a wall clock.
    else res.end('<form method="post"><button>Write once</button></form>');
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'delayed-write') });
  t.after(async () => {
    if (pendingResponse && !pendingResponse.writableEnded) pendingResponse.end('<p>Saved.</p>');
    await nativeWork?.catch(() => {});
    await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve));
  });
  const ctx = { config: { allowPrivateHosts: true, browserRuntimeV2: true }, settings: { headless: true } };
  const snapshot = await adapter.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}` }, ctx);
  const ref = /\[ref=([^\]]+)\] button Write once/.exec(snapshot)[1];
  const run = adapter.run;
  adapter.run = async (...args) => {
    if (preparationDelayMs) await new Promise(resolve => setTimeout(resolve, preparationDelayMs));
    nativeWork = run.apply(adapter, args); // Delay preparation without stubbing any native browser answer.
    return nativeWork;
  };
  const result = await adapter.execute({ action: 'act', op: 'click', ref }, { ...ctx, signal: controller.signal });
  assert.equal(result.status, 'uncertain');
  assert.equal(result.steps[0].retrySafe, false);
  assert.equal(controller.signal.aborted, true);
  assert.ok(pendingResponse, 'the independent server write must trigger Stop');
  assert.equal(pendingResponse.writableEnded, false, 'Stop must return while the server response is still held');
  pendingResponse.end('<p>Saved.</p>');
  await nativeWork;
  assert.equal(writes, 1);
  console.log('DELAYED_WRITE_STOP_LIVE', JSON.stringify({ preparationDelayMs, writes, status: result.status, retrySafe: result.steps[0].retrySafe, returnedBeforeResponse: true, nativeSettled: true }));
});
