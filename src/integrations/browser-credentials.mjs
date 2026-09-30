// Vault records are scoped to an origin, never to a registrable parent domain.
export const CREDENTIAL_STORE_FILENAME = 'browser-credentials.json';
export const CREDENTIAL_WAIT_MS = 30 * 60_000; // Thirty minutes for a user-mediated sign-in; Stop aborts immediately.
export const MAX_CREDENTIAL_FIELDS = 2; // At most one private username and password slot per selection.
export const CREDENTIAL_SELECTION_MESSAGE = 'Select at most one username and one password using observed refs. credential_fields accepts only credential=username or credential=password. Put the button ref in submit_ref. No credential was read or filled; choose from the fresh snapshot and call browser login again.'; // Fixed correction text never echoes model arguments or private input.
export function credentialFields(value) {
  if (value === undefined) return [];
  if (!Array.isArray(value) || !value.length || value.length > MAX_CREDENTIAL_FIELDS || value.some(field => !field || typeof field.ref !== 'string' || !field.ref || !['username', 'password'].includes(field.credential)) || new Set(value.map(field => field.credential)).size !== value.length) throw new Error(CREDENTIAL_SELECTION_MESSAGE);
  return value;
}
const URL_SCHEME = /^[a-z][a-z\d+.-]*:\/\//i; // URL syntax; bare hostnames default to HTTPS.
export function credentialOrigin(value) {
  if (typeof value !== 'string' || !value.trim()) throw new Error('Enter a valid website');
  let url;
  try { url = new URL(URL_SCHEME.test(value) ? value : `https://${value}`); }
  catch { throw new Error('Enter a valid website'); }
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if (url.username || url.password || (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback))) throw new Error('Credentials require HTTPS (or a local test server) without URL credentials');
  return url.origin;
}
export function credentialPage(value) { credentialOrigin(value); return new URL(URL_SCHEME.test(value) ? value : `https://${value}`).href; }
