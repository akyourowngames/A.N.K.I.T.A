/**
 * Alert composition.
 *
 * Watch alerts are written by the model, not from a template, so they read
 * like a person reporting news ("users dipped 7, signups still climbing")
 * rather than a monitoring line. `renderAlertFallback` exists so a model
 * failure degrades to a plain but complete notification instead of silence.
 */

const MAX_EXCERPT = 400;

export function direction(delta) {
  if (delta === null || delta === undefined) return "changed";
  if (delta > 0) return "rose";
  if (delta < 0) return "fell";
  return "unchanged";
}

function excerpt(text) {
  const s = String(text ?? "").replace(/\s+/g, " ").trim();
  if (!s) return "";
  return s.length > MAX_EXCERPT ? s.slice(0, MAX_EXCERPT) + "\u2026" : s;
}

function how(watch) {
  if (watch.selector) return `extracted with selector "${watch.selector}"`;
  if (watch.regex) return `extracted with regex "${watch.regex}"`;
  return "whole page tracked (no extractor)";
}

/**
 * One prompt describing every change from a single check, so a tick produces
 * one message rather than one per watch.
 */
export function buildAlertPrompt({ username, agentName = "ankita", changes = [], template = "" } = {}) {
  const lines = changes.map((c, i) => {
    const { watch } = c;
    const delta = c.delta;
    const deltaText =
      delta === null || delta === undefined ? "unknown" : `${delta > 0 ? "+" : ""}${delta}`;
    const bits = [
      `  ${i + 1}. ${watch.name}  (${watch.url})`,
      `     was ${c.previous ?? "(none)"} -> now ${c.value === null ? "(page text)" : c.value}` +
        `   change ${deltaText} (${direction(delta)})`,
      `     ${how(watch)}`,
    ];
    const ex = excerpt(watch.lastText);
    if (ex) bits.push(`     page says: ${ex}`);
    return bits.join("\n");
  });

  if (template && template.trim()) {
    return template
      .replaceAll("{{username}}", username || "there")
      .replaceAll("{{agentName}}", agentName)
      .replaceAll("{{count}}", String(changes.length))
      .replaceAll("{{changes}}", lines.join("\n"));
  }

  return [
    `You are ${agentName}, messaging ${username || "the user"} because numbers they asked you to watch just moved.`,
    "",
    changes.length === 1 ? "One watch changed:" : `${changes.length} watches changed:`,
    "",
    lines.join("\n"),
    "",
    `Write the notification to ${username || "the user"} in 1-2 natural sentences.`,
    "Address them by name, and react to the direction: something like a bit of a cheer when a number climbs,",
    "and a calm flag when one falls or spikes - never alarmist. Include the real numbers.",
    "",
    "Grounding rule: if the page excerpt above is missing, or a change looks abnormal (a spike, a sharp",
    "drop, an error rate, a first-ever reading), make ONE read-only check before you write - web_fetch the",
    "URL, or web_search for context - so the message is grounded in something you actually saw.",
    "Never propose a cause you did not observe. You cannot change anything.",
    "Skip preamble. Write the message text only.",
  ]
    .filter(Boolean)
    .join("\n");
}

/** Plain-text notification used when the model is unavailable. Always complete. */
export function renderAlertFallback(changes = []) {
  const lines = changes.map((c) => {
    const delta = c.delta;
    const arrow = c.previous === null || c.previous === undefined ? "\u2192" : `${c.previous} \u2192`;
    const sign = delta === null || delta === undefined ? "" : ` (${delta > 0 ? "+" : ""}${delta})`;
    const value = c.value === null ? "page changed" : c.value;
    return `\u{1F514} ${c.watch.name}: ${arrow} ${value}${sign}\n${c.watch.url}`;
  });
  return lines.join("\n\n");
}
