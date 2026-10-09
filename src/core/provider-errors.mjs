// Bytes: bound error-envelope inspection; remote text is classified, never displayed.
const ERROR_ENVELOPE_BYTES = 16_384;
const HTTP_ERROR_MIN = 400; // HTTP status range eligible for provider error metadata.
const HTTP_ERROR_MAX = 599;
const MESSAGES = Object.freeze({
  provider_rate_limit: 'The provider is rate-limiting this model. Wait before retrying or choose another eligible model.',
  provider_quota: 'The provider reports exhausted credits or quota. Check your account balance or choose an eligible free model.',
  provider_model_access: 'This model requires account access or credits. Choose an eligible model or check your provider account.',
  provider_client_restricted: 'This free model is restricted to the provider client. Choose a model available through its API.',
  provider_authentication: 'The provider rejected authentication. Check the API key and endpoint in provider settings.',
  provider_vision: 'The selected model does not support image input. Choose a vision-capable model or use browser text observations.',
  provider_unavailable: 'The provider or its upstream model is unavailable. Retry later or choose another model.',
  provider_generation: 'The provider failed to generate a reply. Check model availability and account access before retrying.',
});
export function providerError(payload, status) {
  const root = payload && typeof payload === 'object' ? payload : {};
  const error = root.error && typeof root.error === 'object' ? root.error : root;
  const hint = [error.code, error.type, error.message, typeof root.error === 'string' ? root.error : ''].filter(value => typeof value === 'string').join(' ').toLowerCase();
  const numeric = Number(error.code);
  status ||= Number.isInteger(numeric) && numeric >= HTTP_ERROR_MIN && numeric <= HTTP_ERROR_MAX ? numeric : undefined;
  let code = 'provider_generation';
  if (/insufficient_quota|quota_exceeded|insufficient (?:credits|balance)|payment_required/.test(hint) || status === 402) code = 'provider_quota';
  else if (/paid_model_auth_required/.test(hint)) code = 'provider_model_access';
  else if (/freetiererror|only.*(?:within|from).*opencode|client.restricted/.test(hint)) code = 'provider_client_restricted';
  else if (/support.*(?:image|vision).*input|image input|vision.*not supported/.test(hint)) code = 'provider_vision';
  else if (status === 429 || /rate_limit|rate.limit/.test(hint)) code = 'provider_rate_limit';
  else if (status === 401 || status === 403) code = 'provider_authentication';
  else if (status >= 500) code = 'provider_unavailable';
  const result = new Error(`${status ? `API error ${status}: ` : ''}${MESSAGES[code]}`);
  result.code = code; result.status = status;
  return result;
}
export async function responseError(response) {
  const reader = response.body?.getReader();
  let data;
  if (reader) {
    const chunks = []; let bytes = 0;
    try {
      while (bytes <= ERROR_ENVELOPE_BYTES) {
        const { done, value } = await reader.read();
        if (done) break;
        bytes += value.byteLength;
        if (bytes <= ERROR_ENVELOPE_BYTES) chunks.push(Buffer.from(value));
      }
      if (bytes <= ERROR_ENVELOPE_BYTES) data = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    } catch {} finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  }
  return providerError(data, response.status);
}
