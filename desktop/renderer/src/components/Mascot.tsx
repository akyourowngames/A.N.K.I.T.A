import { useEffect, useRef } from 'react';
import { MascotEngine, type MascotState } from '../island/engine';
import { playSound } from '../island/sound';

/** Mutable cursor-look target shared without re-rendering ({ x, y } in -1…1). */
export type LookRef = { current: { x: number; y: number } };

const MASCOT_PX = 52; // CSS pixels; must fit the compact bar (see island.css).
const HOVER_LOVE_MS = 2000; // Rest the pointer on the mascot this long → hearts.
const LOVE_COOLDOWN_MS = 8000;
const DIZZY_MS = 2200; // Three fast clicks → dizzy, then back to the live state.

let greetedOnce = false; // The launch wave plays once per renderer load.

export function Mascot({ state, lookRef, size = MASCOT_PX, awake = true }: { state: MascotState; lookRef: LookRef; size?: number; awake?: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<MascotEngine | null>(null);
  const stateRef = useRef(state);
  const dizzyUntil = useRef(0);
  const hoverTimer = useRef<number | null>(null);
  const lastLove = useRef(0);
  stateRef.current = state;

  if (!engineRef.current) {
    const engine = new MascotEngine();
    engine.onDizzy = () => {
      engine.setState('dizzy');
      playSound('dizzy');
      dizzyUntil.current = performance.now() + DIZZY_MS;
      window.setTimeout(() => engine.setState(stateRef.current), DIZZY_MS);
    };
    engineRef.current = engine;
  }

  // Greeting wave on first reveal (not while tucked above the edge).
  useEffect(() => {
    if (!awake || greetedOnce) return;
    greetedOnce = true;
    const timer = window.setTimeout(() => engineRef.current?.greet(), 350);
    return () => window.clearTimeout(timer);
  }, [awake]);

  // Live state from the app (approvals, jobs, flashes). Dizzy wins while active.
  useEffect(() => {
    if (performance.now() < dizzyUntil.current) return;
    engineRef.current?.setState(state);
    if (state === 'finished') engineRef.current?.triggerEmote('happy');
  }, [state]);

  // RAF loop; paused while the page is hidden so idle costs nothing.
  useEffect(() => {
    const canvas = canvasRef.current;
    const engine = engineRef.current;
    if (!canvas || !engine) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = MASCOT_PX * dpr;
    canvas.height = MASCOT_PX * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    let raf = 0;
    let last = performance.now();
    let running = true;
    const frame = (t: number) => {
      if (!running) return;
      const dt = Math.min(0.05, (t - last) / 1000);
      last = t;
      engine.lookX = lookRef.current.x;
      engine.lookY = lookRef.current.y;
      engine.update(dt);
      ctx.clearRect(0, 0, MASCOT_PX, MASCOT_PX);
      engine.draw(ctx, MASCOT_PX, MASCOT_PX);
      raf = requestAnimationFrame(frame);
    };
    const onVis = () => {
      if (document.hidden) { running = false; cancelAnimationFrame(raf); }
      else if (!running) { running = true; last = performance.now(); raf = requestAnimationFrame(frame); }
    };
    document.addEventListener('visibilitychange', onVis);
    raf = requestAnimationFrame(frame);
    return () => { running = false; cancelAnimationFrame(raf); document.removeEventListener('visibilitychange', onVis); };
  }, [lookRef]);

  // Hover → love; click → slap (squish + annoyed, dizzy on the third fast one).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const startHover = () => {
      if (hoverTimer.current != null) return;
      hoverTimer.current = window.setTimeout(() => {
        hoverTimer.current = null;
        const t = performance.now();
        if (t - lastLove.current < LOVE_COOLDOWN_MS) return;
        lastLove.current = t;
        playSound('love');
        engineRef.current?.triggerEmote('love');
      }, HOVER_LOVE_MS);
    };
    const stopHover = () => {
      if (hoverTimer.current != null) { window.clearTimeout(hoverTimer.current); hoverTimer.current = null; }
    };
    canvas.addEventListener('mouseenter', startHover);
    canvas.addEventListener('mouseleave', stopHover);
    return () => { canvas.removeEventListener('mouseenter', startHover); canvas.removeEventListener('mouseleave', stopHover); stopHover(); };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="island-mascot-canvas"
      style={{ width: size, height: size }}
      aria-hidden="true"
      onClick={event => { event.stopPropagation(); engineRef.current?.slap(); }}
    />
  );
}
