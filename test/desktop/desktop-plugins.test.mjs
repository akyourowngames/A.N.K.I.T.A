import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ComposioStore } from '../../src/integrations/composio-store.mjs';
import { DesktopPlugins } from '../../desktop/electron/plugins.mjs';

const json = body => new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });

test('plugins require setup before listing or changing accounts', async () => {
  const plugins = new DesktopPlugins({ getConfig: () => ({}), fetchImpl: () => { throw new Error('unexpected network'); } });
  assert.deepEqual(await plugins.overview(), { mode: 'unavailable', live: false, services: {} });
  await assert.rejects(plugins.catalog(), /Composio project key/);
  assert.throws(() => plugins.connect({ slug: 'gmail' }), /Composio project key/);
});

test('desktop plugins expose catalog and owned accounts through the existing Composio flow', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-plugins-'));
  const file = path.join(dir, 'composio.json');
  new ComposioStore(file).update({ userId: 'ankita_test', sessionId: 's1' });
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    const address = String(url);
    calls.push({ address, method: init.method || 'GET' });
    if (address.includes('/auth_configs?')) return json({ items: [] });
    if (address.includes('/tool_router/session/s1/link')) return json({ redirect_url: 'https://app.composio.dev/connect/gmail' });
    if (address.includes('/connected_accounts?')) return json({ items: [{ id: 'acc1', toolkit: { slug: 'gmail' }, status: 'ACTIVE', alias: 'work' }] });
    if (address.includes('/tool_router/session/s1/toolkits?')) return json({ items: [{ slug: 'gmail', is_no_auth: false }] });
    if (address.includes('/tool_router/session/s1')) return json({ session_id: 's1', mcp: { url: 'https://app.composio.dev/tool_router/v3/s1/mcp' }, config: { user_id: 'ankita_test', multi_account: { enable: true }, auth_configs: {} } });
    if (address.includes('/toolkits?')) return json({ items: [{ slug: 'gmail', name: 'Gmail', description: 'Read your inbox' }, { slug: 'slack', name: 'Slack', description: 'Team chat' }] });
    if (init.method === 'DELETE') return json({});
    throw new Error(`Unexpected request: ${address}`);
  };
  try {
    const plugins = new DesktopPlugins({ getConfig: () => ({ composioApiKey: 'ak_test' }), storeFile: file, fetchImpl, isLive: () => true });
    const overview = await plugins.overview();
    assert.equal(overview.mode, 'direct');
    assert.equal(overview.live, true);
    assert.deepEqual(overview.services.gmail.accounts, [{ id: 'acc1', alias: 'work', status: 'ACTIVE' }]);
    assert.deepEqual((await plugins.catalog({ query: 'team' })).cards.map(card => card.slug), ['slack']);
    assert.deepEqual(await plugins.connect({ slug: 'gmail' }), { url: 'https://app.composio.dev/connect/gmail' });
    assert.deepEqual(await plugins.disconnectAccount({ slug: 'gmail', accountId: 'acc1' }), { removed: 1 });
    assert.deepEqual(await plugins.disconnectService({ slug: 'gmail' }), { removed: 1 });
    assert.ok(calls.some(call => call.address.includes('/connected_accounts/acc1?revoke_on_delete=true') && call.method === 'DELETE'));
    assert.equal(JSON.stringify(overview).includes('ak_test'), false);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('plugin search scans later catalog pages and keeps a cursor for more results', async () => {
  const calls = [];
  const fetchImpl = async url => {
    calls.push(String(url));
    return json(String(url).includes('cursor=next')
      ? { items: [{ slug: 'linear', name: 'Linear', description: 'Issue tracking' }], next_cursor: 'later' }
      : { items: [{ slug: 'gmail', name: 'Gmail', description: 'Email' }], next_cursor: 'next' });
  };
  const plugins = new DesktopPlugins({ getConfig: () => ({ composioApiKey: 'ak_test' }), fetchImpl });
  const result = await plugins.catalog({ query: 'issue' });
  assert.deepEqual(result.cards.map(card => card.slug), ['linear']);
  assert.equal(result.nextCursor, 'later');
  assert.equal(calls.length, 2);
});
