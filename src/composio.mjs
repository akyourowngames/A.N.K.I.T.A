import { randomUUID } from 'node:crypto';

const API = 'https://backend.composio.dev/api/v3.1';
const TOOLKITS_API = 'https://backend.composio.dev/api/v3';
const TOKEN = /^[0-9a-f]{64}$/;
const ACCOUNT_ID = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
const SESSION_CONFIG = {
  enable: true,
  max_accounts_per_toolkit: 5,
  require_explicit_selection: true,
};
const attemptedSessionUpgrades = new Set();

export function connectionMode(config = {}) {
  if (String(config.composioApiKey || '').trim()) return 'direct';
  if (String(config.composioBrokerUrl || '').trim()) return 'broker';
  return 'unavailable';
}

export function projectHeaders(apiKey, json = false) {
  if (!String(apiKey || '').trim().startsWith('ak_')) throw new Error('Composio project API keys start with ak_');
  return { 'x-api-key': apiKey.trim(), ...(json ? { 'content-type': 'application/json' } : {}) };
}

export function canonicalSlug(value) {
  const slug = String(value || '').trim().toLowerCase();
  if (!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(slug)) throw new Error('Invalid connected app name');
  return slug === 'x' ? 'twitter' : slug;
}

function trustedComposioUrl(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error('Composio returned an untrusted URL'); }
  if (url.protocol !== 'https:' || url.username || url.password ||
      (url.hostname !== 'composio.dev' && !url.hostname.endsWith('.composio.dev'))) {
    throw new Error('Composio returned an untrusted URL');
  }
  return url.toString();
}

function brokerBase(config) {
  const url = new URL(config.composioBrokerUrl);
  if (url.protocol !== 'https:' || url.username || url.password || url.search || url.hash) {
    throw new Error('The connected-apps broker must be an HTTPS URL without credentials or a query');
  }
  return `${url.origin}${url.pathname.replace(/\/+$/, '')}`;
}

async function request(fetchImpl, url, { method = 'GET', headers = {}, body } = {}) {
  const response = await fetchImpl(url, { method, headers, ...(body === undefined ? {} : { body: JSON.stringify(body) }), signal: AbortSignal.timeout(30000) });
  if (!response.ok) throw Object.assign(new Error(`Composio request failed (HTTP ${response.status})`), { status: response.status });
  if (response.status === 204) return {};
  return response.json();
}

function state(config) {
  if (!config.composioStore) throw new Error('Composio store is unavailable');
  return config.composioStore;
}

async function brokerAccess(config, fetchImpl) {
  const base = brokerBase(config);
  const store = state(config).load();
  let token = String(config.composioBrokerToken || store.data.broker?.token || '');
  if (!token) {
    const created = await request(fetchImpl, `${base}/v1/installations`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: {} });
    token = String(created.token || '');
    if (!TOKEN.test(token) || !created.installationId) throw new Error('Broker returned invalid installation credentials');
    store.update({ broker: { installationId: created.installationId, token } });
  }
  if (!TOKEN.test(token)) throw new Error('Invalid connected-apps broker token');
  return { base, headers: { authorization: `Bearer ${token}` } };
}

function directConfig(config) {
  return { api: String(config.composioApi || API).replace(/\/$/, ''), key: config.composioApiKey };
}

async function authConfigs(config, fetchImpl) {
  const { api, key } = directConfig(config);
  const selected = new Map();
  let cursor = '';
  for (let page = 0; page < 20; page++) {
    const params = new URLSearchParams({ is_composio_managed: 'false', limit: '100' });
    if (cursor) params.set('cursor', cursor);
    const result = await request(fetchImpl, `${api}/auth_configs?${params}`, { headers: projectHeaders(key) });
    for (const item of result.items || []) {
      if (!item.id || !item.toolkit?.slug || item.status === 'DISABLED' || item.is_enabled_for_tool_router === false) continue;
      const slug = canonicalSlug(item.toolkit.slug);
      const old = selected.get(slug);
      if (!old || (item.last_updated_at || '') > old.updated) selected.set(slug, { id: item.id, updated: item.last_updated_at || '' });
    }
    const next = result.next_cursor || '';
    if (!next || next === cursor) break;
    cursor = next;
  }
  return Object.fromEntries([...selected].map(([slug, info]) => [slug, info.id]));
}

function validSession(value) {
  if (!value?.session_id || !value?.mcp?.url) throw new Error('Composio returned an invalid session');
  trustedComposioUrl(value.mcp.url);
  return value;
}

export async function ensureSession(config, fetchImpl = fetch) {
  if (connectionMode(config) !== 'direct') throw new Error('A Composio project key is required');
  const { api, key } = directConfig(config);
  projectHeaders(key);
  const store = state(config).load();
  // Some projects cannot list auth configs; managed-toolkit sessions still work.
  const wanted = await authConfigs(config, fetchImpl).catch(() => ({}));
  let current = null;
  if (store.data.sessionId) {
    const response = await fetchImpl(`${api}/tool_router/session/${encodeURIComponent(store.data.sessionId)}`, {
      headers: projectHeaders(key), signal: AbortSignal.timeout(30000),
    });
    if (response.ok) current = validSession(await response.json());
    else if (response.status !== 404) throw new Error(`Composio session lookup failed (HTTP ${response.status})`);
  }
  const upgradeKey = (sessionId) => `${sessionId}:${JSON.stringify(wanted)}`;
  const covers = current && (
    (current.config?.multi_account?.enable === true &&
      Object.entries(wanted).every(([slug, id]) => current.config?.auth_configs?.[slug] === id)) ||
    attemptedSessionUpgrades.has(upgradeKey(current.session_id))
  );
  if (covers) return current;
  const userId = current?.config?.user_id || store.data.userId || `ankita_${randomUUID()}`;
  const body = {
    user_id: userId,
    manage_connections: { enable: true, enable_wait_for_connections: true, enable_connection_removal: true },
    multi_account: SESSION_CONFIG,
    ...(Object.keys(wanted).length ? { auth_configs: wanted } : {}),
  };
  // Keep the user ID before the request so a failed retry cannot orphan existing grants.
  store.update({ userId });
  const created = validSession(await request(fetchImpl, `${api}/tool_router/session`, {
    method: 'POST', headers: projectHeaders(key, true), body,
  }));
  attemptedSessionUpgrades.add(upgradeKey(created.session_id));
  store.update({ userId, sessionId: created.session_id });
  return created;
}

export async function mcpEndpoint(config, fetchImpl = fetch) {
  if (connectionMode(config) === 'direct') {
    const session = await ensureSession(config, fetchImpl);
    return { url: trustedComposioUrl(session.mcp.url), headers: projectHeaders(config.composioApiKey) };
  }
  if (connectionMode(config) === 'broker') {
    const { base, headers } = await brokerAccess(config, fetchImpl);
    return { url: `${base}/v1/mcp`, headers };
  }
  throw new Error('Connected apps are not configured');
}

async function apiCall(config, fetchImpl, directPath, brokerPath, options = {}) {
  if (connectionMode(config) === 'direct') {
    const { api, key } = directConfig(config);
    return request(fetchImpl, `${api}${directPath}`, { ...options, headers: { ...projectHeaders(key, options.body !== undefined), ...options.headers } });
  }
  if (connectionMode(config) === 'broker') {
    const { base, headers } = await brokerAccess(config, fetchImpl);
    return request(fetchImpl, `${base}${brokerPath}`, { ...options, headers: { ...headers, ...(options.body !== undefined ? { 'content-type': 'application/json' } : {}) } });
  }
  throw new Error('Connected apps are not configured');
}

export async function listToolkits(config, { query = '', cursor = '' } = {}, fetchImpl = fetch) {
  let body;
  if (connectionMode(config) === 'direct') {
    const base = String(config.composioToolkitsApi || TOOLKITS_API).replace(/\/$/, '');
    const params = new URLSearchParams({ limit: '500', sort_by: 'usage' });
    if (cursor) params.set('cursor', cursor);
    body = await request(fetchImpl, `${base}/toolkits?${params}`, { headers: projectHeaders(config.composioApiKey) });
  } else {
    body = await apiCall(config, fetchImpl, '', `/v1/catalog${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`);
  }
  const cards = (body.items || body.data || body.cards || []).map(item => ({
    slug: item.slug, label: item.name || item.label || item.slug,
    blurb: item.description || item.blurb || '', logo: item.logo || '',
    noAuth: Boolean(item.is_no_auth || item.noAuth), domain: item.app_website || item.domain || '',
  })).filter(item => !query || `${item.slug} ${item.label} ${item.blurb}`.toLowerCase().includes(String(query).toLowerCase()));
  return { cards, nextCursor: body.next_cursor || body.nextCursor || null };
}

async function allAccounts(config, fetchImpl) {
  const session = await ensureSession(config, fetchImpl);
  const userId = session.config?.user_id || state(config).data.userId;
  const { api, key } = directConfig(config);
  const accounts = [];
  let cursor = '';
  for (let page = 0; page < 100; page++) {
    const params = new URLSearchParams({ limit: '50', user_ids: userId, order_by: 'updated_at', order_direction: 'desc' });
    if (cursor) params.set('cursor', cursor);
    const body = await request(fetchImpl, `${api}/connected_accounts?${params}`, { headers: projectHeaders(key) });
    accounts.push(...(body.items || []));
    const next = body.next_cursor || '';
    if (!next || next === cursor) break;
    cursor = next;
  }
  return accounts;
}

export async function connectedServices(config, fetchImpl = fetch) {
  if (connectionMode(config) === 'broker') {
    const body = await apiCall(config, fetchImpl, '', '/v1/connectors/connected');
    return Object.fromEntries(Object.entries(body.services || {}).map(([slug, value]) => [canonicalSlug(slug), value]));
  }
  const session = await ensureSession(config, fetchImpl);
  const { api, key } = directConfig(config);
  const [accounts, toolkits] = await Promise.all([
    allAccounts(config, fetchImpl),
    (async () => {
      const items = [];
      let cursor = '';
      for (let page = 0; page < 100; page++) {
        const params = new URLSearchParams({ limit: '50', is_connected: 'true' });
        if (cursor) params.set('cursor', cursor);
        const body = await request(fetchImpl, `${api}/tool_router/session/${encodeURIComponent(session.session_id)}/toolkits?${params}`, { headers: projectHeaders(key) });
        items.push(...(body.items || []));
        const next = body.next_cursor || '';
        if (!next || next === cursor) break;
        cursor = next;
      }
      return items;
    })(),
  ]);
  const services = {};
  for (const item of toolkits) {
    if (item.slug) services[canonicalSlug(item.slug)] = { connected: Boolean(item.is_no_auth), pending: false, status: item.is_no_auth ? 'ACTIVE' : 'INACTIVE', accounts: [] };
  }
  for (const account of accounts) {
    if (!account.toolkit?.slug || !ACCOUNT_ID.test(account.id || '')) continue;
    const slug = canonicalSlug(account.toolkit.slug);
    const service = services[slug] ||= { connected: false, pending: false, status: 'INACTIVE', accounts: [] };
    const status = account.status || 'UNKNOWN';
    service.accounts.push({ id: account.id, ...(account.alias ? { alias: account.alias } : {}), status });
    if (/^active$/i.test(status)) service.connected = true;
    if (/^(initiated|initializing|pending)$/i.test(status)) service.pending = true;
    if (service.status !== 'ACTIVE') service.status = status;
  }
  return services;
}

export async function authorize(config, slug, alias, fetchImpl = fetch) {
  const toolkit = canonicalSlug(slug);
  const trimmedAlias = alias === undefined ? undefined : String(alias).trim();
  if (trimmedAlias !== undefined && (!trimmedAlias || trimmedAlias.length > 64 || /[\x00-\x1f\x7f]/.test(trimmedAlias))) throw new Error('Account alias must be 1-64 printable characters');
  const body = { ...(trimmedAlias ? { alias: trimmedAlias } : {}) };
  if (connectionMode(config) === 'broker') {
    const result = await apiCall(config, fetchImpl, '', `/v1/connectors/${encodeURIComponent(toolkit)}/authorize`, { method: 'POST', body });
    return { url: trustedComposioUrl(result.url) };
  }
  const session = await ensureSession(config, fetchImpl);
  const result = await apiCall(config, fetchImpl, `/tool_router/session/${encodeURIComponent(session.session_id)}/link`, '', { method: 'POST', body: { toolkit, ...body } });
  return { url: trustedComposioUrl(result.redirect_url) };
}

export async function removeAccount(config, slug, accountId, fetchImpl = fetch) {
  const toolkit = canonicalSlug(slug);
  if (!ACCOUNT_ID.test(String(accountId || ''))) throw new Error('Invalid account ID');
  if (connectionMode(config) === 'broker') {
    return apiCall(config, fetchImpl, '', `/v1/connectors/${encodeURIComponent(toolkit)}/accounts/${encodeURIComponent(accountId)}`, { method: 'DELETE' });
  }
  const accounts = await allAccounts(config, fetchImpl);
  if (!accounts.some(a => a.id === accountId && a.toolkit?.slug && canonicalSlug(a.toolkit.slug) === toolkit)) throw new Error('Account not found or not owned by this user');
  await apiCall(config, fetchImpl, `/connected_accounts/${encodeURIComponent(accountId)}?revoke_on_delete=true`, '', { method: 'DELETE' });
  return { removed: 1 };
}

export async function removeService(config, slug, fetchImpl = fetch) {
  const toolkit = canonicalSlug(slug);
  if (connectionMode(config) === 'broker') return apiCall(config, fetchImpl, '', `/v1/connectors/${encodeURIComponent(toolkit)}`, { method: 'DELETE' });
  const accounts = (await allAccounts(config, fetchImpl)).filter(a => a.toolkit?.slug && canonicalSlug(a.toolkit.slug) === toolkit);
  for (const account of accounts) await removeAccount(config, toolkit, account.id, fetchImpl);
  return { removed: accounts.length };
}
