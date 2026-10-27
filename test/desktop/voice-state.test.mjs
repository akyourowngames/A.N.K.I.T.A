import test from 'node:test';
import assert from 'node:assert/strict';

const voice = await import('../../desktop/shared/voice.mjs').catch(() => ({}));

test('voice snapshots are independent, bounded and safe to send to both surfaces', () => {
  const initial = voice.emptyVoiceState();
  const next = voice.voiceStatePatch(initial, { active: true, sessionId: 'session', threadId: 'owner',
    phase: 'listening', inputLevel: 50, caption: 'word '.repeat(500), sarvamApiKey: 'must-not-leak' });
  assert.equal(initial.active, false);
  assert.equal(next.inputLevel, 1);
  assert.equal(next.sessionId, 'session');
  assert.equal(next.phase, 'listening');
  assert.ok(next.caption.length <= voice.VOICE_CAPTION_CHARS);
  assert.equal(next.revision, initial.revision + 1);
  assert.ok(!JSON.stringify(next).includes('must-not-leak'));
  assert.equal(voice.voiceStatePatch(next, { inputLevel: NaN }).inputLevel, 0);
  assert.equal(voice.voiceStatePatch(next, { phase: 'invented' }).phase, next.phase);
});

test('voice phase labels describe listening, work, pause and errors without a fake progress estimate', () => {
  for (const phase of ['starting', 'listening', 'transcribing', 'working', 'speaking', 'approval', 'paused', 'error']) {
    assert.ok(voice.VOICE_PHASE_LABELS[phase]);
  }
  assert.notEqual(voice.VOICE_ACTIONS.end, voice.VOICE_ACTIONS.cancel);
});
