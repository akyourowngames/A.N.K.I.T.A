import type { Routine } from '../../../shared/wire';
import { Icon } from './Icons';

export function nextRunLabel(job: Routine) {
  if (job.running) return `Running · step ${job.step}`;
  if (!job.enabled) return 'Paused';
  if (!job.nextRunAt) return job.cronLabel;
  return new Intl.DateTimeFormat(undefined, { timeZone: job.timeZone, weekday: 'short', hour: 'numeric', minute: '2-digit' }).format(new Date(job.nextRunAt));
}
export function ScheduledTaskCard({ job, onOpen, removed = false }: { job: Routine; onOpen: (id: string) => void; removed?: boolean }) {
  return <section className="scheduled-task-card" aria-label={`Scheduled task ${job.name}`}>
    <header><span className="task-card-icon"><Icon name={job.kind === 'heartbeat' ? 'pulse' : 'clock'} size={20} /></span><div><strong>{job.name}</strong><small>{removed ? 'Removed task' : job.kind === 'heartbeat' ? 'Heartbeat' : 'Scheduled task'}</small></div></header>
    <p>{job.description || job.prompt}</p>
    <div className="task-card-timing"><span>{removed ? 'No further runs' : nextRunLabel(job)}</span><small>{job.timeZone}</small></div>
    {!removed && <button onClick={() => onOpen(job.id)}>View scheduled task <Icon name="arrowRight" size={14} /></button>}
  </section>;
}
