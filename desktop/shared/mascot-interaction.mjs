export const INTERACTION_MS = Object.freeze({ rest: 0, anticipate: 0, grab: 0, gulp: 720, reading: 0, success: 760, error: 620 }); // Milliseconds; results wait for real extraction.
const REST = Object.freeze({ mouth: 0, sx: 1, sy: 1, tilt: 0, lift: 0, fileProgress: 0, done: false });
const MOTION = Object.freeze({ hungryMouth: .95, hungryWidth: 1.06, hungryHeight: 1.12, grabWidth: .88, grabHeight: 1.16, swallowWidth: .2, swallowHeight: .16, swallowClose: .72, chewMouth: .09, chewWidth: .04, chewSpeed: 18, bounce: .18, shake: .13, shakeCycles: 5 }); // Body-relative ratios; scale with canvas size.
const TAU = Math.PI * 2;
export function interactionFrame(phase, elapsedMs, reducedMotion = false) {
  const duration = INTERACTION_MS[phase] || 0;
  const progress = duration ? Math.min(1, Math.max(0, elapsedMs / duration)) : 0;
  const frame = { ...REST, done: duration > 0 && progress >= 1 };
  if (reducedMotion) return { ...frame, mouth: phase === 'anticipate' ? MOTION.hungryMouth : 0, fileProgress: phase === 'gulp' ? 1 : 0, done: duration > 0 };
  if (phase === 'anticipate') return { ...frame, mouth: MOTION.hungryMouth, sx: MOTION.hungryWidth, sy: MOTION.hungryHeight };
  if (phase === 'grab') return { ...frame, sx: MOTION.grabWidth, sy: MOTION.grabHeight, tilt: MOTION.shake };
  if (phase === 'gulp') {
    const pulse = Math.sin(progress * Math.PI);
    return { ...frame, mouth: MOTION.hungryMouth * Math.max(0, 1 - progress / MOTION.swallowClose), sx: 1 + pulse * MOTION.swallowWidth, sy: 1 - pulse * MOTION.swallowHeight, fileProgress: 1 - (1 - progress) ** 3 };
  }
  if (phase === 'reading') return { ...frame, mouth: MOTION.chewMouth, sx: 1 + Math.sin(elapsedMs / 1000 * MOTION.chewSpeed) * MOTION.chewWidth, sy: 1 - Math.sin(elapsedMs / 1000 * MOTION.chewSpeed) * MOTION.chewWidth };
  if (phase === 'success') return { ...frame, lift: -Math.sin(progress * Math.PI) * MOTION.bounce, sy: 1 + Math.sin(progress * TAU) * MOTION.chewWidth };
  if (phase === 'error') return { ...frame, mouth: Math.sin(progress * Math.PI) * MOTION.chewMouth, tilt: Math.sin(progress * TAU * MOTION.shakeCycles) * MOTION.shake * (1 - progress) };
  return frame;
}
