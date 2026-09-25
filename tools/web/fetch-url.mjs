const BINARY_HINT = /image|audio|video|octet-stream|zip|gzip|pdf|font|wasm/i;

export const name = "fetch_url";
export const description =
  "Fetch a URL over HTTP(S) and return its text, truncated to max_bytes. Follows redirects. " +
  "Use it to read docs, APIs, or pages instead of shelling out to curl.";

export const parameters = {
  type: "object",
  properties: {
    url: { type: "string", description: "http(s) URL to fetch." },
    max_bytes: { type: "integer", description: "Keep at most this many response bytes. Default 100000." },
    timeout_ms: { type: "integer", description: "Give up after this many milliseconds. Default 30000." },
  },
  required: ["url"],
};

export const readOnly = true;
export const needsApproval = false;

function clampInt(value, fallback, min, max) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, Math.floor(n)));
}

export async function run(args) {
  const url = String(args.url || "");
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    throw new Error(`invalid URL: ${url || "(empty)"}`);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error(`only http(s) URLs are allowed: ${url}`);
  }

  const maxBytes = clampInt(args.max_bytes, 100000, 256, 1024 * 1024);
  const timeoutMs = clampInt(args.timeout_ms, 30000, 100, 300000);

  let res;
  try {
    res = await fetch(url, {
      signal: AbortSignal.timeout(timeoutMs),
      redirect: "follow",
      headers: {
        "User-Agent": "ankita-cli/2",
        Accept: "text/html,application/json,text/*;q=0.9,*/*;q=0.1",
      },
    });
  } catch (err) {
    if (err.name === "TimeoutError" || err.name === "AbortError") {
      throw new Error(`request timeout after ${timeoutMs}ms: ${url}`);
    }
    throw err;
  }
  if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText || ""} for ${url}`.trim());

  const contentType = res.headers.get("content-type") || "";
  if (BINARY_HINT.test(contentType)) {
    throw new Error(`refusing non-text content (${contentType}) for ${url}`);
  }

  const reader = res.body.getReader();
  const chunks = [];
  let total = 0;
  let truncated = false;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      total += value.length;
      if (total > maxBytes) {
        chunks.push(value.subarray(0, Math.max(0, maxBytes - (total - value.length))));
        truncated = true;
        try {
          await reader.cancel();
        } catch {}
        break;
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const text = Buffer.concat(chunks).toString("utf8");
  const head = `URL: ${url}\n${contentType ? `Content-Type: ${contentType}\n` : ""}`;
  return truncated ? `${head}[truncated to ${maxBytes} of ${total}+ bytes]\n${text}` : `${head}${text}`;
}
