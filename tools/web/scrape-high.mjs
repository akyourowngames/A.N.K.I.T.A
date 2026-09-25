import {
  normalizeUrl,
  truncateHeadTail,
  cacheKey,
  webCache,
  allowPrivateHosts,
  runBridge,
  scrapeCfg,
  landingBlocked,
  guardUrl,
  guardLanding,
  needsStealthResult,
  formatRecord,
} from "../shared/_web.mjs";

export const name = "scrape_high";
export const description =
  "Crawl multiple pages (BFS, depth<=2, <=20 pages, same-domain by default). " +
  "Static first per page, stealth only for pages that fail statically. " +
  "Use ONLY when the user asks to scrape multiple pages; prefer scrape_low/mid otherwise.";

export const parameters = {
  type: "object",
  properties: {
    urls: { type: "string", description: "Seed URL(s), space/comma separated." },
    depth: { type: "integer", description: "Link-follow depth 0-2. Default 1." },
    limit: { type: "integer", description: "Max pages. Default 8, max 20." },
    same_domain: { type: "boolean", description: "Stay on seed domains. Default true." },
    selectors: { type: "string", description: "Optional 'field=css, ...' extraction." },
    mode: { type: "string", description: "auto (default), static, or stealth." },
    max_chars: { type: "integer", description: "Cap returned characters. Default 8000." },
  },
  required: ["urls"],
};

export const readOnly = true;
export const needsApproval = false;

function sameHost(a, b) {
  try {
    return new URL(a).hostname.toLowerCase() === new URL(b).hostname.toLowerCase();
  } catch {
    return false;
  }
}

export async function run(args, ctx = {}) {
  const seeds = String(args.urls || "")
    .split(/[\s,;]+/)
    .map((s) => s.trim())
    .filter((s) => /^https?:\/\//i.test(s));
  if (!seeds.length) return "ERROR: 'urls' must be one or more http(s) URLs.";
  const cfg = scrapeCfg(ctx);
  if (cfg.disabled) return "ERROR: scraping is disabled (ANKITA_NO_SCRAPE=1).";
  for (const s of seeds) {
    const refused = await guardUrl(s, ctx);
    if (refused) return refused;
  }

  const clampNotes = [];
  let depth = Number(args.depth ?? 1);
  if (!Number.isFinite(depth)) return "ERROR: 'depth' must be a number 0-2.";
  depth = Math.floor(depth);
  if (depth < 0 || depth > 2) {
    clampNotes.push(`depth clamped ${depth}->${Math.max(0, Math.min(2, depth))} (max 2)`);
    depth = Math.max(0, Math.min(2, depth));
  }
  let limit = Math.floor(Number(args.limit) || 8);
  if (!Number.isFinite(limit)) return "ERROR: 'limit' must be a number.";
  limit = Math.max(1, Math.min(cfg.maxPages, limit));
  if ((Number(args.limit) || 8) > limit) clampNotes.push(`limit clamped (max ${cfg.maxPages})`);

  const md = String(args.mode || "auto").trim().toLowerCase() || "auto";
  if (!["auto", "static", "stealth"].includes(md)) {
    return "ERROR: 'mode' must be auto, static, or stealth.";
  }
  const selectors = String(args.selectors || "").trim();
  const sameDomain = args.same_domain === undefined ? true : Boolean(args.same_domain);
  const cap = Math.max(500, Math.floor(Number(args.max_chars) || 0) || cfg.maxOutput);

  const key = cacheKey("scrape:high", {
    urls: seeds.map(normalizeUrl).sort().join(","),
    depth,
    limit,
    same: sameDomain,
    sels: selectors,
    mode: md,
    cap,
  });
  webCache.setTtl(cfg.cacheTtl);
  const [hit, ok] = webCache.get(key);
  if (ok && hit) return hit + "\n(cached; high)";

  const seedHosts = new Set();
  for (const s of seeds) {
    try {
      seedHosts.add(new URL(s).hostname.toLowerCase());
    } catch {}
  }

  const t0 = Date.now();
  const budgetMs = Math.min(240000, Math.max(20000, cfg.timeoutS * 4000));
  const visited = new Set();
  const queue = seeds.slice(0, limit).map((s) => ({ url: s, d: 0 }));
  const pages = [];
  let stealthUses = 0;

  const fetchStatic = async (urls) => {
    const bridge = await runBridge(
      {
        cmd: "static",
        urls,
        timeout_s: cfg.timeoutS,
        retries: cfg.retries,
        markdown: true,
        selectors,
        allow_private: allowPrivateHosts(ctx),
      },
      { timeoutMs: (cfg.timeoutS + 15) * 1000 + urls.length * 5000, pythonBin: cfg.pythonBin }
    );
    if (!bridge.ok) return urls.map((u) => ({ url: u, error: bridge.error }));
    return (bridge.results || []).map((r, i) => ({ url: urls[i], ...r }));
  };
  const fetchStealth = async (url) => {
    const bridge = await runBridge(
      {
        cmd: "stealth",
        url,
        wait_selector: "",
        timeout_ms: cfg.stealthTimeoutMs,
        markdown: true,
        selectors,
        allow_private: allowPrivateHosts(ctx),
      },
      { timeoutMs: cfg.stealthTimeoutMs + 20000, pythonBin: cfg.pythonBin }
    );
    if (!bridge.ok || !bridge.result || bridge.result.error) {
      return { url, error: !bridge.ok ? bridge.error : bridge.result?.error || "no result" };
    }
    return { ...bridge.result, mode: "stealth" };
  };

  while (queue.length && pages.length < limit && Date.now() - t0 < budgetMs) {
    // One level at a time so static fetches batch into a single bridge call.
    const level = [];
    while (queue.length && level.length + pages.length < limit && level.length < limit) {
      const next = queue.shift();
      const k = normalizeUrl(next.url);
      if (visited.has(k)) continue;
      visited.add(k);
      level.push(next);
    }
    if (!level.length) break;

    let statics = [];
    if (md === "stealth") {
      statics = level.map(({ url }) => ({ url, error: "__stealth__" }));
    } else {
      statics = await fetchStatic(level.map((l) => l.url));
    }

    for (let i = 0; i < level.length; i++) {
      if (pages.length >= limit || Date.now() - t0 >= budgetMs) break;
      const { url, d } = level[i];
    const refused = await guardUrl(s, ctx);
      if (refused) {
        pages.push({ url, mode: "skipped-private", title: "", text: refused });
        continue;
      }
      let entry = statics[i] || { url, error: "no result" };
      let used = "static";
      if (entry.error === "__stealth__" || (md === "auto" && needsStealthResult(entry, Boolean(selectors)))) {
        if (md === "static") {
          pages.push({ url, mode: "blocked-static", title: "", text: String(entry.error || "") });
          continue;
        }
        const stealth = await fetchStealth(url);
        stealthUses++;
        if (stealth.error) {
          if (entry.error && entry.error !== "__stealth__") {
            used = "static+stealth-failed";
          } else {
            pages.push({ url, mode: "failed", title: "", text: "" });
            continue;
          }
        } else {
          entry = stealth;
          used = "stealth";
        }
      }
      if (entry.error && used !== "static+stealth-failed") {
        pages.push({ url, mode: "failed", title: "", text: "" });
        continue;
      }
      const landed = await guardLanding(entry.history, entry.final_url, url, ctx);
      if (landed) {
        pages.push({ url, mode: "blocked-private-redirect", title: "", text: "" });
        continue;
      }
      const status = Number(entry.status) || 200;
      if (status < 200 || status >= 400) {
        pages.push({ url, mode: `http-${status}`, title: "", text: "" });
        continue;
      }
      const page = { url, mode: used, title: entry.title || "" };
      if (selectors) page.fields = entry.fields || {};
      else page.text = String(entry.markdown || entry.text || "").slice(0, 2000);
      pages.push(page);

      if (d < depth && pages.length + queue.length < limit * 2) {
        const seenLinks = new Set();
        for (const link of entry.links || []) {
          if (!/^https?:\/\//i.test(link) || seenLinks.has(normalizeUrl(link))) continue;
          seenLinks.add(normalizeUrl(link));
          try {
            if (sameDomain && !seedHosts.has(new URL(link).hostname.toLowerCase())) continue;
          } catch {
            continue;
          }
          queue.push({ url: link, d: d + 1 });
        }
      }
    }
  }

  if (!pages.length) return "ERROR: crawl fetched nothing.";
  let tail = `(high/${md}; ${pages.length} page(s), ${stealthUses} stealth)`;
  if (clampNotes.length) tail += " [" + clampNotes.join("; ") + "]";
  const lines = pages.map((p, i) => formatRecord(p, i + 1));
  lines.push(`(${tail})`);
  const out = truncateHeadTail(lines.join("\n"), cap).text;
  webCache.put(key, out);
  return out;
}
