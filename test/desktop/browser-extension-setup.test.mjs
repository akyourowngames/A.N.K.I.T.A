import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { BrowserPluginStore } from '../../src/integrations/browser-plugins.mjs';
import { DesktopBrowserPlugins } from '../../desktop/electron/browser-plugins.mjs';

test('extension connection selection survives settings reload and starts without another approval', async t => {
  const dir = await mkdtemp(join(tmpdir(), 'extension-setup-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const file = join(dir, 'browser.json'), store = new BrowserPluginStore(file).load();
  store.setEnabled('local', true);
  assert.doesNotThrow(() => store.setChromeMode('extension'));
  assert.equal(new BrowserPluginStore(file).load().get('local').connection, 'extension');
  const connections = [];
  const plugins = new DesktopBrowserPlugins({ browserFile: file, mcpFile: join(dir, 'mcp.json'),
    approvals: { request() { assert.fail('one-time extension pairing already authorized the connection'); } },
    mcp: { has: () => false, connect: async options => connections.push(options) },
  });
  plugins.extensionService = async () => ({ browserStatus: () => ({ paired: true, connected: true }), browserGateway: async () => ({ url: 'http://127.0.0.1:12345/test-private-capability' }) });
  await plugins.startChrome();
  assert.equal(connections.length, 1);
  assert.equal(connections[0].transport, 'http');
  assert.equal(connections[0].hidden, true);
});
