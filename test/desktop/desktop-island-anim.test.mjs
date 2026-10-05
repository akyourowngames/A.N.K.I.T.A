import test from 'node:test';
import assert from 'node:assert/strict';
import { Ease, cubicBezier, lerp, clamp, Spring, Tracked, makeCloseCurve } from '../../desktop/shared/anim.mjs';

test('easing functions span 0 to 1', () => {
  for (const ease of [Ease.out, Ease.inOut, Ease.back, Ease.lin, Ease.easeIn]) {
    assert.ok(Math.abs(ease(0)) < 1e-9);
    assert.ok(Math.abs(ease(1) - 1) < 1e-9);
  }
  assert.ok(Ease.out(0.5) > 0.5);
  assert.ok(Ease.easeIn(0.5) < 0.5);
});

test('cubicBezier spans 0 to 1 and matches the close curve', () => {
  const ease = cubicBezier(0.4, 0, 0.2, 1);
  assert.ok(Math.abs(ease(0)) < 1e-9);
  assert.ok(Math.abs(ease(1) - 1) < 1e-3);
  assert.ok(ease(0.5) > 0 && ease(0.5) < 1);
  const close = makeCloseCurve();
  assert.ok(Math.abs(close(0.5) - cubicBezier(0.45, 0, 0.2, 1)(0.5)) < 1e-9);
});

test('lerp and clamp behave', () => {
  assert.equal(lerp(10, 20, 0.25), 12.5);
  assert.equal(clamp(99, 0, 10), 10);
  assert.equal(clamp(-5, 0, 10), 0);
});

test('spring settles on its target', () => {
  const spring = new Spring(0);
  spring.target = 100;
  for (let i = 0; i < 600 && !spring.settled; i++) spring.step(1 / 60);
  assert.ok(spring.settled);
  assert.ok(Math.abs(spring.value - 100) < 0.01);
});

test('tracked spring grows and curve shrinks without overshoot', () => {
  const tracked = new Tracked(76);
  tracked.springTo(232);
  assert.ok(tracked.animating);
  let min = Infinity;
  for (let i = 0; i < 600 && tracked.animating; i++) { tracked.step(1 / 60); min = Math.min(min, tracked.value); }
  assert.ok(Math.abs(tracked.value - 232) < 0.01);
  tracked.curveTowards(76, 340, 0);
  let now = 0;
  let lowest = Infinity;
  while (tracked.animating && now < 2000) { now += 1000 / 60; tracked.step(1 / 60, now); lowest = Math.min(lowest, tracked.value); }
  assert.ok(Math.abs(tracked.value - 76) < 0.05, 'close curve lands on the target');
  assert.ok(lowest >= 76 - 0.05, 'close curve never overshoots below the target');
  assert.ok(min >= 76 - 1, 'spring grow starts at the current value');
});

test('close curve is monotonic-ish from 0 to 1', () => {
  const curve = makeCloseCurve();
  assert.equal(curve(0), 0);
  assert.ok(Math.abs(curve(1) - 1) < 0.05);
  let prev = -Infinity;
  for (let i = 1; i <= 10; i++) {
    const v = curve(i / 10);
    assert.ok(v >= prev - 1e-9);
    prev = v;
  }
});
