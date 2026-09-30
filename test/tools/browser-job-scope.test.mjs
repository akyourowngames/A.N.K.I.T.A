import test from 'node:test';
import assert from 'node:assert/strict';
import { BrowserSessionManager } from '../../tools/browser/session.mjs';
import { ChromeBrowserAdapter } from '../../tools/browser/chrome.mjs';
const store = { load() { return this; }, get() { return { enabled: true, headless: false }; } };

test('switching watched job tabs changes only the preview and preserves the worker target and refs', async () => {
  let selected = '2', invalidations = 0;
  const adapter = {
    tabs: async () => [{ id: '1', url: 'https://example.com/one', active: selected === '1' }, { id: '2', url: 'https://example.com/two', active: selected === '2' }],
    run: async () => `Worker reading tab ${selected}`,
    preview: async ({ tab } = {}) => `frame-${tab || selected}`,
    selectTab: async tab => { selected = tab; invalidations++; },
    close: async () => {},
  };
  const root = new BrowserSessionManager({ store, isolatedFactory: () => adapter });
  const job = root.createScope('job-preview', { mode: 'isolated', independentPreview: true });
  await job.run({ action: 'tabs' });
  const preview = await job.selectTab('1');
  assert.equal((await job.view()).screenshot, 'frame-1');
  assert.equal(preview.tabs.find(tab => tab.active).id, '1');
  const proof = await job.view({ automation: true });
  assert.equal(proof.tabs.find(tab => tab.active).id, '2'); assert.equal(proof.screenshot, 'frame-2');
  assert.equal((await job.view()).screenshot, 'frame-1', 'Proof capture must not replace the selected UI preview');
  assert.equal(await job.run({ action: 'read' }), 'Worker reading tab 2');
  assert.equal(selected, '2'); assert.equal(invalidations, 0);
  await root.close();
});
test('job scope keeps independent adapters and cancellation leaves foreground alive', async () => {
  const closed = [];
  const manager = new BrowserSessionManager({ store, isolatedFactory: options => ({
    async run(_args, ctx) { return `${options?.scope || 'foreground'}:${ctx.settings.headless}`; },
    tabs: async () => [], close: async () => closed.push(options?.scope || 'foreground'),
  }) });
  assert.equal(typeof manager.createScope, 'function');
  const job = manager.createScope('job-one', { profile: 'test-profile', mode: 'isolated', headless: true });
  assert.equal(await manager.run({ action: 'tabs' }), 'foreground:false');
  assert.equal(await job.run({ action: 'tabs' }), 'job-one:true');
  await manager.closeScope('job-one');
  assert.deepEqual(closed, ['job-one']);
  assert.equal(await manager.run({ action: 'tabs' }), 'foreground:false');
  await manager.close();
});
test('browser manager applies runtime policy to every batch step, before any adapter side effect', async () => {
  const calls = [];
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({ run: async args => { calls.push(args.action); return 'ok'; }, tabs: async () => [] }) });
  const result = await manager.run({ action: 'batch', steps: [{ action: 'open', url: 'https://example.com' }, { action: 'act', ref: 'opaque' }] }, {
    authorizeBrowser: async args => { if (args.action === 'act') throw new Error('permission denied'); },
  });
  assert.match(result, /permission denied/);
  assert.deepEqual(calls, ['open']);
  await manager.close();
});
test('stopping the foreground preview preserves job browser scopes', async () => {
  const closed = [];
  const manager = new BrowserSessionManager({ store, isolatedFactory: options => ({ run: async () => 'ok', tabs: async () => [], close: async () => closed.push(options?.scope || 'foreground') }) });
  const job = manager.createScope('job', { mode: 'isolated' });
  await manager.run({ action: 'tabs' }, { browserThreadId: 'owner' }); await job.run({ action: 'tabs' });
  await manager.close({ includeScopes: false });
  assert.deepEqual(closed, ['foreground']); assert.equal(manager.scopes.get('job'), job);
  await manager.close();
});

test('foreground cancellation preserves the shared Chrome transport when a job scope exists', async () => {
  let connected = true, begin;
  const began = new Promise(resolve => { begin = resolve; });
  const manager = new BrowserSessionManager({ store, chromeFactory: () => ({ tabs: async () => [], close: async () => { connected = false; }, invalidate() {}, run: async (_args, ctx) => { begin(); await new Promise(resolve => ctx.signal.addEventListener('abort', resolve, { once: true })); throw new Error('cancelled'); } }) });
  manager.createScope('job', { mode: 'local' });
  const work = manager.run({ action: 'snapshot', mode: 'local' }, { browserThreadId: 'owner' }); await began; manager.cancel('owner'); await work; await manager.tail;
  assert.equal(connected, true); await manager.close();
});

test('background approval waits outlive browser transport deadlines and remain cancellable', async t => {
  let approve, began, settled = false;
  const gate = new Promise(resolve => { approve = resolve; }), started = new Promise(resolve => { began = resolve; });
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => ({ tabs: async () => [], run: async () => 'ok', close: async () => {} }) });
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const work = manager.run({ action: 'open', url: 'https://example.com' }, { backgroundJob: true, authorizeBrowser: async () => { began(); await gate; } }).then(value => { settled = true; return value; });
  await started; t.mock.timers.tick(300_001); await new Promise(resolve => setImmediate(resolve));
  assert.equal(settled, false); approve(); assert.equal(await work, 'ok');
  t.mock.timers.reset(); await manager.close();
});
test('Chrome job scope cannot select or close user tabs and does not disconnect shared MCP', async () => {
  const calls = [];
  let tabs = '1: https://example.com [selected]';
  const mcp = { has: () => true, async callTool(name, args) {
    calls.push([name, args]);
    if (name.endsWith('list_pages')) return tabs;
    if (name.endsWith('new_page')) { tabs += '\n2: https://example.com'; return 'created'; }
    return 'page';
  }, disconnect: async () => calls.push(['disconnect']) };
  const adapter = new ChromeBrowserAdapter(mcp, { ownedTabs: true });
  assert.deepEqual(await adapter.tabs(), []);
  await adapter.run({ action: 'open', url: 'https://example.com' }, { config: { allowPrivateHosts: true } });
  assert.deepEqual((await adapter.tabs()).map(x => x.id), ['2']);
  await assert.rejects(adapter.run({ action: 'close', tab: '1' }, {}), /job|owned/i);
  await adapter.close();
  assert.equal(calls.some(x => x[0] === 'disconnect'), false);
  assert.deepEqual(calls.filter(x => x[0].endsWith('close_page')).map(x => x[1].pageId), [2]);
});
