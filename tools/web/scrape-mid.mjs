import {
  normalizeUrl,
  truncateHeadTail,
  cacheKey,
  webCache,
  fitJson,
  allowPrivateHosts,
  runBridge,
  scrapeCfg,
  landingBlocked,
  guardUrl,
  guardLanding,
  needsStealthResult,
} from "../shared/_web.mjs";

export const name = "scrape_mid";
export const description =
  "Scrape one page that blocks static fetch (or extract named fields): tries static " +
  "first, auto-escalates to a headless stealth browser on block signals. " +
  "Selectors map field names to CSS (or 'xpath:...').";

export const parameters = {
  type: "object",
  properties: {
    url: { type: "string", description: "http(s) page URL." },
    selectors: {
      type: "string",
      description: "Optional fields: 'title=h1, price=.price' (CSS) or 'xpath://h1'.",
    },
    format: { type: "string", description: "markdown (default), text, or json." },
    mode: { type: "string", description: "auto (default), static, or stealth." },
    wait_selector: { type: "string", description: "CSS to wait for in stealth mode." },
    max_chars: { type: "integer", description: "Cap returned characters. Default 8000." },
  },
  required: ["url"],
};

export const readOnly = true;
export const needsApproval = false;

export async function run(args, ctx = {}) {
  const u = String(args.url || "").trim().split(/\s+/)[0] || "";
  if (!u || !/^https?:\/\//i.test(u)) return "ERROR: 'url' must start with http(s)://.";
  const cfg = scrapeCfg(ctx);
  if (cfg.disabled) return "ERROR: scraping is disabled (ANKITA_NO_SCRAPE=1).";
  const refused = await guardUrl(u, ctx);
  if (refused) return refused;

  const md = String(args.mode || "auto").trim().toLowerCase() || "auto";
  if (!["auto", "static", "stealth"].includes(md)) {
    return "ERROR: 'mode' must be auto, static, or stealth.";
  }
  const fmt = String(args.format || "markdown").trim().toLowerCase() || "markdown";
  if (!["markdown", "text", "json"].includes(fmt)) {
    return "ERROR: 'format' must be markdown, text, or json.";
  }
  const selectors = String(args.selectors || "").trim();
  const cap = Math.max(500, Math.floor(Number(args.max_chars) || 0) || cfg.maxOutput);
  const key = cacheKey("scrape:mid", {
    url: normalizeUrl(u),
    sels: selectors,
    format: fmt,
    mode: md,
    cap,
  });
  webCache.setTtl(cfg.cacheTtl);
  const [hit, ok] = webCache.get(key);
  if (ok && hit) return hit + "\n(cached; mid)";

  let result = null;
  let used = "static";
  if (md === "auto" || md === "static") {
    const bridge = await runBridge(
      {
        cmd: "static",
        urls: [u],
        timeout_s: cfg.timeoutS,
        retries: cfg.retries,
        markdown: fmt !== "text",
        selectors,
        allow_private: allowPrivateHosts(ctx),
      },
      { timeoutMs: (cfg.timeoutS + 15) * 1000, pythonBin: cfg.pythonBin }
    );
    if (!bridge.ok) {
      if (md === "static") return `ERROR: scrape-mid static fetch failed for ${u}: ${bridge.error}`;
    } else {
      const first = (bridge.results || [])[0] || {};
      if (!first.error) result = first;
      else if (md === "static") return `ERROR: scrape-mid static fetch failed for ${u}: ${first.error}`;
    }
  }
  if (md === "stealth" || (md === "auto" && needsStealthResult(result, Boolean(selectors)))) {
    const bridge = await runBridge(
      {
        cmd: "stealth",
        url: u,
        wait_selector: args.wait_selector || "",
        timeout_ms: cfg.stealthTimeoutMs,
        markdown: fmt !== "text",
        selectors,
        allow_private: allowPrivateHosts(ctx),
      },
      { timeoutMs: cfg.stealthTimeoutMs + 20000, pythonBin: cfg.pythonBin }
    );
    if (!bridge.ok || !bridge.result || bridge.result.error) {
      const err = !bridge.ok ? bridge.error : bridge.result?.error || "no result";
      if (!result) return `ERROR: scrape-mid stealth fetch failed for ${u}: ${err}`;
      used = "static+stealth-failed";
    } else {
      result = bridge.result;
      used = "stealth";
    }
  }
  if (!result) return `ERROR: scrape-mid fetch failed for ${u}.`;

  const landed = await guardLanding(result.history, result.final_url, u, ctx);
  if (landed) return landed;
  const status = Number(result.status) || 200;
  if (status < 200 || status >= 400) return `ERROR: scrape-mid http ${status} for ${u} (${used}).`;

  let out;
  if (selectors) {
    out = fitJson([{ url: u, mode: used, fields: result.fields || {} }], cap);
    webCache.put(key, out);
    return out + `\n(mid/${used}; selectors)`;
  }
  if (fmt === "json") {
    out = fitJson([{ url: u, mode: used, title: result.title || "", text: result.markdown || result.text || "" }], cap);
  } else {
    const text = String((fmt === "text" ? result.text : result.markdown || result.text) || "").trim();
    if (!text) return `ERROR: no readable text at ${u} (${used}).`;
    out = truncateHeadTail(text, cap).text;
  }
  if (!String(out).trim()) {
    return `ERROR: no readable text at ${u} (${used}). Try format:"text" or mode:"stealth".`;
  }
  webCache.put(key, out);
  return out + `\n(mid/${used})`;
}
