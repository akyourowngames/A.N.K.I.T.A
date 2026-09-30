import { STATE_FILE } from '../../src/core/config.mjs';
import { RoutineStore } from '../../src/automation/routines.mjs';
import { describeCron } from '../../src/automation/cron.mjs';
export const name = 'schedule_status';
export const description = 'Read background job status and upcoming runs. Quote the last summary; this tool never runs or changes a job.';
export const parameters = { type: 'object', properties: {} };
export const needsApproval = false;
export const readOnly = true;
export function run(_args, ctx = {}) {
  return JSON.stringify(ctx.scheduler ? ctx.scheduler.status(ctx.scheduleThreadId) : new RoutineStore(STATE_FILE).load().routines.map(r => ({ id: r.id, name: r.name, cronLabel: describeCron(r.cron), enabled: r.enabled, lastStatus: r.lastStatus, lastSummary: r.lastSummary })));
}
