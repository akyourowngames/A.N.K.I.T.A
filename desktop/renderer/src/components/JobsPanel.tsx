import { useState } from 'react';
import type { Routine, Teammate } from '../../../shared/wire';
import { Icon } from './Icons';
import { nextRunLabel } from './ScheduledTaskCard';
import { JobCard } from './JobCard';
import { JOB_EXECUTION_BOUNDED } from '../../../../src/automation/job-policy.mjs';

export function JobsPanel({ jobs, teammates, selectedId, onChoose, onEdit, onWatch, onAsk, onClose }: { jobs: Routine[]; teammates: Teammate[]; selectedId?: string; onChoose: (id: string) => void; onEdit: (id: string) => void; onWatch: (job: Routine) => void; onAsk: () => void; onClose: () => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const selected = jobs.find(job => job.id === selectedId);
  const ordered = [...jobs].sort((a, b) => Number(b.running) - Number(a.running) || Number(b.enabled) - Number(a.enabled) || String(a.nextRunAt || '').localeCompare(String(b.nextRunAt || '')));
  const act = async (action: string, payload: object) => { setBusy(true); setError(''); try { await window.ankita.invoke(action, payload); } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); } finally { setBusy(false); } };
  return <aside className="jobs-panel" aria-label="Upcoming scheduled jobs">
    <header><div><Icon name="clock" size={18} /><strong>Scheduled tasks</strong></div><button className="icon-button" aria-label="Close scheduled tasks" onClick={onClose}><Icon name="close" size={17} /></button></header>
    <div className="jobs-panel-scroll">
      <div className="jobs-panel-intro"><span>Upcoming</span><button onClick={onAsk}><Icon name="plus" size={14} /> Ask Ankita</button></div>
      {!jobs.length && <div className="jobs-empty"><Icon name="clock" size={24} /><h3>A little ahead of time.</h3><p>Tell Ankita what to do and when. Your scheduled tasks will appear here.</p><button className="primary" onClick={onAsk}>Create a task in chat</button></div>}
      {ordered.map(job => <button className={`upcoming-job ${job.id === selectedId ? 'selected' : ''}`} key={job.id} onClick={() => onChoose(job.id)}><span className={`upcoming-job-icon ${job.running ? 'running' : ''}`}><Icon name={job.kind === 'heartbeat' ? 'pulse' : 'clock'} size={17} /></span><span><strong>{job.name}</strong><small>{job.needsApproval ? 'Needs your attention' : nextRunLabel(job)}</small></span><Icon name="chevron" size={13} /></button>)}
      {selected && <section className="job-detail">
        <div className="job-detail-title"><h3>{selected.name}</h3><button className="icon-button" aria-label="Edit task settings" onClick={() => onEdit(selected.id)}><Icon name="edit" size={16} /></button></div>
        <dl><dt>Schedule</dt><dd>{selected.cronLabel}</dd><dt>Timezone</dt><dd>{selected.timeZone}</dd><dt>Teammate</dt><dd>{teammates.find(item => item.id === selected.threadId)?.name || 'Choose a teammate'}</dd><dt>Execution</dt><dd>{selected.executionPolicy === JOB_EXECUTION_BOUNDED ? 'Explicit limits' : 'Until complete'}</dd><dt>Last run</dt><dd>{selected.lastStatus?.replaceAll('-', ' ') || 'Not run yet'}</dd></dl>
        <div className="job-detail-actions"><button disabled={busy} onClick={() => void act('scheduleEnable', { id: selected.id, enabled: !selected.enabled })}>{selected.enabled ? 'Pause' : 'Resume'}</button>{selected.running ? <><button onClick={() => onWatch(selected)}>Watch live</button><button disabled={busy} onClick={() => void act('scheduleStop', { id: selected.id })}>Stop</button></> : <button disabled={busy} onClick={() => void act('scheduleRunNow', { id: selected.id })}>Run now</button>}</div>
        <section className="job-task-instructions" aria-label="Task instructions"><h4>Task instructions</h4><p>{selected.prompt}</p></section>
        {selected.lastReceipt && <JobCard receipt={selected.lastReceipt} />}
      </section>}
      {error && <p className="job-owner-warning" role="status">{error}</p>}
    </div>
    <footer><small>Runs while Ankita is open, including in the tray.</small></footer>
  </aside>;
}
