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
  BLOCK_STATUS,
  guardUrl,
  guardLanding,
} from "./_web.mjs";

export const name = "scrape_low";
export const description =
  "Scrape one simple page: fast static fetch with browser impersonation, readable " +
  "markdown/text out, no browser. If it reports a block, escalate to scrape_mid.";

export const parameters = {
  type: "object",
  properties: {
    url: { type: "string", description: "http(s) page URL." },
    format: { type: "string", description: "markdown (default), text, or json." },
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

  const fmt = String(args.format || "markdown").trim().toLowerCase() || "markdown";
  if (!["markdown", "text", "json"].includes(fmt)) {
    return "ERROR: 'format' must be markdown, text, or json.";
  }
  const cap = Math.max(500, Math.floor(Number(args.max_chars) || 0) || cfg.maxOutput);
  const key = cacheKey("scrape:low", { url: normalizeUrl(u), format: fmt, cap });
  webCache.setTtl(cfg.cacheTtl);
  const [hit, ok] = webCache.get(key);
  if (ok && hit) return hit + "\n(cached; low/static)";

  const bridge = await runBridge(
    {
      cmd: "static",
      urls: [u],
      timeout_s: cfg.timeoutS,
      retries: cfg.retries,
      markdown: fmt !== "text",
      allow_private: allowPrivateHosts(ctx),
    },
    { timeoutMs: (cfg.timeoutS + 15) * 1000, pythonBin: cfg.pythonBin }
  );
  if (!bridge.ok) return `ERROR: scrape-low failed for ${u}: ${bridge.error}`;
  const result = (bridge.results || [])[0] || {};
  if (result.error) return `ERROR: scrape-low fetch failed for ${u}: ${result.error}`;

  const landed = await guardLanding(result.history, result.final_url, u, ctx);
  if (landed) return landed;
  const status = Number(result.status) || 200;
  if (BLOCK_STATUS.has(status)) {
    return `ERROR: ${u} blocked static fetch (http ${status}). Use scrape_mid (auto stealth) for this page.`;
  }
  if (status < 200 || status >= 400) return `ERROR: scrape-low http ${status} for ${u}.`;

  let out;
  if (fmt === "json") {
    out = fitJson([{ url: u, title: result.title || "", text: result.markdown || result.text || "" }], cap);
  } else {
    const text = String((fmt === "text" ? result.text : result.markdown || result.text) || "").trim();
    if (!text) {
      return `ERROR: no readable text at ${u} (static). Use scrape_mid for JS/blocked pages.`;
    }
    out = truncateHeadTail(text, cap).text;
  }
  if (!String(out).trim()) {
    return `ERROR: no readable text at ${u} (static). Use scrape_mid for JS/blocked pages.`;
  }
  webCache.put(key, out);
  return out + "\n(low/static)";
}
