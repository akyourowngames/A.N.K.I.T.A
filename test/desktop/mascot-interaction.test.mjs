import test from 'node:test';
import assert from 'node:assert/strict';

const motion = await import('../../desktop/shared/mascot-interaction.mjs').catch(() => null);
test('file anticipation opens a large mouth without claiming completion', () => {
  assert.ok(motion, 'mascot interaction timeline is implemented');
  const frame = motion.interactionFrame('anticipate', 0);
  assert.ok(frame.mouth > 0.8);
  assert.equal(frame.done, false);
});
test('swallow closes only after the file crosses the mouth; reading stays live', () => {
  assert.ok(motion, 'mascot interaction timeline is implemented');
  const start = motion.interactionFrame('gulp', 0);
  const end = motion.interactionFrame('gulp', motion.INTERACTION_MS.gulp);
  assert.equal(start.fileProgress, 0);
  assert.equal(end.fileProgress, 1);
  assert.ok(start.mouth > end.mouth);
  assert.equal(end.done, true);
  assert.equal(motion.interactionFrame('reading', 10000).done, false);
});
test('result returns to rest and reduced motion skips the swallow', () => {
  assert.ok(motion, 'mascot interaction timeline is implemented');
  assert.equal(motion.interactionFrame('success', motion.INTERACTION_MS.success).done, true);
  const frame = motion.interactionFrame('gulp', 0, true);
  assert.equal(frame.done, true);
  assert.equal(frame.fileProgress, 1);
  assert.equal(frame.sx, 1);
});
