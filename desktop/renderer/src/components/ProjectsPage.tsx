import { useEffect, useState, type KeyboardEvent } from 'react';
import type { Project } from '../../../shared/wire';
import { Icon } from './Icons';
import { WindowControls } from './WindowControls';
import { TeammateAvatar } from './TeammateAvatar';

type Draft = { name: string; summary: string; path: string; repo: string; client: string; conventions: string };
const blank = (): Draft => ({ name: '', summary: '', path: '', repo: '', client: '', conventions: '' });
const draftOf = (project: Project): Draft => ({ name: project.name, summary: project.summary, path: project.path, repo: project.repo, client: project.client, conventions: project.conventions.join('\n') });
const sections = ['Overview', 'Tasks', 'Context'] as const;
type Section = typeof sections[number];
type ProjectInput = { todo: string; record: string; kind: 'note' | 'decision' };
const emptyInput: ProjectInput = { todo: '', record: '', kind: 'decision' };
const recordKinds = ['decision', 'note'] as const;
const openTaskLabel = (count: number) => `${count} open ${count === 1 ? 'task' : 'tasks'}`;
const recordCountLabel = (count: number) => `${count} ${count === 1 ? 'record' : 'records'}`;
function recordDate(at: string) {
  const date = new Date(at);
  return Number.isFinite(date.getTime()) ? date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' }) : '';
}

export function ProjectsPage({ projects, selectedThread, chrome, sidebarOpen, onToggleSidebar, onRefresh, onAssign }: {
  projects: Project[]; selectedThread: { id: string; name: string; projectId: string | null } | null;
  chrome: string; sidebarOpen: boolean; onToggleSidebar: () => void; onRefresh: () => Promise<void>;
  onAssign: (projectId: string | null) => Promise<void>;
}) {
  const [id, setId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(blank);
  const [section, setSection] = useState<Section>('Overview');
  const [inputs, setInputs] = useState<Record<string, ProjectInput>>({});
  const [contextFilter, setContextFilter] = useState<'all' | 'note' | 'decision'>('all');
  const [query, setQuery] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const project = projects.find(item => item.id === id) || null;
  const input = project ? inputs[project.id] || emptyInput : emptyInput;
  const setInput = (projectId: string, patch: Partial<ProjectInput>) => setInputs(current => ({ ...current, [projectId]: { ...(current[projectId] || emptyInput), ...patch } }));
  const clearSubmitted = (projectId: string, field: 'todo' | 'record', value: string) => setInputs(current => {
    const saved = current[projectId];
    return saved?.[field] === value ? { ...current, [projectId]: { ...saved, [field]: '' } } : current;
  });
  const openTasks = project?.todos.filter(task => !task.done) || [];
  const doneTasks = project?.todos.filter(task => task.done) || [];
  const context = project ? recordKinds.flatMap(kind => project[kind === 'note' ? 'notes' : 'decisions'].map((item, index) => ({ ...item, kind, key: `${kind}-${index}` }))).sort((a, b) => b.at.localeCompare(a.at)) : [];
  const shownContext = context.filter(item => (contextFilter === 'all' || item.kind === contextFilter) && item.text.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const liveProjects = projects.filter(item => !item.archived);
  useEffect(() => { if (!creating && !projects.some(item => item.id === id)) setId(projects[0]?.id || null); }, [projects, id, creating]);
  useEffect(() => { if (project && !editing) setDraft(draftOf(project)); }, [project?.id, editing]);

  const run = async (action: string, payload: unknown) => {
    setBusy(true); setError('');
    try { await window.ankita.invoke(action, payload); await onRefresh(); return true; }
    catch (err) { setError(err instanceof Error ? err.message : String(err)); return false; }
    finally { setBusy(false); }
  };
  const save = async () => {
    const input = { name: draft.name.trim(), summary: draft.summary.trim(), path: draft.path.trim(), repo: draft.repo.trim(), client: draft.client.trim(), conventions: draft.conventions.split('\n').map(line => line.trim()).filter(Boolean) };
    if (!input.name) return;
    const action = creating ? 'createProject' : 'updateProject';
    const payload = creating ? input : { id: project!.id, patch: input };
    setBusy(true); setError('');
    try {
      const saved = await window.ankita.invoke<Project>(action, payload);
      await onRefresh(); setId(saved.id); setCreating(false); setEditing(false);
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  };
  const startNew = () => { setCreating(true); setEditing(true); setDraft(blank()); setError(''); };
  const openProject = (next: Project) => { setId(next.id); setCreating(false); setEditing(false); setDraft(draftOf(next)); setError(''); setQuery(''); };
  const tabKey = (event: KeyboardEvent<HTMLButtonElement>, active: Section) => {
    const direction = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
    if (!direction && event.key !== 'Home' && event.key !== 'End') return;
    event.preventDefault();
    const next = event.key === 'Home' ? sections[0] : event.key === 'End' ? sections.at(-1)! : sections[(sections.indexOf(active) + direction + sections.length) % sections.length];
    setSection(next); document.getElementById(`project-tab-${next}`)?.focus();
  };

  return <main className="projects-pane">
    <header className="projects-header drag-region"><div className="no-drag">{!sidebarOpen && <>{chrome === 'custom' && <WindowControls />}<button className="icon-button" onClick={onToggleSidebar} aria-label="Show sidebar" aria-expanded={false}><Icon name="panelLeft" size={18} /></button></>}<span>Projects</span></div><button className="projects-new no-drag" onClick={startNew}><Icon name="plus" size={15} /> New project</button></header>
    <div className="projects-layout">
      <nav className="projects-list" aria-label="Projects"><div className="projects-list-heading">Your projects <span>{liveProjects.length}</span></div>{liveProjects.map(item => <button key={item.id} title={item.name} aria-label={item.name} aria-current={item.id === id && !creating ? 'page' : undefined} className={item.id === id && !creating ? 'active' : ''} onClick={() => openProject(item)}><span className="project-list-mark"><Icon name="folder" size={16} /></span><span><strong>{item.name}</strong><small>{openTaskLabel(item.todos.filter(task => !task.done).length)}</small></span><Icon name="chevron" size={12} /></button>)}{!liveProjects.length && <p>Create a project to keep its workspace and team context together.</p>}</nav>
      <div className="project-detail-scroll"><div className="project-detail">
        {error && <div className="project-error" role="alert">{error}</div>}
        {creating || editing ? <form className="project-form" onSubmit={event => { event.preventDefault(); void save(); }}>
          <div className="project-heading"><span className="project-symbol"><Icon name="folder" size={21} /></span><h1>{creating ? 'New project' : 'Project details'}</h1><p>Keep the path, context, and decisions together for every teammate assigned here.</p></div>
          <label>Project name<input autoFocus required maxLength={80} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} placeholder="Name this work" /></label>
          <label>What is it?<textarea rows={3} maxLength={400} value={draft.summary} onChange={event => setDraft({ ...draft, summary: event.target.value })} placeholder="A sentence teammates can carry into each conversation" /></label>
          <label>Working folder<input value={draft.path} onChange={event => setDraft({ ...draft, path: event.target.value })} placeholder="Path to your workspace" /><small>Commands and file tools run from this folder when the path exists.</small></label>
          <div className="project-form-pair"><label>Repository<input value={draft.repo} onChange={event => setDraft({ ...draft, repo: event.target.value })} placeholder="Optional repository URL" /></label><label>Client<input value={draft.client} onChange={event => setDraft({ ...draft, client: event.target.value })} placeholder="Optional" /></label></div>
          <label>Conventions<textarea rows={4} value={draft.conventions} onChange={event => setDraft({ ...draft, conventions: event.target.value })} placeholder="One working rule per line" /><small>Up to five rules appear in the teammate’s project brief.</small></label>
          <div className="project-form-actions"><button type="button" onClick={() => { setCreating(false); setEditing(false); setError(''); }}>Cancel</button><button className="button-primary" disabled={busy || !draft.name.trim()} type="submit">{busy ? 'Saving…' : creating ? 'Create project' : 'Save changes'}</button></div>
        </form> : project ? <>
          <div className="project-heading project-workspace-heading"><span className="project-symbol"><Icon name="folder" size={22} /></span><div className="project-heading-row"><div><small className="section-eyebrow">Project workspace</small><h1>{project.name}</h1></div><button aria-label="Edit project" onClick={() => { setDraft(draftOf(project)); setEditing(true); }}><Icon name="edit" size={15} /> Edit</button></div><p>{project.summary || 'Add a description to introduce this project to the team.'}</p></div>
          <div className="project-tabs" role="tablist" aria-label="Project sections">{sections.map(item => <button type="button" role="tab" key={item} id={`project-tab-${item}`} aria-controls="project-section-panel" aria-selected={section === item} tabIndex={section === item ? 0 : -1} onKeyDown={event => tabKey(event, item)} onClick={() => setSection(item)}>{item}{item !== 'Overview' && <span aria-hidden="true">{item === 'Tasks' ? openTasks.length : context.length}</span>}</button>)}</div>
          <div className="project-tab-content" key={`${project.id}-${section}`} id="project-section-panel" role="tabpanel" aria-labelledby={`project-tab-${section}`}>
            {section === 'Overview' && <>
              <section className="project-overview-section"><div className="section-heading"><Icon name="folder" size={16} /><h2>Workspace</h2></div><dl className="project-workspace-facts"><div><dt>Working folder</dt><dd>{project.path ? <code>{project.path}</code> : <span>No folder set</span>}</dd></div>{project.repo && <div><dt>Repository</dt><dd><code>{project.repo}</code></dd></div>}{project.client && <div><dt>Client</dt><dd>{project.client}</dd></div>}</dl></section>
              {selectedThread && <div className="project-team-row"><TeammateAvatar id={selectedThread.id} /><div><strong>{selectedThread.name}</strong><small>{selectedThread.projectId === project.id ? 'Assigned to this workspace' : 'Bring this teammate into the project'}</small></div><button className="section-secondary" disabled={busy} onClick={() => void onAssign(selectedThread.projectId === project.id ? null : project.id)}>{selectedThread.projectId === project.id ? 'Unassign' : 'Assign teammate'}</button></div>}
              <section className="project-overview-section"><div className="section-heading"><Icon name="check" size={16} /><h2>Working rules</h2><span>{project.conventions.length}</span></div>{project.conventions.length ? <ol className="project-rule-list">{project.conventions.map((rule, index) => <li key={index}><span>{String(index + 1).padStart(2, '0')}</span><p>{rule}</p></li>)}</ol> : <p className="section-muted">Add working rules in project details to guide the team.</p>}</section>
              <div className="project-shortcuts"><button onClick={() => setSection('Tasks')}><Icon name="check" size={17} /><span><strong>{openTaskLabel(openTasks.length)}</strong><small>Keep the next steps in view</small></span><Icon name="arrowRight" size={16} /></button><button onClick={() => setSection('Context')}><Icon name="chat" size={17} /><span><strong>{recordCountLabel(context.length)} saved</strong><small>Notes & decisions for the team</small></span><Icon name="arrowRight" size={16} /></button></div>
            </>}
            {section === 'Tasks' && <>
              <div className="section-heading"><h2>Next steps</h2><span>{openTasks.length} open</span></div><p className="section-muted">Tasks stay with this project across conversations.</p>
              <form className="project-task-compose" onSubmit={async event => { event.preventDefault(); if (input.todo.trim() && await run('addProjectTodo', { id: project.id, text: input.todo.trim() })) clearSubmitted(project.id, 'todo', input.todo); }}><Icon name="plus" size={17} /><input aria-label="New project task" value={input.todo} onChange={event => setInput(project.id, { todo: event.target.value })} placeholder="What needs to happen next?" /><button className="section-primary" disabled={!input.todo.trim() || busy} type="submit">Add task</button></form>
              <div className="project-task-list">{openTasks.map(item => <div key={item.id}><button disabled={busy} aria-label={`Complete ${item.text}`} onClick={() => void run('completeProjectTodo', { id: project.id, ref: item.id })}><Icon name="check" size={13} /></button><span>{item.text}</span></div>)}</div>
              {!openTasks.length && <div className="section-empty"><Icon name="check" size={24} /><h3>All clear here</h3><p>Add a task when there’s a next step to remember.</p></div>}
              {doneTasks.length > 0 && <details className="project-completed"><summary>Completed <span>{doneTasks.length}</span><Icon name="chevron" size={14} /></summary>{doneTasks.map(item => <div key={item.id}><Icon name="check" size={14} /><span>{item.text}</span></div>)}</details>}
            </>}
            {section === 'Context' && <>
              <div className="section-heading"><h2>Team memory</h2><span>{recordCountLabel(context.length)}</span></div><p className="section-muted">Keep decisions and useful details close to the work.</p>
              <form className="project-context-compose" onSubmit={async event => { event.preventDefault(); if (input.record.trim() && await run('addProjectRecord', { id: project.id, kind: input.kind, text: input.record.trim() })) clearSubmitted(project.id, 'record', input.record); }}><div className="project-record-kind" aria-label="Record type">{recordKinds.map(kind => <button type="button" key={kind} aria-pressed={input.kind === kind} onClick={() => setInput(project.id, { kind })}>{kind === 'decision' ? 'Decision' : 'Note'}</button>)}</div><textarea aria-label={`New ${input.kind}`} rows={3} value={input.record} onChange={event => setInput(project.id, { record: event.target.value })} placeholder={input.kind === 'decision' ? 'What did you decide, and why?' : 'What should the team remember?'} /><div className="project-context-compose-foot"><small>Shared with teammates in this project</small><button className="section-primary" type="submit" disabled={!input.record.trim() || busy}>{busy ? 'Saving…' : 'Save context'}</button></div></form>
              <div className="project-context-toolbar"><div>{(['all', ...recordKinds] as const).map(kind => <button key={kind} aria-pressed={contextFilter === kind} onClick={() => setContextFilter(kind)}>{kind === 'all' ? 'All' : kind === 'decision' ? 'Decisions' : 'Notes'}</button>)}</div><label><Icon name="search" size={14} /><input aria-label="Search project context" placeholder="Find in context" value={query} onChange={event => setQuery(event.target.value)} /></label></div>
              <div className="project-context-records">{shownContext.map(item => <details key={item.key}><summary><span className={`context-record-mark ${item.kind}`}><Icon name={item.kind === 'decision' ? 'check' : 'chat'} size={14} /></span><span className="context-record-copy"><small>{item.kind === 'decision' ? 'Decision' : 'Note'}<time dateTime={item.at}>{recordDate(item.at)}</time></small><span>{item.text}</span></span><Icon name="chevron" size={14} /></summary><div className="context-record-body">{item.text}</div></details>)}</div>
              {!shownContext.length && <div className="section-empty"><Icon name="chat" size={24} /><h3>{context.length ? 'No matching context' : 'Start the shared memory'}</h3><p>{context.length ? 'Try another search or filter.' : 'Save a note or decision above for the team.'}</p></div>}
            </>}
          </div>
        </> : <div className="project-blank"><span className="project-symbol"><Icon name="folder" size={24} /></span><h1>Give the work a home.</h1><p>Choose a project or create one to keep its folder, decisions, and open tasks close to the conversation.</p><button className="button-primary" onClick={startNew}>Create project</button></div>}
      </div></div>
    </div>
  </main>;
}
