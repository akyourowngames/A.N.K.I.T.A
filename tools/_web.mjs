import dns from "node:dns";
import net from "node:net";
import crypto from "node:crypto";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

/**
 * Shared web plumbing: URL normalization, head+tail truncation, TTL cache,
 * SSRF guard, and a small retrying HTTP helper. Zero dependencies.
 */

export const BROWSER_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36";
export const HONEST_UA = "ankita/2.0";

export function browserHeaders() {
  return {
    "User-Agent": BROWSER_UA,
    "Accept-Language": "en-US,en;q=0.9",
    Accept: "text/html,application/xhtml+xml",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-User": "?1",
  };
}

export function honestHeaders() {
  return { "User-Agent": HONEST_UA, "Accept-Language": "en-US,en;q=0.9" };
}

/** Lowercase scheme/host, drop tracking params, strip trailing slash. */
export function normalizeUrl(u) {
  try {
    const p = new URL(String(u || "").trim());
    for (const k of [...p.searchParams.keys()]) {
      const low = k.toLowerCase();
      if (low.startsWith("utm_") || low === "fbclid" || low === "gclid") p.searchParams.delete(k);
    }
    let path = p.pathname.replace(/\/+$/, "") || "/";
    return `${p.protocol}//${p.hostname.toLowerCase()}${p.port ? ":" + p.port : ""}${path}${p.search}`;
  } catch {
    return String(u || "").trim().replace(/\/+$/, "");
  }
}

export function truncateHeadTail(text, cap) {
  const s = String(text ?? "");
  const limit = Math.max(200, Math.floor(Number(cap) || 8000));
  if (s.length <= limit) return { text: s, truncated: false };
  const head = Math.floor((limit * 4) / 5);
  const tail = limit - head;
  const note = `\n[...truncated ${s.length - limit} chars; showing head+tail...]\n`;
  return { text: s.slice(0, head) + note + s.slice(-tail), truncated: true };
}

export function cacheKey(kind, parts = {}) {
  const blob = kind + "|" + Object.keys(parts).sort().map((k) => `${k}=${parts[k]}`).join("|");
  return crypto.createHash("sha256").update(blob, "utf8").digest("hex").slice(0, 24);
}

/** Tiny TTL cache (in-process). */
export class TtlCache {
  constructor(ttlSec = 300) {
    this.ttlMs = Math.max(0, Number(ttlSec) || 0) * 1000;
    this.map = new Map();
  }
  setTtl(ttlSec) {
    this.ttlMs = Math.max(0, Number(ttlSec) || 0) * 1000;
  }
  get(key) {
    const entry = this.map.get(key);
    if (!entry) return [null, false];
    if (this.ttlMs <= 0 || Date.now() - entry[0] >= this.ttlMs) {
      this.map.delete(key);
      return [null, false];
    }
    return [entry[1], true];
  }
  put(key, data) {
    if (this.ttlMs <= 0) return;
    if (this.map.size > 2000) this.map.delete(this.map.keys().next().value);
    this.map.set(key, [Date.now(), data]);
  }
}

export const webCache = new TtlCache(300);

/* ------------------------------------------------------------------ */
/* SSRF guard                                                          */
/* ------------------------------------------------------------------ */

function v4Private(ip) {
  const b = ip.split(".").map(Number);
  if (b.length !== 4 || b.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) return true;
  const [a, c] = [b[0], b[1]];
  if (a === 10 || a === 127 || a === 0) return true;
  if (a === 172 && c >= 16 && c <= 31) return true;
  if (a === 192 && c === 168) return true;
  if (a === 169 && c === 254) return true;
  if (a === 192 && (c === 0 || c === 2)) return true;
  if (b[0] === 192 && b[1] === 88 && b[2] === 99) return true;
  if (a === 198 && (c === 18 || c === 19 || c === 51 || c === 100)) return true;
  if (a === 203 && c === 0 && b[2] === 113) return true;
  if (a >= 224) return true;
  return false;
}

function v6Private(ip) {
  const low = ip.toLowerCase().split("%")[0];
  if (low === "::1" || low === "::") return true;
  if (low.startsWith("fe80:") || low.startsWith("fec0:") || low.startsWith("fc") || low.startsWith("fd"))
    return true;
  if (low.startsWith("ff")) return true;
  return false;
}

/** True when the literal IP is safe to fetch (i.e. globally routable). */
export function isPublicIp(ip) {
  const clean = String(ip || "").split("%")[0];
  const family = net.isIP(clean);
  if (family === 4) return !v4Private(clean);
  if (family === 6) return !v6Private(clean);
  return false;
}

async function defaultResolve(host) {
  const records = await dns.promises.lookup(host, { all: true });
  return records.map((r) => r.address);
}

/**
 * "" when fetchable, else an "ERROR: ..." refusal. Never throws.
 *
 * Loopback and private ranges are refused by default (a fetched page must not
 * be able to make the agent probe your LAN). Pass allowPrivate:true — from
 * ALLOW_PRIVATE_HOSTS=1 — to watch your own dev server or a home dashboard.
 * The host must still resolve, so a typo is still caught.
 *
 * resolveFn(host) -> string[] is injectable for tests.
 */
export async function checkUrlPublic(url, resolveFn = defaultResolve, { allowPrivate = false } = {}) {
  let host = "";
  try {
    host = (new URL(String(url || "").trim()).hostname || "").toLowerCase().replace(/\.+$/, "");
  } catch {
    return `ERROR: refusing to fetch ${url} (unparseable URL).`;
  }
  if (!host) return `ERROR: refusing to fetch ${url} (missing host).`;
  if (!allowPrivate && host === "localhost") {
    return `ERROR: refusing to fetch ${url} (loopback host). Set ALLOW_PRIVATE_HOSTS=1 to watch local pages.`;
  }
  let ips;
  try {
    ips = await resolveFn(host);
  } catch {
    return `ERROR: refusing to fetch ${url} (DNS does not resolve: ${host}).`;
  }
  if (!ips || !ips.length) return `ERROR: refusing to fetch ${url} (DNS does not resolve: ${host}).`;
  if (allowPrivate) return "";
  for (const ip of ips) {
    if (!isPublicIp(ip)) {
      return `ERROR: refusing to fetch ${url} (non-public address (${ip})). Set ALLOW_PRIVATE_HOSTS=1 to watch local pages.`;
    }
  }
  return "";
}

/** checkUrlPublic with the session's ALLOW_PRIVATE_HOSTS preference applied. */
export function guardUrl(url, ctx) {
  return checkUrlPublic(url, undefined, { allowPrivate: allowPrivateHosts(ctx) });
}

/** landingBlocked with the session's ALLOW_PRIVATE_HOSTS preference applied. */
export function guardLanding(history, finalUrl, fallback, ctx) {
  return landingBlocked(history, finalUrl, fallback, { allowPrivate: allowPrivateHosts(ctx) });
}

/* ------------------------------------------------------------------ */
/* HTTP with retry                                                     */
/* ------------------------------------------------------------------ */

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * GET/POST returning { status, headers, text() }. Retries 429/503 honoring
 * Retry-After (capped), then throws the last error. Never returns null.
 */
export async function httpFetch(url, { method = "GET", headers = {}, body = null, timeoutMs = 20000, retries = 1 } = {}) {
  const tries = 1 + Math.max(0, Math.min(3, Math.floor(Number(retries) || 0)));
  let lastError = null;
  for (let attempt = 0; attempt < tries; attempt++) {
    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(new Error(`timeout after ${timeoutMs}ms`)), Math.max(1000, timeoutMs));
      let res;
      try {
        const init = { method, headers, signal: ctrl.signal, redirect: "follow" };
        if (body !== null && body !== undefined) {
          init.body = body instanceof URLSearchParams ? body : JSON.stringify(body);
          if (!(body instanceof URLSearchParams) && !init.headers["Content-Type"]) {
            init.headers = { ...init.headers, "Content-Type": "application/json" };
          }
        }
        res = await fetch(url, init);
      } finally {
        clearTimeout(timer);
      }
      if ((res.status === 429 || res.status === 503) && attempt < tries - 1) {
        let wait = 2000;
        const ra = Number(res.headers.get("retry-after"));
        if (Number.isFinite(ra) && ra > 0 && ra <= 20) wait = ra * 1000;
        try {
          await res.body?.cancel();
        } catch {}
        await sleep(wait);
        continue;
      }
      const text = await res.text().catch(() => "");
      return { status: res.status, headers: res.headers, text };
    } catch (err) {
      lastError = err;
      if (attempt < tries - 1) await sleep(1000);
    }
  }
  throw lastError || new Error(`HTTP request failed: ${url}`);
}

/** Shrink a JSON payload to fit `cap` without corrupting it. */
export function fitJson(obj, cap) {
  const limit = Math.max(200, Math.floor(Number(cap) || 8000));
  const shrink = (node) => {
    let cut = false;
    const walk = (n) => {
      if (Array.isArray(n)) {
        for (let i = 0; i < n.length; i++) {
          if (typeof n[i] === "string" && n[i].length > 100) {
            n[i] = n[i].slice(0, Math.max(1, 100 - Math.floor(n[i].length / 4)));
            cut = true;
          } else if (n[i] && typeof n[i] === "object") walk(n[i]);
        }
      } else if (n && typeof n === "object") {
        for (const k of Object.keys(n)) {
          if (typeof n[k] === "string" && n[k].length > 100) {
            n[k] = n[k].slice(0, Math.max(1, 100 - Math.floor(n[k].length / 4)));
            cut = true;
          } else if (n[k] && typeof n[k] === "object") walk(n[k]);
        }
      }
    };
    walk(node);
    return cut;
  };
  const clone = JSON.parse(JSON.stringify(obj));
  let blob = JSON.stringify(clone);
  if (blob.length <= limit) return blob;
  for (let i = 0; i < 12; i++) {
    if (!shrink(clone)) break;
    blob = JSON.stringify(clone);
    if (blob.length <= limit) return blob;
  }
  return blob.slice(0, limit);
}

const BRIDGE_NAME = "scrape_bridge.py";

function bridgePath() {
  try {
    return path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "scripts", BRIDGE_NAME);
  } catch {
    return path.join("scripts", BRIDGE_NAME);
  }
}

function pythonCandidates(explicit = "") {
  if (explicit && explicit.trim()) return [[explicit.trim()]];
  return process.platform === "win32" ? [["python"], ["py", "-3"]] : [["python3"], ["python"]];
}

/**
 * Run the Scrapling bridge: spawn python, pass one JSON argv, parse one JSON
 * stdout. Returns the parsed object or { ok:false, error }. Never throws.
 */
export async function runBridge(payload, { timeoutMs = 60000, pythonBin = "" } = {}) {
  const arg = JSON.stringify(payload || {});
  // Belt and braces with the bridge's own reconfigure(): stops Python from
  // picking the ANSI codepage and dying on non-ASCII page content.
  const env = { ...process.env, PYTHONIOENCODING: "utf-8", PYTHONUTF8: "1" };
  const errors = [];
  for (const prefix of pythonCandidates(pythonBin)) {
    const result = await new Promise((resolve) => {
      let child;
      try {
        child = spawn(prefix[0], [...prefix.slice(1), bridgePath(), arg], {
          windowsHide: true,
          stdio: ["ignore", "pipe", "pipe"],
          env,
        });
      } catch (err) {
        return resolve({ spawnError: err.message });
      }
      let out = "";
      let errText = "";
      let settled = false;
      const finish = (value) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        resolve(value);
      };
      const timer = setTimeout(() => {
        try {
          child.kill("SIGKILL");
        } catch {}
        finish({ timeout: true });
      }, Math.max(2000, timeoutMs));
      child.stdout.on("data", (d) => {
        out += d.toString("utf8");
        if (out.length > 12 * 1024 * 1024) {
          try {
            child.kill("SIGKILL");
          } catch {}
          finish({ timeout: false, overflow: true });
        }
      });
      child.stderr.on("data", (d) => {
        errText += d.toString("utf8").slice(0, 500);
      });
      child.on("error", (err) => finish({ spawnError: err.message }));
      child.on("close", () => finish({ out, errText }));
    });
    if (result.spawnError && /ENOENT|not recognized|not found/i.test(result.spawnError)) {
      errors.push(`${prefix.join(" ")}: ${result.spawnError}`);
      continue;
    }
    if (result.timeout) return { ok: false, error: `scrape bridge timed out after ${timeoutMs}ms` };
    if (result.overflow) return { ok: false, error: "scrape bridge output exceeded 12MB" };
    if (result.spawnError) return { ok: false, error: `cannot start python: ${result.spawnError}` };
    try {
      return JSON.parse(String(result.out || "").trim());
    } catch {
      return { ok: false, error: `bridge returned non-JSON output${result.errText ? ": " + result.errText.slice(0, 200) : ""}` };
    }
  }
  return { ok: false, error: `no python found (${errors.join("; ") || "tried python"}). Install Python 3 + pip install scrapling` };
}

/* ------------------------------------------------------------------ */
/* layered settings: app config (camelCase) > UPPER env > default      */
/* ------------------------------------------------------------------ */

const CONFIG_CAMEL = {
  WEB_TIMEOUT: "webTimeout",
  WEB_MAX_OUTPUT: "webMaxOutput",
  WEB_CACHE_TTL: "webCacheTtl",
  WEB_RETRIES: "webRetries",
  WEB_REGION: "webRegion",
  JINA_FALLBACK: "jinaFallback",
  SCRAPE_TIMEOUT: "scrapeTimeout",
  SCRAPE_STEALTH_TIMEOUT: "scrapeStealthTimeout",
  SCRAPE_MAX_OUTPUT: "scrapeMaxOutput",
  SCRAPE_MAX_PAGES: "scrapeMaxPages",
  SCRAPE_RETRIES: "scrapeRetries",
  PYTHON_BIN: "pythonBin",
  ALLOW_PRIVATE_HOSTS: "allowPrivateHosts",
  ANKITA_NO_WEB: null,
  ANKITA_NO_SCRAPE: null,
};

/** True when the user has opted into fetching loopback/private hosts. */
export function allowPrivateHosts(ctx) {
  const raw = cfgVal(ctx, "ALLOW_PRIVATE_HOSTS", "");
  return raw === true || /^(1|on|true|yes)$/i.test(String(raw));
}

/** App config (camelCase) > UPPER env var > default. Parsing is the caller's job. */
export function cfgVal(ctx, upper, dflt) {
  const camel = CONFIG_CAMEL[upper];
  if (camel) {
    const c = ctx?.config?.[camel];
    if (c !== undefined) return c;
  }
  const e = process.env[upper];
  return e === undefined || e === "" ? dflt : e;
}

/* ------------------------------------------------------------------ */
/* scrape tiers shared bits                                            */
/* ------------------------------------------------------------------ */

export const BLOCK_STATUS = new Set([403, 429, 503]);
export const THIN_BODY_CHARS = 600;

export function scrapeCfg(ctx = {}) {
  const env = (k, dflt) => cfgVal(ctx, k, dflt);
  return {
    timeoutS: Math.max(2, Number(env("SCRAPE_TIMEOUT", 30)) || 30),
    stealthTimeoutMs: Math.max(5000, Math.floor(Number(env("SCRAPE_STEALTH_TIMEOUT", 30)) * 1000) || 30000),
    maxOutput: Math.max(500, Number(env("SCRAPE_MAX_OUTPUT", 8000)) || 8000),
    maxPages: Math.max(1, Math.min(50, Math.floor(Number(env("SCRAPE_MAX_PAGES", 20)) || 20))),
    retries: Math.max(0, Math.min(3, Math.floor(Number(env("SCRAPE_RETRIES", 1)) || 0))),
    cacheTtl: Math.max(0, Number(env("WEB_CACHE_TTL", 300)) || 0),
    pythonBin: String(env("PYTHON_BIN", "") || ""),
    disabled: String(env("ANKITA_NO_SCRAPE", "") || "") === "1",
  };
}

/**
 * Structural block signal only (status / body length) — never content cues.
 * When selectors already matched fields, there is nothing to gain from a
 * browser launch; when they matched nothing on a thin page, escalate anyway
 * (likely a JS shell rather than a bad selector).
 */
export function needsStealthResult(result, hasSelectors = false) {
  if (!result || result.error) return true;
  if (BLOCK_STATUS.has(Number(result.status) || 200)) return true;
  if (hasSelectors) {
    const fields = result.fields || {};
    const keys = Object.keys(fields);
    if (keys.length && keys.some((k) => (fields[k] || []).length)) return false;
  }
  return String(result.text || "").length < THIN_BODY_CHARS;
}

/** Re-check every hop of a redirect chain; "" when clean, else ERROR text. */
export async function landingBlocked(history = [], finalUrl = "", fallback = "", opts = {}) {
  const urls = [...(history || []), finalUrl || fallback].filter(Boolean);
  const seen = [...new Set(urls)];
  for (const u of seen) {
    const refused = await checkUrlPublic(u, undefined, opts);
    if (refused) {
      return `ERROR: refusing ${fallback} (redirect chain hit non-public host: ${refused}).`;
    }
  }
  return "";
}

export function formatRecord(page, index) {
  const title = String(page.title || "(untitled)").slice(0, 160);
  const lines = [`[${index}] ${title} — ${page.mode || ""}\n    ${page.url || ""}`];
  if (page.fields && Object.keys(page.fields).length) {
    for (const [k, vals] of Object.entries(page.fields)) {
      const shown = ((vals || []).slice(0, 5).join("; ") || "(no match)").slice(0, 400);
      lines.push(`    ${k}: ${shown}`);
    }
  } else if (page.text) {
    lines.push(`    ${String(page.text).slice(0, 500)}`);
  }
  return lines.join("\n");
}

/** Named entities common in feeds and scraped prose. */
const NAMED = {
  nbsp: " ",
  ensp: " ",
  emsp: " ",
  thinsp: " ",
  shy: "",
  zwj: "",
  zwnj: "",
  ldquo: "\u201c",
  rdquo: "\u201d",
  lsquo: "\u2018",
  rsquo: "\u2019",
  sbquo: "\u201a",
  bdquo: "\u201e",
  laquo: "\u00ab",
  raquo: "\u00bb",
  mdash: "\u2014",
  ndash: "\u2013",
  minus: "\u2212",
  hellip: "\u2026",
  bull: "\u2022",
  middot: "\u00b7",
  dagger: "\u2020",
  permil: "\u2030",
  prime: "\u2032",
  times: "\u00d7",
  divide: "\u00f7",
  deg: "\u00b0",
  plusmn: "\u00b1",
  frac12: "\u00bd",
  sup2: "\u00b2",
  sup3: "\u00b3",
  copy: "\u00a9",
  reg: "\u00ae",
  trade: "\u2122",
  sect: "\u00a7",
  para: "\u00b6",
  euro: "\u20ac",
  pound: "\u00a3",
  yen: "\u00a5",
  cent: "\u00a2",
  larr: "\u2190",
  rarr: "\u2192",
  harr: "\u2194",
  infin: "\u221e",
  ne: "\u2260",
  le: "\u2264",
  ge: "\u2265",
  asymp: "\u2248",
  epsilon: "\u03b5",
  alpha: "\u03b1",
  beta: "\u03b2",
  pi: "\u03c0",
  agrave: "\u00e0",
  aacute: "\u00e1",
  eacute: "\u00e9",
  egrave: "\u00e8",
  iacute: "\u00ed",
  oacute: "\u00f3",
  uacute: "\u00fa",
  ntilde: "\u00f1",
  ccedil: "\u00e7",
  uuml: "\u00fc",
  ouml: "\u00f6",
  auml: "\u00e4",
};

/** HTML entity decoder (no DOM needed). &amp; is resolved last so that
 *  double-escaped sequences ("&amp;lt;") do not become markup. */
export function decodeEntities(s) {
  return String(s ?? "")
    .replace(/&#x([0-9a-fA-F]+);/g, (_, h) => {
      try {
        return String.fromCodePoint(parseInt(h, 16));
      } catch {
        return "";
      }
    })
    .replace(/&#(\d+);/g, (_, n) => {
      try {
        return String.fromCodePoint(Number(n));
      } catch {
        return "";
      }
    })
    .replace(/&([a-zA-Z][a-zA-Z0-9]{1,31});/g, (whole, name) =>
      Object.prototype.hasOwnProperty.call(NAMED, name.toLowerCase()) ? NAMED[name.toLowerCase()] : whole
    )
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#0?39;|&apos;/g, "'")
    .replace(/&amp;/g, "&");
}
