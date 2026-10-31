import type { Routine } from '../../../shared/wire';

export function nextRunLabel(job: Routine) {
  if (job.running) return `Running · step ${job.step}`;
  if (!job.enabled) return 'Paused';
  if (!job.nextRunAt) return job.cronLabel;
  return new Intl.DateTimeFormat(undefined, { timeZone: job.timeZone, weekday: 'short', hour: 'numeric', minute: '2-digit' }).format(new Date(job.nextRunAt));
}

// Blocked on the user, missing an owner, or behind schedule — these outrank
// every other state wherever a job summary is shown.
export function jobNeedsAttention(job: Routine) {
  return Boolean(job.needsApproval || job.ownerMissing || job.lastStatus === 'missed');
}

// A heartbeat waiting for the owner to finish replying. It is not "running" and
// not "skipped": it is pending, and the panel says so.
export function jobIsDeferred(job: Routine) {
  return job.kind === 'heartbeat' && Boolean(job.pendingHeartbeatAt);
}

/** One calm line for a waiting result row. */
export function pendingSummary(count: number) {
  if (!count) return '';
  return count === 1 ? '1 result ready' : `${count} results ready`;
}

// One calm line shared by the context-bar chip and the jobs panel intro, so the
// status reads the same before and after opening the panel.
export function jobStatusSummary(jobs: Routine[]) {
  const attention = jobs.filter(jobNeedsAttention).length;
  if (attention) return attention === 1 ? 'Needs attention' : `${attention} need attention`;
  const running = jobs.filter(job => job.running).length;
  if (running) return running === 1 ? 'Running' : `${running} running`;
  const next = jobs.filter(job => job.enabled && !job.running && job.nextRunAt).sort((a, b) => Date.parse(a.nextRunAt!) - Date.parse(b.nextRunAt!))[0];
  if (next) return `Next ${nextRunLabel(next)}`;
  return jobs.length ? 'All paused' : 'Nothing scheduled';
}
