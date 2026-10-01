import { useState } from 'react';
import type { Routine } from '../../../shared/wire';
import { Icon } from './Icons';
import { nextRunLabel } from './ScheduledTaskCard';

// The pill's collapsed line doubles as the global status readout: attention and
// running states outrank the next scheduled time so nothing urgent stays hidden.
function pillState(job: Routine) {
  if (job.needsApproval) return { key: 'attention', label: 'Waiting for approval' };
  if (job.ownerMissing) return { key: 'attention', label: 'Owner missing — choose a teammate' };
  if (job.running) return { key: 'running', label: `Running step ${job.step}` };
  if (job.pausedReason) return { key: 'paused', label: `Paused: ${job.pausedReason}` };
  if (job.lastStatus === 'missed') return { key: 'attention', label: 'Missed last run' };
  if (!job.enabled) return { key: 'paused', label: 'Paused' };
  return { key: 'ready', label: job.cronLabel };
}

export function JobsPill({ jobs, onEdit, onWatch }: { jobs: Routine[]; onEdit: (id?: string) => void; onWatch: (job: Routine) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState('');
  if (!jobs.length) return null;
  const approval = jobs.filter(job => job.needsApproval).length, running = jobs.filter(job => job.running).length;
  const next = jobs.filter(job => job.nextRunAt).sort((a, b) => Date.parse(a.nextRunAt!) - Date.parse(b.nextRunAt!))[0];
  const status = approval ? `${approval} needs approval` : running ? `${running} running` : next ? `Next ${nextRunLabel(next)} · ${next.timeZone}` : 'Paused';
  return <div className={`jobs-pill ${expanded ? 'expanded' : ''}`}>
    <button className="jobs-pill-toggle" onClick={() => setExpanded(!expanded)} aria-expanded={expanded}>
      <span className="jobs-pill-glyph"><Icon name="clock" size={15} /></span>
      <strong>Jobs</strong>
      <span className="jobs-pill-status">{status}</span>
      <Icon name="chevron" size={14} />
    </button>
    {expanded && <div className="jobs-pill-list">{jobs.map(job => {
      const state = pillState(job);
      return <div className="job-pill-row" key={job.id}>
        <span className={`job-pill-dot ${state.key}`} aria-hidden="true" />
        <div className="job-pill-copy"><strong>{job.name}</strong><small>{state.label}</small></div>
        <div className="job-pill-actions">{job.running && job.scope && <button onClick={() => onWatch(job)}>Watch live</button>}<button onClick={() => { if (job.needsApproval) document.getElementById(`job-review-${job.id}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' }); else onEdit(job.id); }}>{job.needsApproval ? 'Review' : 'Run now / Edit'}</button><button onClick={() => { setError(''); void window.ankita.invoke('scheduleEnable', { id: job.id, enabled: !job.enabled }).catch(cause => setError(cause.message)); }}>{job.enabled ? 'Pause' : 'Resume'}</button></div>
      </div>;
    })}<button className="job-link" onClick={() => onEdit()}>Add scheduled job</button>{error && <p role="status" className="job-owner-warning">{error}</p>}</div>}
  </div>;
}
