import { useState } from 'react';
import type { Routine } from '../../../shared/wire';
import { Icon } from './Icons';
import { nextRunLabel } from './ScheduledTaskCard';
export function JobsPill({ jobs, onEdit, onWatch }: { jobs: Routine[]; onEdit: (id?: string) => void; onWatch: (job: Routine) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState('');
  if (!jobs.length) return null;
  const approval = jobs.filter(job => job.needsApproval).length, running = jobs.filter(job => job.running).length;
  const next = jobs.filter(job => job.nextRunAt).sort((a, b) => Date.parse(a.nextRunAt!) - Date.parse(b.nextRunAt!))[0];
  return <div className="jobs-pill">
    <button className="jobs-pill-toggle" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}><Icon name="clock" size={15} /><strong>Jobs</strong><span>{approval ? `${approval} needs approval` : running ? `${running} running` : next ? `Next ${nextRunLabel(next)} · ${next.timeZone}` : 'Paused'}</span><Icon name="chevron" size={14} /></button>
    {expanded && <div className="jobs-pill-list">{jobs.map(job => <div className="job-pill-row" key={job.id}><div><strong>{job.name}</strong><small>{job.ownerMissing ? 'Owner missing — choose a teammate' : job.needsApproval ? 'Waiting for approval' : job.running ? `Running step ${job.step}` : job.pausedReason ? `Paused: ${job.pausedReason}` : job.lastStatus === 'missed' ? 'Missed last run' : job.enabled ? job.cronLabel : 'Paused'}</small></div><div>{job.running && job.scope && <button onClick={() => onWatch(job)}>Watch live</button>}<button onClick={() => { if (job.needsApproval) document.getElementById(`job-review-${job.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }); else onEdit(job.id); }}>{job.needsApproval ? 'Review' : 'Run now / Edit'}</button><button onClick={() => { setError(''); void window.ankita.invoke('scheduleEnable', { id: job.id, enabled: !job.enabled }).catch(cause => setError(cause.message)); }}>{job.enabled ? 'Pause' : 'Resume'}</button></div></div>)}<button className="job-link" onClick={() => onEdit()}>Add scheduled job</button>{error && <p role="status" className="job-owner-warning">{error}</p>}</div>}
  </div>;
}
