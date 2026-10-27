import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';
import type { BrowserSessionView, ChatMessage, DesktopPreferences, DesktopSettingsResult, MenuCommand, Model, Project, Teammate, UpdateEvent, Routine } from '../../shared/wire';
import { reducer, initialState } from './state/store';
import { Sidebar } from './components/Sidebar';
import { ChatPane } from './components/ChatPane';
import { ApprovalDialog } from './components/ApprovalDialog';
import { TeammateDialog } from './components/TeammateDialog';
import { ConfirmDialog } from './components/ConfirmDialog';
import { UpdateBanner } from './components/UpdateBanner';
import { VersionMismatchNotice } from './components/VersionMismatchNotice';
import { SettingsDialog, type SettingsTab } from './components/SettingsDialog';
import { OnboardingDialog } from './components/OnboardingDialog';
import { PluginsPage } from './components/PluginsPage';
import { ProjectsPage } from './components/ProjectsPage';
import { WorkspacePanel } from './components/WorkspacePanel';
import { SubagentPanel } from './components/SubagentPanel';
import { activityFromReceipt } from '../../shared/subagent-state.mjs';
import type { SubagentActivity } from '../../shared/subagent-state.mjs';
import { BrowserStage } from './components/BrowserStage';
import { BROWSER_PREVIEW_POLL, publicBrowserView } from '../../shared/browser-progress.mjs';
import { SecureStoreProvider } from './components/SecureStore';
import { Icon } from './components/Icons';
import { NoticeCard } from './components/NoticeCard';
import { describeErrorNotice } from '../../shared/error-notices.mjs';
import { IPC_CONTRACT, checkCompat } from '../../shared/version.mjs';
import { RoutineSheet } from './components/RoutineSheet';
import { JobsPanel } from './components/JobsPanel';
import { PaletteModal } from './components/PaletteModal';
import { CAPTURE_UI_EVENTS } from '../../browser-helper/protocol.mjs';
import { COMPOSE_EVENT, sidebarWidth as normalizeSidebarWidth } from '../../shared/desktop-layout.mjs';
import { DESKTOP_ACTIONS } from '../../../src/palette/index.mjs';

type Bootstrap = { teammates: Teammate[]; models: Model[]; settings: { username: string; provider: string; model: string; tools: string[] }; preferences?: DesktopPreferences; version?: string; contract?: number; chrome: string; jobs: Routine[] };
type UiState = { selectedId?: string | null; sidebarWidth?: number; sidebarOpen?: boolean };

const UI_KEY = 'ankita.ui';
const TRANSIENT_NOTICE_MS = 6000; // ms — how long a confirmation notice stays before fading out

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
  const [pluginsSection, setPluginsSection] = useState<'apps' | 'skills'>('apps');
  const [projects, setProjects] = useState<Project[]>([]);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [subagentFocus, setSubagentFocus] = useState<string | null>(null);
  const [subagentOpen, setSubagentOpen] = useState(false);
  const [browserOpen, setBrowserOpen] = useState(false);
  const [browserView, setBrowserView] = useState<BrowserSessionView | null>(null);
  const [browserThreadId, setBrowserThreadId] = useState<string | null>(null);
  const [browserScope, setBrowserScope] = useState<string | null>(null);
  const browserScopeRef = useRef<string | null>(null);
  const [jobSheet, setJobSheet] = useState<{ id?: string; advanced?: boolean } | null>(null);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const editJob = useCallback((id?: string) => { setJobSheet({ id }); setReviewOpen(false); setBrowserOpen(false); setSubagentOpen(false); }, []);
  const [workspaceRevision, setWorkspaceRevision] = useState(0);
  const [toolsRevision, setToolsRevision] = useState(0);
  const [preferences, setPreferences] = useState<DesktopPreferences>({ provider: 'kilo', model: '', customApiBase: '', appearance: 'graphite', contextWindow: 0, maxTokens: 0, imageApiBase: '', imageModel: 'gpt-image-1', username: '', timeZone: '', profileSetupDone: false, hasImageApiKey: false, hasUnsplashAccessKey: false, hasPixabayApiKey: false, hasCustomApiKey: false, hasGroqKey: false, hasKiloKey: false, hasComposioKey: false });
  const [version, setVersion] = useState(__ANKITA_VERSION__);
  const [secretNotice, setSecretNotice] = useState('');
  const closeSettings = useCallback(() => setSettingsTab(null), []);
  const [sidebarOpen, setSidebarOpen] = useState(initialUi.sidebarOpen !== false);
  const [sidebarWidth, setSidebarWidth] = useState(() => normalizeSidebarWidth(initialUi.sidebarWidth));
  const [update, setUpdate] = useState<UpdateEvent | null>(null);
  const [onboardingClosed, setOnboardingClosed] = useState(false);
  const manualCheck = useRef(false);
  const downloadActive = useRef(false);
  const selectedIdRef = useRef<string | null>(null);
  const projectsRequest = useRef(0);
  // Auto-open only for sub-agents that appear while this thread is selected.
  const subagentSeen = useRef<Set<string>>(new Set());
  const subagentThread = useRef<string | null | undefined>(undefined);
  const subagentOpenRef = useRef(false);
  const browserOpenRef = useRef(false);
  const jobSheetRef = useRef<{ id?: string; advanced?: boolean } | null>(null);
  const refreshProjects = useCallback(async () => {
    const request = ++projectsRequest.current;
    const next = await window.ankita.invoke<Project[]>('listProjects');
    if (request === projectsRequest.current) setProjects(next);
  }, []);

  useEffect(() => { saveUi({ sidebarOpen }); }, [sidebarOpen]);
  useEffect(() => { saveUi({ sidebarWidth }); }, [sidebarWidth]);
  useEffect(() => { document.documentElement.dataset.theme = preferences.appearance; }, [preferences.appearance]);
  useEffect(() => { selectedIdRef.current = state.selectedId; }, [state.selectedId]);
  useEffect(() => { browserScopeRef.current = browserScope; }, [browserScope]);
  useEffect(() => { subagentOpenRef.current = subagentOpen; }, [subagentOpen]);
  useEffect(() => { browserOpenRef.current = browserOpen; }, [browserOpen]);
  useEffect(() => { jobSheetRef.current = jobSheet; }, [jobSheet]);

  useEffect(() => {
    if (!window.ankita) { dispatch({ type: 'event', event: { type: 'error', threadId: null, message: 'Open Ankita with npm run desktop:dev or npm run desktop:start.' } }); return; }
    const unsubscribe = window.ankita.onEvent(event => {
      dispatch({ type: 'event', event });
      if (event.type === 'companion-capture-ready' && event.capture.surface === 'main') { dispatch({ type: 'select', id: event.capture.threadId }); setView('chat'); }
      if (event.type === 'settings-updated') setPreferences(event.preferences);
      if (event.type === 'phone-pairing-request') setSettingsTab('phone');
      if (event.type === 'secret-notice') setSecretNotice(event.message);
      if (event.type === 'routine-draft') { dispatch({ type: 'select', id: event.threadId }); setView('chat'); editJob(event.routineId); }
      if (event.type === 'routine-run-end' && browserScopeRef.current === `job:${event.routineId}`) { setBrowserOpen(false); setBrowserScope(null); setBrowserView(null); }
      if (event.type === 'teammates-changed') void window.ankita.invoke<Teammate[]>('listTeammates').then(teammates => dispatch({ type: 'teammates-loaded', teammates }));
      if (event.type === 'projects-changed') void refreshProjects();
      if (event.type === 'tools-changed') setToolsRevision(value => value + 1);
      if (event.type === 'workspace-changed' && event.threadId === selectedIdRef.current) { setWorkspaceRevision(value => value + 1); if (event.open && !subagentOpenRef.current) setReviewOpen(true); }
      if (event.type === 'browser-state' && (browserScopeRef.current ? event.threadId === browserScopeRef.current : !event.threadId || event.threadId === selectedIdRef.current)) {
        setBrowserView(previous => ({ ...event.state, screenshot: event.state.screenshot || (event.state.mode === previous?.mode && !['error', 'stopped', 'idle'].includes(event.state.status) ? previous?.screenshot || null : null) }));
        if (event.threadId && !browserScopeRef.current) setBrowserThreadId(event.threadId);
        if (event.state.status === 'working' && event.state.mode) { setBrowserOpen(true); setReviewOpen(false); setSubagentOpen(false); }
      }
    });
    void window.ankita.invoke<Bootstrap>('initialize')
      .then(data => {
        dispatch({ type: 'bootstrap', ...data, selectedId: loadUi().selectedId ?? null });
        if (data.preferences) setPreferences(data.preferences);
        if (data.version) setVersion(data.version);
        // The window knows its own build; the main process just told us its own.
        // If they disagree, say so instead of failing piecemeal later.
        dispatch({ type: 'compat', compat: checkCompat({ version: data.version, contract: data.contract }, { version: __ANKITA_VERSION__, contract: IPC_CONTRACT }) });
        void refreshProjects();
      })
      .catch(err => dispatch({ type: 'event', event: { type: 'error', threadId: null, message: err.message } }));
    return unsubscribe;
  }, [refreshProjects, editJob]);

  useEffect(() => {
    if (!state.selectedId || !window.ankita) return;
    const id = state.selectedId;
    saveUi({ selectedId: id });
    void window.ankita.invoke<ChatMessage[]>('loadThread', { id }).then(messages => dispatch({ type: 'thread-loaded', id, messages })).catch(err => dispatch({ type: 'event', event: { type: 'error', threadId: id, message: err.message } }));
  }, [state.selectedId]);

  useEffect(() => {
    if (!secretNotice) return;
    const timer = setTimeout(() => setSecretNotice(''), TRANSIENT_NOTICE_MS);
    return () => clearTimeout(timer);
  }, [secretNotice]);

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
        if (!dialog && !settingsTab && !confirm && !state.approvals.length) setPaletteOpen(true);
      }
    });
  }, [dialog, settingsTab, confirm, state.approvals.length]);

  useEffect(() => {
    if (!window.ankita?.onUpdateEvent) return;
    return window.ankita.onUpdateEvent(event => {
      if (event.type === 'checking' && event.manual) manualCheck.current = true;
      if (event.type === 'available' || event.type === 'progress' || event.type === 'stalled') downloadActive.current = true;
      // Quiet background checks, but always surface a failure after a download starts.
      const show = manualCheck.current || downloadActive.current;
      if ((event.type === 'checking' || event.type === 'current' || event.type === 'unsupported' || event.type === 'error') && !show) return;
      if (event.type === 'current' || event.type === 'unsupported' || event.type === 'error' || event.type === 'downloaded') {
        manualCheck.current = false;
        downloadActive.current = false;
      }
      setUpdate(event);
    });
  }, []);

  useEffect(() => {
    if (!browserView?.mode || browserOpen) return;
    let active = true;
    let timer: number;
    const poll = async () => {
      const started = performance.now();
      try { const next = await window.ankita.invoke<BrowserSessionView>('browserSessionView', { scope: browserScope }); if (active) setBrowserView(previous => ({ ...publicBrowserView(next), screenshot: next.screenshot || (next.status !== 'error' && next.mode === previous?.mode ? previous?.screenshot || null : null) })); }
      catch { /* keep the last useful frame */ }
      finally { if (active) timer = window.setTimeout(() => void poll(), Math.max(0, BROWSER_PREVIEW_POLL.thumbnail - (performance.now() - started))); }
    };
    void poll();
    return () => { active = false; window.clearInterval(timer); };
  }, [browserView?.mode, browserOpen, browserScope]);

  useEffect(() => {
    if (!update) return;
    if (update.type === 'current' || update.type === 'unsupported') {
      const timer = setTimeout(() => setUpdate(null), TRANSIENT_NOTICE_MS);
      return () => clearTimeout(timer);
    }
  }, [update]);

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey)) return;
      const name = event.key.toLowerCase();
      if (name === 'n') { event.preventDefault(); setDialog('create'); }
      if (name === 'k') { event.preventDefault(); if (!dialog && !settingsTab && !confirm && !state.approvals.length) setPaletteOpen(true); }
      if (name === 'b' && event.shiftKey) { event.preventDefault(); setBrowserOpen(open => !open); setReviewOpen(false); }
      else if (name === 'b') { event.preventDefault(); setSidebarOpen(open => !open); }
      if (event.key === ',') { event.preventDefault(); setSettingsTab('model'); }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [view, dialog, settingsTab, confirm, state.approvals.length]);

  useEffect(() => {
    const open = () => { if (!dialog && !settingsTab && !confirm && !state.approvals.length) setPaletteOpen(true); };
    window.addEventListener('ankita:palette', open);
    return () => window.removeEventListener('ankita:palette', open);
  }, [dialog, settingsTab, confirm, state.approvals.length]);

  const selected = state.teammates.find(t => t.id === state.selectedId) || null;
  useEffect(() => {
    const captured = (event: Event) => { const id = (event as CustomEvent).detail; if (state.teammates.some(item => item.id === id)) { dispatch({type: 'select', id}); setView('chat'); } };
    window.addEventListener(CAPTURE_UI_EVENTS.main, captured);
    return () => window.removeEventListener(CAPTURE_UI_EVENTS.main, captured);
  }, [state.teammates]);
  // The transcript is the fallback source for sub-agents whose live events were
  // missed, so a completed run can still be reopened in the side panel.
  const messages = state.selectedId ? state.threads[state.selectedId] || [] : [];
  const liveSubagents = state.selectedId ? state.subagents[state.selectedId] : undefined;
  const subagentActivities = useMemo(() => {
    const merged: Record<string, SubagentActivity> = { ...(liveSubagents || {}) };
    for (const message of messages) {
      if (message.role !== 'tool' || message.name !== 'delegate_task') continue;
      if (merged[message.callId]) continue;
      const past = activityFromReceipt(message.result);
      if (past) merged[past.parentCallId || message.callId] = past;
    }
    return merged;
  }, [liveSubagents, messages]);
  const openSubagent = useCallback((key?: string) => {
    const keys = Object.keys(subagentActivities);
    const remembered = subagentFocus && subagentActivities[subagentFocus] ? subagentFocus : null;
    const working = [...keys].reverse().find(item => subagentActivities[item].status === 'running');
    const target = key && subagentActivities[key] ? key : working || remembered || keys.at(-1);
    if (!target) return;
    setSubagentFocus(target);
    setSubagentOpen(true);
    setReviewOpen(false);
    setBrowserOpen(false);
    setJobSheet(null);
  }, [subagentActivities, subagentFocus]);
  const subagentPanelOpen = subagentOpen && Boolean(subagentFocus && subagentActivities[subagentFocus]);
  const toggleSubagent = useCallback(() => {
    if (subagentPanelOpen) setSubagentOpen(false);
    else openSubagent();
  }, [subagentPanelOpen, openSubagent]);
  // A freshly delegated child takes the side slot so the user can watch it work.
  // Runs already present on thread switch stay inline until the user asks for them.
  useEffect(() => {
    const live = liveSubagents || {};
    const liveKeys = Object.keys(live);
    if (state.selectedId !== subagentThread.current) {
      subagentThread.current = state.selectedId;
      subagentSeen.current = new Set(liveKeys);
      setSubagentFocus(null);
      setSubagentOpen(false);
      return;
    }
    const fresh = liveKeys.filter(key => !subagentSeen.current.has(key));
    liveKeys.forEach(key => subagentSeen.current.add(key));
    if (!fresh.length || browserOpenRef.current || jobSheetRef.current) return;
    // Several read-only children can start together; the newest running one leads,
    // but never steal the panel from a child the user is already watching.
    const next = [...fresh].reverse().find(key => live[key].status === 'running') || fresh.at(-1);
    if (!next) return;
    setSubagentFocus(current => {
      const activity = current ? subagentActivities[current] : null;
      return current && activity?.status === 'running' ? current : next;
    });
    setSubagentOpen(true);
    setReviewOpen(false);
  }, [state.selectedId, liveSubagents, subagentActivities]);
  useEffect(() => {
    if (subagentFocus && !subagentActivities[subagentFocus]) { setSubagentFocus(null); setSubagentOpen(false); }
  }, [subagentFocus, subagentActivities]);
  const send = useCallback((text: string, attachments?: { name: string; data: string; kind?: 'document'; images?: string[] }[]) => {
    if (!state.selectedId || !window.ankita) return;
    void window.ankita.invoke('send', { id: state.selectedId, text, attachments }).catch(err => dispatch({ type: 'event', event: { type: 'error', threadId: state.selectedId, message: err.message } }));
  }, [state.selectedId]);
  const stop = () => { if (state.selectedId) void window.ankita.invoke('cancel', { id: state.selectedId }); };
  // First-launch profile step: only after a provider connected (models listed)
  // and only until it is saved or skipped. A failure toast means no models, so
  // no onboarding - the user must fix the connection first.
  const showOnboarding = Boolean(state.settings) && state.models.length > 0 && !preferences.profileSetupDone && !onboardingClosed;
  const saveOnboarding = useCallback(async (patch: { username: string; timeZone: string }) => {
    if (!window.ankita) return;
    await window.ankita.invoke('saveDesktopSettings', { ...patch, profileSetupDone: true });
    setOnboardingClosed(true);
  }, []);
  const skipOnboarding = useCallback(async () => {
    if (!window.ankita) return;
    await window.ankita.invoke('saveDesktopSettings', { profileSetupDone: true });
    setOnboardingClosed(true);
  }, []);
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
  // The palette and slash menu use the same desktop actions and confirmation flow.
  const runCommand = (command: string) => {
    if (command === DESKTOP_ACTIONS.newTeammate) setDialog('create');
    if (command === DESKTOP_ACTIONS.settings) setSettingsTab('model');
    if (command === DESKTOP_ACTIONS.jobs) { setView('chat'); editJob(); }
    if (command === DESKTOP_ACTIONS.plugins || command === DESKTOP_ACTIONS.browser || command === DESKTOP_ACTIONS.skills) {
      setPluginsSection(command === DESKTOP_ACTIONS.skills ? 'skills' : 'apps');
      setView('plugins');
      const selector = command === DESKTOP_ACTIONS.browser ? '.browser-plugins-section' : null;
      if (selector) requestAnimationFrame(() => document.querySelector(selector)?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    }
    if (command === DESKTOP_ACTIONS.projects) setView('projects');
    if (command === DESKTOP_ACTIONS.review) { setReviewOpen(true); setBrowserOpen(false); setSubagentOpen(false); }
    if (command === DESKTOP_ACTIONS.clear) clear();
    if (command === DESKTOP_ACTIONS.updates) void window.ankita.updateAction('check');
    if (command === DESKTOP_ACTIONS.export && state.selectedId) void window.ankita.invoke('exportChat', { id: state.selectedId }).catch(cause => dispatch({ type: 'event', event: { type: 'error', threadId: state.selectedId, message: cause.message } }));
  };
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
  // One recovery for a version mismatch: finish a downloaded update if there is
  // one, otherwise just relaunch so the on-disk build is picked up.
  const recoverFromMismatch = () => {
    if (update?.type === 'downloaded') { void window.ankita.updateAction('install'); return; }
    void window.ankita.appAction('relaunch');
  };

  const showBrowser = view === 'chat' && browserOpen && Boolean(browserView?.mode) && browserThreadId === state.selectedId;
  useEffect(() => { if (showBrowser) setSidebarOpen(false); }, [showBrowser]);
  const stopBrowser = () => {
    if (state.selectedId && !browserScope) void window.ankita.invoke('cancel', { id: state.selectedId });
    void window.ankita.invoke('browserSessionStop', { scope: browserScope }).finally(() => { setBrowserOpen(false); setBrowserView(null); setBrowserThreadId(null); setBrowserScope(null); });
  };
  const watchJob = async (job: Routine) => {
    if (!job.scope || !state.selectedId) return;
    try { const next = await window.ankita.invoke<BrowserSessionView>('browserSessionView', { scope: job.scope }); setBrowserScope(job.scope); setBrowserThreadId(state.selectedId); setBrowserView(next); setBrowserOpen(true); setJobSheet(null); setReviewOpen(false); setSubagentOpen(false); }
    catch (error) { dispatch({ type: 'event', event: { type: 'error', threadId: state.selectedId, message: error instanceof Error ? error.message : String(error) } }); }
  };
  const threadJobs = state.jobs.filter(job => job.threadId === state.selectedId || (job.ownerMissing && job.deliveryThreadId === state.selectedId));

  return <SecureStoreProvider><div className={`app-shell desktop-workbench ${reviewOpen && view === 'chat' && state.selectedId ? 'review-visible' : ''} ${subagentPanelOpen ? 'subagent-visible' : ''} ${showBrowser ? 'browser-visible' : ''}`}>
    <Sidebar
      teammates={state.teammates} selectedId={state.selectedId} search={search} onSearch={setSearch}
      onSelect={id => { setView('chat'); dispatch({ type: 'select', id }); }} onCreate={() => { setView('chat'); setDialog('create'); }} onOpenSettings={() => setSettingsTab('model')}
      onOpenPlugins={() => { setPluginsSection('apps'); setView('plugins'); }} pluginsOpen={view === 'plugins'} onOpenProjects={() => setView('projects')} projectsOpen={view === 'projects'}
      onOpenChat={() => setView('chat')}
      provider={state.settings?.provider || 'Copilot'} model={state.settings?.model || ''} phase={state.phase}
      chrome={state.chrome} unread={state.unread} toolsCount={state.settings?.tools.length || 0}
      width={sidebarWidth} collapsed={!sidebarOpen} onCollapse={() => setSidebarOpen(false)} onResize={setSidebarWidth}
    />
    {view === 'plugins' ? <PluginsPage chrome={state.chrome} sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen(open => !open)} onOpenSettings={() => setSettingsTab('providers')} hasComposioKey={preferences.hasComposioKey} toolsRevision={toolsRevision} initialSection={pluginsSection} /> : view === 'projects' ? <ProjectsPage projects={projects} selectedThread={selected} chrome={state.chrome} sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen(open => !open)} onRefresh={refreshProjects} onAssign={assignProject} /> : <ChatPane
      teammate={selected} messages={messages}
      jobs={threadJobs} onEditJob={editJob}
      running={Boolean(state.selectedId && state.running[state.selectedId])}
      models={state.models} projects={projects} defaultModel={state.settings?.model || ''} provider={state.settings?.provider}
      usage={state.selectedId ? state.usage[state.selectedId] : undefined}
      loadedSkills={state.selectedId ? state.loadedSkills[state.selectedId] : undefined}
      subagents={subagentActivities} subagentOpen={subagentPanelOpen} onToggleSubagent={toggleSubagent} onOpenSubagent={openSubagent}
      onCommand={runCommand} commandsRevision={toolsRevision}
      chrome={state.chrome} sidebarOpen={sidebarOpen} reviewOpen={reviewOpen} browserRun={!browserScope && browserThreadId === state.selectedId ? browserView : null} onOpenBrowser={() => { setBrowserOpen(true); setReviewOpen(false); setSubagentOpen(false); }} onOpenBrowserPlugins={() => runCommand(DESKTOP_ACTIONS.browser)} onToggleSidebar={() => setSidebarOpen(open => !open)} onToggleReview={() => { setReviewOpen(open => !open); setBrowserOpen(false); setSubagentOpen(false); }} onProject={id => void assignProject(id)} onOpenProjects={() => setView('projects')}
      onSend={send} onStop={stop} onModel={model} onEdit={() => setDialog('edit')} onCreate={() => setDialog('create')} onClear={clear} onDelete={remove}
    />}
    {view === 'chat' && state.selectedId && <BrowserStage key={browserScope || state.selectedId} scope={browserScope} view={browserThreadId === state.selectedId ? browserView : null} visible={showBrowser} onView={setBrowserView} onStop={stopBrowser} onOpenSetup={() => setView('plugins')} />}
    {view === 'chat' && state.selectedId && jobSheet && (jobSheet.advanced ? <RoutineSheet key={jobSheet.id || 'new'} routine={threadJobs.find(job => job.id === jobSheet.id) || null} jobs={threadJobs} teammates={state.teammates} threadId={state.selectedId} onChoose={id => setJobSheet({ id, advanced: true })} onClose={() => editJob(jobSheet.id)} /> : <JobsPanel jobs={threadJobs} teammates={state.teammates} threadId={state.selectedId} selectedId={jobSheet.id} onChoose={editJob} onEdit={id => setJobSheet({ id, advanced: true })} onWatch={job => { setJobSheet(null); void watchJob(job); }} onAsk={() => { setJobSheet(null); window.dispatchEvent(new CustomEvent(COMPOSE_EVENT, { detail: 'Schedule a task: ' })); }} onClose={() => setJobSheet(null)} />)}
    {view === 'chat' && state.selectedId && <WorkspacePanel threadId={state.selectedId} revision={workspaceRevision} visible={reviewOpen && !subagentPanelOpen} onClose={() => setReviewOpen(false)} />}
    {view === 'chat' && state.selectedId && <SubagentPanel activities={subagentActivities} focus={subagentFocus} visible={subagentPanelOpen} onFocus={key => { setSubagentFocus(key); setSubagentOpen(true); }} onClose={() => setSubagentOpen(false)} onStop={stop} />}
    {dialog && <TeammateDialog teammate={dialog === 'edit' ? selected : null} projects={projects} onSave={saveTeammate} onClose={() => setDialog(null)} />}
    {confirm && <ConfirmDialog action={confirm.action} name={confirm.name} onCancel={() => setConfirm(null)} onConfirm={confirmAction} jobsCount={state.jobs.filter(job => job.threadId === confirm.id).length} onRehome={() => { const job = state.jobs.find(item => item.threadId === confirm.id); setConfirm(null); if (job) editJob(job.id); }} />}
    {settingsTab && <SettingsDialog tab={settingsTab} onTab={setSettingsTab} onClose={closeSettings} preferences={preferences} models={state.models} teammates={state.teammates} selectedThreadId={state.selectedId} jobs={state.jobs} onOpenJobs={job => { const ownerId = job ? job.ownerMissing ? job.deliveryThreadId : job.threadId : state.selectedId || state.teammates[0]?.id; if (!ownerId) return; dispatch({ type: 'select', id: ownerId }); setView('chat'); closeSettings(); editJob(job?.id); }} version={version} onSaved={(result: DesktopSettingsResult) => { setPreferences(result.preferences); dispatch({ type: 'event', event: { type: 'settings-updated', ...result } }); }} />}
    {state.approvals[0] && <ApprovalDialog approval={state.approvals[0]} onAnswer={answer} />}
    {state.deviceCode && <div className="modal-backdrop"><div className="auth-dialog" role="dialog" aria-modal="true"><div className="modal-symbol"><Icon name="external" size={22} /></div><h2>Connect to GitHub</h2><p>Open the verification page and enter this code to connect your Copilot account.</p><div className="device-code">{state.deviceCode.user_code}</div><button className="button-primary" onClick={() => void window.ankita.openExternal(state.deviceCode!.verification_uri)}>Open GitHub <Icon name="external" size={15} /></button><small>Waiting for authorization…</small></div></div>}
    {showOnboarding && <OnboardingDialog initialName={preferences.username} initialTimeZone={preferences.timeZone} onSave={saveOnboarding} onSkip={skipOnboarding} />}
    {update && <UpdateBanner update={update} onInstall={installUpdate} onOpenRelease={() => void window.ankita.openExternal('https://github.com/akyourowngames/A.N.K.I.T.A/releases/latest')} onDismiss={dismissUpdate} />}
    {state.compat && !state.compat.ok && !state.compatDismissed && <VersionMismatchNotice compat={state.compat} hasUpdate={update?.type === 'downloaded'} onRestart={recoverFromMismatch} onDismiss={() => dispatch({ type: 'compat-dismissed' })} />}
    {paletteOpen && <PaletteModal threadId={state.selectedId} revision={`${toolsRevision}:${state.jobs.map(job => `${job.id}:${job.enabled}:${job.nextRunAt}`).join('|')}`} onClose={() => setPaletteOpen(false)} onCommand={runCommand} />}
    {(state.error || secretNotice) && <div className="notice-stack">
      {state.error && <NoticeCard notice={describeErrorNotice(state.error)} dismissLabel="Dismiss error" onDismiss={() => dispatch({ type: 'dismiss-error' })} />}
      {secretNotice && <NoticeCard notice={{ tone: 'info', title: 'Secret protection', detail: secretNotice }} dismissLabel="Dismiss secret notice" onDismiss={() => setSecretNotice('')} />}
    </div>}
  </div></SecureStoreProvider>;
}
