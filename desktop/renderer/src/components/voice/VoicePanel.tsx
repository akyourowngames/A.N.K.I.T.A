import { useEffect, useRef } from 'react';
import type { VoiceState } from '../../../../shared/voice.mjs';
import { VOICE_PHASE_LABELS } from '../../../../shared/voice.mjs';
import { VoiceOrb } from './VoiceOrb';
import { VoiceCaptions } from './VoiceCaptions';
import { Icon } from '../Icons';
import './voice.css';

const ACTIVE_TASK = new Set(['queued', 'running', 'waiting_for_approval', 'waiting_for_resource', 'cancelling']);
const JOB_STATE: Record<string, string> = { queued: 'Starting', running: 'Working', waiting_for_approval: 'Permission needed', waiting_for_resource: 'Waiting for access', cancelling: 'Stopping', done: 'Done', partial: 'Partial result', failed: 'Needs attention', cancelled: 'Stopped' };
const PLACEHOLDERS = { idle: 'Speak when you’re ready.', starting: 'Getting your voice ready.', listening: 'Go ahead. I’m listening.',
  transcribing: 'Catching your words.', working: 'I’m on it.', speaking: '', approval: 'Your permission is needed.', paused: 'Take your time.', error: 'Let’s get voice ready.' };

export function VoicePanel({ voice, error = '', busy = false, compact = false, onEnd, onPause, onResume, onCancel, onIsland, onSettings, onStart, onFocus }: {
  voice: VoiceState; error?: string; busy?: boolean; compact?: boolean;
  onEnd: () => unknown; onPause: () => unknown; onResume: () => unknown; onCancel: (taskId?: string) => unknown;
  onIsland?: () => unknown; onSettings?: () => unknown; onStart?: () => unknown; onFocus?: () => unknown;
}) {
  const end = useRef<HTMLButtonElement>(null);
  const phase = error ? 'error' : voice.phase;
  const jobs = voice.jobs?.length ? voice.jobs : voice.task ? [voice.task] : [];
  const activeJobs = jobs.filter(job => ACTIVE_TASK.has(job.status) || job.resourcesHeld);
  const visibleJobs = [...activeJobs, ...jobs.filter(job => !ACTIVE_TASK.has(job.status) && !job.resourcesHeld).slice(0, compact ? 1 : 2)];
  const working = activeJobs.length > 0;
  const issue = error || voice.error;
  useEffect(() => { if (!compact) end.current?.focus({ preventScroll: true }); }, [compact]);
  useEffect(() => {
    if (compact) return;
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape' && !document.querySelector('[aria-modal="true"]')) { event.preventDefault(); onEnd(); } };
    window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key);
  }, [compact, onEnd]);
  return <section className={`voice-panel ${compact ? 'voice-panel-compact' : ''} ${jobs.length ? 'voice-panel-with-jobs' : ''}`} aria-label="Voice conversation" data-phase={phase}>
    {!compact && <div className="voice-panel-top">
      <button className="voice-text-button" onClick={onSettings}><Icon name="settings" size={15} /> Voice settings</button></div>}
    <div className="voice-stage">
      <VoiceOrb phase={phase} inputLevel={voice.inputLevel} compact={compact} task={voice.task} />
      <div className="voice-phase" data-phase={phase}><i />{VOICE_PHASE_LABELS[phase]}</div>
      <VoiceCaptions text={voice.caption || PLACEHOLDERS[phase]} role={voice.captionRole} />
      <div className="voice-work-line" role="status" aria-live="polite" aria-atomic="true">
        {issue ? <span className="voice-error">{issue}</span> : voice.phase === 'approval' ? 'Review the permission request to continue.' : voice.update || (working ? 'You can give me another request.' : voice.task?.status === 'done' ? 'Done · saved in this conversation' : voice.task?.status === 'partial' ? 'Some findings are ready · open the result below' : voice.task?.status === 'failed' ? 'Work needs attention · see the conversation' : voice.task?.status === 'cancelled' ? 'Work stopped' : voice.paused ? 'Microphone is off' : 'Speak naturally. Pause to send.')}
      </div>
    </div>
    {jobs.length > 0 && <div className="voice-jobs" aria-label="Voice jobs">
      <div className="voice-jobs-heading"><span>{activeJobs.length ? 'In progress' : 'Recent results'} <b>{activeJobs.length || visibleJobs.length}</b></span><span>Open a request for details</span></div>
      {visibleJobs.map(job => <div className="voice-job" key={job.id} data-status={job.status}>
        <span className="voice-job-dot" /><div><details className="voice-job-details"><summary title={job.label || 'Voice request'}>
          <span className="voice-job-name">{job.label || 'Voice request'}</span><span className="voice-job-status">{job.resourcesHeld ? 'Command active' : JOB_STATE[job.status] || job.status}</span>
        </summary><div className="voice-job-result">
          {job.waitingFor && <p>{job.waitingFor}</p>}
          {job.resourcesHeld && <p>The report is ready. Its command still holds shared access until it exits or you stop it.</p>}
          {job.error && <p className="voice-job-issue">{job.error}</p>}
          {job.summary && <p>{job.summary}</p>}
          {job.steps.length > 0 && <small>{job.steps.filter(step => step.state === 'done').length} of {job.steps.length} actions completed</small>}
        </div></details></div>
        {(ACTIVE_TASK.has(job.status) || job.resourcesHeld) && <button className="voice-job-stop" onClick={() => onCancel(job.id)} disabled={busy || job.status === 'cancelling'} aria-label={`Stop ${job.label || 'voice request'}`}><Icon name="stop" size={12} /></button>}
      </div>)}
    </div>}
    <div className="voice-controls">
      {voice.active ? <>
        <button className={`voice-control ${voice.paused ? 'is-muted' : ''}`} disabled={busy} onClick={voice.paused ? onResume : onPause} aria-label={voice.paused ? 'Resume microphone' : 'Pause microphone'} aria-pressed={voice.paused} title={voice.paused ? 'Resume microphone' : 'Pause microphone'}><Icon name={voice.paused ? 'micOff' : 'mic'} size={20} /></button>
        <button ref={end} className="voice-control voice-end" onClick={onEnd} aria-label="End voice" title="End voice · work keeps running"><Icon name="phoneEnd" size={21} /><span>End voice</span></button>
      </> : <button ref={end} className="voice-start" onClick={onStart} disabled={busy || !onStart}><Icon name="mic" size={18} />{busy ? 'Getting ready…' : 'Try voice again'}</button>}
      {working && <button className="voice-control voice-stop" onClick={() => onCancel()} disabled={busy} aria-label="Stop all work" title="Cancel all voice jobs"><Icon name="stop" size={14} /><span>Stop all</span></button>}
    </div>
    <div className="voice-panel-foot">{compact ? <><button className="voice-text-button" onClick={onFocus}>Open conversation <Icon name="external" size={13} /></button>{issue && <button className="voice-text-button" onClick={onSettings}><Icon name="settings" size={13} /> Voice settings</button>}</>
      : <><span>{working ? 'End voice keeps your work running.' : ''}</span><button className="voice-text-button" onClick={onIsland}><Icon name="panel" size={14} /> Continue in island</button></>}
    </div>
  </section>;
}
