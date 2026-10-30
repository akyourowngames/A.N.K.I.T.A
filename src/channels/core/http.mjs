import { DeliveryError } from './outbox.mjs';
import { REQUEST_TIMEOUT_MS } from './contract.mjs';

const MILLISECONDS_PER_SECOND = 1000; // Platform retry-after values and HTTP headers use seconds.
const MAX_TIMER_MS = 2_147_483_647; // Node's maximum timer delay; larger values otherwise fire almost immediately.
const HTTP_RATE_LIMITED = 429; // Explicit rejection: retrying cannot duplicate an accepted write.
const HTTP_CLIENT_MIN = 400; // HTTP status boundaries, not provider-specific magic values.
const HTTP_SERVER_MIN = 500;

export function httpFailure(platform, status, data = {}, headers = null) {
  const effective = Number(data?.error_code) >= HTTP_CLIENT_MIN ? Number(data.error_code) : status;
  if (effective === HTTP_RATE_LIMITED) {
    const seconds = Number(data?.parameters?.retry_after ?? data?.retry_after ?? headers?.get?.('retry-after'));
    const retryAfterMs = Number.isFinite(seconds) && seconds >= 0 ? seconds * MILLISECONDS_PER_SECOND : null;
    if (retryAfterMs > MAX_TIMER_MS) return new DeliveryError('permanent', `${platform} requested an unusually long retry delay; check the service before retrying`);
    return new DeliveryError('rate_limited', `${platform} rate limit; waiting before retrying`, { retryAfterMs });
  }
  if (effective >= HTTP_SERVER_MIN || effective === 408) return new DeliveryError('unknown', `${platform} send outcome is unknown; check the conversation before retrying`);
  return new DeliveryError('permanent', `${platform} rejected this request (HTTP ${effective})`, { deadTarget: [403, 404].includes(effective) });
}

/** No credentials, signed URLs, or upstream response bodies are echoed into errors. */
export async function requestResponse(url, { platform = 'Channel', fetchImpl = fetch, signal, timeoutMs = REQUEST_TIMEOUT_MS, ...options } = {}) {
  signal?.throwIfAborted();
  const timeout = AbortSignal.timeout(timeoutMs), combined = signal ? AbortSignal.any([signal, timeout]) : timeout;
  let response;
  try { response = await fetchImpl(url, { ...options, redirect: 'error', signal: combined }); }
  catch { throw new DeliveryError('unknown', `${platform} connection ended without a delivery receipt; check the conversation before retrying`); }
  return response;
}

export async function requestJson(url, { platform = 'Channel', emptyResponse = false, ...options } = {}) {
  const response = await requestResponse(url, { platform, ...options });
  if (response.ok && response.status === 204 && emptyResponse) return { data: {}, status: response.status, headers: response.headers };
  const data = await response.json().catch(() => null);
  if (!response.ok) throw httpFailure(platform, response.status, data, response.headers);
  if (!data || typeof data !== 'object') throw new DeliveryError('unknown', `${platform} returned no readable delivery receipt`);
  return { data, status: response.status, headers: response.headers };
}
