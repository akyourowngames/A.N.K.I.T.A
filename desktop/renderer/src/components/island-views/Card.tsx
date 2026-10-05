// Shared island card pieces — React ports of the helpers in Coucou's
// windows/src/views/views.ts (MIT License, (c) Louis Raille): card wash,
// pill buttons, and the coloured dot + name + label "who" row.

import type { CSSProperties, ReactNode } from 'react';

/** Card wash colours (Coucou's CardBackground.washColor). */
export type Wash = 'red' | 'green' | 'pink' | 'amber' | 'cyan' | 'indigo' | 'soft' | null;

const WASH_RGBA: Record<Exclude<Wash, null>, string> = {
  red: 'rgba(244,80,94,0.55)',
  green: 'rgba(52,211,153,0.5)',
  pink: 'rgba(244,114,182,0.55)',
  amber: 'rgba(245,165,36,0.42)',
  cyan: 'rgba(34,211,238,0.38)',
  indigo: 'rgba(99,102,241,0.5)',
  soft: 'rgba(255,255,255,0.08)',
};

export function washStyle(wash: Wash): CSSProperties {
  if (!wash) return {};
  return { '--wash': WASH_RGBA[wash] } as CSSProperties;
}

export function Card({ wash, className, children }: { wash: Wash; className?: string; children: ReactNode }) {
  return (
    <div className={`island-card${className ? ` ${className}` : ''}`} style={washStyle(wash)}>
      {children}
    </div>
  );
}

export function Dot({ color, size = 8 }: { color: string; size?: number }) {
  return <span className="dot" style={{ width: size, height: size, background: color }} />;
}

/** AgentWho — coloured dot + task name + grey label. */
export function WhoRow({ color, name, label }: { color: string | null; name: string | null; label: string }) {
  return (
    <div className="island-who">
      {color && <Dot color={color} />}
      {name && <span className="n">{name}</span>}
      <span className="t">{label}</span>
    </div>
  );
}

export function PillBtn({
  kind, kbd, onClick, children, disabled = false,
}: {
  kind: 'primary' | 'secondary';
  kbd?: string;
  onClick: () => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  // island-btn carries the full pill shape so the button looks right anywhere;
  // island-allow/island-deny only tint it (kept for the action-row selectors).
  return (
    <button disabled={disabled} className={`island-btn ${kind === 'primary' ? 'island-allow' : 'island-deny'}`} onClick={onClick}>
      {children}
      {kbd && <span className="island-kbd" aria-hidden="true">{kbd}</span>}
    </button>
  );
}
