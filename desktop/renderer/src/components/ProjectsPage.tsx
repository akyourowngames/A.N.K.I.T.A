import { useEffect, useState } from 'react';
import type { Project } from '../../../shared/wire';
import { Icon } from './Icons';
import { WindowControls } from './WindowControls';

type Draft = { name: string; summary: string; path: string; repo: string; client: string; conventions: string };
const blank = (): Draft => ({ name: '', summary: '', path: '', repo: '', client: '', conventions: '' });
const draftOf = (project: Project): Draft => ({ name: project.name, summary: project.summary, path: project.path, repo: project.repo, client: project.client, conventions: project.conventions.join('\n') });

export function ProjectsPage({ projects, selectedThread, chrome, sidebarOpen, onToggleSidebar, onRefresh, onAssign }: {
  projects: Project[]; selectedThread: { id: string; name: string; projectId: string | null } | null;
  chrome: string; sidebarOpen: boolean; onToggleSidebar: () => void; onRefresh: () => Promise<void>;
  onAssign: (projectId: string | null) => Promise<void>;
}) {
  const [id, setId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Draft>(blank);
  const [todo, setTodo] = useState('');
  const [record, setRecord] = useState('');
  const [recordKind, setRecordKind] = useState<'note' | 'decision'>('decision');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const project = projects.find(item => item.id === id) || null;
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
  const openProject = (next: Project) => { setId(next.id); setCreating(false); setEditing(false); setDraft(draftOf(next)); setError(''); };

  return <main className="projects-pane">
    <header className="projects-header drag-region"><div className="no-drag">{!sidebarOpen && <>{chrome === 'custom' && <WindowControls />}<button className="icon-button" onClick={onToggleSidebar} aria-label="Show sidebar" aria-expanded={false}><Icon name="panelLeft" size={18} /></button></>}<span>Projects</span></div><button className="projects-new no-drag" onClick={startNew}><Icon name="plus" size={15} /> New project</button></header>
    <div className="projects-layout">
      <nav className="projects-list" aria-label="Projects"><div className="projects-list-heading">Your work <span>{projects.length}</span></div>{projects.filter(item => !item.archived).map(item => <button key={item.id} className={item.id === id && !creating ? 'active' : ''} onClick={() => openProject(item)}><span className="project-list-mark">{item.name.slice(0, 1).toUpperCase()}</span><span><strong>{item.name}</strong><small>{item.summary || item.path || 'Add a description'}</small></span><span className="project-list-open">{item.todos.filter(task => !task.done).length || ''}</span></button>)}{!projects.length && <p>No projects yet. Create one to give teammates a workspace and shared context.</p>}</nav>
      <div className="project-detail-scroll"><div className="project-detail">
        {error && <div className="project-error" role="alert">{error}</div>}
        {creating || editing ? <form className="project-form" onSubmit={event => { event.preventDefault(); void save(); }}>
          <div className="project-heading"><span className="project-symbol"><Icon name="folder" size={21} /></span><h1>{creating ? 'New project' : 'Project details'}</h1><p>Keep the path, context, and decisions together for every teammate assigned here.</p></div>
          <label>Project name<input autoFocus required maxLength={80} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} placeholder="Name this work" /></label>
          <label>What is it?<textarea rows={3} maxLength={400} value={draft.summary} onChange={event => setDraft({ ...draft, summary: event.target.value })} placeholder="A sentence teammates can carry into each conversation" /></label>
          <label>Working folder<input value={draft.path} onChange={event => setDraft({ ...draft, path: event.target.value })} placeholder="C:\\path\\to\\project" /><small>Commands and file tools run from this folder when the path exists.</small></label>
          <div className="project-form-pair"><label>Repository<input value={draft.repo} onChange={event => setDraft({ ...draft, repo: event.target.value })} placeholder="Optional repository URL" /></label><label>Client<input value={draft.client} onChange={event => setDraft({ ...draft, client: event.target.value })} placeholder="Optional" /></label></div>
          <label>Conventions<textarea rows={4} value={draft.conventions} onChange={event => setDraft({ ...draft, conventions: event.target.value })} placeholder="One working rule per line" /><small>Up to five rules appear in the teammate’s project brief.</small></label>
          <div className="project-form-actions"><button type="button" onClick={() => { setCreating(false); setEditing(false); setError(''); }}>Cancel</button><button className="button-primary" disabled={busy || !draft.name.trim()} type="submit">{busy ? 'Saving…' : creating ? 'Create project' : 'Save changes'}</button></div>
        </form> : project ? <>
          <div className="project-heading"><span className="project-symbol">{project.name.slice(0, 1).toUpperCase()}</span><div className="project-heading-row"><h1>{project.name}</h1><button onClick={() => { setDraft(draftOf(project)); setEditing(true); }}><Icon name="edit" size={15} /> Edit</button></div><p>{project.summary || 'Add a short description so teammates know what this project is for.'}</p></div>
          <div className="project-facts">{project.path && <div><span>Working folder</span><code>{project.path}</code></div>}{project.repo && <div><span>Repository</span><code>{project.repo}</code></div>}{project.client && <div><span>Client</span><strong>{project.client}</strong></div>}{!project.path && <div><span>Working folder</span><em>No folder set yet</em></div>}</div>
          {selectedThread && <div className="project-assignment"><div><strong>{selectedThread.name}</strong><span>{selectedThread.projectId === project.id ? 'Works in this project' : 'Assign this teammate to this project'}</span></div><button disabled={busy} onClick={() => void onAssign(selectedThread.projectId === project.id ? null : project.id)}>{selectedThread.projectId === project.id ? 'Unassign' : 'Assign teammate'}</button></div>}
          {project.conventions.length > 0 && <section className="project-section"><h2>Working rules</h2><ul className="project-rules">{project.conventions.map((rule, index) => <li key={index}>{rule}</li>)}</ul></section>}
          <section className="project-section"><h2>Open tasks <span>{project.todos.filter(item => !item.done).length}</span></h2><form className="project-add-todo" onSubmit={async event => { event.preventDefault(); if (todo.trim() && await run('addProjectTodo', { id: project.id, text: todo.trim() })) setTodo(''); }}><input aria-label="New project task" value={todo} onChange={event => setTodo(event.target.value)} placeholder="Add a task worth remembering" /><button disabled={!todo.trim() || busy} type="submit"><Icon name="plus" size={16} /></button></form><div className="project-tasks">{project.todos.filter(item => !item.done).map(item => <div key={item.id}><button aria-label={`Complete ${item.text}`} onClick={() => void run('completeProjectTodo', { id: project.id, ref: item.id })}><Icon name="check" size={13} /></button><span>{item.text}</span></div>)}{!project.todos.some(item => !item.done) && <p>No open tasks recorded.</p>}</div></section>
          <section className="project-section"><h2>Record context</h2><div className="project-record-controls"><select aria-label="Record type" value={recordKind} onChange={event => setRecordKind(event.target.value as 'note' | 'decision')}><option value="decision">Decision</option><option value="note">Note</option></select><form onSubmit={async event => { event.preventDefault(); if (record.trim() && await run('addProjectRecord', { id: project.id, kind: recordKind, text: record.trim() })) setRecord(''); }}><input aria-label={`New ${recordKind}`} value={record} onChange={event => setRecord(event.target.value)} placeholder={recordKind === 'decision' ? 'What did you decide?' : 'What should the team remember?'} /><button type="submit" disabled={!record.trim() || busy}>Save</button></form></div></section>
          {project.decisions.length > 0 && <section className="project-section"><h2>Decisions</h2><div className="project-records">{[...project.decisions].reverse().map((item, index) => <p key={index}>{item.text}</p>)}</div></section>}
          {project.notes.length > 0 && <section className="project-section"><h2>Notes</h2><div className="project-records">{[...project.notes].reverse().map((item, index) => <p key={index}>{item.text}</p>)}</div></section>}
        </> : <div className="project-blank"><span className="project-symbol"><Icon name="folder" size={24} /></span><h1>Give the work a home.</h1><p>Choose a project or create one to keep its folder, decisions, and open tasks close to the conversation.</p><button className="button-primary" onClick={startNew}>Create project</button></div>}
      </div></div>
    </div>
  </main>;
}
