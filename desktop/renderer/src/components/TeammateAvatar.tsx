import type { CSSProperties } from 'react';

// Stable expressions come from teammate identity, without a canvas or render loop per row.
const EXPRESSION_COUNT = 3; // Expressions; neutral, curious and cheerful faces.
const APP_AVATAR_ID = 'ankita'; // Stable visual identity for app branding, independent of saved teammates.
export function TeammateAvatar({ id = APP_AVATAR_ID, color, className = '' }: { id?: string; color?: string; className?: string }) {
  const expression = [...id].reduce((sum, char) => sum + char.charCodeAt(0), 0) % EXPRESSION_COUNT;
  return <span className={`teammate-face ${className}`} data-expression={expression} style={{ '--face-color': color } as CSSProperties} aria-hidden="true"><i /><i /></span>;
}
