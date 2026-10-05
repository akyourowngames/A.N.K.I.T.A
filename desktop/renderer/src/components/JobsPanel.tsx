import { useState } from 'react';
import type { Routine, Teammate } from '../../../shared/wire';
import { Icon } from './Icons';
import { nextRunLabel } from './ScheduledTaskCard';
import { JobCard } from './JobCard';
import { JOB_EXECUTION_BOUNDED } from '../../../../src/automation/job-policy.mjs';
import { relativeTime } from '../lib/relative-time';
import { TeammateAvatar } from './TeammateAvatar';

// A task is worth surfacing before the rest when it is blocked on the user,
// lost its owner, or missed its last window. Grouping keeps the panel scannable
// instead of forcing a linear read of every job.
function needsAttention(job: Routine) {
  return Boolean(job.needsApproval || job.ownerMissing || job.lastStatus === 'missed');
}

function rowMeta(job: Routine) {
  if (job.needsApproval) return 'Needs your attention';
  if (job.ownerMissing) return 'Owner missing — choose a teammate';
  if (job.running) return `Running · step ${job.step}`;
  if (job.lastStatus === 'missed') return 'Missed last run';
  if (job.pausedReason) return `Paused: ${job.pausedReason}`;
  if (!job.enabled) return 'Paused';
  return nextRunLabel(job);
}

function runAgo(at: string) {
  const label = relativeTime(at);
  return label === 'now' ? 'just now' : label === 'yesterday' ? 'yesterday' : `${label} ago`;
}

function rowState(job: Routine) {
  if (needsAttention(job)) return 'attention';
  if (job.running) return 'running';
  if (!job.enabled) return 'paused';
  return 'ready';
}

// `jobs` is already scoped to `threadId` by the caller, so a run started here always
// executes and reports in the conversation the panel was opened from.
export function JobsPanel({ jobs, teammates, threadId, selectedId, onChoose, onEdit, onWatch, onAsk, onClose }: { jobs: Routine[]; teammates: Teammate[]; threadId?: string; selectedId?: string; onChoose: (id: string) => void; onEdit: (id: string) => void; onWatch: (job: Routine) => void; onAsk: () => void; onClose: () => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const ownerName = teammates.find(item => item.id === threadId)?.name;
  const selected = jobs.find(job => job.id === selectedId);
  const ordered = [...jobs].sort((a, b) => Number(b.running) - Number(a.running) || Number(b.enabled) - Number(a.enabled) || String(a.nextRunAt || '').localeCompare(String(b.nextRunAt || '')));
  const groups = [
    { key: 'attention', label: 'Needs attention', jobs: ordered.filter(needsAttention) },
    { key: 'running', label: 'Running now', jobs: ordered.filter(job => !needsAttention(job) && job.running) },
    { key: 'upcoming', label: 'Upcoming', jobs: ordered.filter(job => !needsAttention(job) && !job.running && job.enabled) },
    { key: 'paused', label: 'Paused', jobs: ordered.filter(job => !needsAttention(job) && !job.running && !job.enabled) },
  ].filter(group => group.jobs.length);
  const running = jobs.filter(job => job.running).length;
  const attention = jobs.filter(needsAttention).length;
  const next = ordered.filter(job => job.enabled && job.nextRunAt).sort((a, b) => Date.parse(a.nextRunAt!) - Date.parse(b.nextRunAt!))[0];
  const summary = attention ? `${attention} need attention` : running ? `${running} running` : next ? `Next ${nextRunLabel(next)}` : jobs.length ? 'All paused' : 'Nothing scheduled';
  const teammateName = selected ? teammates.find(item => item.id === selected.threadId)?.name || 'Choose a teammate' : '';
  const lastRun = selected ? selected.lastStatus?.replaceAll('-', ' ') || 'Not run yet' : '';
  const act = async (action: string, payload: object) => { setBusy(true); setError(''); try { await window.ankita.invoke(action, payload); } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); } finally { setBusy(false); } };
  return <aside className="jobs-panel" aria-label="Upcoming scheduled jobs">
    <header>
      <div className="jobs-panel-heading"><Icon name="clock" size={18} /><strong>Scheduled tasks</strong>{jobs.length > 0 && <span className="jobs-panel-count">{jobs.length}</span>}</div>
      <button className="icon-button" aria-label="Close scheduled tasks" onClick={onClose}><Icon name="close" size={17} /></button>
    </header>
    <div className="jobs-panel-scroll">
      {jobs.length > 0 && <div className="jobs-panel-intro">
        <span className={`jobs-panel-summary ${attention ? 'attention' : ''}`}>{summary}</span>
        <button onClick={onAsk}><Icon name="plus" size={14} /> Ask Ankita</button>
      </div>}
      {!jobs.length && <div className="jobs-empty"><div className="jobs-empty-companion"><TeammateAvatar id={threadId} color={teammates.find(item => item.id === threadId)?.color} /><span><Icon name="clock" size={19} /></span></div><span className="section-eyebrow">A hand with the routine</span><h3>Leave the next one to {ownerName || 'Ankita'}.</h3><p>Pick the work and the time. Your teammate will run it and bring the result back here.</p><ol className="jobs-empty-steps"><li><span>1</span>Describe what to do</li><li><span>2</span>Choose when it runs</li><li><span>3</span>Get the result in this chat</li></ol><button className="section-primary" onClick={onAsk}><Icon name="plus" size={15} /> Create a task in chat</button></div>}
      {groups.map(group => <section className={`jobs-group ${group.key}`} key={group.key}>
        <div className="jobs-group-title"><span>{group.label}</span><small>{group.jobs.length}</small></div>
        {group.jobs.map(job => <button className={`upcoming-job ${job.id === selectedId ? 'selected' : ''}`} key={job.id} onClick={() => onChoose(job.id)}>
          <span className={`upcoming-job-icon ${rowState(job)}`}><Icon name={job.kind === 'heartbeat' ? 'pulse' : 'clock'} size={16} /></span>
          <span><strong>{job.name}</strong><small>{rowMeta(job)}</small></span>
          <Icon name="chevron" size={13} />
        </button>)}
      </section>)}
      {selected && <section className="job-detail" key={selected.id}>
        <div className="job-detail-title"><h3>{selected.name}</h3><button className="icon-button" aria-label="Edit task settings" onClick={() => onEdit(selected.id)}><Icon name="edit" size={16} /></button></div>
        {(selected.description || selected.prompt) && <p className="job-detail-description">{selected.description || selected.prompt}</p>}
        <div className="job-next-run"><Icon name="clock" size={18} /><div><span>Next run</span><strong>{nextRunLabel(selected)}</strong><small>{selected.cronLabel} · {selected.timeZone}</small></div></div>
        <div className="job-detail-owner"><TeammateAvatar id={selected.threadId || undefined} color={teammates.find(item => item.id === selected.threadId)?.color} /><div><strong>{teammateName}</strong><small>Reports in this conversation</small></div></div>
        <div className="job-stats">
          <div className="job-stat"><span>Execution</span><strong>{selected.executionPolicy === JOB_EXECUTION_BOUNDED ? 'Explicit limits' : 'Until complete'}</strong></div>
          <div className="job-stat"><span>Last run</span><strong>{lastRun}</strong>{selected.lastReceipt && <small>{runAgo(selected.lastReceipt.at)}</small>}</div>
        </div>
        <div className="job-detail-actions"><button disabled={busy} onClick={() => void act('scheduleEnable', { id: selected.id, enabled: !selected.enabled })}>{selected.enabled ? 'Pause' : 'Resume'}</button>{selected.running ? <><button onClick={() => onWatch(selected)}>Watch live</button><button disabled={busy} onClick={() => void act('scheduleStop', { id: selected.id })}>Stop</button></> : <button disabled={busy} onClick={() => void act('scheduleRunNow', { id: selected.id })}>Run now</button>}</div>
        {selected.lastReceipt && <JobCard receipt={selected.lastReceipt} />}
      </section>}
      {error && <p className="job-owner-warning" role="status">{error}</p>}
    </div>
    <footer><small>{ownerName ? `Runs as ${ownerName} and reports in this chat. ` : ''}Runs while Ankita is open, including in the tray.</small></footer>
  </aside>;
}
