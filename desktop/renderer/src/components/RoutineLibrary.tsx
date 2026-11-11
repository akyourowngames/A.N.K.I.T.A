import { useEffect, useId, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react';
import type { AssistantRoutine, AssistantTask, Routine, Teammate } from '../../../shared/wire';
import { ASSISTANT_ACTIONS } from '../../../shared/assistant.mjs';
import { ROUTINE_NAME_CHARS, ROUTINE_TEMPLATE_CHARS, routineParameterNames } from '../../../../src/assistant/routine-policy.mjs';
import { describeCron, parseCron } from '../../../../src/automation/cron.mjs';
import './routine-library.css';

type Owner = Pick<Teammate, 'id' | 'name'>;
type Editor = { source?: AssistantTask; routine?: AssistantRoutine };
type Invoke = <T>(action: string, payload: unknown) => Promise<T>;

function RoutineDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null), titleId = useId();
  useEffect(() => { ref.current?.showModal(); }, []);
  return <dialog className="routine-dialog" ref={ref} aria-labelledby={titleId} onCancel={event => { event.preventDefault(); onClose(); }}>
    <header><h2 id={titleId}>{title}</h2><button type="button" onClick={onClose}>Close</button></header>{children}
  </dialog>;
}

function RoutineEditor({ editor, invoke, onSaved, onClose }: { editor: Editor; invoke: Invoke; onSaved: () => void; onClose: () => void }) {
  const { routine, source } = editor;
  const [name, setName] = useState(routine?.name || source?.goal.slice(0, ROUTINE_NAME_CHARS) || '');
  const [template, setTemplate] = useState(routine?.template || source?.goal || '');
  const [defaults, setDefaults] = useState<Record<string, string>>(() => Object.fromEntries((routine?.parameters || []).map(input => [input.name, input.defaultValue ?? ''])));
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const parsed = useMemo(() => { try { return { names: routineParameterNames(template), error: '' }; } catch (cause) { return { names: [], error: String((cause as Error).message) }; } }, [template]);
  const save = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await invoke(ASSISTANT_ACTIONS.routineSave, { id: routine?.id, ownerId: routine?.ownerId || source?.ownerId,
        expectedRevision: routine?.revision, sourceTaskId: source?.id, name, template,
        parameters: parsed.names.map(parameter => ({ name: parameter, label: routine?.parameters.find(input => input.name === parameter)?.label || parameter,
          defaultValue: defaults[parameter]?.trim() ? defaults[parameter] : null })) });
      onSaved(); onClose();
    } catch (cause) { setError((cause as Error).message); } finally { setBusy(false); }
  };
  return <RoutineDialog title={routine ? 'Edit routine' : 'Save a routine'} onClose={onClose}><form onSubmit={event => void save(event)}>
    <p>Keep the useful instructions. Add a placeholder such as <code>{'{{topic}}'}</code> for anything that changes next time.</p>
    <label>Routine name<input required maxLength={ROUTINE_NAME_CHARS} value={name} onChange={event => setName(event.target.value)} /></label>
    <label>Instructions<textarea required maxLength={ROUTINE_TEMPLATE_CHARS} value={template} onChange={event => setTemplate(event.target.value)} /></label>
    {parsed.error && <p className="today-error">{parsed.error}</p>}
    {parsed.names.map(parameter => <label key={parameter}>Default for {parameter}<input aria-label={`Default for ${parameter}`} value={defaults[parameter] || ''} onChange={event => setDefaults(current => ({ ...current, [parameter]: event.target.value }))} /><small>Leave empty to ask each time.</small></label>)}
    <p>Saved from finished work. Each run checks the current state and uses the normal approval controls. Saving does not schedule anything.</p>
    {error && <p role="alert" className="today-error">{error}</p>}
    <footer><button type="button" onClick={onClose}>Cancel</button><button className="button-primary" disabled={busy || Boolean(parsed.error) || !name.trim()}>Save routine</button></footer>
  </form></RoutineDialog>;
}

function RoutineRunner({ routine, schedule, invoke, onRun, onSchedule, onClose }: { routine: AssistantRoutine; schedule: boolean;
  invoke: Invoke; onRun: () => void; onSchedule: (job: Routine) => void; onClose: () => void }) {
  const [values, setValues] = useState<Record<string, string>>({}), [cron, setCron] = useState('');
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const missing = routine.parameters.filter(input => input.defaultValue === null);
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const payload = { routineId: routine.id, ownerId: routine.ownerId, values, ...(schedule ? { cron } : {}) };
      if (schedule) onSchedule(await invoke<Routine>(ASSISTANT_ACTIONS.routineSchedule, payload));
      else { await invoke(ASSISTANT_ACTIONS.routineRun, payload); onRun(); }
      onClose();
    } catch (cause) { setError((cause as Error).message); } finally { setBusy(false); }
  };
  return <RoutineDialog title={`${schedule ? 'Schedule' : 'Run'} ${routine.name}`} onClose={onClose}><form onSubmit={event => void submit(event)}>
    <p className="routine-template">{routine.template}</p>
    {missing.map(input => <label key={input.name}>{input.label}<input required value={values[input.name] || ''} onChange={event => setValues(current => ({ ...current, [input.name]: event.target.value }))} /></label>)}
    {routine.parameters.some(input => input.defaultValue !== null) && <details><summary>Saved default values</summary>{routine.parameters.filter(input => input.defaultValue !== null).map(input => <p key={input.name}>{input.label}: {input.defaultValue}</p>)}</details>}
    {schedule ? <><label>Schedule<input aria-label="Schedule" required value={cron} onChange={event => setCron(event.target.value)} placeholder="weekdays 09:00" /><small>{parseCron(cron) ? describeCron(cron) : 'Use daily 08:00, weekdays 09:30, or every 30m.'}</small></label><p>This opens a paused schedule draft. Review its instructions and background permissions before turning it on. Background runs support fewer actions than chat.</p></> : <p>This starts a fresh request in its original conversation. Actions still use the normal approval controls.</p>}
    {error && <p role="alert" className="today-error">{error}</p>}
    <footer><button type="button" onClick={onClose}>Cancel</button><button className="button-primary" disabled={busy || (schedule && !parseCron(cron))}>{schedule ? 'Review schedule draft' : 'Run now'}</button></footer>
  </form></RoutineDialog>;
}

export function RoutineLibrary({ routines, teammates, source, onClearSource, onRefresh, onOpenThread, onOpenJob }: {
  routines: AssistantRoutine[]; teammates: Owner[]; source: AssistantTask | null; onClearSource: () => void;
  onRefresh: () => void; onOpenThread: (id: string) => void; onOpenJob: (job: Routine) => void;
}) {
  const [editor, setEditor] = useState<Editor | null>(null), [runner, setRunner] = useState<{ routine: AssistantRoutine; schedule: boolean } | null>(null);
  const [error, setError] = useState(''), [removing, setRemoving] = useState<string | null>(null);
  const invoke: Invoke = (action, payload) => window.ankita.invoke(action, payload);
  const remove = async (routine: AssistantRoutine) => {
    setRemoving(routine.id); setError('');
    try { await invoke(ASSISTANT_ACTIONS.routineRemove, { routineId: routine.id, ownerId: routine.ownerId }); onRefresh(); }
    catch (cause) { setError((cause as Error).message); } finally { setRemoving(null); }
  };
  return <section className="today-knowledge routine-library" aria-label="Saved routines"><div className="today-section-heading"><div><h2>Teach once, use again</h2><p>Save a finished request as a routine, then change only what you need.</p></div></div>
    {!routines.length && <p className="today-empty">Finish a request, then choose “Save as routine” beside its result.</p>}
    {error && <p role="alert" className="today-error">{error}</p>}
    <div className="routine-library-list">{routines.map(routine => {
      const owner = teammates.find(item => item.id === routine.ownerId);
      return <article key={routine.id}><small>{owner?.name || 'Conversation unavailable'}</small><h3>{routine.name}</h3><p>{routine.template}</p>
        <div className="today-task-actions"><button disabled={!owner} onClick={() => setRunner({ routine, schedule: false })}>Run routine</button><button disabled={!owner} onClick={() => setEditor({ routine })}>Edit routine</button><button disabled={!owner} onClick={() => setRunner({ routine, schedule: true })}>Schedule routine</button><button disabled={removing === routine.id} onClick={() => void remove(routine)}>Remove routine</button></div>
        <details><summary>Original result</summary><p>Saved {new Date(routine.sourceEvidence.at).toLocaleString()}. {routine.sourceEvidence.tools.length ? `Completed actions: ${routine.sourceEvidence.tools.join(', ')}.` : 'Saved from a completed reply.'}</p><button disabled={!owner} onClick={() => onOpenThread(routine.ownerId)}>Open source conversation</button></details>
      </article>;
    })}</div>
    {(source || editor) && <RoutineEditor key={source?.id || editor?.routine?.id} editor={source ? { source } : editor!} invoke={invoke} onSaved={onRefresh} onClose={() => { onClearSource(); setEditor(null); }} />}
    {runner && <RoutineRunner key={`${runner.routine.id}:${runner.schedule}`} {...runner} invoke={invoke} onRun={() => { onRefresh(); onOpenThread(runner.routine.ownerId); }} onSchedule={onOpenJob} onClose={() => setRunner(null)} />}
  </section>;
}
