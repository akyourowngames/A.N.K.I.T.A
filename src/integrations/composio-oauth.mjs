import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import crypto from "node:crypto";
import { writeTextFile } from "../../tools/shared/_shared.mjs";

/**
 * Composio Connect OAuth (the keyless path).
 *
 * `connect.composio.dev/mcp` rejects the REST credentials outright - `ak_`
 * project keys, `uak_` CLI keys and `x-consumer-api-key` all 401 with "not a
 * valid AuthKit JWT". The only accepted auth is a Bearer token minted by the
 * standard MCP OAuth flow, so this module implements that flow:
 *
 *   discovery -> dynamic client registration -> browser authorize
 *     -> single-use loopback callback -> PKCE code exchange -> vault grant
 *
 * Two rules shape the implementation:
 *
 *  1. Nothing needs to be hosted. The redirect is a loopback listener on
 *     127.0.0.1 that lives only for the duration of one sign-in (RFC 8252).
 *     There is no public callback, no domain, no certificate and no broker.
 *  2. The token never leaves the vault. Only a `grantId` and the endpoint are
 *     written to the metadata file; `withToken` hands the plaintext to a
 *     callback and nowhere else, matching the existing SecureStore contract.
 */

export const CALLBACK_PATH = "/callback";
/** Preferred loopback port. Registered with the AS so the redirect URI is stable. */
export const PREFERRED_PORT = 5757;
export const COMPOSIO_MCP_URL = "https://connect.composio.dev/mcp";
export const COMPOSIO_HOST_SUFFIX = ".composio.dev";
export const COMPOSIO_ROOT_HOST = "composio.dev";
export const GRANT_SECRET_PREFIX = "composio-grant-";
export const OAUTH_TIMEOUT_MS = 5 * 60_000; // A human logging in by hand.
export const REQUEST_TIMEOUT_MS = 30_000; // Matches the rest of the Composio layer.
const GRANT_VERSION = 1;

export function isLoopbackHost(host) {
  return host === "127.0.0.1" || host === "[::1]" || host === "::1" || host === "localhost";
}

/**
 * Endpoint allowlist (§9). https on *.composio.dev in production.
 *
 * `allowLoopback` exists for tests and for a user-approved self-hosted
 * authorization server; it is off by default so a URL that arrived inside tool
 * output or a redirect chain can never become a live connection.
 */
export function assertTrustedEndpoint(value, { allowLoopback = false } = {}) {
  let url;
  try { url = new URL(String(value)); } catch { throw new Error(`OAuth endpoint is not a URL: ${String(value).slice(0, 80)}`); }
  if (url.username || url.password) throw new Error("OAuth endpoint must not carry credentials");
  if (url.protocol === "https:") {
    if (url.hostname === COMPOSIO_ROOT_HOST || url.hostname.endsWith(COMPOSIO_HOST_SUFFIX)) return url.toString();
    throw new Error(`OAuth endpoint is not a trusted Composio host: ${url.hostname}`);
  }
  if (allowLoopback && url.protocol === "http:" && isLoopbackHost(url.hostname)) return url.toString();
  throw new Error("OAuth endpoint must be https on a trusted Composio host");
}

export function base64url(buffer) {
  return Buffer.from(buffer).toString("base64").replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

/** RFC 7636 S256. The verifier is the secret; the challenge is what the AS sees. */
export function createPkce() {
  const verifier = base64url(crypto.randomBytes(32));
  const challenge = base64url(crypto.createHash("sha256").update(verifier).digest());
  return { verifier, challenge, method: "S256" };
}

export function createState() {
  return base64url(crypto.randomBytes(16));
}

async function getJson(fetchImpl, url, init = {}) {
  const response = await fetchImpl(url, { ...init, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  if (!response.ok) throw Object.assign(new Error(`OAuth request failed (HTTP ${response.status})`), { status: response.status });
  return response.json();
}

/**
 * Protected-resource metadata points at the authorization server; the AS
 * metadata then supplies the three endpoints. Both are validated against the
 * host allowlist before anything else happens.
 */
export async function discover(serverUrl, fetchImpl = fetch, { allowLoopback = false } = {}) {
  const origin = new URL(assertTrustedEndpoint(serverUrl, { allowLoopback })).origin;
  const resource = await getJson(fetchImpl, `${origin}/.well-known/oauth-protected-resource`);
  const issuer = assertTrustedEndpoint(resource?.authorization_servers?.[0], { allowLoopback });
  const metadata = await getJson(fetchImpl, `${issuer.replace(/\/+$/, "")}/.well-known/oauth-authorization-server`);
  const authorizationEndpoint = assertTrustedEndpoint(metadata?.authorization_endpoint, { allowLoopback });
  const tokenEndpoint = assertTrustedEndpoint(metadata?.token_endpoint, { allowLoopback });
  const registrationEndpoint = metadata?.registration_endpoint
    ? assertTrustedEndpoint(metadata.registration_endpoint, { allowLoopback })
    : null;
  return { origin, issuer, authorizationEndpoint, tokenEndpoint, registrationEndpoint };
}

/** Dynamic client registration. A public client: no secret is issued or stored. */
export async function registerClient({ registrationEndpoint, redirectUri, clientName, fetchImpl = fetch, allowLoopback = false }) {
  if (!registrationEndpoint) throw new Error("The authorization server does not support dynamic client registration");
  assertTrustedEndpoint(registrationEndpoint, { allowLoopback });
  const body = {
    client_name: clientName,
    redirect_uris: [redirectUri],
    grant_types: ["authorization_code"],
    response_types: ["code"],
    token_endpoint_auth_method: "none",
  };
  const result = await getJson(fetchImpl, registrationEndpoint, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  const clientId = String(result?.client_id || "").trim();
  if (!clientId) throw new Error("The authorization server did not return a client id");
  return { clientId, raw: result };
}

/**
 * `resource` is the RFC 8707 resource indicator: the MCP server URL the token
 * is for. The MCP authorization spec requires it in both the authorize and the
 * token request so the AS binds the token audience to this exact server, and
 * servers reject a token issued without it. Omitting it is the difference
 * between a granted sign-in and a 400 from the authorization server.
 */
export function buildAuthorizeUrl({ authorizationEndpoint, clientId, redirectUri, state, challenge, resource, scopes = [] }) {
  const url = new URL(authorizationEndpoint);
  url.searchParams.set("response_type", "code");
  url.searchParams.set("client_id", clientId);
  url.searchParams.set("redirect_uri", redirectUri);
  url.searchParams.set("state", state);
  url.searchParams.set("code_challenge", challenge);
  url.searchParams.set("code_challenge_method", "S256");
  if (resource) url.searchParams.set("resource", resource);
  if (scopes.length) url.searchParams.set("scope", scopes.join(" "));
  return url.toString();
}

function bind(server, port) {
  return new Promise((resolve, reject) => {
    const onError = (error) => { server.removeListener("listening", onListening); reject(error); };
    const onListening = () => { server.removeListener("error", onError); resolve(); };
    server.once("error", onError);
    server.once("listening", onListening);
    server.listen(port, "127.0.0.1");
  });
}

const CALLBACK_PAGE = "<!doctype html><meta charset=\"utf-8\"><title>Ankita</title><body style=\"font-family:system-ui;background:#1b1d1e;color:#ecece8;display:grid;place-items:center;height:100vh;margin:0\"><div style=\"text-align:center\"><h1 style=\"font-weight:600\">Connected.</h1><p style=\"color:#b9bbba\">You can close this tab and return to Ankita.</p></div>";

/**
 * Single-use loopback listener.
 *
 * Binds the preferred port, falling back to an OS-assigned one if it is taken
 * (RFC 8252 requires the AS to accept any port for loopback redirects, but the
 * failure is reported rather than guessed at). One code, one use; the server is
 * closed on every exit path so nothing keeps listening after sign-in.
 */
export async function startLoopbackCallback({ state, port = PREFERRED_PORT, timeoutMs = OAUTH_TIMEOUT_MS, pathName = CALLBACK_PATH } = {}) {
  const server = http.createServer();
  try {
    await bind(server, port);
  } catch (error) {
    if (error.code !== "EADDRINUSE") { server.close(); throw error; }
    await bind(server, 0);
  }
  const actualPort = server.address().port;
  const redirectUri = `http://127.0.0.1:${actualPort}${pathName}`;

  let settle;
  const code = new Promise((resolve, reject) => { settle = { resolve, reject }; });
  const finish = (fn, value) => {
    clearTimeout(timer);
    server.removeAllListeners("request");
    server.closeAllConnections?.();
    server.close();
    fn(value);
  };
  const timer = setTimeout(() => finish(settle.reject, new Error("Timed out waiting for the browser to finish signing in")), timeoutMs);

  server.on("request", (request, response) => {
    let url;
    try { url = new URL(request.url, `http://127.0.0.1:${actualPort}`); } catch { response.writeHead(400).end(); return; }
    if (url.pathname !== pathName) { response.writeHead(404).end(); return; }
    const deny = (message) => { response.writeHead(400, { "content-type": "text/plain" }).end(message); finish(settle.reject, new Error(message)); };
    // A mismatched state means this callback is not the answer to our request.
    if (url.searchParams.get("state") !== state) return deny("OAuth state did not match; sign-in was ignored.");
    const error = url.searchParams.get("error");
    if (error) return deny(`Authorization was denied (${error}).`);
    const value = url.searchParams.get("code");
    if (!value) return deny("The authorization server returned no code.");
    response.writeHead(200, { "content-type": "text/html; charset=utf-8" }).end(CALLBACK_PAGE);
    finish(settle.resolve, value);
  });

  return { redirectUri, code, close: () => finish(settle.reject, new Error("Sign-in was cancelled")), port: actualPort };
}

export async function exchangeCode({ tokenEndpoint, clientId, code, verifier, redirectUri, resource, fetchImpl = fetch, allowLoopback = false }) {
  assertTrustedEndpoint(tokenEndpoint, { allowLoopback });
  const body = new URLSearchParams({
    grant_type: "authorization_code",
    code,
    redirect_uri: redirectUri,
    client_id: clientId,
    code_verifier: verifier,
    // RFC 8707: repeated in the token request, matching the authorize request.
    ...(resource ? { resource } : {}),
  });
  const result = await getJson(fetchImpl, tokenEndpoint, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: body.toString() });
  const accessToken = String(result?.access_token || "").trim();
  if (!accessToken) throw new Error("The token endpoint returned no access token");
  const tokenType = String(result?.token_type || "bearer").toLowerCase();
  if (tokenType !== "bearer") throw new Error(`Unsupported token type "${tokenType}"`);
  return { accessToken, scope: String(result?.scope || ""), expiresIn: Number(result?.expires_in) || null };
}

/**
 * Grant metadata plus the vaulted token.
 *
 * The file holds no secret: `grantId`, endpoint, apps and timestamps only. The
 * token lives in the injected vault (`saveSecret`/`withSecret`), which is the
 * same adapter `SecureStore` already implements and is therefore desktop-first.
 */
export class ComposioGrantStore {
  constructor(file, { secrets } = {}) {
    this.file = file;
    this.secrets = secrets || null;
    this.data = { version: GRANT_VERSION, grants: [] };
    if (file) this.load();
  }

  load() {
    if (!this.file) return this;
    try {
      const parsed = JSON.parse(fs.readFileSync(this.file, "utf8"));
      this.data = {
        version: GRANT_VERSION,
        grants: Array.isArray(parsed?.grants) ? parsed.grants.filter((grant) => grant && typeof grant.grantId === "string") : [],
      };
    } catch {
      this.data = { version: GRANT_VERSION, grants: [] };
    }
    return this;
  }

  save() {
    if (!this.file) return this;
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    writeTextFile(this.file, JSON.stringify(this.data, null, 2), "\n");
    return this;
  }

  _fresh() {
    if (this.file) this.load();
    return this;
  }

  get grants() {
    return this.data.grants;
  }

  /** The most recent grant for an endpoint, or null. */
  active(endpoint = null) {
    const list = endpoint ? this.grants.filter((grant) => grant.endpoint === endpoint) : this.grants;
    return list.at(-1) || null;
  }

  secretName(grantId) {
    return `${GRANT_SECRET_PREFIX}${grantId}`;
  }

  /** Records grant metadata. `save()` is the disk write, as in the other stores. */
  record({ grantId, endpoint, apps = [], scope = "" }) {
    if (!this.secrets?.saveSecret) throw new Error("A secret store is required to keep the Composio token");
    this._fresh();
    this.data.grants.push({ grantId, endpoint, apps, scope, createdAt: new Date().toISOString(), lastUsedAt: null });
    this.save();
    return this.active(endpoint);
  }

  /** Hands the plaintext token to a callback; it is never returned. */
  withToken(grantId, callback) {
    if (!this.secrets?.withSecret) return Promise.resolve(null);
    return this.secrets.withSecret(this.secretName(grantId), callback);
  }

  markUsed(grantId) {
    const grant = this._fresh().grants.find((item) => item.grantId === grantId);
    if (!grant) return null;
    grant.lastUsedAt = new Date().toISOString();
    this.save();
    return grant;
  }

  /**
   * Revoking is one action: drop the vaulted token, forget the metadata. The
   * caller does the best-effort remote revoke, which may not be reachable.
   */
  async revoke(grantId) {
    const grant = this._fresh().grants.find((item) => item.grantId === grantId);
    if (!grant) return null;
    if (this.secrets?.removeSecret) await this.secrets.removeSecret(this.secretName(grantId));
    this.data.grants = this.grants.filter((item) => item.grantId !== grantId);
    this.save();
    return grant;
  }
}

/**
 * The whole flow, start to finish. `openUrl` is injected so the caller owns how
 * a browser is opened (Electron `shell.openExternal`, or a test's capture).
 */
export async function connectComposio({
  serverUrl = COMPOSIO_MCP_URL, openUrl, secrets, grants = null, file = null, fetchImpl = fetch,
  allowLoopback = false, clientName = "Ankita", apps = [], port = PREFERRED_PORT,
  timeoutMs = OAUTH_TIMEOUT_MS, onStatus = () => {},
} = {}) {
  if (typeof openUrl !== "function") throw new Error("connectComposio needs a way to open the browser");
  if (!secrets?.saveSecret) throw new Error("A secret store is required to keep the Composio token");

  onStatus("discovering");
  const metadata = await discover(serverUrl, fetchImpl, { allowLoopback });
  // The token audience (RFC 8707) is the MCP server this grant will mount.
  const endpoint = assertTrustedEndpoint(serverUrl, { allowLoopback });

  const state = createState();
  const pkce = createPkce();
  const callback = await startLoopbackCallback({ state, port, timeoutMs });
  try {
    onStatus("registering");
    const { clientId } = await registerClient({ registrationEndpoint: metadata.registrationEndpoint, redirectUri: callback.redirectUri, clientName, fetchImpl, allowLoopback });

    const authorizeUrl = buildAuthorizeUrl({ authorizationEndpoint: metadata.authorizationEndpoint, clientId, redirectUri: callback.redirectUri, state, challenge: pkce.challenge, resource: endpoint });
    onStatus("authorizing");
    await openUrl(authorizeUrl);

    const code = await callback.code;
    onStatus("exchanging");
    const token = await exchangeCode({ tokenEndpoint: metadata.tokenEndpoint, clientId, code, verifier: pkce.verifier, redirectUri: callback.redirectUri, resource: endpoint, fetchImpl, allowLoopback });

    const grantId = crypto.randomUUID().slice(0, 8);
    // Reuse the host's store when it has one, so the desktop engine and the
    // chat tool cannot end up with two views of the same sign-in.
    const store = grants || new ComposioGrantStore(file, { secrets });
    await secrets.saveSecret(store.secretName(grantId), token.accessToken);
    const grant = store.record({ grantId, endpoint, apps, scope: token.scope });
    onStatus("connected");
    return { grant, endpoint };
  } finally {
    callback.close();
  }
}
