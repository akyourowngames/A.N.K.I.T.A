// Scheduler turn card — a job run's output as one compact collapsible row:
// status dot + job name + status · time, tap to unfold the full markdown.
// Keeps stacked runs scannable instead of one long blob.

import { useRef, useState, type ReactNode } from 'react';
import { Dot } from './Card';
import { Icon } from './icons';

function statusColor(status: string): string {
  const s = status.toLowerCase();
  if (s.includes('fail') || s.includes('error')) return '#F4505E';
  if (s.includes('ok') || s.includes('finish') || s.includes('done') || s.includes('complete')) return '#34D399';
  return '#F5A524';
}

/** HH:MM UTC from an ISO timestamp; empty when unparseable. */
export function shortTime(at: string): string {
  const ms = Date.parse(at);
  if (Number.isNaN(ms)) return '';
  return `${new Date(ms).toISOString().slice(11, 16)} UTC`;
}

export function TurnCard({
  name, status, at, children,
}: {
  name: string;
  status: string;
  at: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const bodyRef = useRef<HTMLDivElement>(null);
  const color = statusColor(status);
  const meta = [status, shortTime(at)].filter(Boolean).join(' · ');
  return (
    <div className="turn-card">
      <button
        className="turn-head"
        aria-expanded={open}
        aria-label={`${name}, ${meta || 'run output'}. ${open ? 'Collapse' : 'Expand'}`}
        onClick={event => {
          event.stopPropagation();
          setOpen(was => !was);
          // Reveal the unfolded body inside the scrolling log.
          window.requestAnimationFrame(() => bodyRef.current?.scrollIntoView({ block: 'nearest' }));
        }}
      >
        <Dot color={color} size={6} />
        <span className="turn-name">{name}</span>
        {meta && <span className="turn-meta">{meta}</span>}
        <span className={`turn-chev${open ? ' open' : ''}`}><Icon name="chevronRight" size={9} stroke={2.4} /></span>
      </button>
      <div ref={bodyRef} className={`turn-body${open ? ' open' : ''}`}>
        <div className="turn-body-inner">{children}</div>
      </div>
    </div>
  );
}
