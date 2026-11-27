import test from 'node:test';
import assert from 'node:assert/strict';
import metrics from '../../admin/api/metrics.mjs';

const TEST_TOKEN = 'test-admin-token';
const TEST_PROJECT_URL = 'https://example.supabase.co';
const TEST_SERVICE_KEY = 'test-service-role-key';

function createResponse() {
  return {
    headers: {},
    statusCode: 200,
    body: '',
    setHeader(name, value) { this.headers[name] = value; },
    end(value) { this.body = value; },
  };
}

function setDashboardEnvironment() {
  process.env.ADMIN_ACCESS_TOKEN = TEST_TOKEN;
  process.env.SUPABASE_URL = TEST_PROJECT_URL;
  process.env.SUPABASE_SECRET_KEY = TEST_SERVICE_KEY;
}

test('the metrics API requires a valid owner token before querying Supabase', async t => {
  setDashboardEnvironment();
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; throw new Error('unexpected upstream request'); };
  t.after(() => { globalThis.fetch = originalFetch; });
  const response = createResponse();

  await metrics({ method: 'GET', headers: {} }, response);

  assert.equal(response.statusCode, 401);
  assert.deepEqual(JSON.parse(response.body), { error: 'unauthorized' });
  assert.equal(response.headers['Cache-Control'], 'private, no-store, max-age=0');
  assert.equal(calls, 0);
});

test('the metrics API calls only the aggregate RPC and returns its result', async t => {
  setDashboardEnvironment();
  const originalFetch = globalThis.fetch;
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return { ok: true, json: async () => ({ summary: { totalUsers: 3 }, recentUsers: [] }) };
  };
  t.after(() => { globalThis.fetch = originalFetch; });
  const response = createResponse();

  await metrics({ method: 'GET', headers: { authorization: `Bearer ${TEST_TOKEN}` } }, response);

  assert.equal(response.statusCode, 200);
  assert.deepEqual(JSON.parse(response.body), { summary: { totalUsers: 3 }, recentUsers: [] });
  assert.equal(request.url, `${TEST_PROJECT_URL}/rest/v1/rpc/heartbeat_admin_metrics`);
  assert.equal(request.options.headers.apikey, TEST_SERVICE_KEY);
  assert.deepEqual(JSON.parse(request.options.body), {});
});

test('the metrics API rejects other methods and hides upstream details', async t => {
  setDashboardEnvironment();
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, status: 403, text: async () => TEST_SERVICE_KEY });
  t.after(() => { globalThis.fetch = originalFetch; });
  const methodResponse = createResponse();
  await metrics({ method: 'POST', headers: { authorization: `Bearer ${TEST_TOKEN}` } }, methodResponse);
  assert.equal(methodResponse.statusCode, 405);
  assert.equal(methodResponse.headers.Allow, 'GET');

  const upstreamResponse = createResponse();
  await metrics({ method: 'GET', headers: { authorization: `Bearer ${TEST_TOKEN}` } }, upstreamResponse);
  assert.equal(upstreamResponse.statusCode, 502);
  assert.equal(upstreamResponse.body.includes(TEST_SERVICE_KEY), false);
});
