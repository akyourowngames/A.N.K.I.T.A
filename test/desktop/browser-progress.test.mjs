import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-browser-progress-view-'));
process.env.CONFIG_DIR = path.join(root, 'config');
const progress = await import('../../desktop/shared/browser-progress.mjs').catch(() => ({}));
const { BrowserSessionManager } = await import('../../tools/browser/session.mjs');
const { BrowserPluginStore } = await import('../../src/integrations/browser-plugins.mjs');
const errors = await import('../../src/integrations/browser-errors.mjs');
test.after(async () => fs.promises.rm(root, { recursive: true, force: true, maxRetries: 10, retryDelay: 100 }));

test('public progress uses bounded labels and never includes entered text or DOM data', () => {
  assert.equal(typeof progress.browserProgress, 'function');
  const result = progress.browserProgress({ phase: 'acting', args: { action: 'sequence', steps: [{ action: 'act', op: 'fill', text: 'private-entry', ref: 'private-ref' }, { action: 'act', op: 'click' }] }, completed: 1 });
  assert.equal(result.completed, 1); assert.equal(result.total, 2);
  assert.equal(result.phase, 'acting');
  assert.equal(result.goalVerified, false);
  assert.ok(!JSON.stringify(result).includes('private-'));
  assert.ok(result.label.length <= progress.BROWSER_PROGRESS_LIMITS.label);
  const publicView = progress.publicBrowserView({ progress: result, screenshot: 'pixels', dialog: { message: 'private-question' } });
  assert.equal(publicView.screenshot, 'pixels'); assert.ok(!JSON.stringify(publicView).includes('private-question'));
});

test('partial and uncertain results stay recoverable and never become a success indicator', () => {
  assert.equal(typeof progress.browserProgress, 'function');
  for (const status of ['partial', 'uncertain', 'failed']) {
    const view = progress.browserProgress({ phase: 'finished', args: { action: 'act', op: 'click' }, result: { status, steps: [{ status: 'uncertain' }], error: { message: 'private-page-data' } } });
    assert.equal(view.phase, 'recovering'); assert.equal(view.outcome, status); assert.equal(view.recoverable, true); assert.equal(view.goalVerified, false);
    assert.ok(!JSON.stringify(view).includes('private-page-data'));
  }
  const dialog = progress.browserProgress({ phase: 'recovering', args: { action: 'act' }, result: { status: 'uncertain', attention: { dialog: { type: 'prompt', message: 'private-page-data', defaultValue: 'private-input' } } } });
  assert.equal(dialog.phase, 'waiting-for-user'); assert.equal(dialog.attention.kind, 'dialog'); assert.equal(dialog.attention.dialogType, 'prompt');
  assert.ok(!JSON.stringify(dialog).includes('private-'));
});

test('manager emits owned progress through dispatch, checking, recovery and Stop', async t => {
  const events = [], store = new BrowserPluginStore(path.join(root, 'browser.json')).load(); store.setEnabled('isolated', true);
  const adapter = { tabs: async () => [], close: async () => {}, invalidate() {}, execute: async (_args, ctx) => {
    ctx.onBrowserDispatch({ phase: 'start' }); ctx.onBrowserDispatch({ phase: 'complete' });
    return { status: 'executed', steps: [{ status: 'executed' }], output: 'clicked', error: null, evidence: [], artifacts: [], observation: null };
  } };
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter, onEvent: (view, thread) => events.push({ view: structuredClone(view), thread }) });
  t.after(() => manager.close());
  await manager.run({ action: 'act', op: 'fill', text: 'private-entry' }, { config: { browserRuntimeV2: true }, browserThreadId: 'owner' });
  assert.ok(events.some(event => event.view.progress?.phase === 'acting'));
  assert.ok(events.some(event => event.view.progress?.phase === 'checking'));
  assert.ok(events.every(event => event.thread === 'owner'));
  assert.ok(!JSON.stringify(events).includes('private-entry'));
  assert.equal(manager.reportPhase('thinking', 'other'), false);
  assert.equal(manager.reportPhase('thinking', 'owner'), true);
  assert.equal(manager.last.progress.phase, 'thinking');
  manager.reportPhase('finished', 'owner'); assert.equal(manager.last.progress.phase, 'finished');
  manager.cancel('owner'); assert.equal(manager.last.progress.phase, 'stopped');
});

test('pending dialogs use a private view, preserve pixels and require an owned manual decision', async t => {
  const events = [], store = new BrowserPluginStore(path.join(root, 'dialog-browser.json')).load(); store.setEnabled('isolated', true);
  let dialog = { id: 'native-first', type: 'prompt', message: 'private-page-question', tabId: 'one' }, previews = 0, decisions = 0;
  const adapter = { tabs: async () => [{ id: 'one', active: true, url: 'https://fixture.test/', title: '' }], attention: () => dialog ? { dialog } : null,
    preview: async () => { previews++; throw new Error('Native dialog blocks capture'); }, close: async () => {}, invalidate() {},
    execute: async args => {
      if (args.action === 'handle_dialog') { assert.equal(args.dialog_id, dialog.id); decisions++; dialog = null; }
      return { status: 'executed', steps: [{ status: 'executed' }], output: 'observed', error: null, attention: dialog ? { dialog } : null };
    } };
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter, onEvent: (view, thread) => events.push({ view: structuredClone(view), thread }) });
  t.after(() => manager.close());
  await manager.run({ action: 'open' }, { config: { browserRuntimeV2: true }, browserThreadId: 'dialog-owner' });
  manager.last.screenshot = 'last-good-frame';
  const view = await manager.view();
  assert.equal(view.dialog?.id, 'native-first'); assert.equal(view.dialog.message, 'private-page-question');
  assert.equal(view.screenshot, 'last-good-frame'); assert.equal(view.progress.phase, 'waiting-for-user'); assert.equal(previews, 0);
  assert.ok(!JSON.stringify(events).includes('private-page-question'));
  await assert.rejects(() => manager.decideDialog({ id: view.dialog.id, decision: 'accept' }), /Take control/);
  await manager.takeover(true);
  await assert.rejects(() => manager.decideDialog({ id: 'old-dialog', decision: 'accept' }), /changed/);
  assert.equal(decisions, 0);
  const queuedRead = manager.run({ action: 'snapshot' }, { config: { browserRuntimeV2: true }, browserThreadId: 'dialog-owner' });
  let deadline;
  const expired = new Promise((_, reject) => { deadline = setTimeout(() => reject(new Error('Manual dialog was stranded behind the paused model queue')), 1000); });
  try { await Promise.race([manager.decideDialog({ id: view.dialog.id, decision: 'accept', prompt_text: 'private-response' }), expired]); }
  finally { clearTimeout(deadline); }
  assert.equal(decisions, 1); assert.equal(manager.paused, true); assert.equal(manager.last.progress.attention, null);
  assert.ok(events.every(event => event.thread === 'dialog-owner'));
  assert.ok(!JSON.stringify(events).includes('private-response'));
  await manager.takeover(false); await queuedRead;
});

test('live desktop dialog controls dismiss and accept without replaying the original action', async t => {
  let writes = 0;
  const server = http.createServer((req, res) => { if (req.method === 'POST') { writes++; res.end('saved'); return; }
    res.setHeader('content-type', 'text/html'); res.end('<button onclick="if(confirm(\'Save?\'))fetch(\'/save\',{method:\'POST\'})">Save</button>'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
  const store = new BrowserPluginStore(path.join(root, 'live-dialog-browser.json')).load(); store.setEnabled('isolated', true);
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'manual-dialog-profile') });
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter });
  t.after(async () => { await manager.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const ctx = { config: { allowPrivateHosts: true, browserRuntimeV2: true }, browserThreadId: 'live-owner' };
  await manager.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}` }, ctx);
  for (const decision of ['dismiss', 'accept']) {
    const snapshot = await manager.run({ action: 'snapshot' }, ctx);
    const ref = /\[ref=([^\]]+)\] button Save/.exec(snapshot)[1];
    await manager.run({ action: 'act', op: 'click', ref }, ctx);
    const view = await manager.view(); assert.equal(view.dialog?.type, 'confirm');
    await manager.takeover(true); await manager.decideDialog({ id: view.dialog.id, decision }); await manager.takeover(false);
  }
  await adapter.page.waitForLoadState();
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal(writes, 1);
  console.log('DESKTOP_DIALOG_CONTROLS_LIVE', JSON.stringify({ decisions: 2, writes, replay: false }));
});

test('batch progress counts the full call and scoped events retain their worker owner', async t => {
  const events = [], store = new BrowserPluginStore(path.join(root, 'batch-browser.json')).load(); store.setEnabled('isolated', true);
  const manager = new BrowserSessionManager({ store, onEvent: (view, scope) => events.push({ view: structuredClone(view), scope }),
    isolatedFactory: () => ({ tabs: async () => [], close: async () => {}, execute: async (_args, ctx) => {
      ctx.onBrowserDispatch({ phase: 'start' }); ctx.onBrowserDispatch({ phase: 'complete' });
      return { status: 'executed', steps: [{ status: 'executed' }], output: 'observed', error: null, timings: {}, evidence: [], artifacts: [] };
    } }) });
  t.after(() => manager.close());
  const scope = manager.createScope('job:one', { mode: 'isolated' });
  await scope.run({ action: 'batch', steps: [{ action: 'act', op: 'click' }, { action: 'read' }, { action: 'snapshot' }] }, { config: { browserRuntimeV2: true }, browserThreadId: 'worker-owner' });
  const states = events.filter(event => event.view.progress);
  assert.ok(states.every(event => event.scope === 'job:one'));
  assert.ok(states.every(event => event.view.progress.total === 3));
  assert.deepEqual(states.filter(event => event.view.progress.phase === 'acting').map(event => event.view.progress.completed), [0, 0, 1, 2]);
  assert.equal(scope.last.progress.completed, 3);
});

test('background preview cadence reuses pixels without delaying visible capture or proof', async t => {
  let captures = 0;
  const store = new BrowserPluginStore(path.join(root, 'preview-cadence.json')).load(); store.setEnabled('isolated', true);
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({
    tabs: async () => [{ id: 'one', url: 'https://fixture.test/', active: true }],
    run: async () => 'opened', preview: async () => `frame-${++captures}`, close: async () => {},
  }) });
  t.after(() => manager.close());
  await manager.run({ action: 'open' }, { browserThreadId: 'owner' });
  assert.equal((await manager.view()).screenshot, 'frame-1');
  assert.equal((await manager.view({ minIntervalMs: 10_000 })).screenshot, 'frame-1');
  assert.equal(captures, 1);
  assert.equal((await manager.view()).screenshot, 'frame-2');
  assert.equal((await manager.view({ automation: true, minIntervalMs: 10_000 })).screenshot, 'frame-3');
});

test('a static page with an invalid reference never claims the website changed', async t => {
  const { PlaywrightBrowserAdapter } = await import('../../tools/browser/playwright.mjs');
  const adapter = new PlaywrightBrowserAdapter({ profile: path.join(root, 'static-reference-profile') });
  const store = new BrowserPluginStore(path.join(root, 'static-reference.json')).load(); store.setEnabled('isolated', true);
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => adapter });
  const server = http.createServer((_req, res) => { res.setHeader('content-type', 'text/html'); res.end('<button>Static control</button>'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => { await manager.close(); await adapter.close(); server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); });
  const ctx = { config: { allowPrivateHosts: true, browserRuntimeV2: true }, browserThreadId: 'static-owner' };
  await manager.run({ action: 'open', url: `http://127.0.0.1:${server.address().port}` }, ctx);
  const pageState = () => adapter.page.evaluate(() => ({ text: document.body.innerText, controls: [...document.querySelectorAll('button')].map(node => ({ text: node.textContent, disabled: node.disabled, box: JSON.stringify(node.getBoundingClientRect()) })) }));
  const before = await pageState();
  const stableRef = /\[ref=([^\]]+)\] button Static control/.exec(await manager.run({ action: 'snapshot' }, ctx))[1];
  const previewRefreshes = 5; // Repeated live capture must not expire a valid static control reference.
  for (let index = 0; index < previewRefreshes; index++) {
    const view = await manager.view();
    assert.equal(view.notice, null); assert.equal(view.status, 'ready');
  }
  assert.match(await manager.run({ action: 'act', op: 'click', ref: stableRef }, ctx), /click complete/);
  assert.equal((await manager.view()).notice, null);
  assert.deepEqual(await pageState(), before);
  await manager.run({ action: 'act', op: 'click', ref: 'invalid-fixture-ref' }, ctx);
  assert.deepEqual(await pageState(), before);
  const view = await manager.view();
  assert.equal(view.notice.kind, 'reference');
  assert.doesNotMatch(view.notice.message, /page changed/i);
  assert.equal(errors.browserNoticeIsRecoverable(view.notice), true);
  assert.equal(errors.browserNoticeIsRecoverable(errors.browserNotice(new Error('connection closed'))), false);
  assert.equal(view.status, 'ready');
  console.log('STATIC_REFERENCE_NOTICE_LIVE', JSON.stringify({ pageUnchanged: true, previewRefreshes, originalRefUsable: true, recoverable: true, status: view.status }));
});
