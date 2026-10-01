import { useCallback, useEffect, useRef, useState, type CSSProperties } from 'react';
import type { EngineEvent, Routine } from '../../../shared/wire';
import type { Approval } from '../state/store';
import type { MascotState } from '../island/engine';
import { playSound } from '../island/sound';
import { Mascot } from './Mascot';

type IslandApproval = Approval | {
  type: 'approval-request';
  requestId: string;
  threadId: string | null;
  toolName: string;
  detail: string;
  routineId?: string;
  runId?: string;
  expiresAt?: string;
};

/** How long a finished/error flash holds the mascot before it settles back. */
const FLASH_MS = 4000;
/** Pixels of cursor travel mapped to a full look swing. */
const LOOK_RANGE_PX = 180;
/** Delay before a revealed petit tab tucks back once the pointer leaves. */
const TUCK_DELAY_MS = 900;
/** Mascot canvas size in the petit tab vs the home card. */
const MASCOT_PETIT_PX = 40;
const MASCOT_HOME_PX = 52;

/** State-tinted glow behind the mascot, Coucou-style. Kept faint on purpose. */
const STATE_GLOW: Record<MascotState, string> = {
  idle: 'rgba(140,150,170,0.16)',
  working: 'rgba(59,158,255,0.28)',
  thinking: 'rgba(139,92,246,0.28)',
  searching: 'rgba(99,102,241,0.28)',
  approval: 'rgba(245,165,36,0.34)',
  question: 'rgba(34,211,238,0.28)',
  error: 'rgba(244,63,94,0.32)',
  finished: 'rgba(52,211,153,0.28)',
  ratelimit: 'rgba(251,146,60,0.28)',
  sleeping: 'rgba(148,163,184,0.2)',
  dizzy: 'rgba(244,114,182,0.28)',
};

function clampLook(v: number): number {
  return Math.max(-1, Math.min(1, v));
}

function routineApprovals(jobs: Routine[]): IslandApproval[] {
  const items: IslandApproval[] = [];
  for (const job of jobs) {
    if (job.pendingApproval) {
      items.push({
        type: 'approval-request',
        requestId: job.pendingApproval.requestId,
        threadId: job.threadId,
        toolName: job.name || 'Scheduled job',
        detail: job.pendingApproval.redactedDetail,
        routineId: job.id,
        runId: job.pendingApproval.runId,
        expiresAt: job.pendingApproval.expiresAt,
      });
    }
  }
  return items;
}

export function Island() {
  const [jobs, setJobs] = useState<Routine[]>([]);
  const [tools, setTools] = useState<IslandApproval[]>([]);
  const [thinking, setThinking] = useState(false);
  const [flash, setFlash] = useState<{ kind: 'finished' | 'error'; key: number } | null>(null);
  const [view, setView] = useState<'tucked' | 'petit' | 'home'>('tucked');
  const turns = useRef(new Map<string, string | undefined>());
  const flashTimer = useRef<number | null>(null);
  const lookRef = useRef({ x: 0, y: 0 });
  const mascotBox = useRef<HTMLDivElement>(null);
  const sizeRef = useRef('');
  // True while home was auto-opened by an approval (so clearing them tucks back).
  const autoHome = useRef(false);

  const openHome = useCallback((auto: boolean) => {
    autoHome.current = auto;
    setView('home');
  }, []);

  const openPetit = useCallback(() => {
    setView(current => (current === 'tucked' ? 'petit' : current));
  }, []);

  const tuckTimer = useRef<number | null>(null);
  const cancelTuck = useCallback(() => {
    if (tuckTimer.current != null) { window.clearTimeout(tuckTimer.current); tuckTimer.current = null; }
  }, []);
  const tuckSoon = useCallback(() => {
    cancelTuck();
    tuckTimer.current = window.setTimeout(() => {
      tuckTimer.current = null;
      autoHome.current = false;
      setView(current => (current === 'petit' ? 'tucked' : current));
    }, TUCK_DELAY_MS);
  }, [cancelTuck]);

  const closeHome = useCallback(() => {
    autoHome.current = false;
    playSound('close');
    setView('petit');
  }, []);

  const showFlash = useCallback((kind: 'finished' | 'error') => {
    if (flashTimer.current != null) window.clearTimeout(flashTimer.current);
    setFlash({ kind, key: Date.now() });
    flashTimer.current = window.setTimeout(() => { setFlash(null); flashTimer.current = null; }, FLASH_MS);
  }, []);

  useEffect(() => {
    let alive = true;
    void window.ankita.invoke<Routine[]>('scheduleList').then(list => { if (alive) setJobs(list || []); }).catch(() => {});
    void window.ankita.invoke<IslandApproval[]>('approvalList').then(list => {
      if (!alive) return;
      setTools(list || []);
      if ((list || []).length > 0) openHome(true);
    }).catch(() => {});
    const off = window.ankita.onEvent((event: EngineEvent) => {
      if (!alive) return;
      if (event.type === 'schedule-changed') setJobs(event.jobs);
      else if (event.type === 'approval-request') {
        setTools(current => current.some(item => item.requestId === event.requestId) ? current : [...current, event]);
        openHome(true);
      } else if (event.type === 'approval-resolved' || event.type === 'routine-approval-ended') {
        setTools(current => current.filter(item => item.requestId !== event.requestId));
      } else if (event.type === 'turn-start') {
        turns.current.set(event.turnId, event.source);
        setThinking(true);
      } else if (event.type === 'turn-end') {
        const source = turns.current.get(event.turnId);
        turns.current.delete(event.turnId);
        if (turns.current.size === 0) {
          setThinking(false);
          if (source !== 'routine') showFlash('finished');
        }
      } else if (event.type === 'routine-run-end') {
        showFlash('finished');
      } else if (event.type === 'routine-failed') {
        showFlash('error');
      }
    });
    return () => { alive = false; off(); if (flashTimer.current != null) window.clearTimeout(flashTimer.current); };
  }, [showFlash, openHome]);

  // Cursor follow: the main process streams the pointer relative to the island
  // window; the mascot watches it through a ref so the pointer never re-renders.
  useEffect(() => {
    const off = window.ankita.onCursor(point => {      const canvas = mascotBox.current?.querySelector('canvas');
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      lookRef.current = {
        x: clampLook((point.x - (rect.left + rect.width / 2)) / LOOK_RANGE_PX),
        y: clampLook(((rect.top + rect.height / 2) - point.y) / LOOK_RANGE_PX),
      };
    });
    return off;
  }, []);

  // Never leave a pending tuck behind on unmount.
  useEffect(() => cancelTuck, [cancelTuck]);

  const approvals = [...tools, ...routineApprovals(jobs)];
  // Expanded while approvals pend (the window grows to fit the body); a quiet
  // home card is header-only so it fits the compact window without clipping.
  const expanded = approvals.length > 0;

  const restore = useCallback(() => {
    playSound('open');
    void window.ankita.islandAction('show-main').catch(() => {});
  }, []);

  // Clicking the header row restores the main window from a quiet home card
  // (whose body is hidden to fit the compact window), or collapses an
  // expanded one back to petit; controls keep their clicks.
  const toggleFromHeader = useCallback((event: React.MouseEvent) => {
    const target = event.target as HTMLElement;
    if (target.closest('button, .island-approvals, .island-body')) return;
    if (expanded) closeHome();
    else restore();
  }, [closeHome, expanded, restore]);

  const running = jobs.filter(job => job.running).length;
  const needing = jobs.filter(job => job.needsApproval).length + tools.length;
  const status = needing > 0
    ? `${needing} need${needing === 1 ? 's' : ''} approval`
    : running > 0 ? `${running} running` : 'All quiet';

  const botState: MascotState =
    approvals.length > 0 ? 'approval'
    : flash?.kind === 'error' ? 'error'
    : flash?.kind === 'finished' ? 'finished'
    : thinking ? 'thinking'
    : running > 0 ? 'working'
    : 'idle';

  // Window size follows view + approvals: tucked sliver, petit tab, home card.
  useEffect(() => {
    const want = view === 'home' ? (approvals.length > 0 ? 'home-expanded' : 'home') : view === 'petit' ? 'petit' : 'tuck';
    if (want !== sizeRef.current) {
      sizeRef.current = want;
      void window.ankita.islandAction(want).catch(() => {});
    }
  }, [view, approvals.length]);

  // Alerts answered → tuck back only if home opened itself for them.
  useEffect(() => {
    if (approvals.length === 0 && autoHome.current && view === 'home') closeHome();
    if (approvals.length === 0 && autoHome.current) tuckSoon();
  }, [approvals.length, view, closeHome, tuckSoon]);

  // State-change jingles, Coucou-style (each state announces itself once).
  const prevState = useRef(botState);
  useEffect(() => {
    if (botState === prevState.current) return;
    prevState.current = botState;
    if (botState === 'approval') playSound('approval');
    else if (botState === 'error') playSound('error');
    else if (botState === 'finished') playSound('finish');
    else if (botState === 'working') playSound('work');
    else if (botState === 'thinking') playSound('think');
  }, [botState]);

  const answer = useCallback(async (requestId: string, result: 'yes' | 'no' | 'always') => {
    playSound(result === 'no' ? 'blip' : 'approve');
    setTools(current => current.filter(item => item.requestId !== requestId));
    try { await window.ankita.invoke('respondApproval', { requestId, answer: result }); } catch { /* engine already settled it */ }
  }, []);

  // Escape tucks home back to the petit tab (and petit back above the edge);
  // Y / N answers the top approval.
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (view === 'home') {
        if (event.key === 'Escape') closeHome();
        else if ((event.key === 'y' || event.key === 'Y') && approvals.length > 0) void answer(approvals[0].requestId, 'yes');
        else if ((event.key === 'n' || event.key === 'N') && approvals.length > 0) void answer(approvals[0].requestId, 'no');
      } else if (view === 'petit' && event.key === 'Escape') {
        autoHome.current = false;
        setView('tucked');
      }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [view, closeHome, approvals, answer]);

  const runningJobs = jobs.filter(job => job.running);

  if (view !== 'home') {
    const tucked = view === 'tucked';
    return (
      <div
        className="island island-petit"
        onClick={() => { playSound('open'); openHome(false); }}
        onMouseEnter={() => { cancelTuck(); if (tucked) { playSound('peek'); openPetit(); } }}
        onMouseLeave={() => { if (!tucked) tuckSoon(); }}
        role="button" tabIndex={-1} aria-label="Open Ankita island" title="Click to open"
      >
        <div className="island-row">
          <div className="island-mascot" ref={mascotBox} onClick={event => event.stopPropagation()}>
            <div className="island-glow" style={{ background: `radial-gradient(circle, ${STATE_GLOW[botState]} 0%, transparent 70%)` }} />
            <Mascot state={botState} lookRef={lookRef} size={MASCOT_PETIT_PX} awake={!tucked} />
          </div>
          <div className="island-status">
            <strong>Ankita</strong>
            <span key={status} className="island-status-text">{status}</span>
          </div>
          {approvals.length > 0 && <span className="island-badge">{approvals.length}</span>}
        </div>
      </div>
    );
  }

  return (
    <div
      className="island island-home island-wash"
      style={{ '--wash': STATE_GLOW[botState] } as CSSProperties}
    >
      <div className="island-row" onClick={toggleFromHeader} role="button" tabIndex={-1} aria-label={expanded ? 'Collapse island' : 'Open Ankita'} title={expanded ? 'Click to collapse' : 'Click to open Ankita'}>
        <div className="island-mascot" ref={mascotBox}>
          <div className={`island-glow${approvals.length > 0 ? ' island-glow-pulse' : ''}`} style={{ background: `radial-gradient(circle, ${STATE_GLOW[botState]} 0%, transparent 70%)` }} />
          <Mascot state={botState} lookRef={lookRef} size={MASCOT_HOME_PX} awake />
        </div>
        <div className="island-status">
          <strong>Ankita</strong>
          <span key={status} className="island-status-text">{status}</span>
        </div>
        {approvals.length > 0 && <span className="island-badge">{approvals.length}</span>}
        <button className="island-collapse" onClick={closeHome} aria-label="Collapse island" title="Collapse (Esc)">▾</button>
      </div>
      {/* The body only fits the expanded window; a quiet home card is
          header-only so nothing renders cut off inside the compact window. */}
      {expanded && (
      <div className="island-body">
        {runningJobs.slice(0, 3).map((job, i) => (
          <div className="island-job" key={job.id} style={{ animationDelay: `${i * 70}ms` }}>
            <span className="island-job-dots" aria-hidden="true"><i /><i /><i /></span>
            <span className="island-job-name">{job.name || 'Job'}</span>
            <span className="island-job-step">{job.lastStatus || 'running'}</span>
          </div>
        ))}
        {approvals.slice(0, 2).map(item => (
          <div className="island-approval" key={item.requestId}>
            <div className="island-who">
              <span className="dot" style={{ background: '#f5a524' }} />
              <span className="n">{item.toolName}</span>
              <span className="t">needs permission</span>
            </div>
            <div className="island-code">{item.detail}</div>
            <div className="island-actions">
              <button className="island-deny" onClick={() => void answer(item.requestId, 'no')}>Deny <span className="island-kbd">N</span></button>
              <button className="island-allow" onClick={() => void answer(item.requestId, 'yes')}>Allow <span className="island-kbd">Y</span></button>
            </div>
          </div>
        ))}
        {runningJobs.length === 0 && approvals.length === 0 && (
          <div className="island-quiet">Nothing running — jobs and approvals appear here.</div>
        )}
        <button className="island-open" onClick={restore}>Open Ankita ↗</button>
      </div>
      )}
    </div>
  );
}
