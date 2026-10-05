/**
 * Easing + spring helpers for island motion.
 * Ported from Coucou's windows/src/core/anim.ts (MIT License, (c) Louis Raille),
 * which mirrors the macOS SwiftUI springs so open/close motion has the same feel.
 */

export const Ease = {
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

export const lerp = (a, b, t) => a + (b - a) * t;
export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/** SwiftUI-equivalent spring, sub-stepped so a dropped frame never destabilises it. */
export class Spring {
  constructor(value, response = 0.5, damping = 0.72) {
    this.value = value;
    this.target = value;
    this.velocity = 0;
    this.omega = (2 * Math.PI) / response;
    this.zeta = damping;
  }

  configure(response, damping) {
    this.omega = (2 * Math.PI) / response;
    this.zeta = damping;
  }

  set(value) {
    this.value = value;
    this.target = value;
    this.velocity = 0;
  }

  get settled() {
    return Math.abs(this.target - this.value) < 0.01 && Math.abs(this.velocity) < 0.05;
  }

  step(dt) {
    const steps = Math.max(1, Math.ceil(dt / (1 / 240)));
    const h = dt / steps;
    for (let i = 0; i < steps; i++) {
      const acc = this.omega * this.omega * (this.target - this.value)
        - 2 * this.zeta * this.omega * this.velocity;
      this.velocity += acc * h;
      this.value += this.velocity * h;
    }
  }
}

/**
 * Value driven by a spring (grow) or a timed close curve (shrink, no overshoot).
 * Drives the island window height animation in the main process.
 */
export class Tracked {
  constructor(value) {
    this.spring = new Spring(value);
    this.curveFrom = 0;
    this.curveTo = 0;
    this.curveStart = 0;
    this.curveDur = 0;
    this.mode = 'idle';
    // Close curve (.45,0,.2,1), 340 ms — matches Coucou's IslandContainer.
    this.closeCurve = makeCloseCurve();
  }

  get value() {
    return this.spring.value;
  }

  get animating() {
    return this.mode !== 'idle';
  }

  jump(v) {
    this.spring.set(v);
    this.mode = 'idle';
  }

  springTo(v, response = 0.5, damping = 0.72) {
    this.spring.configure(response, damping);
    this.spring.target = v;
    this.mode = 'spring';
  }

  curveTowards(v, durationMs = 340, nowMs = Date.now()) {
    this.curveFrom = this.spring.value;
    this.curveTo = v;
    this.curveStart = nowMs;
    this.curveDur = durationMs;
    this.spring.target = v;
    this.spring.velocity = 0;
    this.mode = 'curve';
  }

  step(dt, nowMs = Date.now()) {
    if (this.mode === 'spring') {
      this.spring.step(dt);
      if (this.spring.settled) {
        this.spring.value = this.spring.target;
        this.spring.velocity = 0;
        this.mode = 'idle';
      }
    } else if (this.mode === 'curve') {
      const p = clamp((nowMs - this.curveStart) / this.curveDur, 0, 1);
      this.spring.value = lerp(this.curveFrom, this.curveTo, this.closeCurve(p));
      if (p >= 1) {
        this.spring.velocity = 0;
        this.mode = 'idle';
      }
    }
  }
}

/** cubic-bezier(x1,y1,x2,y2) solver — bisection on x, 12 iterations.
 * Ported from Coucou's windows/src/core/anim.ts (MIT License, (c) Louis Raille). */
export function cubicBezier(x1, y1, x2, y2) {
  const cx = t => ((1 - t) ** 2 * 3 * t * x1) + (3 * (1 - t) * t * t * x2) + t ** 3;
  const cy = t => ((1 - t) ** 2 * 3 * t * y1) + (3 * (1 - t) * t * t * y2) + t ** 3;
  return x => {
    let lo = 0, hi = 1, t = x;
    for (let i = 0; i < 12; i++) {
      const v = cx(t);
      if (v < x) lo = t;
      else hi = t;
      t = (lo + hi) / 2;
    }
    return cy(t);
  };
}

/** Close curve (.45,0,.2,1), 340 ms — matches Coucou's IslandContainer. */
export function makeCloseCurve() {
  return cubicBezier(0.45, 0, 0.2, 1);
}
