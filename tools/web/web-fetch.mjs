import {
  browserHeaders,
  honestHeaders,
  normalizeUrl,
  truncateHeadTail,
  cacheKey,
  webCache,
  decodeEntities,
  cfgVal,
  allowPrivateHosts,
  checkUrlPublic,
  httpFetch,
} from "../shared/_web.mjs";

export const name = "web_fetch";
export const description =
  "Read a web page as text: downloads the URL, strips navigation/chrome, and returns " +
  "readable content. Falls back to a text-reader service when extraction is thin. " +
  "Use after web_search to read the best result in full (fetch_url is the raw " +
  "byte fetcher for APIs/exact content). Not for structured scraping — use " +
  "scrape_low/mid/high when the user asks to scrape.";

export const parameters = {
  type: "object",
  properties: {
    url: { type: "string", description: "http(s) URL to read." },
    max_chars: { type: "integer", description: "Cap returned characters. Default 8000." },
    timeout_ms: { type: "integer", description: "Give up after this many milliseconds. Default 20000." },
    raw: { type: "boolean", description: "Return the raw body without text extraction. Default false." },
    no_cache: {
      type: "boolean",
      description: "Always go to the network. Use when the current value matters more than speed.",
    },
  },
  required: ["url"],
};

export const readOnly = true;
export const needsApproval = false;

const SKIP_TAGS = new Set(["script", "style", "nav", "footer", "header", "aside", "form", "noscript"]);
const BLOCK_TAGS = new Set(["p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "div", "section", "article"]);

// Comments, CDATA and declarations (<!doctype ...>, <?xml ...?>) come first so
// the scanner consumes them instead of emitting them as text — otherwise a JS
// shell page yields literal "<!doctype html>" as its "readable content".
const TAG_RE = new RegExp(
  [
    /<!--[\s\S]*?-->/,
    /<!\[CDATA\[[\s\S]*?\]\]>/,
    /<![^>]*>/,
    /<\?[\s\S]*?\?>/,
    /<\/?([a-zA-Z][a-zA-Z0-9]*)[^>]*>/,
    /([^<]+)/,
  ]
    .map((r) => r.source)
    .join("|"),
  "g"
);

/** HTML → readable text without a DOM. Never throws. "" means "not readable". */
export function extractReadable(html) {
  try {
    const src = String(html || "").slice(0, 500000);
    let out = "";
    let skip = 0;
    TAG_RE.lastIndex = 0;
    let m;
    while ((m = TAG_RE.exec(src))) {
      if (m[2] !== undefined) {
        if (!skip && m[2].trim()) out += m[2];
        continue;
      }
      if (m[1] === undefined) continue; // comment / declaration: dropped
      const closing = m[0][1] === "/";
      const tag = m[1].toLowerCase();
      if (SKIP_TAGS.has(tag)) {
        skip += closing ? -1 : 1;
        if (skip < 0) skip = 0;
      } else if (!skip && !closing && BLOCK_TAGS.has(tag)) {
        out += "\n";
      } else if (!skip && closing && (tag === "p" || tag === "li" || /^h[1-6]$/.test(tag))) {
        out += "\n";
      }
    }
    out = decodeEntities(out).replace(/<[^>]{0,300}>/g, " ");
    out = out.replace(/[ \t]+/g, " ").replace(/\n\s*\n+/g, "\n\n").trim();
    // Leftover markup means this was a script shell, not an article. Returning
    // "" lets the caller fall back instead of shipping tag soup to the model.
    if (!out || /<!doctype|<html|<script/i.test(out.slice(0, 500))) return "";
    return out;
  } catch {}
  try {
    let txt = String(html || "");
    txt = txt.replace(/<!--[\s\S]*?-->/g, " ");
    txt = txt.replace(/<script[\s\S]*?<\/script>/gi, " ").replace(/<style[\s\S]*?<\/style>/gi, " ");
    txt = txt.replace(/<[^>]+>/g, " ");
    const text = decodeEntities(txt).replace(/\s+/g, " ").trim();
    return /<!doctype|<html/i.test(text.slice(0, 500)) ? "" : text;
  } catch {
    return "";
  }
}

function webCfg(ctx = {}) {
  const env = (k, dflt) => cfgVal(ctx, k, dflt);
  return {
    timeoutMs: Math.max(2000, Number(env("WEB_TIMEOUT", 20)) * 1000 || 20000),
    maxOutput: Math.max(500, Number(env("WEB_MAX_OUTPUT", 8000)) || 8000),
    cacheTtl: Math.max(0, Number(env("WEB_CACHE_TTL", 300)) || 0),
    jina: String(env("JINA_FALLBACK", "1") ?? "1") !== "0",
    disabled: String(env("ANKITA_NO_WEB", "") || "") === "1",
  };
}

export async function fetchRun(
  { url, max_chars = 0, timeout_ms = 0, raw = false, no_cache = false } = {},
  ctx = {},
  http = httpFetch
) {
  const u = String(url || "").trim();
  if (!u || !/^https?:\/\//i.test(u)) return "ERROR: 'url' must start with http(s)://.";
  const cfg = webCfg(ctx);
  if (cfg.disabled) return "ERROR: web fetch is disabled (ANKITA_NO_WEB=1).";
  const refused = await checkUrlPublic(u, undefined, { allowPrivate: allowPrivateHosts(ctx) });
  if (refused) return refused;

  const cap = Math.max(500, Math.floor(Number(max_chars) || 0) || cfg.maxOutput);
  const key = cacheKey("fetch", { url: normalizeUrl(u), cap, raw: !!raw });
  webCache.setTtl(cfg.cacheTtl);
  if (!no_cache) {
    const [hit, ok] = webCache.get(key);
    if (ok && hit) return hit + "\n(cached)";
  }

  const timeout = Math.max(1000, Math.floor(Number(timeout_ms) || 0) || cfg.timeoutMs);
  let res;
  try {
    res = await http(u, { headers: browserHeaders(), timeoutMs: timeout });
  } catch (err) {
    return `ERROR: fetch failed for ${u}: ${err.message}`;
  }
  if (res.status !== 200) {
    const hint =
      res.status === 401 || res.status === 403 || res.status === 429
        ? " Try scrape_mid (headless browser) or another source."
        : "";
    return `ERROR: fetch http ${res.status} for ${u}.${hint}`;
  }
  const ctype = String(res.headers?.get?.("content-type") || "").toLowerCase();
  const body = res.text || "";

  let text;
  if (ctype.includes("json")) {
    try {
      text = JSON.stringify(JSON.parse(body), null, 2);
    } catch {
      text = body;
    }
  } else if (raw) {
    text = body;
  } else if (ctype.includes("html") || body.slice(0, 2000).toLowerCase().includes("<html")) {
    text = extractReadable(body);
  } else {
    text = body;
  }
  text = String(text || "").trim();

  let readerTried = false;
  if (text.length < 600 && !raw && cfg.jina && u.startsWith("http")) {
    readerTried = true;
    try {
      const jr = await http("https://r.jina.ai/" + u, { headers: honestHeaders(), timeoutMs: timeout });
      const jt = String(jr.text || "").trim();
      if (jr.status === 200 && jt.length > text.length && !/^\{"data":null/.test(jt)) text = jt;
    } catch {}
  }
  if (!text) {
    return (
      `ERROR: no readable text at ${u} - the page is a script shell` +
      (readerTried ? " and the reader fallback was refused" : "") +
      ". Use scrape_mid (headless browser) for this URL, or pick another source."
    );
  }
  const out = truncateHeadTail(text, cap).text;
  // A caller asking for the current value did not ask for it to be remembered.
  if (!no_cache) webCache.put(key, out);
  return out;
}

export function run(args, ctx) {
  return fetchRun(
    {
      url: args.url,
      max_chars: args.max_chars,
      timeout_ms: args.timeout_ms,
      raw: args.raw,
      no_cache: args.no_cache,
    },
    ctx || {}
  );
}
