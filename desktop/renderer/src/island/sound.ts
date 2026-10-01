// Original synthesized sound effects for the island.
// Coucou plays 28 handcrafted WAVs at these same cue points, but those files
// are proprietary artwork (LICENSE-ASSETS) and cannot be copied — so every cue
// here is synthesized live with WebAudio: same timing and purpose, original
// sound. No assets, no downloads, works offline.
//
// Volume mirrors Coucou's player (0.12 master). Browsers start AudioContext
// suspended before the first user gesture, so cues that fire before the first
// click are silently skipped; a pointerdown listener unlocks audio on contact.

export type SoundCue =
  | 'peek' | 'open' | 'close' | 'hover' | 'blip' | 'slap' | 'annoyed' | 'dizzy' | 'greet'
  | 'work' | 'finish' | 'error' | 'approval' | 'question' | 'approve' | 'gulp' | 'tick'
  | 'send' | 'love' | 'pop' | 'proud' | 'wink' | 'yawn' | 'attach' | 'think' | 'search'
  | 'rate' | 'sleep';

const MASTER_VOLUME = 0.12; // Coucou's default player volume.

let ctx: AudioContext | null = null;
let master: GainNode | null = null;
let unlockAttached = false;

function audio(): AudioContext | null {
  try {
    if (!ctx) {
      const Ctor = window.AudioContext
        ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!Ctor) return null;
      ctx = new Ctor();
      master = ctx.createGain();
      master.gain.value = MASTER_VOLUME;
      master.connect(ctx.destination);
    }
    if (ctx.state === 'suspended') void ctx.resume();
    if (!unlockAttached) {
      unlockAttached = true;
      window.addEventListener('pointerdown', () => { if (ctx?.state === 'suspended') void ctx.resume(); }, { once: true });
    }
    return ctx.state === 'suspended' ? null : ctx;
  } catch {
    return null;
  }
}

type ToneOpts = {
  type: OscillatorType;
  from: number;
  to?: number;
  dur: number;
  at?: number;
  vol?: number;
};

function tone(opts: ToneOpts): void {
  const c = audio();
  if (!c || !master) return;
  const t0 = c.currentTime + (opts.at ?? 0);
  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.type = opts.type;
  osc.frequency.setValueAtTime(Math.max(1, opts.from), t0);
  if (opts.to !== undefined) osc.frequency.exponentialRampToValueAtTime(Math.max(1, opts.to), t0 + opts.dur);
  gain.gain.setValueAtTime(0.0001, t0);
  gain.gain.exponentialRampToValueAtTime(opts.vol ?? 1, t0 + 0.012);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + opts.dur);
  osc.connect(gain);
  gain.connect(master);
  osc.start(t0);
  osc.stop(t0 + opts.dur + 0.05);
}

function arpeggio(freqs: number[], type: OscillatorType, noteDur: number, step: number): void {
  freqs.forEach((freq, i) => tone({ type, from: freq, dur: noteDur, at: i * step }));
}

const RECIPES: Record<SoundCue, () => void> = {
  peek: () => tone({ type: 'sine', from: 520, to: 700, dur: 0.08 }),
  open: () => tone({ type: 'sine', from: 440, to: 660, dur: 0.09 }),
  close: () => tone({ type: 'sine', from: 660, to: 440, dur: 0.09 }),
  hover: () => tone({ type: 'sine', from: 700, to: 900, dur: 0.05, vol: 0.4 }),
  blip: () => tone({ type: 'square', from: 660, to: 880, dur: 0.07, vol: 0.5 }),
  slap: () => tone({ type: 'square', from: 160, to: 90, dur: 0.09, vol: 0.8 }),
  annoyed: () => tone({ type: 'sawtooth', from: 220, to: 170, dur: 0.16, vol: 0.5 }),
  dizzy: () => {
    tone({ type: 'sine', from: 420, to: 180, dur: 0.4 });
    tone({ type: 'sine', from: 630, to: 270, dur: 0.4, at: 0.05, vol: 0.6 });
  },
  greet: () => {
    tone({ type: 'sine', from: 523, dur: 0.12 });
    tone({ type: 'sine', from: 784, dur: 0.14, at: 0.11 });
  },
  work: () => tone({ type: 'sine', from: 600, to: 800, dur: 0.07, vol: 0.35 }),
  think: () => tone({ type: 'sine', from: 550, to: 750, dur: 0.08, vol: 0.35 }),
  search: () => tone({ type: 'triangle', from: 500, to: 900, dur: 0.1, vol: 0.4 }),
  finish: () => arpeggio([523, 659, 784], 'sine', 0.1, 0.08),
  error: () => tone({ type: 'square', from: 200, to: 120, dur: 0.2, vol: 0.5 }),
  approval: () => {
    tone({ type: 'triangle', from: 440, dur: 0.1 });
    tone({ type: 'triangle', from: 440, dur: 0.1, at: 0.14 });
  },
  approve: () => {
    tone({ type: 'sine', from: 880, dur: 0.08 });
    tone({ type: 'sine', from: 1320, dur: 0.1, at: 0.07 });
  },
  question: () => tone({ type: 'triangle', from: 600, to: 800, dur: 0.12 }),
  gulp: () => tone({ type: 'sine', from: 300, to: 150, dur: 0.15 }),
  tick: () => tone({ type: 'square', from: 1000, dur: 0.03, vol: 0.3 }),
  send: () => tone({ type: 'sine', from: 700, to: 1100, dur: 0.08 }),
  love: () => {
    tone({ type: 'sine', from: 660, to: 990, dur: 0.1 });
    tone({ type: 'sine', from: 990, to: 1320, dur: 0.12, at: 0.09 });
  },
  pop: () => tone({ type: 'sine', from: 500, to: 950, dur: 0.09 }),
  proud: () => arpeggio([392, 523, 659], 'triangle', 0.1, 0.08),
  wink: () => tone({ type: 'sine', from: 900, to: 600, dur: 0.08, vol: 0.4 }),
  yawn: () => tone({ type: 'sine', from: 300, to: 150, dur: 0.4, vol: 0.5 }),
  attach: () => tone({ type: 'triangle', from: 500, to: 700, dur: 0.08 }),
  rate: () => tone({ type: 'sawtooth', from: 300, to: 150, dur: 0.25, vol: 0.4 }),
  sleep: () => tone({ type: 'sine', from: 400, to: 200, dur: 0.5, vol: 0.4 }),
};

export function playSound(cue: SoundCue): void {
  try {
    RECIPES[cue]?.();
  } catch {
    // Audio must never break the island.
  }
}
