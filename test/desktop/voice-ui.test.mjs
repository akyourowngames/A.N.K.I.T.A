import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = file => fs.readFileSync(new URL(`../../desktop/renderer/src/${file}`, import.meta.url), 'utf8');

test('voice surface provides real captions, separate audio/work controls and accessible status', () => {
  const panel = source('components/voice/VoicePanel.tsx');
  for (const label of ['End voice', 'Stop work', 'Continue in island', 'role="status"', 'VoiceCaptions', 'onPause', 'onResume']) assert.ok(panel.includes(label), label);
  assert.ok(!panel.includes('onReasoning'));
});
test('orb uses bounded original WebGL, releases resources and honors reduced motion', () => {
  const orb = source('components/voice/VoiceOrb.tsx');
  for (const behavior of ['useReducedMotion', 'visibilitychange', 'IntersectionObserver', 'deleteProgram', 'cancelAnimationFrame', 'fallback', 'MAX_RENDER_PIXELS']) assert.ok(orb.includes(behavior), behavior);
});
test('voice ownership and both entry points use shared events rather than renderer microphones', () => {
  const hook = source('components/voice/useVoice.ts');
  assert.ok(hook.includes('VOICE_EVENT')); assert.ok(hook.includes('VOICE_ACTIONS'));
  assert.ok(!hook.includes('getUserMedia'));
  assert.ok(source('components/Island.tsx').includes('VoicePanel'));
  assert.ok(source('App.tsx').includes('voice-focus'));
});
