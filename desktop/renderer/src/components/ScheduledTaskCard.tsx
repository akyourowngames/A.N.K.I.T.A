import type { Routine } from '../../../shared/wire';
import { Icon } from './Icons';
import { relativeTime } from '../lib/relative-time';

export function nextRunLabel(job: Routine) {
  if (job.running) return `Running · step ${job.step}`;
  if (!job.enabled) return 'Paused';
  if (!job.nextRunAt) return job.cronLabel;
  return new Intl.DateTimeFormat(undefined, { timeZone: job.timeZone, weekday: 'short', hour: 'numeric', minute: '2-digit' }).format(new Date(job.nextRunAt));
}

// A single state word the eye can attach to without reading the timing line.
function cardState(job: Routine, removed: boolean) {
  if (removed) return { key: 'paused', label: 'Removed' };
  if (job.running) return { key: 'running', label: 'Running' };
  if (job.needsApproval) return { key: 'attention', label: 'Needs approval' };
  if (!job.enabled) return { key: 'paused', label: 'Paused' };
  return { key: 'ready', label: job.kind === 'heartbeat' ? 'Heartbeat' : 'Scheduled' };
}

export function ScheduledTaskCard({ job, onOpen, removed = false }: { job: Routine; onOpen: (id: string) => void; removed?: boolean }) {
  const state = cardState(job, removed);
  return <section className={`scheduled-task-card ${removed ? 'removed' : ''}`} aria-label={`Scheduled task ${job.name}`}>
    <header><span className="task-card-icon"><Icon name={job.kind === 'heartbeat' ? 'pulse' : 'clock'} size={20} /></span><div><strong>{job.name}</strong><small>{removed ? 'Removed task' : job.kind === 'heartbeat' ? 'Heartbeat' : 'Scheduled task'}</small></div><span className={`task-card-state ${state.key}`}>{state.label}</span></header>
    <p>{job.description || job.prompt}</p>
    <div className="task-card-timing"><span>{removed ? 'No further runs' : nextRunLabel(job)}</span>{!removed && job.lastReceipt && <small>· ran {relativeTime(job.lastReceipt.at)}</small>}<small className="task-card-zone">{job.timeZone}</small></div>
    {!removed && <button onClick={() => onOpen(job.id)}>View scheduled task <Icon name="arrowRight" size={14} /></button>}
  </section>;
}
