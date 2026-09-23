import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type { ChatMessage, DesktopPreferences, DesktopSettingsResult, MenuCommand, Model, Project, Teammate, UpdateEvent } from '../../shared/wire';
import { reducer, initialState } from './state/store';
import { Sidebar } from './components/Sidebar';
import { ChatPane } from './components/ChatPane';
import { ApprovalDialog } from './components/ApprovalDialog';
import { TeammateDialog } from './components/TeammateDialog';
import { ConfirmDialog } from './components/ConfirmDialog';
import { UpdateBanner } from './components/UpdateBanner';
import { SettingsDialog, type SettingsTab } from './components/SettingsDialog';
import { PluginsPage } from './components/PluginsPage';
import { ProjectsPage } from './components/ProjectsPage';
import { WorkspacePanel } from './components/WorkspacePanel';
import { Icon } from './components/Icons';

type Bootstrap = { teammates: Teammate[]; models: Model[]; settings: { username: string; provider: string; model: string; tools: string[] }; preferences?: DesktopPreferences; version?: string; chrome: string };
type UiState = { selectedId?: string | null; sidebarWidth?: number; sidebarOpen?: boolean };

const UI_KEY = 'ankita.ui';

function loadUi(): UiState {
  try { return JSON.parse(localStorage.getItem(UI_KEY) || '{}'); } catch { return {}; }
}

function saveUi(patch: UiState) {
  try { localStorage.setItem(UI_KEY, JSON.stringify({ ...loadUi(), ...patch })); } catch { /* storage disabled */ }
}

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const initialUi = useMemo(loadUi, []);
  const [search, setSearch] = useState('');
  const [dialog, setDialog] = useState<'create' | 'edit' | null>(null);
  const [confirm, setConfirm] = useState<{ action: 'clear' | 'delete'; id: string; name: string } | null>(null);
  const [settingsTab, setSettingsTab] = useState<SettingsTab | null>(null);
  const [view, setView] = useState<'chat' | 'plugins' | 'projects'>('chat');
  const [projects, setProjects] = useState<Project[]>([]);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [workspaceRevision, setWorkspaceRevision] = useState(0);
  const [toolsRevision, setToolsRevision] = useState(0);
  const [preferences, setPreferences] = useState<DesktopPreferences>({ provider: 'copilot', model: '', customApiBase: '', appearance: 'graphite', contextWindow: 0, maxTokens: 0, hasCustomApiKey: false, hasGroqKey: false, hasKiloKey: false, hasComposioKey: false });
  const [version, setVersion] = useState('2.1.1');
  const closeSettings = useCallback(() => setSettingsTab(null), []);
  const [sidebarOpen, setSidebarOpen] = useState(initialUi.sidebarOpen !== false);
  const [sidebarWidth, setSidebarWidth] = useState(initialUi.sidebarWidth && initialUi.sidebarWidth >= 236 ? initialUi.sidebarWidth : 292);
  const [update, setUpdate] = useState<UpdateEvent | null>(null);
  const manualCheck = useRef(false);
  const selectedIdRef = useRef<string | null>(null);
  const projectsRequest = useRef(0);
  const refreshProjects = useCallback(async () => {
    const request = ++projectsRequest.current;
    const next = await window.ankita.invoke<Project[]>('listProjects');
    if (request === projectsRequest.current) setProjects(next);
  }, []);

  useEffect(() => { saveUi({ sidebarOpen }); }, [sidebarOpen]);
  useEffect(() => { saveUi({ sidebarWidth }); }, [sidebarWidth]);
  useEffect(() => { document.documentElement.dataset.theme = preferences.appearance; }, [preferences.appearance]);
  useEffect(() => { selectedIdRef.current = state.selectedId; }, [state.selectedId]);

  useEffect(() => {
    if (!window.ankita) { dispatch({ type: 'event', event: { type: 'error', threadId: null, message: 'Open Ankita with npm run desktop:dev or npm run desktop:start.' } }); return; }
    const unsubscribe = window.ankita.onEvent(event => {
      dispatch({ type: 'event', event });
      if (event.type === 'settings-updated') setPreferences(event.preferences);
      if (event.type === 'teammates-changed') void window.ankita.invoke<Teammate[]>('listTeammates').then(teammates => dispatch({ type: 'teammates-loaded', teammates }));
      if (event.type === 'projects-changed') void refreshProjects();
      if (event.type === 'tools-changed') setToolsRevision(value => value + 1);
      if (event.type === 'workspace-changed' && event.threadId === selectedIdRef.current) { setWorkspaceRevision(value => value + 1); if (event.open) setReviewOpen(true); }
    });
    void window.ankita.invoke<Bootstrap>('initialize')
      .then(data => { dispatch({ type: 'bootstrap', ...data, selectedId: loadUi().selectedId ?? null }); if (data.preferences) setPreferences(data.preferences); if (data.version) setVersion(data.version); void refreshProjects(); })
      .catch(err => dispatch({ type: 'event', event: { type: 'error', threadId: null, message: err.message } }));
    return unsubscribe;
  }, [refreshProjects]);

  useEffect(() => {
    if (!state.selectedId || !window.ankita) return;
    const id = state.selectedId;
    saveUi({ selectedId: id });
    void window.ankita.invoke<ChatMessage[]>('loadThread', { id }).then(messages => dispatch({ type: 'thread-loaded', id, messages })).catch(err => dispatch({ type: 'event', event: { type: 'error', threadId: id, message: err.message } }));
  }, [state.selectedId]);

  useEffect(() => {
    if (!state.error) return;
    const timer = setTimeout(() => dispatch({ type: 'dismiss-error' }), 7000);
    return () => clearTimeout(timer);
  }, [state.error]);

  useEffect(() => {
    const unread = state.teammates.filter(t => state.unread[t.id] && t.id !== state.selectedId).length;
    document.title = unread ? `(${unread}) Ankita` : 'Ankita';
  }, [state.unread, state.selectedId, state.teammates]);

  useEffect(() => {
    if (!window.ankita?.onMenuCommand) return;
    return window.ankita.onMenuCommand((command: MenuCommand) => {
      if (command === 'new-teammate') setDialog('create');
      else if (command === 'settings') setSettingsTab('model');
      else if (command === 'about') setSettingsTab('about');
      else if (command === 'toggle-sidebar') setSidebarOpen(open => !open);
      else if (command === 'find') {
        setSidebarOpen(true);
        requestAnimationFrame(() => document.querySelector<HTMLInputElement>('.search-box input')?.focus());
      }
    });
  }, []);

  useEffect(() => {
    if (!window.ankita?.onUpdateEvent) return;
    return window.ankita.onUpdateEvent(event => {
      if (event.type === 'checking' && event.manual) manualCheck.current = true;
      const manual = manualCheck.current;
      // Background checks stay quiet unless there is something to act on.
      if (!manual && (event.type === 'checking' || event.type === 'current' || event.type === 'unsupported' || event.type === 'error')) return;
      if (event.type === 'current' || event.type === 'unsupported' || event.type === 'error' || event.type === 'downloaded') manualCheck.current = false;
      setUpdate(event);
    });
  }, []);

  useEffect(() => {
    if (!update) return;
    if (update.type === 'current' || update.type === 'unsupported' || update.type === 'error') {
      const timer = setTimeout(() => setUpdate(null), 6000);
      return () => clearTimeout(timer);
    }
  }, [update]);

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      const name = event.key.toLowerCase();
      if (name === 'n') { event.preventDefault(); setDialog('create'); }
      if (name === 'k') { event.preventDefault(); if (view === 'plugins') requestAnimationFrame(() => document.querySelector<HTMLInputElement>('.plugins-search input')?.focus()); else { setSidebarOpen(true); requestAnimationFrame(() => document.querySelector<HTMLInputElement>('.search-box input')?.focus()); } }
      if (name === 'b') { event.preventDefault(); setSidebarOpen(open => !open); }
      if (event.key === ',') { event.preventDefault(); setSettingsTab('model'); }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [view]);

  const selected = state.teammates.find(t => t.id === state.selectedId) || null;
  const send = useCallback((text: string) => {
    if (!state.selectedId || !window.ankita) return;
    void window.ankita.invoke('send', { id: state.selectedId, text }).catch(err => dispatch({ type: 'event', event: { type: 'error', threadId: state.selectedId, message: err.message } }));
  }, [state.selectedId]);
  const stop = () => { if (state.selectedId) void window.ankita.invoke('cancel', { id: state.selectedId }); };
  const answer = useCallback((choice: 'yes' | 'no' | 'always') => {
    const approval = state.approvals[0];
    if (!approval) return;
    void window.ankita.invoke('respondApproval', { requestId: approval.requestId, answer: choice })
      .then(() => dispatch({ type: 'approval-dismissed', requestId: approval.requestId }))
      .catch(err => dispatch({ type: 'event', event: { type: 'error', threadId: approval.threadId, message: err.message } }));
  }, [state.approvals]);
  const saveTeammate = (input: { name: string; persona: string; color: string; emoji: string; projectId: string | null }) => {
    const action = dialog === 'edit' && selected ? 'updateTeammate' : 'createTeammate';
    const payload = action === 'updateTeammate' ? { id: selected?.id, patch: input } : input;
    void window.ankita.invoke<Teammate>(action, payload).then(item => { dispatch({ type: 'select', id: item.id }); setView('chat'); setDialog(null); }).catch(err => dispatch({ type: 'event', event: { type: 'error', threadId: null, message: err.message } }));
  };
  const clear = () => { if (selected) setConfirm({ action: 'clear', id: selected.id, name: selected.name }); };
  const remove = () => { if (selected) setConfirm({ action: 'delete', id: selected.id, name: selected.name }); };
  const confirmAction = () => {
    if (!confirm) return;
    const { action, id } = confirm;
    setConfirm(null);
    void window.ankita.invoke(action === 'clear' ? 'clearThread' : 'deleteTeammate', { id }).catch(err => dispatch({ type: 'event', event: { type: 'error', threadId: id, message: err.message } }));
  };
  const model = (modelId: string) => { if (selected) void window.ankita.invoke('setModel', { id: selected.id, modelId }).catch(err => dispatch({ type: 'event', event: { type: 'error', threadId: selected.id, message: err.message } })); };
  const assignProject = useCallback(async (projectId: string | null) => {
    if (!state.selectedId) return;
    try {
      await window.ankita.invoke('assignProject', { id: state.selectedId, projectId });
      const teammates = await window.ankita.invoke<Teammate[]>('listTeammates');
      dispatch({ type: 'teammates-loaded', teammates });
      setWorkspaceRevision(value => value + 1);
    } catch (err) { dispatch({ type: 'event', event: { type: 'error', threadId: state.selectedId, message: err instanceof Error ? err.message : String(err) } }); }
  }, [state.selectedId]);
  const installUpdate = () => { void window.ankita.updateAction('install'); };
  const dismissUpdate = () => setUpdate(null);

  return <div className={`app-shell ${reviewOpen && view === 'chat' && state.selectedId ? 'review-visible' : ''}`}>
    <Sidebar
      teammates={state.teammates} selectedId={state.selectedId} search={search} onSearch={setSearch}
      onSelect={id => { setView('chat'); dispatch({ type: 'select', id }); }} onCreate={() => { setView('chat'); setDialog('create'); }} onOpenSettings={() => setSettingsTab('model')}
      onOpenPlugins={() => setView('plugins')} pluginsOpen={view === 'plugins'} onOpenProjects={() => setView('projects')} projectsOpen={view === 'projects'}
      provider={state.settings?.provider || 'Copilot'} model={state.settings?.model || ''} phase={state.phase}
      chrome={state.chrome} unread={state.unread} toolsCount={state.settings?.tools.length || 0}
      width={sidebarWidth} collapsed={!sidebarOpen} onCollapse={() => setSidebarOpen(false)} onResize={setSidebarWidth}
    />
    {view === 'plugins' ? <PluginsPage chrome={state.chrome} sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen(open => !open)} onOpenSettings={() => setSettingsTab('providers')} hasComposioKey={preferences.hasComposioKey} toolsRevision={toolsRevision} /> : view === 'projects' ? <ProjectsPage projects={projects} selectedThread={selected} chrome={state.chrome} sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen(open => !open)} onRefresh={refreshProjects} onAssign={assignProject} /> : <ChatPane
      teammate={selected} messages={state.selectedId ? state.threads[state.selectedId] || [] : []}
      running={Boolean(state.selectedId && state.running[state.selectedId])}
      models={state.models} projects={projects} defaultModel={state.settings?.model || ''}
      usage={state.selectedId ? state.usage[state.selectedId] : undefined}
      chrome={state.chrome} sidebarOpen={sidebarOpen} reviewOpen={reviewOpen} onToggleSidebar={() => setSidebarOpen(open => !open)} onToggleReview={() => setReviewOpen(open => !open)} onProject={id => void assignProject(id)} onOpenProjects={() => setView('projects')}
      onSend={send} onStop={stop} onModel={model} onEdit={() => setDialog('edit')} onClear={clear} onDelete={remove}
    />}
    {view === 'chat' && state.selectedId && <WorkspacePanel threadId={state.selectedId} revision={workspaceRevision} visible={reviewOpen} onClose={() => setReviewOpen(false)} />}
    {dialog && <TeammateDialog teammate={dialog === 'edit' ? selected : null} projects={projects} onSave={saveTeammate} onClose={() => setDialog(null)} />}
    {confirm && <ConfirmDialog action={confirm.action} name={confirm.name} onCancel={() => setConfirm(null)} onConfirm={confirmAction} />}
    {settingsTab && <SettingsDialog tab={settingsTab} onTab={setSettingsTab} onClose={closeSettings} preferences={preferences} models={state.models} teammates={state.teammates} version={version} onSaved={(result: DesktopSettingsResult) => { setPreferences(result.preferences); dispatch({ type: 'event', event: { type: 'settings-updated', ...result } }); }} />}
    {state.approvals[0] && <ApprovalDialog approval={state.approvals[0]} onAnswer={answer} />}
    {state.deviceCode && <div className="modal-backdrop"><div className="auth-dialog" role="dialog" aria-modal="true"><div className="modal-symbol"><Icon name="external" size={22} /></div><h2>Connect to GitHub</h2><p>Open the verification page and enter this code to connect your Copilot account.</p><div className="device-code">{state.deviceCode.user_code}</div><button className="button-primary" onClick={() => void window.ankita.openExternal(state.deviceCode!.verification_uri)}>Open GitHub <Icon name="external" size={15} /></button><small>Waiting for authorization…</small></div></div>}
    {update && <UpdateBanner update={update} onInstall={installUpdate} onDismiss={dismissUpdate} />}
    {state.error && <div className="error-toast" role="alert"><Icon name="alert" size={18} /><span>{state.error}</span><button onClick={() => dispatch({ type: 'dismiss-error' })} aria-label="Dismiss error"><Icon name="close" size={16} /></button></div>}
  </div>;
}
