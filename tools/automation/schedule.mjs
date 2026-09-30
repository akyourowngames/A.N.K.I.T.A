import { STATE_FILE, PROJECTS_FILE } from "../../src/core/config.mjs";
import { RoutineStore, describeRoutine } from "../../src/automation/routines.mjs";
import { ProjectStore, resolveProjectRef } from "../../src/memory/projects.mjs";
import { describeCron, normalizeSchedule, parseCron } from "../../src/automation/cron.mjs";
import { createHash } from 'node:crypto';
import { HEARTBEAT_CRON, HEARTBEAT_PROMPT, JOB_MUTABLE_FIELDS, JOB_EXECUTION_POLICIES, SCHEDULE_TASK_GUIDANCE } from '../../src/automation/job-policy.mjs';

export const name = "schedule";
export const description =
  'Create and manage durable scheduled tasks. Desktop add activates a task and shows a card in this conversation; no form is needed. ' +
  'Use update with id and patch to change it, list to inspect, enable/disable to resume/pause, remove to delete, and run ONLY when an immediate execution is requested. ' +
  'Supply the complete task, success check and schedule. Clarify missing timing or task details first. Use kind=heartbeat for an idle proactive check. ' +
  'Creating a job does not require browsing or element refs. Store task instructions, never snapshot refs; each worker observes fresh controls when it runs. ' +
  'Desktop browser jobs use isolated Chromium and saved credentials; first sign-in or MFA may need foreground input. Read the returned status/nextRunAt; creation is not execution. CLI delivery uses the daemon. ' + SCHEDULE_TASK_GUIDANCE;

export const parameters = {
  type: "object",
  properties: {
    action: { type: 'string', enum: ['add', 'update', 'list', 'remove', 'enable', 'disable', 'run', 'needs_input'] },
    reason: { type: 'string', description: 'Background needs_input only: what user input is required, such as an authenticator code. Never include credentials.' },
    kind: { type: 'string', enum: ['routine', 'heartbeat'], description: 'Desktop: heartbeat runs only while the owner is idle and suppresses uneventful reports.' },
    description: { type: 'string', description: 'One sentence describing the task for its chat card.' },
    requestKey: { type: 'string', description: 'Stable creation key for retries of this same request. Never reuse for another task.' },
    name: { type: "string", description: "Short label, e.g. 'Morning briefing'." },
    cron: {
      type: "string",
      description:
        "When to run. Accepts cron ('0 8 * * *'), shorthands ('every 30m', 'daily 08:00', 'weekdays 09:30'), or @aliases (@daily, @hourly).",
    },
    prompt: {
      type: "string",
      description: SCHEDULE_TASK_GUIDANCE,
    },
    id: { type: "string", description: "Existing routine id or name (required for update/remove/enable/disable/run)." },
    threadId: { type: 'string', description: 'Desktop owning teammate; defaults to this thread.' },
    browserPolicy: { type: 'string', enum: ['autonomous', 'scoped'], description: 'Desktop defaults to autonomous browser use for the requested task; scoped is an explicitly restricted task.' },
    executionPolicy: { type: 'string', enum: JOB_EXECUTION_POLICIES, description: 'Desktop regular tasks default to complete, without token/time/tool-count cutoffs. Use bounded only for limits explicitly requested by the user; heartbeats default to bounded.' },
    allow: { type: 'object', properties: { read: { type: 'boolean' }, interact: { type: 'boolean' }, login: { type: 'boolean' }, sites: { type: 'array', items: { type: 'string' } }, mode: { type: 'string', enum: ['isolated'] } } },
    timeoutMs: { type: 'number', description: 'Optional bounded-policy active execution deadline, milliseconds. Ignored in complete execution.' },
    enabled: { type: 'boolean', description: 'Desktop: active by default. False creates or updates a paused job.' },
    headless: { type: 'boolean', description: 'Desktop: background Chromium is headless by default; its live preview remains available.' },
    onNewRequest: { type: 'string', enum: ['pause-ask', 'deny'], description: 'Scoped browser policy only: behavior for a site outside saved permissions.' },
    budget: { type: 'object', description: 'Optional bounded-policy daily limits explicitly requested by the user. Ignored in complete execution; usage is still recorded. Do not estimate ceilings on behalf of the user.', properties: { maxRunsPerDay: { type: 'number' }, maxTokensPerDay: { type: 'number' }, maxMinutesPerDay: { type: 'number' } } },
    patch: { type: 'object', description: 'Fields to update: name, description, cron, prompt, kind, threadId, enabled, browserPolicy, allow, timeoutMs, budget.' },
    project: {
      type: "string",
      description:
        "Project to attach this routine to, by name or id. Defaults to the active project. Use 'none' to leave it unattached.",
    },
  },
  required: ["action"],
};
parameters.properties.patch.properties = {
  ...Object.fromEntries(JOB_MUTABLE_FIELDS.filter(field => parameters.properties[field]).map(field => [field, parameters.properties[field]])),
  projectId: { type: ['string', 'null'], description: 'Existing project id for this job; null clears a fixed project.' },
  projectDetached: { type: 'boolean', description: 'True runs without inheriting the owning teammate project.' },
};
parameters.properties.patch.additionalProperties = false;

export const needsApproval = false;

function store() {
  return new RoutineStore(STATE_FILE).load();
}

function desktopJob(scheduler, reference, threadId) {
  const key = String(reference ?? '').trim().toLowerCase();
  const exact = scheduler.list().find(job => job.id === key);
  if (exact) return exact;
  const matches = scheduler.list(threadId).filter(job => String(job.name || '').toLowerCase() === key);
  if (matches.length > 1) throw new Error('Task name is ambiguous. Use its id from the scheduling list.');
  if (!matches.length) throw new Error('Task not found in this teammate. Use its id from the scheduling list.');
  return matches[0];
}

function updatePatch(args) {
  if (args.patch !== undefined && (!args.patch || typeof args.patch !== 'object' || Array.isArray(args.patch))) throw new Error('Update patch must contain fields to update.');
  const patch = { ...args.patch };
  if (Object.keys(patch).some(field => !JOB_MUTABLE_FIELDS.includes(field))) throw new Error('Update patch contains unsupported fields. Use the scheduling schema.');
  for (const field of JOB_MUTABLE_FIELDS) {
    if (args[field] === undefined) continue;
    if (patch[field] !== undefined && JSON.stringify(patch[field]) !== JSON.stringify(args[field])) throw new Error(`Conflicting update values for ${field}; supply it once in patch.`);
    patch[field] = args[field];
  }
  if (!Object.keys(patch).length) throw new Error('Supply fields to update in patch. An empty update cannot change the task.');
  return patch;
}

/** Small note appended to results so the tag is never silent. */
export function tagNote(projectId) {
  return projectId ? `\nAttached to project "${projectId}".` : "\nNot attached to any project.";
}

export async function run(args = {}, ctx = {}) {
  const action = String(args.action || "list").toLowerCase();
  if (ctx.backgroundJob) {
    if (action === 'needs_input' && ctx.requireForeground) { ctx.requireForeground(String(args.reason || 'This task needs foreground input.')); return JSON.stringify({ action, status: 'needs-input' }); }
    if (action !== 'list') return 'Error: Background workers cannot change schedules. Use needs_input when manual sign-in or verification is required.';
  }
  if (ctx.scheduler) {
    const scheduler = ctx.scheduler;
    try {
      if (action === 'list') return JSON.stringify(scheduler.list(ctx.scheduleThreadId));
      if (action === 'add') {
        const project = resolveProjectRef(new ProjectStore(ctx.projectsFile || PROJECTS_FILE).load(), args.project, ctx.projectId);
        if (!project.ok) return `Error: ${project.error}`;
        const input = { ...args, threadId: args.threadId || ctx.scheduleThreadId, browserPolicy: args.browserPolicy || 'autonomous',
          ...(args.project !== undefined || ctx.projectId ? { projectId: project.projectId, projectDetached: String(args.project || '').trim().toLowerCase() === 'none' } : {}),
          cron: args.cron || (args.kind === 'heartbeat' ? HEARTBEAT_CRON : undefined), prompt: args.prompt || (args.kind === 'heartbeat' ? HEARTBEAT_PROMPT : undefined) };
        input.requestKey ||= createHash('sha256').update(JSON.stringify([input.threadId, input.name, normalizeSchedule(input.cron), input.prompt, input.kind || 'routine'])).digest('hex');
        const routine = scheduler.add(input);
        return JSON.stringify({ action, job: routine });
      }
      if (action === 'update') return JSON.stringify({ action, job: scheduler.update(desktopJob(scheduler, args.id, ctx.scheduleThreadId).id, updatePatch(args)) });
      if (action === 'remove') return JSON.stringify({ action, job: scheduler.remove(desktopJob(scheduler, args.id, ctx.scheduleThreadId).id) });
      if (action === 'enable' || action === 'disable') return JSON.stringify({ action, job: scheduler.enable(desktopJob(scheduler, args.id, ctx.scheduleThreadId).id, action === 'enable') });
      if (action === 'run') { const id = desktopJob(scheduler, args.id, ctx.scheduleThreadId).id; return JSON.stringify({ action, ...await scheduler.runNow(id), job: scheduler.list().find(job => job.id === id) }); }
      return 'Error: unknown schedule action.';
    } catch (error) { return `Error: ${error.message}`; }
  }
  const s = store();

  if (action === "add") {
    if (!args.cron) return "Error: 'cron' is required to add a routine.";
    if (!args.prompt) return "Error: 'prompt' is required to add a routine.";
    if (!parseCron(args.cron)) {
      return `Error: could not parse schedule "${args.cron}". Try "0 8 * * *", "daily 08:00", "weekdays 09:30" or "every 2h".`;
    }
    const resolved = resolveProjectRef(new ProjectStore(PROJECTS_FILE).load(), args.project, ctx.projectId);
    if (!resolved.ok) return `Error: ${resolved.error}`;
    try {
      const routine = s.addRoutine({
        name: args.name || args.cron,
        cron: args.cron,
        prompt: args.prompt,
        projectId: resolved.projectId,
      });
      return (
        `Scheduled "${routine.name}" (${routine.id}) - ${describeCron(routine.cron)}` +
        tagNote(routine.projectId) +
        "\nIt will run in the background; start one with: ankita --daemon"
      );
    } catch (err) {
      return `Error: ${err.message}`;
    }
  }

  if (action === "list") {
    if (!s.routines.length) return "No routines scheduled.";
    return (
      s.routines.map(describeRoutine).join("\n") +
      "\n\n(ids are the second column; [project] at the end when attached)"
    );
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
