import {
  browserHeaders,
  honestHeaders,
  normalizeUrl,
  truncateHeadTail,
  cacheKey,
  webCache,
  decodeEntities,
  cfgVal,
  httpFetch,
} from "../shared/_web.mjs";

export const name = "web_search";
export const description =
  "Search the live internet (no API key). Fuses DuckDuckGo web results with Wikipedia, " +
  "news, and Hacker News. Use for anything time-sensitive instead of guessing, then " +
  "web_fetch the top URL for depth.";

export const parameters = {
  type: "object",
  properties: {
    query: { type: "string", description: "What to search for." },
    backend: {
      type: "string",
      description: "auto (default), web, news, wikipedia, hn, or reddit.",
    },
    when: {
      type: "string",
      description: "Freshness: 1h, 1d, 7d, 30d, 1y. Empty means anytime.",
    },
    limit: { type: "integer", description: "Max results. Default 8, max 20." },
  },
  required: ["query"],
};

export const readOnly = true;
export const needsApproval = false;

const DDG_CAPTCHA = ["anomaly-modal", "captcha", "challenge-platform", "Please complete the following challenge"];
const FRESH_TO_DF = { "1h": "d", "1d": "d", "7d": "w", "30d": "m", "1y": "y" };
const WHEN_TO_SEC = { "1h": 3600, "1d": 86400, "7d": 604800, "30d": 2592000, "1y": 31536000 };

function decodeDdgHref(href) {
  try {
    if (href.includes("uddg=")) {
      const u = new URL(href, "https://duckduckgo.com");
      const direct = u.searchParams.get("uddg");
      if (direct) return decodeURIComponent(direct);
      const m = href.match(/uddg=([^&]+)/);
      if (m) return decodeURIComponent(m[1]);
    }
    if (href.startsWith("//")) return "https:" + href;
    return href;
  } catch {
    return href;
  }
}

/**
 * Decode first, then strip: RSS descriptions carry escaped markup
 * ("&lt;a href=...&gt;Title&lt;/a&gt;"), so stripping before decoding finds
 * no tags and the markup surfaces as visible text.
 */
function stripTags(s) {
  const decoded = decodeEntities(String(s ?? ""));
  const stripped = decoded.replace(/<[^>]+>/g, " ");
  // Zero-width characters survive decoding and are invisible noise in results.
  return decodeEntities(stripped)
    .replace(/[\u200b-\u200d\ufeff]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function parseDdgHtml(html, limit) {
  if (DDG_CAPTCHA.some((m) => html.includes(m))) return { results: [], blocked: true };
  const out = [];
  const linkRe = /<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)<\/a>/gis;
  let m;
  while ((m = linkRe.exec(html))) {
    const url = decodeDdgHref(decodeEntities(m[1].trim()));
    const title = stripTags(m[2]);
    const seg = html.slice(m.index + m[0].length, m.index + m[0].length + 3000);
    let snippet = "";
    const sm = /class="result__snippet"[^>]*>(.*?)<\/\w+>/is.exec(seg);
    if (sm) {
      const cand = stripTags(sm[1]);
      if (cand.length >= 8) snippet = cand;
    }
    if (title && /^https?:\/\//i.test(url)) {
      out.push({ title: title.slice(0, 220), url, snippet: snippet.slice(0, 400), source: "web" });
      if (out.length >= limit) break;
    }
  }
  if (!out.length) {
    const fallback = /<a[^>]*href="([^"]+)"[^>]*>([^<]{8,160})<\/a>/gi;
    while ((m = fallback.exec(html))) {
      const url = decodeDdgHref(decodeEntities(m[1].trim()));
      if (!/^https?:\/\//i.test(url) || url.includes("duckduckgo.com")) continue;
      const title = stripTags(m[2]);
      if (!title) continue;
      out.push({ title: title.slice(0, 220), url, snippet: "", source: "web" });
      if (out.length >= limit) break;
    }
  }
  return { results: out, blocked: false };
}

export async function searchDdg(query, { freshness = "", region = "wt-wt", limit = 8, timeoutMs = 20000 } = {}, http = httpFetch) {
  const form = new URLSearchParams({ q: query, kl: region || "wt-wt" });
  if (FRESH_TO_DF[freshness]) form.set("df", FRESH_TO_DF[freshness]);
  const tryLite = async () => {
    const lite = await http(`https://lite.duckduckgo.com/lite/?q=${encodeURIComponent(query)}`, {
      headers: browserHeaders(),
      timeoutMs,
    });
    return parseDdgHtml(lite.text || "", limit);
  };
  try {
    const r = await http("https://html.duckduckgo.com/html/", {
      method: "POST",
      headers: browserHeaders(),
      body: form,
      timeoutMs,
    });
    if (r.status !== 200) {
      try {
        const second = await tryLite();
        if (!second.blocked && second.results.length) {
          return { results: second.results, note: `(DDG html http ${r.status}; lite fallback)` };
        }
      } catch {}
      return { results: [], note: `DDG http ${r.status}` };
    }
    const { results, blocked } = parseDdgHtml(r.text || "", limit);
    if (!blocked && results.length) return { results, note: "" };
    try {
      const second = await tryLite();
      if (!second.blocked && second.results.length) {
        return { results: second.results, note: "(DDG html empty/blocked; lite fallback)" };
      }
    } catch {}
    if (results.length) return { results, note: "" };
    return { results: [], note: "(DDG blocked; partial results)" };
  } catch (err) {
    return { results: [], note: `DDG error: ${err.message}` };
  }
}

export function parseGnewsXml(xml, limit) {
  const out = [];
  const itemRe = /<item>(.*?)<\/item>/gis;
  const tag = (block, name) => {
    const mm = new RegExp(`<${name}[^>]*>([\\s\\S]*?)<\\/${name}>`, "i").exec(block);
    return mm ? mm[1].trim() : "";
  };
  let m;
  while ((m = itemRe.exec(xml))) {
    const block = m[1];
    const title = decodeEntities(tag(block, "title"));
    const link = tag(block, "link");
    const pub = tag(block, "pubDate");
    const srcM = /<source[^>]*>([\s\S]*?)<\/source>/i.exec(block);
    const src = srcM ? stripTags(srcM[1]) : "news";
    const desc = stripTags(tag(block, "description"));
    if (title && link) {
      out.push({
        title: title.slice(0, 220),
        url: link,
        snippet: desc.slice(0, 400),
        source: src || "news",
        date: pub.slice(0, 32),
      });
      if (out.length >= limit) break;
    }
  }
  return out;
}

export async function searchNews(query, { when = "1d", limit = 8, timeoutMs = 20000 } = {}, http = httpFetch) {
  let q = query;
  if (when && !/\b(when|after|before):\S+/.test(query)) q = `${query} when:${when}`;
  const params = new URLSearchParams({ q, hl: "en-US", gl: "US", ceid: "US:en" });
  try {
    const r = await http(`https://news.google.com/rss/search?${params}`, { headers: honestHeaders(), timeoutMs });
    if (r.status !== 200) return { results: [], note: `GNews http ${r.status}` };
    return { results: parseGnewsXml(r.text || "", limit), note: "" };
  } catch (err) {
    return { results: [], note: `GNews error: ${err.message}` };
  }
}

export async function searchWikipedia(query, { limit = 5, timeoutMs = 20000 } = {}, http = httpFetch) {
  const params = new URLSearchParams({
    action: "query",
    list: "search",
    format: "json",
    srsearch: query,
    srlimit: String(Math.max(1, Math.min(limit, 20))),
    srprop: "snippet",
  });
  try {
    const r = await http(`https://en.wikipedia.org/w/api.php?${params}`, { headers: honestHeaders(), timeoutMs });
    if (r.status !== 200) return { results: [], note: `Wiki http ${r.status}` };
    let data;
    try {
      data = JSON.parse(r.text);
    } catch {
      return { results: [], note: "Wiki: bad JSON" };
    }
    const out = [];
    for (const item of ((data?.query || {}).search || []).slice(0, limit)) {
      const title = String(item.title || "");
      const snip = stripTags(item.snippet || "");
      out.push({
        title: title.slice(0, 220),
        url: "https://en.wikipedia.org/wiki/" + encodeURIComponent(title.replace(/ /g, "_")),
        snippet: snip.slice(0, 400),
        source: "wikipedia",
      });
    }
    return { results: out, note: "" };
  } catch (err) {
    return { results: [], note: `Wiki error: ${err.message}` };
  }
}

export async function searchHn(query, { when = "", limit = 5, timeoutMs = 20000 } = {}, http = httpFetch) {
  const params = new URLSearchParams({ query, tags: "story", hitsPerPage: String(Math.max(1, Math.min(limit, 20))) });
  if (WHEN_TO_SEC[when]) params.set("numericFilters", `created_at_i>${Math.floor(Date.now() / 1000) - WHEN_TO_SEC[when]}`);
  try {
    const r = await http(`https://hn.algolia.com/api/v1/search?${params}`, { headers: honestHeaders(), timeoutMs });
    if (r.status !== 200) return { results: [], note: `HN http ${r.status}` };
    let data;
    try {
      data = JSON.parse(r.text);
    } catch {
      return { results: [], note: "HN: bad JSON" };
    }
    const out = [];
    for (const h of (data?.hits || []).slice(0, limit)) {
      const title = String(h.title || "");
      const url = String(h.url || "") || `https://news.ycombinator.com/item?id=${h.objectID}`;
      out.push({
        title: (title || url).slice(0, 220),
        url,
        snippet: `${h.points ?? ""} points by ${h.author ?? "?"}`.slice(0, 200),
        source: "hn",
      });
    }
    return { results: out, note: "" };
  } catch (err) {
    return { results: [], note: `HN error: ${err.message}` };
  }
}

export async function searchReddit(query, { when = "", limit = 5, timeoutMs = 20000 } = {}, http = httpFetch) {
  const tmap = { "1h": "hour", "1d": "day", "7d": "week", "30d": "month", "1y": "year" };
  const params = new URLSearchParams({
    q: query,
    limit: String(Math.max(1, Math.min(limit, 20))),
    sort: "new",
    t: tmap[when] || "week",
  });
  try {
    const r = await http(`https://www.reddit.com/search.json?${params}`, { headers: honestHeaders(), timeoutMs });
    if (r.status !== 200) return { results: [], note: `Reddit http ${r.status} (rate-limited?)` };
    let data;
    try {
      data = JSON.parse(r.text);
    } catch {
      return { results: [], note: "Reddit: bad JSON" };
    }
    const out = [];
    for (const child of (((data?.data || {}).children) || []).slice(0, limit)) {
      const d = child.data || {};
      out.push({
        title: String(d.title || "").slice(0, 220),
        url: "https://www.reddit.com" + String(d.permalink || ""),
        snippet: `r/${d.subreddit} · ${d.score}↑ · ${d.num_comments} comments`.slice(0, 200),
        source: "reddit",
      });
    }
    return { results: out, note: "" };
  } catch (err) {
    return { results: [], note: `Reddit error: ${err.message}` };
  }
}

const TECH_HINTS = [
  "python", "javascript", "typescript", "rust", "golang", " llm", " ai ", "api", "github",
  "startup", "launch", "framework", "database", "linux", "dev", "code", "app ",
];

function isTechy(query) {
  const low = ` ${String(query || "").toLowerCase()} `;
  return TECH_HINTS.some((h) => h.trim() && low.includes(h));
}

export function formatSearch(results, note = "") {
  if (!results.length) return `ERROR: no results.${note ? " " + note : ""}`.trim();
  const lines = [];
  results.forEach((r, i) => {
    const date = r.date ? ` (${r.date})` : "";
    lines.push(`[${i + 1}] ${r.title || "(untitled)"} — ${r.source || "web"}${date}\n    ${(r.snippet || "").slice(0, 300)}\n    ${r.url || ""}`);
  });
  if (note) lines.push(`(${note})`);
  return truncateHeadTail(lines.join("\n"), 8000).text;
}

function webCfg(ctx = {}) {
  const env = (k, dflt) => cfgVal(ctx, k, dflt);
  return {
    timeoutMs: Math.max(2000, Number(env("WEB_TIMEOUT", 20)) * 1000 || 20000),
    maxOutput: Math.max(500, Number(env("WEB_MAX_OUTPUT", 8000)) || 8000),
    cacheTtl: Math.max(0, Number(env("WEB_CACHE_TTL", 300)) || 0),
    retries: Math.max(0, Math.min(3, Math.floor(Number(env("WEB_RETRIES", 1)) || 0))),
    region: String(env("WEB_REGION", "wt-wt") || "wt-wt").trim() || "wt-wt",
    disabled: String(env("ANKITA_NO_WEB", "") || "") === "1",
  };
}

export async function searchRun({ query, backend = "auto", when = "", limit = 8 } = {}, ctx = {}, http = httpFetch) {
  const q = String(query || "").trim();
  if (!q) return "ERROR: 'query' is required.";
  const cfg = webCfg(ctx);
  if (cfg.disabled) return "ERROR: web search is disabled (ANKITA_NO_WEB=1).";
  const be = String(backend || "auto").trim().toLowerCase();
  const lim = Math.max(1, Math.min(Number(limit) || 8, 20));
  webCache.setTtl(cfg.cacheTtl);

  const key = cacheKey("search", { q, backend: be, when: when || "", limit: lim });
  const [hit, ok] = webCache.get(key);
  if (ok && hit) return hit + "\n(cached)";

  const opt = { timeoutMs: cfg.timeoutMs };
  let results = [];
  const notes = [];
  const take = (res, note) => {
    results.push(...res);
    if (note) notes.push(note);
  };

  if (be === "web") {
    const { results: r, note } = await searchDdg(q, { freshness: when, region: cfg.region, limit: lim, ...opt }, http);
    take(r, note);
  } else if (be === "news") {
    const { results: r, note } = await searchNews(q, { when: when || "7d", limit: lim, ...opt }, http);
    take(r, note);
  } else if (be === "wikipedia") {
    const { results: r, note } = await searchWikipedia(q, { limit: lim, ...opt }, http);
    take(r, note);
  } else if (be === "hn") {
    const { results: r, note } = await searchHn(q, { when, limit: lim, ...opt }, http);
    take(r, note);
  } else if (be === "reddit") {
    const { results: r, note } = await searchReddit(q, { when, limit: lim, ...opt }, http);
    take(r, note);
  } else {
    const jobs = [
      searchDdg(q, { freshness: when, region: cfg.region, limit: lim, ...opt }, http),
      searchWikipedia(q, { limit: 5, ...opt }, http),
    ];
    if (when || isTechy(q)) jobs.push(searchHn(q, { when, limit: 5, ...opt }, http));
    const low = q.toLowerCase();
    if (low.includes("news") || low.includes("today") || when) {
      jobs.splice(1, 0, searchNews(q, { when: when || "7d", limit: 5, ...opt }, http));
    }
    const settled = await Promise.all(jobs.map((p) => p.catch((err) => ({ results: [], note: String(err?.message || err) }))));
    for (const s of settled) take(s.results || [], s.note || "");
  }

  const seen = new Set();
  const fused = [];
  for (const r of results) {
    const k = normalizeUrl(r.url || "");
    if (!k || seen.has(k)) continue;
    seen.add(k);
    fused.push(r);
    if (fused.length >= lim) break;
  }
  const note = notes.filter(Boolean).join("; ");
  const out = formatSearch(fused, note);
  webCache.put(key, out);
  return out;
}

export function run(args, ctx) {
  return searchRun(
    { query: args.query, backend: args.backend, when: args.when, limit: args.limit },
    ctx || {}
  );
}
