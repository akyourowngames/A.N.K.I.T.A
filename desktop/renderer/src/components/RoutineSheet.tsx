import { useEffect, useState } from 'react';
import type { Routine, RoutineAllow, Teammate } from '../../../shared/wire';
import { DEFAULT_JOB_ALLOW, DEFAULT_JOB_BUDGET, JOB_TIMEOUT_MS, JOB_EXECUTION_COMPLETE, JOB_EXECUTION_BOUNDED } from '../../../../src/automation/job-policy.mjs';
import { describeCron, parseCron } from '../../../../src/automation/cron.mjs';
import { Icon } from './Icons';
import { JobCard } from './JobCard';
const MINUTE_MS = 60_000; // Display timeout in minutes; IPC uses milliseconds.
export function RoutineSheet({ routine, jobs, teammates, threadId, onChoose, onClose }: { routine: Routine | null; jobs: Routine[]; teammates: Teammate[]; threadId: string; onChoose: (id?: string) => void; onClose: () => void }) {
  const initial = routine ? { ...routine, ...routine.draftPatch } : null;
  const [name, setName] = useState(initial?.name || '');
  const [cron, setCron] = useState(initial?.cron || '');
  const [prompt, setPrompt] = useState(initial?.prompt || '');
  const [owner, setOwner] = useState(initial?.threadId || threadId);
  const [allow, setAllow] = useState<RoutineAllow>({ ...DEFAULT_JOB_ALLOW, ...initial?.allow, mode: 'isolated' });
  const [sites, setSites] = useState(initial?.allow.sites.join('\n') || '');
  const [enabled, setEnabled] = useState(initial?.draft ? true : initial?.enabled ?? true);
  const [headless, setHeadless] = useState(initial?.headless ?? true);
  const [newRequest, setNewRequest] = useState<'pause-ask' | 'deny'>(initial?.onNewRequest || 'pause-ask');
  const [timeout, setTimeoutValue] = useState(String((initial?.timeoutMs || JOB_TIMEOUT_MS) / MINUTE_MS));
  const [budget, setBudget] = useState({ ...DEFAULT_JOB_BUDGET, ...initial?.budget });
  const [executionPolicy, setExecutionPolicy] = useState(initial?.executionPolicy || JOB_EXECUTION_COMPLETE);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [confirmRun, setConfirmRun] = useState(false);
  const [host, setHost] = useState({ startAtLogin: false, supported: false });
  useEffect(() => { void window.ankita.invoke<typeof host>('scheduleHostSettings').then(setHost).catch(() => {}); }, []);
  useEffect(() => { const key = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); }; window.addEventListener('keydown', key); return () => window.removeEventListener('keydown', key); }, [onClose]);
  const save = async () => {
    setBusy(true); setError('');
    try {
      const patch = { name, cron, prompt, threadId: owner, allow: { ...allow, sites: sites.split('\n').map(value => value.trim()).filter(Boolean) }, enabled, headless, onNewRequest: newRequest, executionPolicy, timeoutMs: Number(timeout) * MINUTE_MS, budget };
      const saved = await window.ankita.invoke<Routine>(routine ? 'scheduleUpdate' : 'scheduleAdd', routine ? { id: routine.id, patch } : patch);
      onChoose(saved.id);
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  const run = async () => { if (!routine) return; setBusy(true); try { const result = await window.ankita.invoke<{ notice?: string }>('scheduleRunNow', { id: routine.id }); setError(result.notice || ''); setConfirmRun(false); } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); } finally { setBusy(false); } };
  const changeState = async (action: 'toggle' | 'stop' | 'remove' | 'pause-all') => {
    setBusy(true); setError('');
    try {
      if (action === 'pause-all') { await window.ankita.invoke('schedulePauseAll'); setEnabled(false); }
      else if (routine && action === 'toggle') { const updated = await window.ankita.invoke<Routine>('scheduleEnable', { id: routine.id, enabled: !routine.enabled }); setEnabled(updated.enabled); }
      else if (routine && action === 'stop') await window.ankita.invoke('scheduleStop', { id: routine.id });
      else if (routine && action === 'remove') { await window.ankita.invoke('scheduleRemove', { id: routine.id }); onChoose(); }
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(false); }
  };
  return <aside className="routine-sheet" aria-label="Scheduled jobs">
    <header><div><Icon name="clock" size={18} /><strong>Scheduled jobs</strong></div><button className="icon-button" onClick={onClose} aria-label="Close job settings"><Icon name="close" size={17} /></button></header>
    <div className="routine-sheet-content">
      <label>Job<select value={routine?.id || ''} onChange={event => onChoose(event.target.value || undefined)}><option value="">New scheduled job</option>{jobs.map(job => <option key={job.id} value={job.id}>{job.name}</option>)}</select></label>
      <label>Name<input value={name} onChange={event => setName(event.target.value)} placeholder="Morning update" /></label>
      <label>Schedule<input aria-label="Schedule" value={cron} onChange={event => setCron(event.target.value)} placeholder="weekdays 09:00" /><small>{parseCron(cron) ? describeCron(cron) : 'Use daily 08:00, weekdays 09:30, every 30m, or a cron expression.'}{routine?.timeZone ? ` · ${routine.timeZone}` : ''}</small></label>
      <label>Deliver to<select value={owner} onChange={event => setOwner(event.target.value)}><option value="" disabled>Choose a teammate</option>{teammates.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      {routine?.ownerMissing && <p className="job-owner-warning">The original teammate is missing. Choose an owner and save.</p>}
      <label>Task instructions<textarea value={prompt} onChange={event => setPrompt(event.target.value)} rows={8} placeholder="Objective, account or resource, steps, completion evidence and report format." /><small>These are the exact instructions the scheduled assistant executes.</small></label>
      <fieldset><legend>Browser permissions</legend>{(['read', 'interact', 'login'] as const).map(key => <label className="job-check" key={key}><input type="checkbox" checked={allow[key]} onChange={event => setAllow({ ...allow, [key]: event.target.checked })} /><span>{key === 'read' ? 'Open and read pages' : key === 'interact' ? 'Fill and click on approved sites' : 'Use saved sign-in credentials'}</span></label>)}<small>First sign-in must be completed in the desktop browser. Jobs never ask for a new password.</small></fieldset>
      <label>Allowed sites<textarea rows={2} value={sites} onChange={event => setSites(event.target.value)} placeholder="One URL per line, such as https://site.com/*" /><small>Empty means ask before visiting each new site.</small></label>
      <label>Browser<select value={allow.mode} onChange={event => setAllow({ ...allow, mode: event.target.value as RoutineAllow['mode'] })}><option value="isolated">Isolated Chromium</option></select><small>Jobs use their own browser profile. Chrome is available for foreground browsing.</small></label>
      {allow.mode === 'isolated' && <label className="job-check"><input type="checkbox" checked={headless} onChange={event => setHeadless(event.target.checked)} />Run without opening a browser window</label>}
      <label>New permissions<select value={newRequest} onChange={event => setNewRequest(event.target.value as typeof newRequest)}><option value="pause-ask">Pause and ask in chat</option><option value="deny">Deny the step</option></select></label>
      <details className="routine-limits"><summary>Execution and background settings</summary><label>Execution<select value={executionPolicy} onChange={event => setExecutionPolicy(event.target.value as typeof executionPolicy)}><option value={JOB_EXECUTION_COMPLETE}>Finish the task</option><option value={JOB_EXECUTION_BOUNDED}>Use explicit limits</option></select><small>{executionPolicy === JOB_EXECUTION_COMPLETE ? 'No token, time or tool-count cutoff. Stop remains available.' : 'The limits below can stop an unfinished task.'}</small></label>{executionPolicy === JOB_EXECUTION_BOUNDED && <><label>Execution timeout (minutes)<input type="number" min="0.1" step="0.1" value={timeout} onChange={event => setTimeoutValue(event.target.value)} /></label>{(Object.keys(budget) as (keyof typeof budget)[]).map(key => <label key={key}>{key === 'maxRunsPerDay' ? 'Runs per day' : key === 'maxTokensPerDay' ? 'Tokens per day' : 'Active minutes per day'}<input type="number" min="1" value={budget[key]} onChange={event => setBudget({ ...budget, [key]: Number(event.target.value) })} /></label>)}</>}<label className="job-check"><input type="checkbox" checked={host.startAtLogin} disabled={!host.supported} onChange={event => { const startAtLogin = event.target.checked; void window.ankita.invoke<typeof host>('scheduleHostSettings', { startAtLogin }).then(setHost).catch(cause => setError(cause.message)); }} />Start Ankita when I sign in</label><small>Jobs continue in the tray. Quit stops them. Only one scheduler can own routines; stop the CLI daemon before using desktop jobs.</small><button className="job-link" disabled={busy} onClick={() => void changeState('pause-all')}>Pause all jobs</button></details>
      <label className="job-check"><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} />Enabled</label>
      {routine?.lastReceipt && <JobCard receipt={routine.lastReceipt} />}
      {confirmRun && <div className="job-run-confirm"><p>The last run may have already completed a post. Review its proof before running it again.</p><button className="button-secondary" onClick={() => setConfirmRun(false)}>Cancel</button><button className="button-primary" disabled={busy} onClick={() => void run()}>Run again anyway</button></div>}
      {error && <p role="status" className="job-owner-warning">{error}</p>}
    </div>
    <footer><button className="button-primary" disabled={busy || !name.trim() || !prompt.trim() || !parseCron(cron)} onClick={() => void save()}>{busy ? 'Working…' : 'Save job'}</button>{routine && <><button className="button-secondary" disabled={busy || routine.running} onClick={() => routine.lastReceipt ? setConfirmRun(true) : void run()}>Run now</button><button className="job-link" disabled={busy} onClick={() => void changeState(routine.running ? 'stop' : 'toggle')}>{routine.running ? 'Stop run' : routine.enabled ? 'Pause' : 'Resume'}</button><button className="icon-button" aria-label="Delete job" disabled={busy || routine.running} onClick={() => void changeState('remove')}><Icon name="trash" size={15} /></button></>}</footer>
  </aside>;
}
