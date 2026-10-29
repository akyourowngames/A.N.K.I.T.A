/** Disposable real-file round trip; player ownership is simulated, not physical audio. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { VoiceResourceBroker, canonicalVoicePath } from '../src/automation/voice-resources.mjs';
import { VoiceSpeechQueue } from '../src/automation/voice-speech-queue.mjs';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-parallel-live-'));
const tick = () => new Promise(resolve => setImmediate(resolve));
const broker = new VoiceResourceBroker();
let active = 0, peak = 0, release;
const bothStarted = new Promise(resolve => { release = resolve; });
try {
  const disjoint = async name => {
    const target = path.join(root, name);
    await broker.acquire(name, [{ kind: 'path', key: canonicalVoicePath(target), mode: 'write' }]);
    try {
      active++; peak = Math.max(peak, active); if (active === 2) release();
      await bothStarted; fs.writeFileSync(target, name); active--;
    } finally { broker.release(name); }
  };
  await Promise.all([disjoint('poem.txt'), disjoint('research.md')]);
  assert.equal(peak, 2);
  const shared = path.join(root, 'shared.txt'); fs.writeFileSync(shared, '0');
  const increment = async id => {
    await broker.acquire(id, [{ kind: 'path', key: canonicalVoicePath(shared), mode: 'write' }]);
    try { const previous = Number(fs.readFileSync(shared)); await tick(); fs.writeFileSync(shared, String(previous + 1)); }
    finally { broker.release(id); }
  };
  await Promise.all([increment('one'), increment('two')]);
  assert.equal(fs.readFileSync(shared, 'utf8'), '2');
  let players = 0, peakPlayers = 0; const heard = [];
  const speech = new VoiceSpeechQueue({ gapMs: 0, play: async audio => {
    players++; peakPlayers = Math.max(peakPlayers, players); heard.push(audio); await tick(); players--;
  } });
  await Promise.all(['poem', 'research'].map(jobId => speech.offer({ key: jobId, jobId, kind: 'report', prepare: async () => `${jobId} ready` })));
  await speech.close(); assert.equal(peakPlayers, 1); assert.equal(heard.length, 2);
  console.log('VOICE_PARALLEL_PRIMITIVES_OK', JSON.stringify({ independentPeak: peak, sharedValue: Number(fs.readFileSync(shared)), peakPlayers, reports: heard, audio: 'simulated player, no microphone or speaker' }));
} finally { fs.rmSync(root, { recursive: true, force: true }); }
