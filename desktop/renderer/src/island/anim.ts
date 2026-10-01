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
