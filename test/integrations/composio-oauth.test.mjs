import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {
  connectComposio, ComposioGrantStore, assertTrustedEndpoint, createPkce, base64url, discover,
  COMPOSIO_MCP_URL, CALLBACK_PATH,
} from '../../src/integrations/composio-oauth.mjs';
import { oauthEndpoint } from '../../src/integrations/composio.mjs';
import { ComposioStore } from '../../src/integrations/composio-store.mjs';
import { McpManager } from '../../src/integrations/mcp-manager.mjs';
import { run as runComposioTool } from '../../tools/connectors/composio.mjs';

const ACCESS_TOKEN = 'oauth-access-token-must-stay-in-the-vault';
const tempDir = () => fs.mkdtempSync(path.join(os.tmpdir(), 'composio-oauth-'));
const waitFor = async (predicate, limit = 2000) => { const until = Date.now() + limit; while (Date.now() < until) { if (predicate()) return; await new Promise(resolve => setTimeout(resolve, 10)); } throw new Error('timed out waiting for the browser step'); };

/** Vault stand-in. Mirrors the SecureStore contract the desktop already implements. */
function memorySecrets() {
  const map = new Map(), removed = [];
  return {
    map, removed,
    saveSecret: async (name, value) => { map.set(name, value); return { name }; },
    withSecret: async (name, callback) => (map.has(name) ? callback(map.get(name)) : null),
    removeSecret: async (name) => { removed.push(name); map.delete(name); return true; },
  };
}

/** A real authorization server over real HTTP, including PKCE verification. */
async function stubAuthorizationServer() {
  const state = { registered: null, token: null, challenge: null, method: null, code: null, redirectUri: null };
  const origin = () => `http://127.0.0.1:${app.address().port}`;
  const app = http.createServer(async (req, res) => {
    const url = new URL(req.url, origin());
    let body = '';
    for await (const chunk of req) body += chunk;
    const json = (value) => { res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify(value)); };
    if (url.pathname === '/.well-known/oauth-protected-resource') return json({ authorization_servers: [origin()] });
    if (url.pathname === '/.well-known/oauth-authorization-server') return json({
      authorization_endpoint: `${origin()}/authorize`,
      token_endpoint: `${origin()}/token`,
      registration_endpoint: `${origin()}/register`,
    });
    if (url.pathname === '/register') { state.registered = JSON.parse(body); return json({ client_id: 'client-1' }); }
    if (url.pathname === '/token') {
      const form = new URLSearchParams(body);
      state.token = Object.fromEntries(form);
      if (form.get('grant_type') !== 'authorization_code') { res.writeHead(400).end('bad grant'); return; }
      if (form.get('code') !== state.code) { res.writeHead(400).end('bad code'); return; }
      if (form.get('redirect_uri') !== state.redirectUri) { res.writeHead(400).end('bad redirect'); return; }
      // Recompute S256: a wrong verifier must not mint a token.
      const challenge = base64url(crypto.createHash('sha256').update(String(form.get('code_verifier'))).digest());
      if (challenge !== state.challenge) { res.writeHead(400).end('pkce mismatch'); return; }
      // RFC 8707: the token request must repeat the resource indicator, and it
      // must match the one the authorize request carried.
      if (form.get('resource') !== state.resource) { res.writeHead(400).end('bad resource'); return; }
      return json({ access_token: ACCESS_TOKEN, token_type: 'bearer', scope: 'gmail' });
    }
    res.writeHead(404).end();
  });
  await new Promise(resolve => app.listen(0, '127.0.0.1', resolve));
  return { base: origin(), state, close: () => new Promise(resolve => { app.closeAllConnections?.(); app.close(resolve); }) };
}

/** Plays the browser: the part the user does by hand. */
async function completeInBrowser(openedUrl, server, { state, code } = {}) {
  const authorize = new URL(openedUrl);
  server.state.challenge = authorize.searchParams.get('code_challenge');
  server.state.method = authorize.searchParams.get('code_challenge_method');
  server.state.resource = authorize.searchParams.get('resource');
  const redirect = new URL(authorize.searchParams.get('redirect_uri'));
  server.state.redirectUri = redirect.origin + redirect.pathname;
  server.state.code = code ?? 'auth-code-1';
  redirect.searchParams.set('code', server.state.code);
  redirect.searchParams.set('state', state ?? authorize.searchParams.get('state'));
  return fetch(redirect);
}

test('a keyless user signs in through the browser and the token stays in the vault', async () => {
  const server = await stubAuthorizationServer();
  const secrets = memorySecrets();
  const dir = tempDir(), file = path.join(dir, 'grants.json');
  try {
    let opened = null;
    const connecting = connectComposio({
      serverUrl: `${server.base}/mcp`, allowLoopback: true, secrets, file, port: 0,
      apps: ['gmail', 'github'], openUrl: async url => { opened = url; },
    });
    await waitFor(() => opened);
    await completeInBrowser(opened, server);
    const { grant, endpoint } = await connecting;

    // PKCE was real: S256, and the server recomputed it from the verifier.
    assert.equal(server.state.method, 'S256');
    // RFC 8707: the target MCP server is named as the token audience.
    assert.equal(server.state.resource, `${server.base}/mcp`, 'the resource indicator names the MCP server');
    assert.equal(server.state.token.code_verifier.length >= 43, true, 'verifier must be long enough');
    assert.equal(server.state.token.client_id, 'client-1');
    assert.equal(server.state.registered.token_endpoint_auth_method, 'none', 'a public client, no secret');
    assert.deepEqual(server.state.registered.redirect_uris, [server.state.redirectUri]);
    assert.match(server.state.redirectUri, new RegExp(`^http://127\\.0\\.0\\.1:\\d+${CALLBACK_PATH}$`), 'loopback only');

    assert.equal(endpoint, `${server.base}/mcp`);
    assert.equal(grant.apps.join(','), 'gmail,github');
    assert.equal(grant.createdAt.length > 0, true);

    // The metadata file is not a secret store.
    const raw = fs.readFileSync(file, 'utf8');
    assert.equal(raw.includes(ACCESS_TOKEN), false, 'the token must never be written to the grant file');
    assert.equal(raw.includes('code_verifier'), false);
    assert.equal(raw.includes('refresh'), false);

    // ...and it is reachable only through the vault callback.
    const store = new ComposioGrantStore(file, { secrets });
    assert.equal(store.active(endpoint).grantId, grant.grantId);
    assert.equal(await store.withToken(grant.grantId, token => token), ACCESS_TOKEN);
    assert.equal(await store.withToken('missing-grant', token => token), null);
  } finally { await server.close(); fs.rmSync(dir, { recursive: true, force: true }); }
});

test('a signed-in grant mounts MCP over Bearer auth with no API key anywhere', async () => {
  const seen = [];
  const app = http.createServer(async (req, res) => {
    seen.push(req.headers.authorization);
    let body = '';
    for await (const chunk of req) body += chunk;
    if (!body) { res.writeHead(202).end(); return; }
    const message = JSON.parse(body);
    // Advertise the discovery meta-tool AND the executor: the gate is only
    // reachable for a tool the manager actually knows about (findTool returns
    // null for an unadvertised name, and needsApproval is false by design).
    const result = message.method === 'tools/list'
      ? { tools: [
          { name: 'COMPOSIO_SEARCH_TOOLS', inputSchema: { type: 'object' } },
          { name: 'COMPOSIO_MULTI_EXECUTE_TOOL', inputSchema: { type: 'object' } },
        ] }
      : { protocolVersion: '2025-11-25' };
    res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ jsonrpc: '2.0', id: message.id, result }));
  });
  await new Promise(resolve => app.listen(0, '127.0.0.1', resolve));
  const endpointUrl = `http://127.0.0.1:${app.address().port}/mcp`;
  const secrets = memorySecrets();
  const dir = tempDir(), file = path.join(dir, 'grants.json');
  const grants = new ComposioGrantStore(file, { secrets });
  const manager = new McpManager();
  try {
    assert.equal(await oauthEndpoint({ grants, secrets }), null, 'no grant, nothing to connect');

    await secrets.saveSecret(grants.secretName('deadbeef'), ACCESS_TOKEN);
    grants.record({ grantId: 'deadbeef', endpoint: endpointUrl, apps: ['gmail'] });
    const endpoint = await oauthEndpoint({ grants, secrets });
    assert.equal(endpoint.url, endpointUrl);
    assert.equal(endpoint.headers.authorization, `Bearer ${ACCESS_TOKEN}`);

    // Exactly how the desktop engine mounts it: no key in the config at all.
    const record = await manager.ensureComposio({}, new ComposioStore(path.join(dir, 'composio.json')).load(), fetch, { grants, secrets });
    assert.equal(record.url, endpointUrl);
    assert.equal(manager.specs()[0].function.name, 'mcp__composio__COMPOSIO_SEARCH_TOOLS');
    assert.equal(seen.includes(`Bearer ${ACCESS_TOKEN}`), true, 'the live request carried the vaulted token');
    assert.ok(grants.active().lastUsedAt, 'the grant is marked used');
    // The keyless path must still be gated by tiers, not trusted blindly.
    assert.equal(manager.needsApproval('mcp__composio__COMPOSIO_SEARCH_TOOLS'), false, 'discovery stays frictionless');
    assert.equal(manager.needsApproval('mcp__composio__COMPOSIO_MULTI_EXECUTE_TOOL', { tools: [{ slug: 'GMAIL_SEND_EMAIL' }] }), true, 'sending still asks');
  } finally {
    await manager.closeAll();
    app.closeAllConnections?.();
    await new Promise(resolve => app.close(resolve));
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('revoking drops the vaulted token and the metadata in one step', async () => {
  const secrets = memorySecrets();
  const dir = tempDir(), file = path.join(dir, 'grants.json');
  const store = new ComposioGrantStore(file, { secrets });
  try {
    await secrets.saveSecret(store.secretName('abcd1234'), ACCESS_TOKEN);
    store.record({ grantId: 'abcd1234', endpoint: COMPOSIO_MCP_URL, apps: ['gmail'] });
    assert.equal(secrets.map.size, 1);

    const removed = await store.revoke('abcd1234');
    assert.equal(removed.grantId, 'abcd1234');
    assert.deepEqual(secrets.removed, ['composio-grant-abcd1234'], 'the token is deleted, not orphaned');
    assert.equal(secrets.map.size, 0);
    assert.equal(new ComposioGrantStore(file, { secrets }).active(), null, 'nothing survives on disk');
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('a callback with the wrong state is refused and no grant is written', async () => {
  const server = await stubAuthorizationServer();
  const secrets = memorySecrets();
  const dir = tempDir(), file = path.join(dir, 'grants.json');
  try {
    let opened = null;
    const connecting = connectComposio({
      serverUrl: `${server.base}/mcp`, allowLoopback: true, secrets, file, port: 0,
      openUrl: async url => { opened = url; },
    });
    const settled = connecting.then(() => 'resolved', error => error.message);
    await waitFor(() => opened);
    // A response the app did not ask for (or a replayed one) must not be accepted.
    const response = await completeInBrowser(opened, server, { state: 'not-our-state' });
    assert.equal(response.status, 400);
    assert.match(await settled, /state did not match/i);
    assert.equal(secrets.map.size, 0, 'no token was stored');
    assert.equal(fs.existsSync(file), false, 'no grant was recorded');
  } finally { await server.close(); fs.rmSync(dir, { recursive: true, force: true }); }
});

test('a denied authorization fails the connect instead of hanging', async () => {
  const server = await stubAuthorizationServer();
  const secrets = memorySecrets();
  const dir = tempDir(), file = path.join(dir, 'grants.json');
  try {
    let opened = null;
    const connecting = connectComposio({
      serverUrl: `${server.base}/mcp`, allowLoopback: true, secrets, file, port: 0,
      openUrl: async url => { opened = url; },
    });
    const settled = connecting.then(() => 'resolved', error => error.message);
    await waitFor(() => opened);
    const authorize = new URL(opened);
    const redirect = new URL(authorize.searchParams.get('redirect_uri'));
    redirect.searchParams.set('error', 'access_denied');
    redirect.searchParams.set('state', authorize.searchParams.get('state'));
    assert.equal((await fetch(redirect)).status, 400);
    assert.match(await settled, /denied/i);
    assert.equal(secrets.map.size, 0);
  } finally { await server.close(); fs.rmSync(dir, { recursive: true, force: true }); }
});

test('the endpoint allowlist rejects anything that is not Composio over https', () => {
  assert.equal(assertTrustedEndpoint('https://connect.composio.dev/mcp'), 'https://connect.composio.dev/mcp');
  assert.match(assertTrustedEndpoint('https://app.composio.dev/1/mcp'), /^https:\/\/app\.composio\.dev/);
  for (const bad of [
    'http://connect.composio.dev/mcp',            // not https
    'https://evil.example.com/mcp',                // not Composio
    'https://composio.dev.evil.example/mcp',       // suffix spoof
    'https://user:pass@connect.composio.dev/mcp',  // embedded credentials
    'not-a-url',
  ]) assert.throws(() => assertTrustedEndpoint(bad), /trusted Composio host|must be https|not a URL|credentials/, bad);
  // Loopback is opt-in, never the default.
  assert.throws(() => assertTrustedEndpoint('http://127.0.0.1:1234/callback'), /must be https/);
  assert.equal(assertTrustedEndpoint('http://127.0.0.1:1234/callback', { allowLoopback: true }), 'http://127.0.0.1:1234/callback');
});

test('the authorize and token requests both carry the RFC 8707 resource indicator', async () => {
  const server = await stubAuthorizationServer();
  const secrets = memorySecrets();
  const dir = tempDir(), file = path.join(dir, 'grants.json');
  try {
    const serverUrl = `${server.base}/mcp`;
    let opened = null;
    // A short timeout so a failed assertion cannot leave the loopback listener
    // open for the full five-minute sign-in budget.
    const connecting = connectComposio({
      serverUrl, allowLoopback: true, secrets, file, port: 0, timeoutMs: 2000,
      openUrl: async url => { opened = url; },
    });
    connecting.catch(() => {});
    await waitFor(() => opened);
    // The authorize URL names the resource...
    assert.equal(new URL(opened).searchParams.get('resource'), serverUrl);
    await completeInBrowser(opened, server);
    await connecting;
    // ...and the token request repeats it, or the stub server refuses (400).
    assert.equal(server.state.token.resource, serverUrl);
  } finally { await server.close(); fs.rmSync(dir, { recursive: true, force: true }); }
});

test('PKCE verifiers are unique, well-formed and S256', () => {
  const a = createPkce(), b = createPkce();
  assert.notEqual(a.verifier, b.verifier);
  assert.match(a.verifier, /^[A-Za-z0-9\-_]+$/);
  assert.ok(a.verifier.length >= 43 && a.verifier.length <= 128);
  assert.equal(base64url(crypto.createHash('sha256').update(a.verifier).digest()), a.challenge);
  assert.equal(a.method, 'S256');
});

test('discovery accepts the real Composio metadata, including the login.* token host', async () => {
  // Captured live from connect.composio.dev on 2026-10-01. The token and
  // registration endpoints live on login.composio.dev - a sibling host the
  // allowlist must still accept, or every sign-in would fail the trust check.
  const RESOURCE = { resource: 'https://connect.composio.dev/mcp', authorization_servers: ['https://connect.composio.dev'] };
  const AUTHORIZATION_SERVER = {
    issuer: 'https://connect.composio.dev',
    authorization_endpoint: 'https://connect.composio.dev/oauth/authorize',
    token_endpoint: 'https://login.composio.dev/oauth2/token',
    registration_endpoint: 'https://login.composio.dev/oauth2/register',
    response_types_supported: ['code'],
    grant_types_supported: ['authorization_code', 'refresh_token'],
    code_challenge_methods_supported: ['S256'],
    token_endpoint_auth_methods_supported: ['none'],
  };
  const fetchImpl = async url => new Response(
    JSON.stringify(String(url).includes('oauth-protected-resource') ? RESOURCE : AUTHORIZATION_SERVER),
    { status: 200, headers: { 'content-type': 'application/json' } },
  );
  const metadata = await discover(COMPOSIO_MCP_URL, fetchImpl);
  assert.equal(metadata.authorizationEndpoint, 'https://connect.composio.dev/oauth/authorize');
  assert.equal(metadata.tokenEndpoint, 'https://login.composio.dev/oauth2/token');
  assert.equal(metadata.registrationEndpoint, 'https://login.composio.dev/oauth2/register');
  // The flow's assumptions must hold for this exact metadata, or silent drift breaks sign-in.
  assert.ok(AUTHORIZATION_SERVER.token_endpoint_auth_methods_supported.includes('none'), 'public clients are accepted');
  assert.ok(AUTHORIZATION_SERVER.code_challenge_methods_supported.includes('S256'), 'PKCE S256 is supported');
  assert.ok(AUTHORIZATION_SERVER.grant_types_supported.includes('authorization_code'));
});

test('the connect tool signs in through the browser with no API key and mounts MCP', async () => {
  const server = await stubAuthorizationServer();
  const secrets = memorySecrets();
  const dir = tempDir(), file = path.join(dir, 'grants.json');
  try {
    const mcp = {
      composioOauth: { serverUrl: `${server.base}/mcp`, secrets, file, allowLoopback: true, port: 0 },
      has: () => false,
      ensureComposio: async () => ({ tools: [{ name: 'COMPOSIO_SEARCH_TOOLS' }] }),
    };
    // The tool owns opening the browser; drive the user's step as soon as it does.
    mcp.composioOauth.openUrl = async url => { await completeInBrowser(url, server); };
    const result = await runComposioTool(
      { action: 'connect', service: 'gmail' },
      { config: {}, composioStore: new ComposioStore(path.join(dir, 'composio.json')).load(), mcp },
    );
    assert.match(result, /Signed in as gmail/);
    assert.match(result, /token is in the OS vault/);
    assert.equal(mcp.composioOauth.openUrl !== undefined, true);
    assert.equal(secrets.map.size, 1, 'the token landed in the vault, not the grant file');
    const raw = fs.readFileSync(file, 'utf8');
    assert.equal(raw.includes(ACCESS_TOKEN), false, 'the token must never be written to the grant file');
    assert.equal(new ComposioGrantStore(file, { secrets }).active().apps.join(','), 'gmail');
  } finally { await server.close(); fs.rmSync(dir, { recursive: true, force: true }); }
});

test('connect without a key and without a host sign-in explains what to do', async () => {
  const dir = tempDir();
  try {
    const result = await runComposioTool(
      { action: 'connect', service: 'gmail' },
      { config: {}, composioStore: new ComposioStore(path.join(dir, 'composio.json')).load(), mcp: { has: () => false } },
    );
    assert.match(result, /no Composio sign-in is available in this host/);
    assert.match(result, /COMPOSIO_API_KEY/);
  } finally { fs.rmSync(dir, { recursive: true, force: true }); }
});

test('a token endpoint that returns no token is an error, not an empty grant', async () => {
  const server = await stubAuthorizationServer();
  const secrets = memorySecrets();
  const dir = tempDir(), file = path.join(dir, 'grants.json');
  try {
    let opened = null;
    const connecting = connectComposio({
      serverUrl: `${server.base}/mcp`, allowLoopback: true, secrets, file, port: 0,
      openUrl: async url => { opened = url; },
    });
    const settled = connecting.then(() => 'resolved', error => error.message);
    await waitFor(() => opened);
    // A verifier the server will reject (PKCE mismatch) must not produce a grant.
    const authorize = new URL(opened);
    server.state.challenge = 'a-challenge-the-verifier-will-not-match';
    const redirect = new URL(authorize.searchParams.get('redirect_uri'));
    redirect.searchParams.set('code', 'auth-code-1');
    redirect.searchParams.set('state', authorize.searchParams.get('state'));
    await fetch(redirect);
    assert.match(await settled, /HTTP 400/);
    assert.equal(secrets.map.size, 0);
  } finally { await server.close(); fs.rmSync(dir, { recursive: true, force: true }); }
});
