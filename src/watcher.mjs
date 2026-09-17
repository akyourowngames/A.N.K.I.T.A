import { fetchRun } from "../tools/web-fetch.mjs";
import { run as scrapeMid } from "../tools/scrape-mid.mjs";
import { hashContent } from "./routines.mjs";

/**
 * Watch checking: fetch a page, extract the thing worth watching, and report
 * what changed. Shared by the `watch` tool (on-demand) and the daemon
 * (scheduled), so both behave identically.
 */

/** Pulls a value out of page text. Pure. */
export function extractValue(text, regex = "") {
  const body = String(text ?? "");
  if (!regex) return { value: null, digestSource: body };
  let re;
  try {
    re = new RegExp(regex, "i");
  } catch (err) {
    return { value: null, digestSource: "", error: `invalid regex: ${err.message}` };
  }
  const match = re.exec(body);
  if (!match) return { value: null, digestSource: "", error: "pattern not found on the page" };
  const value = (match[1] ?? match[0] ?? "").trim();
  if (!value) return { value: null, digestSource: "", error: "pattern matched nothing" };
  return { value, digestSource: value };
}

/**
 * Checks one watch. Never throws. Returns { value, text, digest, error }.
 * Selector watches go through the scrape tiers so blocked/JS pages still work.
 */
export async function checkWatch(watch, ctx = {}) {
  if (watch.selector) {
    let raw;
    try {
      raw = await scrapeMid(
        { url: watch.url, selectors: `value=${watch.selector}`, format: "json", max_chars: 8000 },
        ctx
      );
    } catch (err) {
      return { error: `scrape failed: ${err.message}` };
    }
    if (typeof raw === "string" && raw.startsWith("ERROR")) return { error: raw };
    const jsonLine = String(raw).split("\n").find((l) => l.trim().startsWith("["));
    if (!jsonLine) return { error: "selector watch got no JSON back" };
    try {
      const parsed = JSON.parse(jsonLine);
      const values = parsed?.[0]?.fields?.value || [];
      if (!values.length) return { error: `selector "${watch.selector}" matched nothing` };
      const value = String(values[0]).trim();
      return { value, text: `selector ${watch.selector}: ${value}`, digest: hashContent(value) };
    } catch (err) {
      return { error: `could not parse selector result: ${err.message}` };
    }
  }

  let text;
  try {
    text = await fetchRun({ url: watch.url, max_chars: 20000 }, ctx);
  } catch (err) {
    return { error: `fetch failed: ${err.message}` };
  }
  if (typeof text === "string" && text.startsWith("ERROR")) return { error: text };

  const extracted = extractValue(text, watch.regex);
  if (extracted.error) return { error: extracted.error };
  return {
    value: extracted.value,
    text,
    digest: hashContent(extracted.digestSource),
  };
}

/** Human-readable status line for a watch. */
export function formatWatchStatus(watch, result) {
  if (result.error) return `${watch.name}: ${result.error}`;
  const delta = result.delta;
  const value = result.value ?? "(page tracked)";
  if (!result.changed) return `${watch.name}: unchanged (${value})`;
  if (delta !== null && delta !== undefined) {
    const sign = delta > 0 ? "+" : "";
    return `${watch.name}: ${result.previous} \u2192 ${value} (${sign}${delta})`;
  }
  return `${watch.name}: changed \u2192 ${value}`;
}
