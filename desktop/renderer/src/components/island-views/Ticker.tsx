// Rolling activity feed adapted from Coucou's windows/src/views/ticker.ts
// (MIT License, (c) Louis Raille). Three rows share one animation clock so bursts
// cannot overlap. Actual tool identities and states survive the visual roll.
import { useEffect, useRef, type CSSProperties } from 'react';
import { cubicBezier } from '../../island/anim';
import { useReducedMotion } from '../../lib/useReducedMotion';
import { Icon } from './icons';
import { TOOL_ICON, TOOL_STATUS, TOOL_ICON_SIZE_PX, TOOL_ICON_STROKE } from './ToolStep';

export type TickerStep = { id: string; text: string; state: keyof typeof TOOL_STATUS };
type RowKind = 'previous' | 'current' | 'incoming';
const ROW_HEIGHT_PX = 22; // CSS pixels; the two visible lines remain inside the focus card.
const VISIBLE_ROWS = 2; // Rows; older history stays available in the conversation.
const DURATION_MS = 380; // Milliseconds; Coucou's upward roll duration.
const MAX_QUEUE = 4; // Steps; bound rapid bursts while retaining the active transition.
const HISTORY_SCALE = 11.5 / 13; // Ratio; receding history is smaller than the current line.
const FADE_RATE = 1.35; // Ratio; the oldest line fades before it leaves the viewport.
const ease = cubicBezier(0.4, 0, 0.2, 1); // Coucou's ticker easing curve.
const ROW_KINDS: RowKind[] = ['previous', 'current', 'incoming']; // Stable DOM row identities.

function Row({ kind, rowRef }: { kind: RowKind; rowRef: (key: string, el: HTMLElement | null) => void }) {
  return <div className={'ticker-row ticker-row-' + kind} ref={el => rowRef(kind, el)}
    aria-hidden={kind !== 'current'} aria-live={kind === 'current' ? 'polite' : undefined} aria-atomic="true">
    <span className="ticker-icon">{Object.entries(TOOL_ICON).map(([state, name]) =>
      <span key={state} className={'ticker-state-' + state}><Icon name={name} size={TOOL_ICON_SIZE_PX} stroke={name === 'xmark' ? undefined : TOOL_ICON_STROKE} /></span>)}</span>
    <span className="ticker-text" ref={el => rowRef(kind + ':text', el)} />
  </div>;
}

export function Ticker({ steps }: { steps: TickerStep[] }) {
  const reducedMotion = useReducedMotion();
  const parts = useRef(new Map<string, HTMLElement | null>());
  const state = useRef({
    queue: [] as TickerStep[], startMs: null as number | null, displayId: null as string | null,
    previous: null as TickerStep | null, current: null as TickerStep | null, incoming: null as TickerStep | null,
  });
  const rowRef = (key: string, el: HTMLElement | null) => { parts.current.set(key, el); };

  useEffect(() => {
    let raf: number | null = null;
    const s = state.current;
    const write = (kind: RowKind, step: TickerStep | null) => {
      s[kind] = step;
      const row = parts.current.get(kind);
      const text = parts.current.get(kind + ':text');
      if (!row || !text) return;
      const label = step ? step.text + ', ' + TOOL_STATUS[step.state] : '';
      if (text.textContent !== (step?.text || '')) text.textContent = step?.text || '';
      row.dataset.state = step?.state || '';
      row.title = label;
      row.setAttribute('aria-label', label);
    };
    const place = (kind: RowKind, y: number, phase: number, opacity: number) => {
      const row = parts.current.get(kind);
      if (!row) return;
      row.style.transform = 'translateY(' + y + 'px) scale(' + (1 - phase * (1 - HISTORY_SCALE)) + ')';
      row.style.opacity = String(s[kind] ? opacity : 0);
    };
    const rest = () => {
      place('previous', 0, 1, 1);
      place('current', ROW_HEIGHT_PX, 0, 1);
      place('incoming', ROW_HEIGHT_PX * VISIBLE_ROWS, 0, 0);
    };
    const reset = () => {
      s.queue = [];
      s.startMs = null;
      s.displayId = steps.at(-1)?.id || null;
      write('previous', steps.at(-2) || null);
      write('current', steps.at(-1) || null);
      write('incoming', null);
      rest();
    };
    const byId = new Map(steps.map(step => [step.id, step]));
    const seenIndex = steps.findIndex(step => step.id === s.displayId);
    if (reducedMotion || seenIndex < 0) reset();
    else {
      // Results update existing rows immediately, including parallel tools still running.
      for (const kind of ROW_KINDS) write(kind, s[kind] ? byId.get(s[kind]!.id) || s[kind] : null);
      s.queue = s.queue.map(step => byId.get(step.id) || step);
      s.queue.push(...steps.slice(seenIndex + 1));
      s.displayId = steps.at(-1)?.id || null;
      if (s.queue.length > MAX_QUEUE) {
        s.queue = s.startMs === null ? s.queue.slice(-MAX_QUEUE) : [s.queue[0], ...s.queue.slice(-(MAX_QUEUE - 1))];
      }
      if (s.startMs === null) rest();
    }
    const frame = (nowMs: number) => {
      raf = null;
      if (document.hidden || reducedMotion || !s.queue.length) return;
      if (s.startMs === null) {
        write('incoming', s.queue[0]);
        s.startMs = nowMs;
      }
      const progress = Math.min(1, Math.max(0, (nowMs - s.startMs) / DURATION_MS));
      const eased = ease(progress);
      place('previous', -ROW_HEIGHT_PX * eased, 1, Math.max(0, 1 - progress * FADE_RATE));
      place('current', ROW_HEIGHT_PX * (1 - eased), eased, 1);
      place('incoming', ROW_HEIGHT_PX * (VISIBLE_ROWS - eased), 0, eased);
      if (progress === 1) {
        write('previous', s.current);
        write('current', s.incoming);
        write('incoming', null);
        s.queue.shift();
        s.startMs = null;
        rest();
      }
      if (s.queue.length) raf = requestAnimationFrame(frame);
    };
    const visibility = () => {
      if (raf !== null) cancelAnimationFrame(raf);
      raf = null;
      // Hidden companions settle to the newest tool instead of replaying stale activity.
      reset();
    };
    document.addEventListener('visibilitychange', visibility);
    if (!document.hidden && !reducedMotion && s.queue.length) raf = requestAnimationFrame(frame);
    return () => {
      if (raf !== null) cancelAnimationFrame(raf);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, [steps, reducedMotion]);

  return <div className="island-ticker" data-reduced-motion={reducedMotion} style={{
    '--ticker-row-height': ROW_HEIGHT_PX + 'px', '--ticker-visible-rows': VISIBLE_ROWS,
  } as CSSProperties}>
    {ROW_KINDS.map(kind => <Row kind={kind} key={kind} rowRef={rowRef} />)}
  </div>;
}
