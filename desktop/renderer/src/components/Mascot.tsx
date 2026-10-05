import { useEffect, useRef } from 'react';
import { MascotEngine, hexToRGB, type MascotState } from '../island/engine';
import { playSound } from '../island/sound';
import { useReducedMotion } from '../lib/useReducedMotion';
import { interactionFrame } from '../../../shared/mascot-interaction.mjs';
import type { MascotInteraction } from '../lib/useMascotInteraction';

/** Mutable cursor-look target shared without re-rendering ({ x, y } in -1…1). */
export type LookRef = { current: { x: number; y: number } };

const MASCOT_PX = 52; // CSS pixels; must fit the compact bar (see island.css).
const HOVER_LOVE_MS = 2000; // Rest the pointer on the mascot this long → hearts.
const LOVE_COOLDOWN_MS = 8000;
const DIZZY_MS = 2200; // Three fast clicks → dizzy, then back to the live state.
const GREETING_DELAY_MS = 350; // Milliseconds; let the reveal settle before waving.
const MAX_DPR = 2; // Canvas pixels per CSS pixel; bound GPU memory on scaled displays.
const MAX_FRAME_SECONDS = 0.05; // Seconds; prevent a background pause from advancing a large frame.
const MS_PER_SECOND = 1000; // Conversion from RAF milliseconds to engine seconds.
const GRAB_SPARKS = 5; // Particles; a short source-window sparkle trail when picked up.

let greetedOnce = false; // The launch wave plays once per renderer load.

export function Mascot({ state, lookRef, size = MASCOT_PX, awake = true, interaction, color }: { state: MascotState; lookRef: LookRef; size?: number; awake?: boolean; interaction?: MascotInteraction; color?: string }) {
  const reducedMotion = useReducedMotion();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<MascotEngine | null>(null);
  const stateRef = useRef(state);
  const dizzyUntil = useRef(0);
  const hoverTimer = useRef<number | null>(null);
  const lastLove = useRef(0);
  const dizzyTimer = useRef<number | null>(null);
  const interactionRef = useRef(interaction);
  interactionRef.current = interaction;
  stateRef.current = state;

  if (!engineRef.current) {
    const engine = new MascotEngine();
    engine.onDizzy = () => {
      engine.setState('dizzy');
      playSound('dizzy');
      dizzyUntil.current = performance.now() + DIZZY_MS;
      if (dizzyTimer.current !== null) window.clearTimeout(dizzyTimer.current);
      dizzyTimer.current = window.setTimeout(() => engine.setState(stateRef.current), DIZZY_MS);
    };
    engineRef.current = engine;
  }

  // Greeting wave on first reveal (not while tucked above the edge).
  useEffect(() => {
    const engine = engineRef.current;
    if (!engine) return;
    engine.bodyColor = color && /^#[0-9a-f]{6}$/i.test(color) ? hexToRGB(color) : null;
    if (!reducedMotion) engine.squash();
  }, [color, reducedMotion]);

  useEffect(() => {
    if (!awake || reducedMotion || greetedOnce) return;
    const timer = window.setTimeout(() => { greetedOnce = true; engineRef.current?.greet(); }, GREETING_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [awake, reducedMotion]);

  // Live state from the app (approvals, jobs, flashes). Dizzy wins while active.
  useEffect(() => {
    if (reducedMotion) return;
    if (interaction?.phase === 'grab') engineRef.current?.emit('spark', GRAB_SPARKS);
    if (interaction?.phase === 'success') engineRef.current?.triggerEmote('happy');
  }, [interaction?.phase, reducedMotion]);
  useEffect(() => {
    if (performance.now() < dizzyUntil.current) return;
    engineRef.current?.setState(state);
    if (state === 'finished' && !reducedMotion) engineRef.current?.triggerEmote('happy');
  }, [state, reducedMotion]);

  // RAF loop; paused while the page is hidden so idle costs nothing.
  useEffect(() => {
    const canvas = canvasRef.current;
    const engine = engineRef.current;
    if (!canvas || !engine) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = Math.min(MAX_DPR, window.devicePixelRatio || 1);
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    let raf = 0;
    let last = performance.now();
    let running = awake && !document.hidden && !reducedMotion;
    const draw = () => {
      const current = interactionRef.current;
      engine.interaction = interactionFrame(current?.phase || 'rest', current ? performance.now() - current.started : 0, reducedMotion);
      ctx.clearRect(0, 0, size, size); engine.draw(ctx, size, size);
    };
    draw();
    const frame = (t: number) => {
      if (!running) return;
      const dt = Math.min(MAX_FRAME_SECONDS, (t - last) / MS_PER_SECOND);
      last = t;
      engine.lookX = lookRef.current.x;
      engine.lookY = lookRef.current.y;
      engine.update(dt);
      draw();
      raf = requestAnimationFrame(frame);
    };
    const onVis = () => {
      if (document.hidden || !awake || reducedMotion) { running = false; cancelAnimationFrame(raf); }
      else if (!running) { running = true; last = performance.now(); raf = requestAnimationFrame(frame); }
    };
    document.addEventListener('visibilitychange', onVis);
    if (running) raf = requestAnimationFrame(frame);
    return () => { running = false; cancelAnimationFrame(raf); document.removeEventListener('visibilitychange', onVis); };
  }, [lookRef, size, awake, reducedMotion, state, interaction?.phase, color]);

  // Hover → love; click → slap (squish + annoyed, dizzy on the third fast one).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const startHover = () => {
      if (reducedMotion) return;
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
  }, [reducedMotion]);

  useEffect(() => () => {
    if (dizzyTimer.current !== null) window.clearTimeout(dizzyTimer.current);
    engineRef.current?.interruptGreet();
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="island-mascot-canvas"
      style={{ width: size, height: size }}
      aria-hidden="true"
      data-interaction={interaction?.phase || 'rest'}
      onClick={event => { event.stopPropagation(); if (!reducedMotion) engineRef.current?.slap(); }}
    />
  );
}
