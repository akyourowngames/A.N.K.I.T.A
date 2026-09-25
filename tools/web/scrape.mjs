import { run as low } from "./scrape-low.mjs";
import { run as mid } from "./scrape-mid.mjs";
import { run as high } from "./scrape-high.mjs";

export const name = "scrape";
export const description =
  "Scrape a page that web_fetch cannot read: blocked or Cloudflare-protected pages, JavaScript shells, " +
  "or pages where you need specific fields. Tiers: low = fast static fetch, mid = static then " +
  "headless browser if blocked, high = multi-page crawl. 'auto' picks mid for one URL and high for " +
  "several. Selectors are 'field=css' or 'xpath:...'.";

export const parameters = {
  type: "object",
  properties: {
    url: { type: "string", description: "One page to scrape." },
    urls: { type: "string", description: "Several seed URLs (space or comma separated) to crawl." },
    tier: {
      type: "string",
      description: "auto (default), low, mid, or high. auto = mid for one URL, high for several.",
    },
    selectors: {
      type: "string",
      description: "Optional fields: 'title=h1, price=.price' (CSS) or 'xpath://h1'.",
    },
    mode: { type: "string", description: "For mid/high: auto (default), static, or stealth." },
    wait_selector: { type: "string", description: "CSS to wait for in stealth mode." },
    depth: { type: "integer", description: "For high: link-follow depth 0-2. Default 1." },
    limit: { type: "integer", description: "For high: max pages. Default 8, max 20." },
    same_domain: { type: "boolean", description: "For high: stay on the seed domains. Default true." },
    format: { type: "string", description: "markdown (default), text, or json." },
    max_chars: { type: "integer", description: "Cap returned characters. Default 8000." },
  },
};

export const readOnly = true;
export const needsApproval = false;

/** auto = one URL is a page (mid), several URLs or a depth is a crawl (high). */
export function resolveTier(args = {}) {
  const asked = String(args.tier ?? "auto").trim().toLowerCase();
  if (asked === "low" || asked === "mid" || asked === "high") return asked;
  const seeds = String(args.urls ?? "").split(/[\s,;]+/).filter(Boolean);
  if (seeds.length > 1 || Number(args.depth) > 0) return "high";
  return "mid";
}

export function run(args = {}, ctx = {}) {
  const tier = resolveTier(args);
  if (tier === "high") {
    return high({ ...args, urls: args.urls || args.url }, ctx);
  }
  if (tier === "low") return low(args, ctx);
  return mid(args, ctx);
}
