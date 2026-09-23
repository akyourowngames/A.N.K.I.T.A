import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ComposioStore } from '../src/composio-store.mjs';
import { connectionMode, ensureSession, mcpEndpoint, authorize, removeAccount, connectedServices, listToolkits } from '../src/composio.mjs';

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });
const session = (id, userId = 'ankita_test') => ({ session_id: id, mcp: { type: 'http', url: `https://app.composio.dev/tool_router/v3/${id}/mcp` }, config: { user_id: userId, multi_account: { enable: true }, auth_configs: {} } });
function fixture() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'composio-'));
  const store = new ComposioStore(path.join(dir, 'composio.json')).load();
  return { store, cleanup: () => fs.rmSync(dir, { recursive: true, force: true }) };
}

test('project key wins; broker URL can auto-register; neither is unavailable', () => {
  assert.equal(connectionMode({ composioApiKey: 'ak_test', composioBrokerUrl: 'https://broker.example' }), 'direct');
  assert.equal(connectionMode({ composioBrokerUrl: 'https://broker.example' }), 'broker');
  assert.equal(connectionMode({}), 'unavailable');
});

test('direct session creates once, reuses, and recreates a missing session with the same user', async () => {
  const { store, cleanup } = fixture();
  try {
    const calls = [];
    let missing = false;
    const fetchImpl = async (url, init = {}) => {
      calls.push({ url: String(url), init });
      if (String(url).includes('/auth_configs?')) return json({ items: [] });
      if (init.method === 'POST') {
        const body = JSON.parse(init.body);
        assert.equal(body.user_id, store.data.userId);
        assert.equal(body.multi_account.require_explicit_selection, true);
        return json(session(missing ? 's2' : 's1', body.user_id));
      }
      return missing ? json({}, 404) : json(session('s1', store.data.userId));
    };
    const cfg = { composioApiKey: 'ak_test', composioStore: store };
    assert.equal((await ensureSession(cfg, fetchImpl)).session_id, 's1');
    const userId = store.data.userId;
    assert.ok(userId.startsWith('ankita_'));
    assert.equal((await ensureSession(cfg, fetchImpl)).session_id, 's1');
    missing = true;
    assert.equal((await ensureSession(cfg, fetchImpl)).session_id, 's2');
    assert.equal(store.data.userId, userId);
    assert.equal(calls.filter(c => c.init.method === 'POST').length, 2);
  } finally { cleanup(); }
});

test('untrusted MCP and authorization URLs are rejected', async () => {
  const { store, cleanup } = fixture();
  try {
    const cfg = { composioApiKey: 'ak_test', composioStore: store };
    const badSession = async (url, init = {}) => String(url).includes('/auth_configs?') ? json({ items: [] }) : json({ ...session('s1'), mcp: { type: 'http', url: 'https://composio.dev.evil.test/mcp' } });
    await assert.rejects(mcpEndpoint(cfg, badSession), /untrusted/i);
    const fetchImpl = async (url, init = {}) => {
      if (String(url).includes('/auth_configs?')) return json({ items: [] });
      if (String(url).endsWith('/link')) return json({ redirect_url: 'https://evil.test/auth' });
      return json(session('s1'));
    };
    await assert.rejects(authorize(cfg, 'gmail', undefined, fetchImpl), /untrusted/i);
  } finally { cleanup(); }
});

test('direct disconnect proves account belongs to this user and revokes it', async () => {
  const { store, cleanup } = fixture();
  try {
    const calls = [];
    const fetchImpl = async (url, init = {}) => {
      calls.push({ url: String(url), method: init.method || 'GET' });
      if (String(url).includes('/auth_configs?')) return json({ items: [] });
      if (String(url).includes('/connected_accounts?')) return json({ items: [{ id: 'a1', toolkit: { slug: 'gmail' }, status: 'ACTIVE' }] });
      if (init.method === 'DELETE') return json({});
      return json(session('s1'));
    };
    const cfg = { composioApiKey: 'ak_test', composioStore: store };
    await assert.rejects(removeAccount(cfg, 'slack', 'a1', fetchImpl), /not found|owned/i);
    assert.equal(calls.some(c => c.method === 'DELETE'), false);
    assert.deepEqual(await removeAccount(cfg, 'gmail', 'a1', fetchImpl), { removed: 1 });
    assert.match(calls.at(-1).url, /connected_accounts\/a1\?revoke_on_delete=true$/);
  } finally { cleanup(); }
});

test('broker registers once and uses stored token for MCP endpoint', async () => {
  const { store, cleanup } = fixture();
  try {
    const calls = [];
    const token = 'a'.repeat(64);
    const fetchImpl = async (url, init = {}) => { calls.push({ url: String(url), init }); return json({ installationId: 'i1', token }, 201); };
    const cfg = { composioBrokerUrl: 'https://broker.example', composioStore: store };
    assert.equal((await mcpEndpoint(cfg, fetchImpl)).headers.authorization, `Bearer ${token}`);
    assert.equal((await mcpEndpoint(cfg, fetchImpl)).url, 'https://broker.example/v1/mcp');
    assert.equal(calls.length, 1);
    assert.equal(store.data.broker.installationId, 'i1');
  } finally { cleanup(); }
});

test('a server that omits multi-account echo does not create a session on every check', async () => {
  const { store, cleanup } = fixture();
  try {
    let creates = 0;
    const noEcho = { ...session('s1'), config: { user_id: 'ankita_test', auth_configs: {} } };
    const fetchImpl = async (url, init = {}) => {
      if (String(url).includes('/auth_configs?')) return json({ items: [] });
      if (init.method === 'POST') { creates++; return json(noEcho); }
      return json(noEcho);
    };
    const cfg = { composioApiKey: 'ak_test', composioStore: store };
    await ensureSession(cfg, fetchImpl);
    await ensureSession(cfg, fetchImpl);
    assert.equal(creates, 1);
  } finally { cleanup(); }
});

test('auth-config inventory outage does not prevent a basic session', async () => {
  const { store, cleanup } = fixture();
  try {
    const fetchImpl = async (url, init = {}) => {
      if (String(url).includes('/auth_configs?')) return json({}, 403);
      if (init.method === 'POST') return json(session('s1'));
      return json(session('s1'));
    };
    assert.equal((await ensureSession({ composioApiKey: 'ak_test', composioStore: store }, fetchImpl)).session_id, 's1');
  } finally { cleanup(); }
});

test('connected services merge toolkit inventory with owned accounts', async () => {
  const { store, cleanup } = fixture();
  try {
    const fetchImpl = async (url, init = {}) => {
      const address = String(url);
      if (address.includes('/auth_configs?')) return json({ items: [] });
      if (address.includes('/connected_accounts?')) return json({ items: [{ id: 'a1', toolkit: { slug: 'gmail' }, alias: 'work', status: 'ACTIVE' }] });
      if (address.includes('/toolkits?')) return json({ items: [{ slug: 'gmail', connected_account: { id: 'a1', status: 'ACTIVE' } }] });
      return json(session('s1'));
    };
    const services = await connectedServices({ composioApiKey: 'ak_test', composioStore: store }, fetchImpl);
    assert.deepEqual(services.gmail, { connected: true, pending: false, status: 'ACTIVE', accounts: [{ id: 'a1', alias: 'work', status: 'ACTIVE' }] });
  } finally { cleanup(); }
});

test('connected service inventory follows toolkit cursors', async () => {
  const { store, cleanup } = fixture();
  try {
    const fetchImpl = async (url) => {
      const address = String(url);
      if (address.includes('/auth_configs?')) return json({ items: [] });
      if (address.includes('/connected_accounts?')) return json({ items: [] });
      if (address.includes('/toolkits?')) return address.includes('cursor=next')
        ? json({ items: [{ slug: 'notion', is_no_auth: true }] })
        : json({ items: [{ slug: 'gmail', is_no_auth: true }], next_cursor: 'next' });
      return json(session('s1'));
    };
    const services = await connectedServices({ composioApiKey: 'ak_test', composioStore: store }, fetchImpl);
    assert.deepEqual(Object.keys(services).sort(), ['gmail', 'notion']);
  } finally { cleanup(); }
});

test('direct catalog maps cards and filters search results', async () => {
  const fetchImpl = async () => json({ items: [
    { slug: 'gmail', name: 'Gmail', description: 'Email', logo: 'logo', app_website: 'gmail.com' },
    { slug: 'slack', name: 'Slack', description: 'Chat' },
  ] });
  const result = await listToolkits({ composioApiKey: 'ak_test' }, { query: 'email' }, fetchImpl);
  assert.deepEqual(result.cards, [{ slug: 'gmail', label: 'Gmail', blurb: 'Email', logo: 'logo', noAuth: false, domain: 'gmail.com' }]);
});
