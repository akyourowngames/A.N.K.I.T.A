// Typed easing helpers for the island mascot (renderer side).
// Mirrors desktop/shared/anim.mjs so the canvas engine stays dependency-free.

export type EaseFn = (t: number) => number;

export const Ease: Record<'out' | 'inOut' | 'back' | 'lin' | 'easeIn', EaseFn> = {
  out: t => 1 - Math.pow(1 - t, 3),
  inOut: t => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2),
  back: t => {
    const c1 = 1.7;
    const c3 = c1 + 1;
    return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
  },
  lin: t => t,
  easeIn: t => t * t * t,
};

export const lerp = (a: number, b: number, t: number): number => a + (b - a) * t;

/** cubic-bezier(x1,y1,x2,y2) solver — TS mirror of cubicBezier in
 * desktop/shared/anim.mjs (itself ported from Coucou's windows/src/core/anim.ts,
 * MIT License, (c) Louis Raille). Kept here so canvas code stays dependency-free. */
export function cubicBezier(x1: number, y1: number, x2: number, y2: number): EaseFn {
  const cx = (t: number) => ((1 - t) ** 2 * 3 * t * x1) + (3 * (1 - t) * t * t * x2) + t ** 3;
  const cy = (t: number) => ((1 - t) ** 2 * 3 * t * y1) + (3 * (1 - t) * t * t * y2) + t ** 3;
  return (x: number) => {
    let lo = 0, hi = 1, t = x;
    for (let i = 0; i < 12; i++) {
      if (cx(t) < x) lo = t;
      else hi = t;
      t = (lo + hi) / 2;
    }
    return cy(t);
  };
}

export type MascotState =
  | 'idle'
  | 'working'
  | 'thinking'
  | 'searching'
  | 'approval'
  | 'question'
  | 'error'
  | 'finished'
  | 'ratelimit'
  | 'sleeping'
  | 'dizzy';

export type MascotEmote = 'love' | 'surprised' | 'proud' | 'wink' | 'yawn' | 'happy' | 'annoyed';
