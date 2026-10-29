import test from 'node:test';
import assert from 'node:assert/strict';
const module = await import('../../tools/browser/extension.mjs').catch(() => null);
import { BrowserPluginStore } from '../../src/integrations/browser-plugins.mjs';
import { BrowserSessionManager } from '../../tools/browser/session.mjs';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('extension adapter uses the MCP transport, observed refs and the existing site policy', async () => {
  assert.ok(module, 'extension browser adapter is implemented');
  const calls = [];
  const mcp = { callToolResult: async (_name, { operation }) => {
    calls.push(operation);
    const result = operation.action === 'tabs' ? [{ id: '1', title: 'Page', url: 'https://example.com/', active: true }]
      : operation.action === 'snapshot' ? { url: 'https://example.com/', title: 'Page', documentId: 'document', text: 'Observed text', controls: [{ ref: 'observed-ref', role: 'button', name: 'Publish' }] }
      : { ok: true };
    return { text: JSON.stringify({ result }), isError: false };
  } };
  const adapter = new module.ExtensionBrowserAdapter(mcp, { ensureConnected: async () => {} });
  const ctx = { settings: { blockedSites: [], allowedSites: [] } };
  await adapter.run({ action: 'snapshot' }, ctx);
  await adapter.run({ action: 'act', ref: 'observed-ref', op: 'click' }, ctx);
  assert.equal(calls.find(c => c.action === 'act').documentId, 'document');
  assert.match((await adapter.execute({ action: 'act', ref: 'made-up-ref' }, ctx)).error.message, /snapshot|reference/i);
  assert.match((await adapter.execute({ action: 'open', url: 'https://blocked.example/' }, { settings: { blockedSites: ['blocked.example'] } })).error.message, /blocked/);
  assert.equal(calls.some(c => c.url === 'https://blocked.example/'), false);
});
test('extension task scope cannot select or close a tab belonging to another task', async () => {
  assert.ok(module, 'extension browser adapter is implemented');
  let writes = 0;
  const adapter = new module.ExtensionBrowserAdapter({ callToolResult: async (_name, { operation }) => {
    if (operation.action !== 'tabs') writes++;
    return { text: JSON.stringify({ result: [] }) };
  } }, { ownedTabs: true, ensureConnected: async () => {} });
  assert.match((await adapter.execute({ action: 'close', tab: 'someone-elses-tab' }, { settings: {} })).error.message, /tab|own/i);
  assert.equal(writes, 0);
});
test('automatic browser selection prefers the paired extension over private Chromium', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'extension-preferred-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const store = new BrowserPluginStore(join(dir, 'browser.json')).load();
  store.setEnabled('isolated', true); store.setEnabled('local', true); store.setChromeMode('extension');
  let local = false;
  const manager = new BrowserSessionManager({ store, isolatedFactory: () => { assert.fail('paired browser should be the automatic choice'); },
    chromeFactory: () => { local = true; return { run: async () => '[]', tabs: async () => [] }; } });
  t.after(() => manager.close());
  await manager.run({ action: 'tabs' });
  assert.equal(local, true);
});
