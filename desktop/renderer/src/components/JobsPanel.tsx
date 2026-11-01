import { useEffect, useState } from 'react';
import type { Routine, Teammate } from '../../../shared/wire';
import { Icon } from './Icons';
import { jobNeedsAttention, jobIsDeferred, jobStatusSummary, nextRunLabel, pendingSummary } from '../lib/jobs';
import { JobCard } from './JobCard';
import { JOB_EXECUTION_BOUNDED, heartbeatRunLabel } from '../../../../src/automation/job-policy.mjs';
import { relativeTime } from '../lib/relative-time';
import { TeammateAvatar } from './TeammateAvatar';

type PendingDelivery = { runId: string; routineId: string; name: string; status: string; at: string };
type AwaySummary = { ran: number; quiet: number; needsYou: number; readyToPost: number };

function rowMeta(job: Routine) {
  if (job.needsApproval) return 'Needs your attention';
  if (job.ownerMissing) return 'Owner missing — choose a teammate';
  if (job.running) return `Running · step ${job.step}`;
  if (jobIsDeferred(job)) return `Waiting for this chat · ${job.coalescedHeartbeats || 1} check${(job.coalescedHeartbeats || 1) === 1 ? '' : 's'} held`;
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
  if (jobNeedsAttention(job)) return 'attention';
  if (job.running) return 'running';
  if (!job.enabled) return 'paused';
  return 'ready';
}

// `jobs` is already scoped to `threadId` by the caller, so a run started here always
// executes and reports in the conversation the panel was opened from.
export function JobsPanel({ jobs, teammates, threadId, selectedId, pending = [], onChoose, onEdit, onWatch, onAsk, onClose }: { jobs: Routine[]; teammates: Teammate[]; threadId?: string; selectedId?: string; pending?: PendingDelivery[]; onChoose: (id: string) => void; onEdit: (id: string) => void; onWatch: (job: Routine) => void; onAsk: () => void; onClose: () => void }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [openDelivery, setOpenDelivery] = useState<string | null>(null);
  const [away, setAway] = useState<AwaySummary | null>(null);
  // Loaded on open so the strip is computed by the scheduler, not re-derived here.
  useEffect(() => {
    let alive = true;
    void window.ankita.invoke<AwaySummary>('scheduleAwaySummary', { threadId }).then(value => { if (alive) setAway(value); }).catch(() => {});
    return () => { alive = false; };
  }, [threadId, jobs.length, pending.length]);
  const ownerName = teammates.find(item => item.id === threadId)?.name;
  const selected = jobs.find(job => job.id === selectedId);
  const ordered = [...jobs].sort((a, b) => Number(b.running) - Number(a.running) || Number(b.enabled) - Number(a.enabled) || String(a.nextRunAt || '').localeCompare(String(b.nextRunAt || '')));
  const groups = [
    { key: 'attention', label: 'Needs attention', jobs: ordered.filter(jobNeedsAttention) },
    { key: 'running', label: 'Running now', jobs: ordered.filter(job => !jobNeedsAttention(job) && job.running) },
    { key: 'upcoming', label: 'Upcoming', jobs: ordered.filter(job => !jobNeedsAttention(job) && !job.running && job.enabled) },
    { key: 'paused', label: 'Paused', jobs: ordered.filter(job => !jobNeedsAttention(job) && !job.running && !job.enabled) },
  ].filter(group => group.jobs.length);
  const attention = jobs.filter(jobNeedsAttention).length;
  const summary = jobStatusSummary(jobs);
  const teammateName = selected ? teammates.find(item => item.id === selected.threadId)?.name || 'Choose a teammate' : '';
  const lastRun = selected ? heartbeatRunLabel(selected.lastStatus, selected.lastReason) || selected.lastStatus?.replaceAll('-', ' ') || 'Not run yet' : '';
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
      {/* While you were away: one strip, counts only, no chat traffic. */}
      {away && (away.ran + away.quiet + away.needsYou > 0) && <div className="jobs-away-strip" role="status" aria-label="While you were away">
        <span className="jobs-away-lead"><Icon name="pulse" size={13} />While you were away</span>
        <span><strong>{away.ran}</strong> ran</span>
        {away.quiet > 0 && <span><strong>{away.quiet}</strong> quiet</span>}
        {away.needsYou > 0 && <span className="is-attention"><strong>{away.needsYou}</strong> need you</span>}
      </div>}
      {/* Results that finished while this teammate was busy. They post only when
          the turn ends; the panel is where you read them without waiting. */}
      {pending.length > 0 && <section className="jobs-group ready" aria-label="Results ready to post">
        <div className="jobs-group-title"><span>{pendingSummary(pending.length)}</span><small>{pending.length}</small></div>
        {pending.map(item => <div className="jobs-delivery" key={item.runId} data-open={openDelivery === item.runId}>
          <button className="jobs-delivery-head" aria-expanded={openDelivery === item.runId} onClick={() => setOpenDelivery(current => current === item.runId ? null : item.runId)}>
            <span className="upcoming-job-icon ready"><Icon name="check" size={14} /></span>
            <span><strong>{item.name}</strong><small>Finished {runAgo(item.at)} · posts when this chat is free</small></span>
            <Icon name="chevron" size={13} />
          </button>
          {openDelivery === item.runId && <div className="jobs-delivery-body">
            <p>{jobs.find(job => job.id === item.routineId)?.lastReceipt?.text || 'The result will appear here once this chat is free.'}</p>
            <button className="settings-text-button" onClick={() => { onChoose(item.routineId); onWatch(jobs.find(job => job.id === item.routineId) || ({} as Routine)); }}>Open the task</button>
          </div>}
        </div>)}
      </section>}
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
        {/* Live progress: the run is happening now, so say what step it is on. */}
        {selected.running && <div className="job-live-run" role="status" aria-live="polite">
          <span className="jobs-live-dot" aria-hidden="true" /><div><span>Running now</span><strong>Step {selected.step || 1}</strong><small>{selected.kind === 'heartbeat' ? 'Checking what changed' : 'Working through the task'}</small></div>
        </div>}
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
