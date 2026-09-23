const REDIRECTS = new Set([301, 302, 303, 307, 308]);
const SENSITIVE_HEADER = /auth|cookie|token|key|secret|credential|password|session/i;
const DISPLAY_HEADERS = /^(accept|content-type|content-length|user-agent|cache-control|if-none-match|if-modified-since)$/i;
const FORWARD_HEADERS = /^(accept|accept-language|user-agent|cache-control|if-none-match|if-modified-since|range)$/i;
const SECRET_FIELD = /(?:auth|bearer|token|secret|passw|cookie|session|credential|api[_-]?key|access[_-]?code|private[_-]?key)/i;
const TEXT_TYPE = /^(text\/|application\/(?:[\w.+-]*\+)?(?:json|xml)\b|application\/(?:javascript|x-www-form-urlencoded)\b)/i;

export const name = "http_request";
export const description = "Make an HTTP(S) request to a website or API, including localhost. GET/HEAD run without approval; other methods require approval. Supports JSON, raw or URL-encoded form bodies, bearer/basic authentication, redirects and bounded text/base64 responses. Returns status, headers and body even for HTTP errors. Never retries a mutation.";
export const parameters = {
  type: "object",
  properties: {
    url: { type: "string", description: "HTTP(S) URL without embedded username/password." },
    method: { type: "string", description: "HTTP method; default GET." },
    headers: { type: "object", additionalProperties: { type: "string" } },
    json: { description: "JSON request body; mutually exclusive with body/form." },
    body: { type: "string", description: "Raw request body; mutually exclusive with json/form." },
    form: { type: "object", description: "URL-encoded form fields; arrays produce repeated fields. Mutually exclusive with json/body." },
    auth: { type: "object", properties: { type: { type: "string", enum: ["bearer", "basic"] }, token: { type: "string" }, username: { type: "string" }, password: { type: "string" } }, required: ["type"] },
    expected_status: { description: "Optional expected HTTP status number or array. A mismatch sets expected_status_matched=false and error, retaining the response body.", anyOf: [{ type: "integer" }, { type: "array", items: { type: "integer" }, minItems: 1 }] },
    redirect: { type: "string", enum: ["follow", "manual", "error"], description: "Default follow. Mutation redirects are only followed for 303 (as GET); replay redirects are rejected. HTTPS downgrade is rejected." },
    max_redirects: { type: "integer", description: "Redirect limit; default 5, maximum 20." },
    response_encoding: { type: "string", enum: ["auto", "text", "base64"], description: "Default auto: textual MIME types as UTF-8; binary as base64." },
    max_bytes: { type: "integer", description: "Maximum response bytes before encoding; default 100000, maximum 1048576." },
    timeout_ms: { type: "integer", description: "Total deadline including redirects and response body; default 30000, maximum 300000." },
  },
  required: ["url"],
};

function methodOf(args = {}) { return String(args.method || "GET").toUpperCase(); }
export function readOnly(args = {}) { return ["GET", "HEAD"].includes(methodOf(args)); }
export function needsApproval(args = {}) { return !readOnly(args); }

function safeUrl(value) {
  try {
    const url = new URL(value);
    url.username = "";
    url.password = "";
    url.hash = "";
    for (const key of [...url.searchParams.keys()]) url.searchParams.set(key, "[REDACTED]");
    return url.toString();
  } catch { return "[invalid URL]"; }
}

export function display(args = {}) {
  const shown = { ...args, url: safeUrl(args.url) };
  if (args.headers) shown.headers = Object.fromEntries(Object.entries(args.headers).map(([key, value]) => [key, DISPLAY_HEADERS.test(key) ? value : "[REDACTED]"]));
  if (args.auth) shown.auth = { type: args.auth.type, credentials: "[REDACTED]" };
  for (const key of ["json", "body", "form"]) if (Object.hasOwn(args, key)) shown[key] = "[request body omitted]";
  return shown;
}

function redactKnown(text, args) {
  const known = [args.auth?.token, args.auth?.password, ...Object.entries(args.headers || {}).filter(([key]) => !DISPLAY_HEADERS.test(key)).map(([, value]) => value)].filter(value => typeof value === 'string' && value.length);
  return known.reduce((result, value) => result.split(value).join('[REDACTED]'), String(text));
}

function approvalUrl(value, args) {
  try {
    const url = new URL(value);
    url.username = ''; url.password = ''; url.hash = '';
    for (const [key, item] of [...url.searchParams.entries()]) {
      if (SECRET_FIELD.test(key)) url.searchParams.set(key, '[REDACTED]');
      else url.searchParams.set(key, redactKnown(item, args));
    }
    return url.toString();
  } catch { return '[invalid URL]'; }
}

function approvalBody(value, args, key = '', depth = 0) {
  if (SECRET_FIELD.test(key)) return '[REDACTED]';
  if (depth > 12) return '[nested value omitted]';
  if (typeof value === 'string') return redactKnown(value, args).slice(0, 4096);
  if (Array.isArray(value)) return value.slice(0, 50).map(item => approvalBody(item, args, '', depth + 1));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).slice(0, 50).map(([field, item]) => [field, approvalBody(item, args, field, depth + 1)]));
  return value;
}

export function approval(args = {}) {
  const detail = { method: methodOf(args), url: approvalUrl(args.url, args), headers: display(args).headers || {} };
  if (Object.hasOwn(args, 'json')) detail.json = approvalBody(args.json, args);
  if (Object.hasOwn(args, 'form')) detail.form = approvalBody(args.form, args);
  if (Object.hasOwn(args, 'body')) detail.body = { preview: approvalBody(args.body, args), bytes: Buffer.byteLength(String(args.body)), truncated: Buffer.byteLength(String(args.body)) > 4096 };
  return `HTTP ${detail.method} ${detail.url}\n${JSON.stringify(detail, null, 2)}`;
}

function boundedInt(value, fallback, min, max) {
  if (value === undefined) return fallback;
  if (!Number.isInteger(value) || value < min || value > max) throw new Error("HTTP request numeric option is outside its supported range");
  return value;
}

function parseUrl(value) {
  let url;
  try { url = new URL(value); } catch { throw new Error("Invalid HTTP request URL"); }
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("Only HTTP(S) request URLs are allowed");
  if (url.username || url.password) throw new Error("Embedded URL credentials are not allowed; use auth or headers");
  url.hash = "";
  return url;
}

function prepare(args) {
  const method = methodOf(args);
  if (!/^[!#$%&'*+.^_`|~0-9A-Z-]+$/.test(method)) throw new Error("Invalid HTTP method");
  const present = ["body", "json", "form"].filter(key => Object.hasOwn(args, key));
  if (present.length > 1) throw new Error("Use only one of body, json, or form");
  if (present.length && ["GET", "HEAD"].includes(method)) throw new Error("GET and HEAD requests cannot contain a body");
  let headers;
  try {
    headers = new Headers(args.headers || {});
    if (!headers.has("user-agent")) headers.set("user-agent", "ankita-cli/2");
    if (!headers.has("accept")) headers.set("accept", "*/*");
    if (args.auth) {
      if (headers.has("authorization")) throw new Error("Ambiguous auth");
      if (args.auth.type === "bearer" && typeof args.auth.token === "string" && args.auth.token) headers.set("authorization", `Bearer ${args.auth.token}`);
      else if (args.auth.type === "basic" && typeof args.auth.username === "string" && typeof args.auth.password === "string" && !args.auth.username.includes(":")) headers.set("authorization", `Basic ${Buffer.from(`${args.auth.username}:${args.auth.password}`).toString("base64")}`);
      else throw new Error("Invalid auth");
    }
  } catch { throw new Error("Invalid HTTP request headers or authentication"); }
  let body;
  if (present[0] === "json") {
    try { body = JSON.stringify(args.json); } catch { throw new Error("Invalid JSON request body"); }
    if (body === undefined) throw new Error("Invalid JSON request body");
    if (!headers.has("content-type")) headers.set("content-type", "application/json");
  } else if (present[0] === "form") {
    if (!args.form || typeof args.form !== "object" || Array.isArray(args.form)) throw new Error("Form body must be an object");
    const form = new URLSearchParams();
    for (const [key, value] of Object.entries(args.form)) for (const item of Array.isArray(value) ? value : [value]) form.append(key, String(item));
    body = form.toString();
    if (!headers.has("content-type")) headers.set("content-type", "application/x-www-form-urlencoded;charset=UTF-8");
  } else if (present[0] === "body") {
    if (typeof args.body !== "string") throw new Error("Raw request body must be a string");
    body = args.body;
  }
  return { method, headers, body };
}

function responseHeaders(headers) {
  return Object.fromEntries(headers);
}

export async function run(args = {}, ctx = {}) {
  let url = parseUrl(args.url);
  const request = prepare(args);
  const maxBytes = boundedInt(args.max_bytes, 100000, 1, 1048576);
  const timeoutMs = boundedInt(args.timeout_ms, 30000, 1, 300000);
  const maxRedirects = boundedInt(args.max_redirects, 5, 0, 20);
  const redirect = args.redirect ?? "follow";
  const requestedEncoding = args.response_encoding ?? "auto";
  if (!["follow", "manual", "error"].includes(redirect)) throw new Error("Invalid redirect policy");
  if (!["auto", "text", "base64"].includes(requestedEncoding)) throw new Error("Invalid response encoding");
  const expected = args.expected_status === undefined ? null : Array.isArray(args.expected_status) ? args.expected_status : [args.expected_status];
  if (expected && (!expected.length || expected.some(status => !Number.isInteger(status) || status < 100 || status > 599))) throw new Error("Expected status must be an HTTP status number or nonempty array");

  const controller = new AbortController();
  let timedOut = false;
  const onAbort = () => controller.abort();
  if (ctx.signal?.aborted) controller.abort();
  else ctx.signal?.addEventListener("abort", onAbort, { once: true });
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
  let response;
  try {
    for (let count = 0; ; count++) {
      response = await fetch(url, { ...request, redirect: "manual", signal: controller.signal });
      if (!REDIRECTS.has(response.status) || !response.headers.has("location") || redirect === "manual") break;
      // Cancel unread redirect bodies before opening another connection.
      void response.body?.cancel().catch(() => {});
      if (redirect === "error") throw new Error("HTTP redirect rejected by policy");
      if (count >= maxRedirects) throw new Error("HTTP redirect limit exceeded");
      let next;
      try { next = parseUrl(new URL(response.headers.get("location"), url).href); } catch { throw new Error("Invalid HTTP redirect URL"); }
      if (url.protocol === "https:" && next.protocol !== "https:") throw new Error("HTTPS redirect downgrade is not allowed");
      if (!["GET", "HEAD"].includes(request.method)) {
        if (response.status !== 303) throw new Error("HTTP redirect would replay a mutation; request rejected");
        request.method = "GET";
        request.body = undefined;
        for (const key of [...request.headers.keys()]) if (key.startsWith("content-")) request.headers.delete(key);
      }
      if (url.origin !== next.origin) {
        for (const key of [...request.headers.keys()]) if (!FORWARD_HEADERS.test(key)) request.headers.delete(key);
      }
      url = next;
    }
    const chunks = [];
    let size = 0;
    let truncated = false;
    if (response.body) {
      const reader = response.body.getReader();
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const remaining = maxBytes - size;
          chunks.push(value.subarray(0, remaining));
          size += Math.min(remaining, value.length);
          if (value.length > remaining) {
            truncated = true;
            void reader.cancel().catch(() => {});
            break;
          }
        }
      } finally { reader.releaseLock(); }
    }
    const bytes = Buffer.concat(chunks, size);
    const type = response.headers.get("content-type") || "";
    const encoding = requestedEncoding === "auto" ? (!type || TEXT_TYPE.test(type) ? "text" : "base64") : requestedEncoding;
    const matched = expected ? expected.includes(response.status) : null;
    return JSON.stringify({ url: safeUrl(url), status: response.status, status_text: response.statusText, ok: response.ok, headers: responseHeaders(response.headers), body: bytes.toString(encoding === "base64" ? "base64" : "utf8"), encoding, truncated, bytes: size, ...(expected ? { expected_status_matched: matched, ...(!matched ? { error: "Unexpected HTTP status" } : {}) } : {}) });
  } catch (err) {
    if (timedOut) throw new Error(`HTTP request timeout after ${timeoutMs}ms`);
    if (controller.signal.aborted) throw new Error("HTTP request aborted");
    // Native fetch errors may contain header values, credentials or sensitive URLs.
    if (/^(HTTP redirect|Invalid HTTP redirect|HTTPS redirect)/.test(err.message)) throw err;
    throw new Error("HTTP request failed (network or response read error)");
  } finally {
    clearTimeout(timer);
    ctx.signal?.removeEventListener("abort", onAbort);
  }
}
