import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import type { AssistantTask, AssistantToday, PersonalMemory, Routine, Teammate } from '../../../shared/wire';
import { ASSISTANT_ACTIONS, ASSISTANT_CHANGED, ASSISTANT_ROUTINES_CHANGED, KNOWLEDGE_CHANGED, MEMORY_TEXT_LIMIT, RESUMABLE_TASK_STATES } from '../../../shared/assistant.mjs';
import { describeCron, parseCron } from '../../../../src/automation/cron.mjs';
import { RoutineLibrary } from './RoutineLibrary';
import { Icon } from './Icons';
import './today.css';

const REFRESH_DELAY_MS = 200; // Coalesce action receipts without repeatedly querying IPC for one step.
const TODAY_UNAVAILABLE = 'Today is unavailable from this app session. Restart Ankita to load matching app components.';
const MEMORY_KINDS = ['fact', 'preference', 'goal', 'commitment'] as const;
const MEMORY_KIND_LABELS: Record<string, string> = { fact: 'Fact', preference: 'Preference', goal: 'Goal', commitment: 'Commitment' };
const EMPTY_MEMORY = { text: '', kind: 'fact', always: false };
const CHECK_APPS_REQUEST = 'Check my connected calendar and inbox for today. Give a short briefing with sources. Say which sources were unavailable. Do not send, change or delete anything.';
const TASK_LABELS: Record<string, string> = { queued: 'Starting', running: 'Working', interrupted: 'Interrupted', failed: 'Needs attention', cancelled: 'Stopped', needs_review: 'Check outcome', completed: 'Finished' };

function TaskCard({ task, owner, busy, run, onOpen, onTeach }: { task: AssistantTask; owner: string; busy: boolean;
  run: (action: string, payload: unknown) => Promise<boolean>; onOpen: (id: string) => void; onTeach: (task: AssistantTask) => void }) {
  const [evidence, setEvidence] = useState<Record<string, string>>({});
  const [outcome, setOutcome] = useState<Record<string, string>>({});
  return <article className="today-task">
    <div className="today-task-meta"><span>{owner}</span><span>{TASK_LABELS[task.status] || task.status}</span></div>
    <h3>{task.goal}</h3>
    {task.error && <p className="today-error">{task.error}</p>}
    <div className="today-task-actions"><button onClick={() => onOpen(task.ownerId)}>Open conversation</button>
      {task.status === 'completed' && !task.error && <button onClick={() => onTeach(task)}>Save as routine</button>}
      {RESUMABLE_TASK_STATES.includes(task.status) && <button disabled={busy} onClick={() => void run(ASSISTANT_ACTIONS.resume, { id: task.ownerId, taskId: task.id }).then(ok => { if (ok) onOpen(task.ownerId); })}>Continue request</button>}
    </div>
    {(task.steps.length > 0 || task.reply) && <details><summary>Saved progress</summary>
      {task.reply && <p className="today-report">{task.reply}</p>}
      {task.checklist.map(item => <p key={item.id}>{item.status === 'completed' ? '✓' : '○'} {item.content}</p>)}
      {task.steps.map(step => <div className="today-receipt" key={step.id}><strong>{step.tool} · {step.phase === 'uncertain' ? 'Outcome unknown' : step.phase.replaceAll('_', ' ')}</strong><p>{step.result}</p>
        {step.phase === 'uncertain' && <form onSubmit={event => { event.preventDefault(); void run(ASSISTANT_ACTIONS.resolve, { id: task.ownerId, taskId: task.id, stepId: step.id, outcome: outcome[step.id] || 'completed', evidence: evidence[step.id] }); }}>
          <p>Check the app or file before recording what happened.</p>
          <label>Observed outcome<select value={outcome[step.id] || 'completed'} onChange={event => setOutcome(current => ({ ...current, [step.id]: event.target.value }))}><option value="completed">It happened</option><option value="not_done">It did not happen</option></select></label>
          <label>What did you check?<input required value={evidence[step.id] || ''} onChange={event => setEvidence(current => ({ ...current, [step.id]: event.target.value }))} /></label>
          <button disabled={busy || !evidence[step.id]?.trim()}>Save observed outcome</button>
        </form>}
      </div>)}
    </details>}
  </article>;
}

export function TodayPage({ teammates, sidebarOpen, onToggleSidebar, onOpenThread, onOpenJob, onAsk, onVoice }: {
  teammates: Pick<Teammate, 'id' | 'name'>[]; sidebarOpen: boolean; onToggleSidebar: () => void;
  onOpenThread: (id: string) => void; onOpenJob: (job: Routine) => void; onAsk: (text: string) => void; onVoice: (id: string) => void;
}) {
  const [today, setToday] = useState<AssistantToday | null>(null), [facts, setFacts] = useState<PersonalMemory[]>([]);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false), [query, setQuery] = useState('');
  const [draft, setDraft] = useState<{ id?: string; text: string; kind: string; always: boolean; expectedUpdatedAt?: string } | null>(null);
  const [briefOpen, setBriefOpen] = useState(false), [briefCron, setBriefCron] = useState('daily 09:00');
  const [briefOwner, setBriefOwner] = useState(''), [briefError, setBriefError] = useState('');
  const [memoryFilter, setMemoryFilter] = useState('all');
  const [teachTask, setTeachTask] = useState<AssistantTask | null>(null);
  const alive = useRef(true), revision = useRef(0);
  const refresh = useCallback(async () => {
    const current = ++revision.current;
    try {
      const snapshot = await window.ankita.invoke<AssistantToday>(ASSISTANT_ACTIONS.today);
      if (!snapshot || !Array.isArray(snapshot.unfinished) || !Array.isArray(snapshot.recent) || !Array.isArray(snapshot.upcoming) || !Array.isArray(snapshot.memories) || !Array.isArray(snapshot.routines)) throw new Error(TODAY_UNAVAILABLE);
      if (alive.current && revision.current === current) { setToday(snapshot); setFacts(snapshot.memories); setError(''); }
    } catch (err) { if (alive.current && revision.current === current) setError(err instanceof Error ? err.message : String(err)); }
  }, []);
  useEffect(() => {
    alive.current = true; void refresh(); let timer: ReturnType<typeof setTimeout> | undefined;
    const off = window.ankita.onEvent(event => {
      if (![ASSISTANT_CHANGED, KNOWLEDGE_CHANGED, ASSISTANT_ROUTINES_CHANGED, 'schedule-changed', 'routine-delivery-state', 'teammates-changed'].includes(event.type)) return;
      clearTimeout(timer); timer = setTimeout(() => void refresh(), REFRESH_DELAY_MS);
    });
    return () => { alive.current = false; revision.current++; clearTimeout(timer); off(); };
  }, [refresh]);
  const run = async (action: string, payload: unknown) => {
    setBusy(true); setError('');
    try { await window.ankita.invoke(action, payload); await refresh(); return true; }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); return false; }
    finally { setBusy(false); }
  };
  const saveMemory = (event: FormEvent) => { event.preventDefault(); if (draft) void run(ASSISTANT_ACTIONS.memorySave, draft).then(ok => { if (ok) setDraft(null); }); };
  const scheduleBriefing = async (event: FormEvent) => {
    event.preventDefault();
    const ownerId = briefOwner || teammates[0]?.id;
    if (!ownerId || !parseCron(briefCron)) return;
    setBusy(true); setBriefError('');
    try {
      const job = await window.ankita.invoke<Routine>(ASSISTANT_ACTIONS.briefingSchedule, { ownerId, cron: briefCron.trim() });
      setBriefOpen(false); onOpenJob(job);
    } catch (err) { setBriefError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  };
  const name = (id: string) => teammates.find(item => item.id === id)?.name || 'Conversation';
  const commitmentGroups = useMemo(() => {
    const groups = new Map<string, { id: string; name: string; items: AssistantToday['commitments'] }>();
    for (const item of today?.commitments || []) {
      const group = groups.get(item.projectId) || { id: item.projectId, name: item.projectName, items: [] };
      group.items.push(item); groups.set(item.projectId, group);
    }
    return [...groups.values()];
  }, [today?.commitments]);
  const sourceLabel = (source: unknown) => {
    if (!source) return 'Source not recorded';
    if (typeof source === 'string') return source;
    const type = typeof (source as { type?: unknown }).type === 'string' ? String((source as { type: string }).type) : '';
    if (!type) return 'Source recorded';
    return type === 'desktop-memory-editor' ? 'Edited on desktop' : type.replaceAll(/[-_]/g, ' ');
  };
  const shown = facts.filter(fact => (memoryFilter === 'all' || fact.kind === memoryFilter)
    && `${fact.text} ${fact.kind}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  return <main className="today-page">
    <header className="today-header drag-region"><div className="no-drag">{!sidebarOpen && <button className="icon-button" aria-label="Show sidebar" onClick={onToggleSidebar}><Icon name="panelLeft" /></button>}<strong>Today</strong></div><div className="no-drag"><button className="icon-button" aria-label="Refresh today" onClick={() => void refresh()}><Icon name="refresh" /></button></div></header>
    <div className="today-scroll"><div className="today-intro"><span className="today-eyebrow">Your day with Ankita</span><h1>What needs your attention?</h1><p>Your requests, saved progress, and what comes next.</p>
      <div className="today-quick-actions"><button className="button-primary" disabled={!teammates.length} onClick={() => onAsk('')}><Icon name="chat" />Ask in chat</button><button disabled={!teammates.length} onClick={() => onVoice(teammates[0].id)}><Icon name="mic" />Talk to Ankita</button></div>
    </div>
    {error && <p role="alert" className="today-error">{error}</p>}
    {!today && !error && <p role="status">Loading your day…</p>}
    {today && <><section className="today-brief" aria-label="Daily briefing"><div className="today-brief-head"><h2>At a glance</h2><span className={`today-source ${today.externalSources.status}`}>{today.externalSources.status === 'not_checked' ? 'External apps not checked' : today.externalSources.status}</span></div>
      <div className="today-stats"><div className="today-stat"><strong>{today.unfinished.length}</strong><span>Unfinished</span></div><div className="today-stat"><strong>{today.recent.length}</strong><span>Completed today</span></div><div className="today-stat"><strong>{today.upcoming.length}</strong><span>Upcoming</span></div><div className="today-stat"><strong>{today.pending.length}</strong><span>Results waiting</span></div></div>
      <p className="today-brief-note">{today.externalSources.notice}</p>
      <div className="today-brief-actions"><button disabled={!teammates.length} onClick={() => onAsk(CHECK_APPS_REQUEST)}>Check connected apps in chat <Icon name="external" size={14} /></button><button disabled={!teammates.length || busy} onClick={() => { setBriefError(''); setBriefOpen(open => !open); }}>Schedule daily briefing</button></div>
      {briefOpen && <form className="today-brief-schedule" onSubmit={event => void scheduleBriefing(event)}>
        <label>Schedule<input aria-label="Briefing schedule" required maxLength={80} value={briefCron} onChange={event => setBriefCron(event.target.value)} placeholder="daily 09:00" /><small>{parseCron(briefCron) ? describeCron(briefCron) : 'Use daily 08:00, weekdays 09:30, or every 30m.'}</small></label>
        {teammates.length > 1 && <label>Conversation<select aria-label="Briefing conversation" value={briefOwner || teammates[0].id} onChange={event => setBriefOwner(event.target.value)}>{teammates.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>}
        <p>Creates a paused draft. Review its instructions and permissions before turning it on. Each run reads current saved facts and marks external apps as not checked.</p>
        {briefError && <p role="alert" className="today-error">{briefError}</p>}
        <div><button className="button-primary" disabled={busy || !parseCron(briefCron)}>Create paused draft</button><button type="button" onClick={() => setBriefOpen(false)}>Cancel</button></div>
      </form>}
    </section>
      <div className="today-columns"><section aria-label="Unfinished requests"><h2>Pick up where you left off <span>{today.unfinished.length}</span></h2>
        {!today.unfinished.length && <p className="today-empty">No unfinished requests. Start with whatever you need today.</p>}
        {today.unfinished.map(task => <TaskCard key={task.id} task={task} owner={name(task.ownerId)} busy={busy} run={run} onOpen={onOpenThread} onTeach={setTeachTask} />)}
      </section><section aria-label="Upcoming tasks"><h2>Coming up</h2>{!today.upcoming.length && <p className="today-empty">No scheduled tasks are turned on.</p>}
        {today.upcoming.map(job => <button className="today-upcoming" key={job.id} onClick={() => onOpenJob(job)}><Icon name="clock" /><span><strong>{job.name}</strong><small>{job.nextRunAt ? new Date(job.nextRunAt).toLocaleString(undefined, { timeZone: today.timeZone }) : job.cronLabel}</small></span><Icon name="chevron" /></button>)}
        <h2>Finished today <span>{today.recent.length}</span></h2>{today.recent.map(task => <TaskCard key={task.id} task={task} owner={name(task.ownerId)} busy={busy} run={run} onOpen={onOpenThread} onTeach={setTeachTask} />)}
      </section></div>
      {today.commitments?.length > 0 && <section className="today-knowledge today-commitments" aria-label="Project commitments"><div className="today-section-heading"><div><h2>Open project commitments <span>{today.commitments.length}</span></h2><p>Promises and next steps you asked to keep visible.</p></div></div>
        <div className="today-commitment-grid">{commitmentGroups.map(group => <article className="today-commitment-card" key={group.id} aria-label={group.name}>
          <header><div><span className="today-project-mark"><Icon name="folder" size={14} /></span><h3>{group.name}</h3></div><span>{group.items.length}</span></header>
          <ul>{group.items.map(item => <li key={item.id}><details className="today-commitment-item"><summary title={item.text}><span>{item.text}</span><Icon name="chevron" size={12} /></summary></details><button className="today-inline-button" disabled={busy} onClick={() => void run(ASSISTANT_ACTIONS.commitmentComplete, { id: item.projectId, ref: item.id })}>Mark completed</button></li>)}</ul>
        </article>)}</div>
      </section>}
      <RoutineLibrary routines={today.routines} teammates={teammates} source={teachTask} onClearSource={() => setTeachTask(null)} onRefresh={() => void refresh()} onOpenThread={onOpenThread} onOpenJob={onOpenJob} />
    </>}
    <section className="today-knowledge" aria-label="Personal memory"><div className="today-section-heading"><div><h2>What Ankita remembers <span>{facts.length}</span></h2><p>Preferences, goals and commitments Ankita should keep in mind.</p></div><button onClick={() => setDraft({ ...EMPTY_MEMORY })}>Add memory</button></div>
      <div className="today-memory-toolbar"><label className="today-search"><Icon name="search" /><input aria-label="Search memory" placeholder="Search your memory" value={query} onChange={event => setQuery(event.target.value)} /></label>
        <div className="today-memory-filters" aria-label="Memory type">{['all', ...MEMORY_KINDS].map(kind => <button key={kind} type="button" aria-pressed={memoryFilter === kind} onClick={() => setMemoryFilter(kind)}>{kind === 'all' ? 'All' : MEMORY_KIND_LABELS[kind] || kind}</button>)}</div></div>
      {draft && <form className="today-memory-editor" onSubmit={saveMemory}><label>Memory text<textarea aria-label="Memory text" required maxLength={MEMORY_TEXT_LIMIT} value={draft.text} onChange={event => setDraft({ ...draft, text: event.target.value })} /></label>
        <label>Type<select value={draft.kind} onChange={event => setDraft({ ...draft, kind: event.target.value })}>{MEMORY_KINDS.map(kind => <option key={kind} value={kind}>{MEMORY_KIND_LABELS[kind] || kind}</option>)}</select></label>
        <label className="today-checkbox"><input type="checkbox" checked={draft.always} onChange={event => setDraft({ ...draft, always: event.target.checked })} />Keep this preference in mind</label>
        <div><button className="button-primary" disabled={busy || !draft.text.trim()}>Save memory</button><button type="button" onClick={() => setDraft(null)}>Cancel</button></div>
      </form>}
      {!shown.length && <p className="today-empty">{query || memoryFilter !== 'all' ? 'No matching memories.' : 'No personal memories saved yet.'}</p>}
      <div className="today-memories">{shown.map(fact => <article className="today-memory-card" key={fact.id}>
        <div className="today-memory-card-head"><span className={`today-kind today-kind-${fact.kind}`}>{MEMORY_KIND_LABELS[fact.kind] || fact.kind}</span>{fact.always && <span className="today-kept">Kept in mind</span>}{fact.conflictsWith?.length ? <span className="today-conflict">Conflicting information</span> : null}</div>
        <details className="today-memory-text"><summary title={fact.text}>{fact.text}</summary></details>
        <div className="today-memory-card-foot"><small>{sourceLabel(fact.source)} · {new Date(fact.updatedAt).toLocaleDateString()}</small><div className="today-memory-actions"><button className="icon-button" aria-label="Edit memory" title="Edit memory" onClick={() => setDraft({ id: fact.id, text: fact.text, kind: fact.kind, always: fact.always, expectedUpdatedAt: fact.updatedAt })}><Icon name="edit" /></button><button className="icon-button" aria-label="Forget memory" title="Forget memory" disabled={busy} onClick={() => void run(ASSISTANT_ACTIONS.memoryForget, { id: fact.id })}><Icon name="trash" /></button></div></div>
      </article>)}</div>
    </section></div>
  </main>;
}
