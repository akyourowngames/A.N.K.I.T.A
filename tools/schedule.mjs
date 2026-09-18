import { STATE_FILE } from "../src/config.mjs";
import { RoutineStore, describeRoutine } from "../src/routines.mjs";
import { describeCron, normalizeSchedule, parseCron } from "../src/cron.mjs";

export const name = "schedule";
export const description =
  "Manage scheduled routines: prompts that run on a cron schedule and are delivered to you " +
  "(Telegram when configured, otherwise shown in the terminal). Use this to set up recurring " +
  "briefings, reminders, or standing checks. Actions: add, list, remove, enable, disable, run.";

export const parameters = {
  type: "object",
  properties: {
    action: { type: "string", description: "add, list, remove, enable, disable, or run." },
    name: { type: "string", description: "Short label, e.g. 'Morning briefing'." },
    cron: {
      type: "string",
      description:
        "When to run. Accepts cron ('0 8 * * *'), shorthands ('every 30m', 'daily 08:00', 'weekdays 09:30'), or @aliases (@daily, @hourly).",
    },
    prompt: {
      type: "string",
      description: "What to ask when it fires. Put every instruction here; nothing else is passed.",
    },
    id: { type: "string", description: "Routine id or name (for remove/enable/disable/run)." },
  },
  required: ["action"],
};

export const needsApproval = false;

function store() {
  return new RoutineStore(STATE_FILE).load();
}

export function run(args = {}, ctx = {}) {
  const s = store();
  const action = String(args.action || "list").toLowerCase();

  if (action === "add") {
    if (!args.cron) return "Error: 'cron' is required to add a routine.";
    if (!args.prompt) return "Error: 'prompt' is required to add a routine.";
    if (!parseCron(args.cron)) {
      return `Error: could not parse schedule "${args.cron}". Try "0 8 * * *", "daily 08:00", "weekdays 09:30" or "every 2h".`;
    }
    try {
      const routine = s.addRoutine({
        name: args.name || args.cron,
        cron: args.cron,
        prompt: args.prompt,
      });
      return `Scheduled "${routine.name}" (${routine.id}) - ${describeCron(routine.cron)}\nIt will run in the background; start one with: ankita --daemon`;
    } catch (err) {
      return `Error: ${err.message}`;
    }
  }

  if (action === "list") {
    if (!s.routines.length) return "No routines scheduled.";
    return s.routines.map(describeRoutine).join("\n") + "\n\n(ids are the second column)";
  }

  if (action === "remove" || action === "enable" || action === "disable") {
    if (!args.id) return `Error: 'id' is required to ${action} a routine.`;
    if (action === "remove") {
      const removed = s.removeRoutine(args.id);
      return removed ? `Removed routine "${removed.name}".` : `Error: no routine "${args.id}".`;
    }
    const updated = s.setRoutineEnabled(args.id, action === "enable");
    return updated
      ? `Routine "${updated.name}" is now ${updated.enabled ? "enabled" : "paused"}.`
      : `Error: no routine "${args.id}".`;
  }

  if (action === "run") {
    if (!args.id) return "Error: 'id' is required to run a routine.";
    const routine = s.scheduleRoutineNow(args.id);
    if (!routine) return `Error: no routine "${args.id}".`;
    return `Queued "${routine.name}" to run on the next daemon tick (a few seconds).`;
  }

  return `Error: unknown action "${action}". Use add, list, remove, enable, disable, or run.`;
}

export { normalizeSchedule, describeCron };
