import { timingSafeEqual } from 'node:crypto';

// Timeout in milliseconds: a slow data source should not hold an admin request open.
const SUPABASE_TIMEOUT_MS = 8000;
const BEARER_PREFIX = 'Bearer ';
const EMPTY_OBJECT = Object.freeze({});

function sendJson(response, statusCode, payload) {
  response.statusCode = statusCode;
  response.setHeader('Content-Type', 'application/json; charset=utf-8');
  response.setHeader('Cache-Control', 'private, no-store, max-age=0');
  response.setHeader('X-Content-Type-Options', 'nosniff');
  response.end(JSON.stringify(payload));
}

function hasValidToken(authorization, expectedToken) {
  if (typeof authorization !== 'string' || !authorization.startsWith(BEARER_PREFIX)) return false;
  const provided = Buffer.from(authorization.slice(BEARER_PREFIX.length));
  const expected = Buffer.from(expectedToken);
  return provided.length === expected.length && timingSafeEqual(provided, expected);
}

export default async function metrics(request, response) {
  if (request.method !== 'GET') {
    response.setHeader('Allow', 'GET');
    sendJson(response, 405, { error: 'method_not_allowed' });
    return;
  }

  const adminToken = process.env.ADMIN_ACCESS_TOKEN;
  if (!adminToken || !hasValidToken(request.headers.authorization, adminToken)) {
    sendJson(response, 401, { error: 'unauthorized' });
    return;
  }

  const projectUrl = process.env.SUPABASE_URL;
  const secretKey = process.env.SUPABASE_SECRET_KEY;
  if (!projectUrl || !secretKey) {
    sendJson(response, 503, { error: 'dashboard_not_configured' });
    return;
  }

  try {
    const endpoint = `${projectUrl.replace(/\/+$/, '')}/rest/v1/rpc/heartbeat_admin_metrics`;
    const upstream = await fetch(endpoint, {
      method: 'POST',
      headers: {
        apikey: secretKey,
        Authorization: `${BEARER_PREFIX}${secretKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(EMPTY_OBJECT),
      signal: AbortSignal.timeout(SUPABASE_TIMEOUT_MS),
    });
    if (!upstream.ok) {
      sendJson(response, 502, { error: 'analytics_unavailable' });
      return;
    }
    sendJson(response, 200, await upstream.json());
  } catch {
    sendJson(response, 502, { error: 'analytics_unavailable' });
  }
}
