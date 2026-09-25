import { STATE_FILE, PROJECTS_FILE } from "../../src/core/config.mjs";
import { RoutineStore, describeWatch } from "../../src/automation/routines.mjs";
import { ProjectStore, resolveProjectRef } from "../../src/memory/projects.mjs";
import { tagNote } from "./schedule.mjs";
import { checkWatch } from "../../src/automation/watcher.mjs";
import { formatDuration } from "../../src/automation/cron.mjs";

export const name = "watch";
export const description =
  "Watch a web page for changes and report back when something moves - new signups, login " +
  "counts, prices, a status page, a dashboard number. Optionally extract one value with a " +
  "regex or a CSS selector so you get numbers and deltas instead of whole-page noise. " +
  "Actions: add, list, remove, check, enable, disable.";

export const parameters = {
  type: "object",
  properties: {
    action: { type: "string", description: "add, list, remove, check, enable, or disable." },
    name: { type: "string", description: "Short label, e.g. 'Signup count'." },
    url: { type: "string", description: "http(s) page to watch." },
    interval: { type: "string", description: "How often to check: 20s, 15m, 1h, 6h, 1d. Default 1h." },
    alert_every: {
      type: "string",
      description:
        "Minimum gap between alerts for this watch, e.g. 10m, 1h. Default 10m - stops a busy number spamming you.",
    },
    regex: {
      type: "string",
      description:
        "Optional regex; capture group 1 becomes the watched value, e.g. '([\\\\d,]+)\\\\s+users'.",
    },
    selector: {
      type: "string",
      description: "Optional CSS selector to read instead of the whole page (uses the scrape tiers).",
    },
    id: { type: "string", description: "Watch id or name (for remove/check/enable/disable)." },
    project: {
      type: "string",
      description:
        "Project to attach this watch to, by name or id. Defaults to the active project. Use 'none' to leave it unattached.",
    },
  },
  required: ["action"],
};

export const needsApproval = false;

function store() {
  return new RoutineStore(STATE_FILE).load();
}

export async function run(args = {}, ctx = {}) {
  const s = store();
  const action = String(args.action || "list").toLowerCase();

  if (action === "add") {
    if (!args.url) return "Error: 'url' is required.";
    if (args.regex) {
      try {
        new RegExp(args.regex);
      } catch (err) {
        return `Error: invalid regex: ${err.message}`;
      }
    }
    const resolved = resolveProjectRef(new ProjectStore(PROJECTS_FILE).load(), args.project, ctx.projectId);
    if (!resolved.ok) return `Error: ${resolved.error}`;
    try {
      const watch = s.addWatch({
        name: args.name || new URL(args.url).hostname,
        url: args.url,
        selector: args.selector || "",
        regex: args.regex || "",
        interval: args.interval || "1h",
        alertEvery: args.alert_every || "10m",
        projectId: resolved.projectId,
      });
      const first = await checkWatch(watch, ctx);
      if (first.error) {
        s.removeWatch(watch.id);
        return `Error: could not read ${watch.url} (${first.error}) - watch not created.`;
      }
      s.recordWatchCheck(watch.id, { value: first.value, text: first.text });
      return (
        `Watching "${watch.name}" (${watch.id}) every ${formatDuration(watch.intervalMs)}` +
        tagNote(watch.projectId) +
        `\nFirst reading: ${first.value ?? "(page content tracked)"}\n` +
        `Alerts arrive when it changes; start the loop with: ankita --daemon`
      );
    } catch (err) {
      return `Error: ${err.message}`;
    }
  }

  if (action === "list") {
    if (!s.watches.length) return "No watches configured.";
    return (
      s.watches.map(describeWatch).join("\n") +
      "\n\n(columns: state, id, interval, last value, name; [project] at the end when attached)"
    );
  }

  if (action === "check") {
    const targets = args.id ? [s.findWatch(args.id)].filter(Boolean) : s.watches;
    if (!targets.length) return args.id ? `Error: no watch "${args.id}".` : "No watches configured.";
    const lines = [];
    for (const watch of targets) {
      const result = await checkWatch(watch, ctx);
      if (result.error) {
        lines.push(`${watch.name}: ERROR ${result.error}`);
        continue;
      }
      const recorded = s.recordWatchCheck(watch.id, { value: result.value, text: result.text });
      const delta = recorded.delta;
      const sign = delta > 0 ? "+" : "";
      lines.push(
        `${watch.name}: ${result.value ?? "(page tracked)"}` +
          (delta !== null && delta !== undefined ? ` (${sign}${delta} since last check)` : "") +
          (recorded.changed ? "  [CHANGED]" : "  [no change]")
      );
    }
    return lines.join("\n");
  }

  if (action === "remove" || action === "enable" || action === "disable") {
    if (!args.id) return `Error: 'id' is required to ${action} a watch.`;
    if (action === "remove") {
      const removed = s.removeWatch(args.id);
      return removed ? `Stopped watching "${removed.name}".` : `Error: no watch "${args.id}".`;
    }
    const updated = s.setWatchEnabled(args.id, action === "enable");
    return updated
      ? `Watch "${updated.name}" is now ${updated.enabled ? "active" : "paused"}.`
      : `Error: no watch "${args.id}".`;
  }

  return `Error: unknown action "${action}". Use add, list, remove, check, enable, or disable.`;
}
