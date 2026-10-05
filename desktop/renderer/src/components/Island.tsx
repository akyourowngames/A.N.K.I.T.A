import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import type { EngineEvent, Routine } from '../../../shared/wire';
import { islandThreadState, type IslandTool } from '../../../shared/island-state.mjs';
import type { MascotState } from '../island/engine';
import { useReducedMotion } from '../lib/useReducedMotion';
import { isSoundEnabled, playSound, setSoundEnabled } from '../island/sound';
import { Mascot } from './Mascot';
import { Header } from './island-views/Header';
import { Icon } from './island-views/icons';
import { Overview, type ActivityItem } from './island-views/Overview';
import { ApprovalView, type ApprovalItem } from './island-views/ApprovalView';
import { Prompt } from './island-views/Prompt';
import { useIslandChat } from './island-views/useIslandChat';
import { SettingsMini } from './island-views/SettingsMini';
import { EmptyView, ErrorView, FinishedView } from './island-views/StaticViews';
import type { IslandHomeView } from './island-views/views';
import { useMascotInteraction } from '../lib/useMascotInteraction';
import { useMascotCapture } from '../lib/useMascotCapture';
import { MascotFile } from './MascotFile';
import { CAPTURE_UI_EVENTS } from '../../../browser-helper/protocol.mjs';

type IslandApproval = ApprovalItem & { threadId?: string | null; routineId?: string };
const FLASH_MS = 4000; // Milliseconds; completion/error expression before returning to live work.
const LOOK_RANGE_PX = 180; // Cursor pixels mapped to a full eye movement.
const TUCK_DELAY_MS = 900; // Milliseconds; close the quiet compact tab after pointer exit.
const HOME_COLLAPSE_MS = 15000; // Milliseconds; Coucou's home-to-compact pause.
const MASCOT_PETIT_PX = 40; // CSS pixels; fits the compact tab.
const MASCOT_HOME_PX = 80; // CSS pixels; focus character beside the home card.
const MAX_JOB_STEPS = 20; // Rows per job; bounded live activity history.
const JOB_COLOR = 'var(--green)'; // Shared theme fallback for jobs without a teammate color.
const TALL_VIEWS: IslandHomeView[] = ['prompt'];
const STATE_GLOW: Record<MascotState, string> = {
  idle: 'rgba(140,150,170,0.16)', working: 'rgba(59,158,255,0.28)',
  thinking: 'rgba(139,92,246,0.28)', searching: 'rgba(99,102,241,0.28)',
  approval: 'rgba(245,165,36,0.34)', question: 'rgba(34,211,238,0.28)',
  error: 'rgba(244,63,94,0.32)', finished: 'rgba(52,211,153,0.28)',
  ratelimit: 'rgba(251,146,60,0.28)', sleeping: 'rgba(148,163,184,0.2)', dizzy: 'rgba(244,114,182,0.28)',
};
const clampLook = (v: number) => Math.max(-1, Math.min(1, v));

export function Island() {
  const reducedMotion = useReducedMotion();
  const chat = useIslandChat();
  const [jobs, setJobs] = useState<Routine[]>([]);
  const [tools, setTools] = useState<IslandApproval[]>([]);
  const [view, setView] = useState<'tucked' | 'petit' | 'home'>('tucked');
  const [navView, setNavView] = useState<IslandHomeView | null>(null);
  const [flash, setFlash] = useState<'finished' | 'error' | null>(null);
  const [errorCard, setErrorCard] = useState<{ who: string; detail: string } | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const selectedTeammate = chat.teammates.find(item => item.id === (navView === 'prompt' ? chat.teammateId : focusId)) || chat.teammates.find(item => item.id === chat.teammateId);
  const { interaction, pose, reset } = useMascotInteraction(selectedTeammate?.id || null);
  const capture = useMascotCapture();
  const dropRecipient = useRef<string | null>(null);
  const [soundOn, setSoundOn] = useState(isSoundEnabled());
  const [pendingApproval, setPendingApproval] = useState<string | null>(null);
  const [approvalError, setApprovalError] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [, setStepTick] = useState(0);
  const mascotBox = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const lookRef = useRef({ x: 0, y: 0 });
  const sizeRef = useRef('');
  const flashTimer = useRef<number | null>(null);
  const tuckTimer = useRef<number | null>(null);
  const homeTimer = useRef<number | null>(null);
  const stepsRef = useRef(new Map<string, string[]>());
  const failedTurns = useRef(new Set<string>());
  const approvalPendingRef = useRef(false);
  const autoHome = useRef(false);
  const dragDepth = useRef(0);

  const approvals = [...new Map([...tools, ...jobs.flatMap(job => job.pendingApproval ? [{
    requestId: job.pendingApproval.requestId, threadId: job.threadId, routineId: job.id,
    toolName: job.name, detail: job.pendingApproval.redactedDetail,
  }] : [])].map(item => [item.requestId, item])).values()];
  const activeThreads = chat.teammates.filter(item => chat.state.threads[item.id]?.running);
  const runningJobs = jobs.filter(job => job.running);
  const runningCount = activeThreads.length + runningJobs.filter(job => !activeThreads.some(item => item.id === job.threadId)).length;
  const engaged = useRef(false);
  engaged.current = approvals.length > 0 || chat.reading || chat.sending || interaction.phase !== 'rest' || Boolean(chat.input.trim() || chat.attachments.length);

  const clearTimers = useCallback(() => {
    if (tuckTimer.current !== null) window.clearTimeout(tuckTimer.current);
    if (homeTimer.current !== null) window.clearTimeout(homeTimer.current);
    tuckTimer.current = homeTimer.current = null;
  }, []);
  const openHome = useCallback((automatic = false) => {
    clearTimers(); autoHome.current = automatic; setView('home');
  }, [clearTimers]);
  const closeHome = useCallback(() => {
    clearTimers(); autoHome.current = false; setNavView(null); setView('petit'); playSound('close');
  }, [clearTimers]);
  const showFlash = useCallback((kind: 'finished' | 'error') => {
    if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    setFlash(kind);
    setView(current => current === 'tucked' ? 'petit' : current);
    flashTimer.current = window.setTimeout(() => { setFlash(null); flashTimer.current = null; }, FLASH_MS);
  }, []);
  const pushStep = useCallback((id: string, line: string) => {
    stepsRef.current.set(id, [...(stepsRef.current.get(id) || []), line].slice(-MAX_JOB_STEPS));
    setStepTick(tick => tick + 1);
  }, []);

  useEffect(() => {
    let alive = true;
    let loadingApprovals = true;
    const resolvedBeforeSnapshot = new Set<string>();
    const refreshApprovals = () => void window.ankita.invoke<IslandApproval[]>('approvalList').then(list => {
      if (!alive) return;
      const pending = (list || []).filter(item => !resolvedBeforeSnapshot.has(item.requestId));
      // Live requests can arrive before an older startup snapshot completes.
      setTools(current => [...new Map([...pending, ...current].map(item => [item.requestId, item])).values()]);
      if (pending.length) openHome(true);
    }).catch(error => { if (alive) setApprovalError(String(error.message || error)); })
      .finally(() => { loadingApprovals = false; resolvedBeforeSnapshot.clear(); });
    void window.ankita.invoke<Routine[]>('scheduleList').then(list => {
      if (!alive) return;
      setJobs(list || []);
      if (list?.some(job => job.pendingApproval)) openHome(true);
    }).catch(error => {
      if (alive) setErrorCard({ who: 'Scheduled jobs', detail: String(error.message || error) });
    });
    refreshApprovals();
    const off = window.ankita.onEvent((event: EngineEvent) => {
      if (!alive) return;
      if (event.type === 'schedule-changed') setJobs(event.jobs);
      else if (event.type === 'routine-run-start' || event.type === 'routine-run-step') {
        pushStep(event.routineId, event.detail || event.status || 'Working…');
        setView(current => current === 'tucked' ? 'petit' : current);
      } else if (event.type === 'approval-request') {
        setTools(current => current.some(item => item.requestId === event.requestId) ? current : [...current, event]);
        setNavView(null); setApprovalError(''); openHome(true);
      } else if (event.type === 'approval-resolved' || event.type === 'routine-approval-ended') {
        if (loadingApprovals) resolvedBeforeSnapshot.add(event.requestId);
        setTools(current => current.filter(item => item.requestId !== event.requestId));
      } else if (event.type === 'turn-start') {
        failedTurns.current.delete(event.threadId);
        setFlash(null); setErrorCard(null);
        setView(current => current === 'tucked' ? 'petit' : current);
      } else if (event.type === 'turn-end') {
        if (!failedTurns.current.has(event.threadId)) showFlash('finished');
      } else if (event.type === 'routine-failed' || event.type === 'error') {
        if (event.threadId) failedTurns.current.add(event.threadId);
        setErrorCard({ who: event.type === 'error' ? 'Ankita' : 'Scheduled job', detail: event.type === 'error' ? event.message : event.text || event.status });
        showFlash('error');
      }
    });
    return () => { alive = false; off(); if (flashTimer.current !== null) window.clearTimeout(flashTimer.current); };
  }, [openHome, pushStep, showFlash]);

  useEffect(() => {
    const off = window.ankita.onCursor(point => {
      const canvas = mascotBox.current?.querySelector('canvas');
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      lookRef.current = { x: clampLook((point.x - rect.left - rect.width / 2) / LOOK_RANGE_PX), y: clampLook((rect.top + rect.height / 2 - point.y) / LOOK_RANGE_PX) };
    });
    return off;
  }, []);
  useEffect(() => () => clearTimers(), [clearTimers]);
  useEffect(() => {
    if (view !== 'home') return;
    const blur = () => { if (!engaged.current) closeHome(); };
    window.addEventListener('blur', blur);
    return () => window.removeEventListener('blur', blur);
  }, [view, closeHome]);

  const routedView: IslandHomeView = approvals.length ? 'approval' : runningCount ? 'overview' : 'empty';
  // Alerts always win over a manually selected tab; approval answers stay visible.
  const activeView: IslandHomeView = approvals.length ? 'approval' : navView || (errorCard ? 'error' : flash === 'finished' && !runningCount ? 'finished' : routedView);
  const liveStates = activeThreads.map(item => islandThreadState(chat.state.threads[item.id]));
  const botState: MascotState = approvals.length ? 'approval' : flash === 'error' ? 'error'
    : liveStates.includes('searching') ? 'searching' : liveStates.includes('working') ? 'working'
    : runningCount ? (activeThreads.length ? 'thinking' : 'working') : flash === 'finished' ? 'finished' : 'idle';

  useEffect(() => {
    const want = view === 'home' ? (TALL_VIEWS.includes(activeView) ? 'home-chat' : 'home-expanded') : view === 'petit' ? 'petit' : 'tuck';
    if (want !== sizeRef.current) { sizeRef.current = want; void window.ankita.islandAction(want, { animate: !reducedMotion }).catch(() => {}); }
    void window.ankita.islandAction(view === 'home' && (activeView === 'prompt' || activeView === 'approval' || activeView === 'settings') ? 'focus-on' : 'focus-off').catch(() => {});
  }, [view, activeView, reducedMotion]);
  useEffect(() => {
    if (!approvals.length && autoHome.current && view === 'home') closeHome();
  }, [approvals.length, view, closeHome]);
  const prevState = useRef(botState);
  useEffect(() => {
    if (botState === prevState.current) return;
    prevState.current = botState;
    const cues = { approval: 'approval', error: 'error', finished: 'finish', working: 'work', thinking: 'think', searching: 'search' } as const;
    if (botState in cues) playSound(cues[botState as keyof typeof cues]);
  }, [botState]);

  const answer = useCallback(async (requestId: string, result: 'yes' | 'no' | 'always') => {
    if (approvalPendingRef.current) return;
    approvalPendingRef.current = true; setPendingApproval(requestId); setApprovalError('');
    try {
      await window.ankita.invoke('respondApproval', { requestId, answer: result });
      setTools(current => current.filter(item => item.requestId !== requestId));
      setNavView(null); playSound(result === 'no' ? 'blip' : 'approve');
    } catch (error) { setApprovalError(error instanceof Error ? error.message : String(error)); }
    finally { approvalPendingRef.current = false; setPendingApproval(null); }
  }, []);
  const restore = () => void window.ankita.islandAction('show-main').catch(() => {});
  const navigate = (target: IslandHomeView) => { clearTimers(); setNavView(target); openHome(); playSound('blip'); };
  const attach = () => { navigate('prompt'); fileInput.current?.click(); };
  useEffect(() => {
    const captured = () => { setFocusId(null); setNavView('prompt'); openHome(); };
    window.addEventListener(CAPTURE_UI_EVENTS.island, captured);
    return () => window.removeEventListener(CAPTURE_UI_EVENTS.island, captured);
  }, [openHome]);
  const toggleSound = () => { const next = !soundOn; setSoundOn(next); setSoundEnabled(next); if (next) playSound('blip'); };

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { dragDepth.current = 0; dropRecipient.current = null; setDragOver(false); if (interaction.phase === 'anticipate' || interaction.phase === 'grab') reset(); if (view === 'home') closeHome(); else { clearTimers(); setView('tucked'); } return; }
      const target = event.target as HTMLElement | null;
      if (target?.closest('input, textarea, select, [contenteditable="true"]') || event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
      if (view === 'home' && approvals.length) {
        if (event.key.toLowerCase() === 'y') { event.preventDefault(); void answer(approvals[0].requestId, 'yes'); }
        if (event.key.toLowerCase() === 'n') { event.preventDefault(); void answer(approvals[0].requestId, 'no'); }
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [view, approvals, answer, clearTimers, closeHome, interaction.phase, reset]);

  const activities: ActivityItem[] = [
    ...chat.teammates.map(teammate => {
      const thread = chat.state.threads[teammate.id];
      const state = islandThreadState(thread);
      return { id: teammate.id, threadId: teammate.id, name: teammate.name, color: teammate.color || JOB_COLOR,
        running: thread?.running === true, needsApproval: approvals.some(item => item.threadId === teammate.id),
        label: state === 'idle' ? 'Ready' : state, steps: [], tools: (thread?.log || []).filter((row): row is IslandTool => row.kind === 'tool') };
    }),
    ...jobs.map(job => ({ id: job.id, routineId: job.id, name: job.name, color: JOB_COLOR, running: job.running,
      needsApproval: job.needsApproval, label: job.running ? 'Running' : job.lastStatus || 'Scheduled',
      steps: stepsRef.current.get(job.id) || [], tools: [] })),
  ];
  const stopActivity = (item: ActivityItem) => void window.ankita.invoke(item.routineId ? 'scheduleStop' : 'cancel', { id: item.routineId || item.threadId })
    .catch(error => setErrorCard({ who: item.name, detail: String(error.message || error) }));
  const status = approvals.length ? approvals.length + ' awaiting permission' : runningCount ? runningCount + ' working' : 'Ready when you are';
  const home = view === 'home';

  const leave = () => {
    clearTimers();
    if (engaged.current) return;
    if (home) homeTimer.current = window.setTimeout(() => {
      if (!engaged.current && !document.activeElement?.closest('input, textarea, select')) closeHome();
    }, HOME_COLLAPSE_MS);
    else if (!runningCount && !flash) tuckTimer.current = window.setTimeout(() => setView('tucked'), TUCK_DELAY_MS);
  };
  return <div className={'island ' + (home ? 'island-home' : 'island-petit') + (dragOver ? ' is-dragging' : '')}
    data-mascot-state={botState} data-shell-view={view} style={{ '--wash': STATE_GLOW[botState] } as CSSProperties}
    onMouseEnter={() => { clearTimers(); if (view === 'tucked') { setView('petit'); playSound('peek'); } }}
    onMouseLeave={leave}
    onDragEnter={event => { if (!event.dataTransfer.types.includes('Files')) return; event.preventDefault(); if (!dragDepth.current) dropRecipient.current = selectedTeammate?.id || null; dragDepth.current++; setDragOver(true); pose('anticipate'); openHome(); }}
    onDragOver={event => { if (event.dataTransfer.types.includes('Files')) { event.preventDefault(); event.dataTransfer.dropEffect = 'copy'; } }}
    onDragLeave={event => { if (!event.dataTransfer.types.includes('Files')) return; if (--dragDepth.current <= 0) { dragDepth.current = 0; setDragOver(false); dropRecipient.current = null; if (interaction.phase === 'anticipate') reset(); } }}
    onDrop={event => { if (!event.dataTransfer.files.length) return; event.preventDefault(); const id = dropRecipient.current || selectedTeammate?.id || chat.teammateId; dragDepth.current = 0; dropRecipient.current = null; setDragOver(false); if (id) { chat.selectTeammate(id); setFocusId(id); } navigate('prompt'); void chat.addFiles(Array.from(event.dataTransfer.files), id); }}>
    <input ref={fileInput} type="file" multiple hidden aria-label="Attach files" onChange={event => {
      const id = selectedTeammate?.id || chat.teammateId; if (id) chat.selectTeammate(id); void chat.addFiles(Array.from(event.target.files || []), id); event.target.value = '';
    }} />
    {home && <div className="island-toolbar">
      <Header view={activeView} soundOn={soundOn} onNavigate={navigate} onDrop={attach} onToggleSound={toggleSound} />
      <span className="island-live-status" role="status">{status}</span>
      <button className="island-tab" aria-label="Open Ankita" title="Open desktop" onClick={restore}><Icon name="arrowUpRight" size={14} /></button>
      <button className="island-tab" aria-label="Collapse island" title="Collapse (Esc)" onClick={closeHome}><Icon name="chevronRight" size={14} stroke={2} /></button>
    </div>}
    <div className="island-content">
      <div className="island-mascot" ref={mascotBox} draggable title={capture.message || 'Drag onto a webpage; drop files here'}
        onMouseEnter={() => { if (!capture.setup?.paired) void capture.refresh(); }}
        onDragStart={event => { if (capture.start(event, selectedTeammate?.id || null)) pose('grab'); }}
        onDragEnd={event => { capture.end(event); reset(); }}>
        <div className={'island-glow' + (approvals.length ? ' island-glow-pulse' : '')} style={{ background: 'radial-gradient(circle, ' + STATE_GLOW[botState] + ' 0%, transparent 70%)' }} />
        <Mascot state={botState} lookRef={lookRef} size={home ? MASCOT_HOME_PX : MASCOT_PETIT_PX} awake={view !== 'tucked'} interaction={interaction} color={selectedTeammate?.color} />
        <MascotFile interaction={interaction} />
        {home && <span className="island-mascot-name" title={selectedTeammate?.name}>{selectedTeammate?.name || 'Ankita'}</span>}
      </div>
      {!home ? <button className="island-compact-open" aria-label="Open Ankita island" onClick={() => { openHome(); playSound('open'); }}>
        <strong>Ankita</strong><span>{status}</span>{approvals.length > 0 && <b>{approvals.length}</b>}
      </button> : <div className="island-body" data-home-view={activeView}>
        {activeView === 'approval' && <ApprovalView items={approvals} answer={answer} pendingId={pendingApproval} error={approvalError} />}
        {activeView === 'overview' && <Overview activities={activities} selectedId={focusId} onFocus={id => { setFocusId(id); chat.selectTeammate(id); }}
          onCaptureDrag={(event, id) => { setFocusId(id); chat.selectTeammate(id); if (capture.start(event, id)) pose('grab'); }}
          onCaptureEnd={event => { capture.end(event); reset(); }}
          onAsk={id => { if (id) chat.selectTeammate(id); navigate('prompt'); }} onStop={stopActivity} />}
        {activeView === 'empty' && <EmptyView onAsk={() => navigate('prompt')} />}
        {activeView === 'error' && errorCard && <ErrorView who={errorCard.who} detail={errorCard.detail} onRetry={() => { setErrorCard(null); navigate('prompt'); }} />}
        {activeView === 'finished' && <FinishedView who={chat.teammateName} detail="All done. Your conversation is saved."
          onOpen={() => navigate('prompt')} onOk={() => { setFlash(null); setNavView(null); }} />}
        {activeView === 'prompt' && <Prompt chat={chat} onAttach={attach} />}
        {activeView === 'settings' && <SettingsMini soundOn={soundOn} onToggleSound={toggleSound} />}
      </div>}
    </div>
    {dragOver && <div className="island-drop-hint" role="status">Feed {selectedTeammate?.name || 'Ankita'} a file</div>}
    {capture.message && !dragOver && <div className="island-capture-status" role="status">{capture.message}</div>}
  </div>;
}
