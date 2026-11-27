import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import metrics from '../../admin/api/metrics.mjs';

const ADMIN_ROOT = fileURLToPath(new URL('../../admin/', import.meta.url));
const ADMIN_TOKEN = 'live-test-admin-token';
const PROJECT_URL = 'https://live-test.supabase.co';
const SERVICE_KEY = 'live-test-service-role-key';
const FIXTURE_METRICS = {
  updatedAt: '2026-11-27T10:00:00Z',
  summary: { totalUsers: 3, activeToday: 2, active7Days: 3, active30Days: 3, newUsers30Days: 2, returningUsers30Days: 1 },
  daily: [],
  platforms: [],
  versions: [],
  recentUsers: [],
};

async function sendStatic(response, file, contentType) {
  response.statusCode = 200;
  response.setHeader('Content-Type', contentType);
  response.end(await readFile(path.join(ADMIN_ROOT, file)));
}

test('the one-page admin site and protected metrics API make a live HTTP round trip', async t => {
  const savedEnvironment = Object.fromEntries(['ADMIN_ACCESS_TOKEN', 'SUPABASE_URL', 'SUPABASE_SECRET_KEY'].map(key => [key, process.env[key]]));
  const originalFetch = globalThis.fetch;
  process.env.ADMIN_ACCESS_TOKEN = ADMIN_TOKEN;
  process.env.SUPABASE_URL = PROJECT_URL;
  process.env.SUPABASE_SECRET_KEY = SERVICE_KEY;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, `${PROJECT_URL}/rest/v1/rpc/heartbeat_admin_metrics`);
    assert.equal(options.headers.apikey, SERVICE_KEY);
    return { ok: true, json: async () => FIXTURE_METRICS };
  };

  const server = createServer(async (request, response) => {
    if (request.url === '/api/metrics') return metrics(request, response);
    if (request.url === '/') return sendStatic(response, 'index.html', 'text/html; charset=utf-8');
    if (request.url === '/styles.css') return sendStatic(response, 'styles.css', 'text/css; charset=utf-8');
    if (request.url === '/src/admin.mjs') return sendStatic(response, 'src/admin.mjs', 'text/javascript; charset=utf-8');
    response.statusCode = 404;
    response.end();
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(async () => {
    globalThis.fetch = originalFetch;
    for (const [key, value] of Object.entries(savedEnvironment)) {
      if (value === undefined) delete process.env[key];
      else process.env[key] = value;
    }
    await new Promise(resolve => server.close(resolve));
  });

  const address = server.address();
  const origin = `http://127.0.0.1:${address.port}`;
  const httpFetch = originalFetch.bind(globalThis);
  const page = await httpFetch(origin);
  assert.equal(page.status, 200);
  assert.match(await page.text(), /Ankita · Fieldnotes/);
  const style = await httpFetch(`${origin}/styles.css`);
  assert.equal(style.status, 200);
  assert.match(await style.text(), /--paper:/);

  const denied = await httpFetch(`${origin}/api/metrics`);
  assert.equal(denied.status, 401);
  const authorized = await httpFetch(`${origin}/api/metrics`, { headers: { Authorization: `Bearer ${ADMIN_TOKEN}` } });
  assert.equal(authorized.status, 200);
  assert.deepEqual(await authorized.json(), FIXTURE_METRICS);
});
