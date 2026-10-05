import { useCallback, useEffect, useRef, useState } from 'react';
import { INTERACTION_MS, type InteractionPhase } from '../../../shared/mascot-interaction.mjs';
import { FILE_ACTIVITY_EVENT } from '../../../browser-helper/protocol.mjs';
import { useReducedMotion } from './useReducedMotion';

export type MascotInteraction = { phase: InteractionPhase; started: number; label: string };
export function useMascotInteraction(threadId: string | null) {
  const reduced = useReducedMotion();
  const [interaction, setInteraction] = useState<MascotInteraction>({ phase: 'rest', started: 0, label: '' });
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const gulpEnd = useRef(0);
  const reset = useCallback(() => { if (timer.current) clearTimeout(timer.current); timer.current = null; gulpEnd.current = 0; setInteraction({ phase: 'rest', started: performance.now(), label: '' }); }, []);
  const pose = useCallback((phase: InteractionPhase, label = '') => {
    if (timer.current) clearTimeout(timer.current);
    const now = performance.now();
    const start = () => {
      setInteraction({ phase, started: performance.now(), label });
      if (phase === 'success' || phase === 'error') timer.current = setTimeout(reset, reduced ? 0 : INTERACTION_MS[phase]);
    };
    if (phase === 'gulp') {
      gulpEnd.current = now + (reduced ? 0 : INTERACTION_MS.gulp);
      start(); timer.current = setTimeout(() => { setInteraction({ phase: 'reading', started: performance.now(), label }); }, reduced ? 0 : INTERACTION_MS.gulp);
    } else if ((phase === 'success' || phase === 'error') && now < gulpEnd.current) timer.current = setTimeout(start, gulpEnd.current - now);
    else start();
  }, [reduced, reset]);
  useEffect(() => {
    reset();
    const activity = (event: Event) => { const detail = (event as CustomEvent).detail; if (detail.threadId === threadId) pose(detail.phase, detail.label); };
    window.addEventListener(FILE_ACTIVITY_EVENT, activity);
    return () => { window.removeEventListener(FILE_ACTIVITY_EVENT, activity); if (timer.current) clearTimeout(timer.current); };
  }, [threadId, pose, reset]);
  return { interaction, pose, reset };
}
