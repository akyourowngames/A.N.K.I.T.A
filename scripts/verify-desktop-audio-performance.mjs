import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { performance } from 'node:perf_hooks';
import { DesktopVoice } from '../desktop/electron/voice.mjs';
import { loadConfig } from '../src/core/config.mjs';
import { synthesizeSarvam, playMp3 } from '../src/channels/voice.mjs';
import { isPrivateAudioOutput } from '../src/channels/audio-device.mjs';

const HEARTBEAT_MS = 20; // Measurement interval, not a production timing guarantee.
const WAIT_MS = 20000; // Fixture deadline for actual microphone startup.
const QUIET_CHECK_MS = 700; // Observe resumed input after the playback guard drains.
const TEST_LINE = 'This is the speaker feedback check. I will listen again after this reply.';
const args = process.argv.slice(2), envIndex = args.indexOf('--env');
const config = loadConfig(envIndex < 0 ? undefined : path.resolve(args[envIndex + 1]));
const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-audio-performance-'));
let nativeApp;
if (process.versions.electron) {
  const native = await import('electron'); nativeApp = native.app;
  nativeApp.setPath('userData', path.join(directory, 'native-profile'));
  await nativeApp.whenReady();
}
let voice, transcripts = 0, jobs = 0, played = 0;
const engine = { listTeammates: () => [{ id: 'audio-check' }], captureVoiceContext: () => ({}),
  runVoiceJob: async () => { jobs++; return { text: 'No action is run by the audio check.' }; }, deliverVoiceJob: async () => {} };
const until = async check => {
  const deadline = Date.now() + WAIT_MS;
  while (!check()) { assert.ok(Date.now() < deadline, 'Audio fixture timed out'); await new Promise(resolve => setTimeout(resolve, HEARTBEAT_MS)); }
};
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
voice = new DesktopVoice({ engine, getConfig: () => config, emit: () => {}, directory, io: args.includes('--play') ? {
  // Skip cached acknowledgement synthesis: this fixture speaks exactly one real line, without a planner.
  synthesizeSarvam: options => options.text === TEST_LINE ? synthesizeSarvam(options) : Promise.resolve(Buffer.alloc(0)),
  transcribeAudio: async () => { transcripts++; return { text: '' }; },
  playMp3: async (audio, options) => {
    assert.ok(!voice.current.input, 'capture must be closed before real speaker playback');
    played++; await playMp3(audio, options);
  },
} : {} });
let last = performance.now(), maxPause = 0, ticks = 0;
const timer = setInterval(() => {
  const now = performance.now(); maxPause = Math.max(maxPause, now - last - HEARTBEAT_MS); last = now; ticks++;
}, HEARTBEAT_MS);
try {
  await wait(HEARTBEAT_MS);
  const begin = performance.now();
  await Promise.all([voice.status(), voice.status()]);
  await wait(HEARTBEAT_MS);
  const cold = { wallMs: Math.round(performance.now() - begin), maxMainThreadPauseMs: Math.round(maxPause), heartbeatTicks: ticks, callers: 2 };
  const warm = performance.now(); await voice.status();
  console.log('AUDIO_PERFORMANCE_OK', JSON.stringify({ runtime: process.versions.electron ? 'electron' : 'node', ...cold, warmStatusMs: Math.round(performance.now() - warm), workerRequests: voice.devices.sequence }));
  if (args.includes('--play')) {
    const hardware = await voice.devices.inspect();
    const speaker = hardware.devices.find(device => device.flow === 'render' && !isPrivateAudioOutput(device));
    assert.ok(speaker, 'Connect a speaker for the open-speaker echo test');
    config.voiceOutputDevice = speaker.id;
    await voice.start({ threadId: 'audio-check' });
    assert.equal(voice.current.bargeIn, false);
    await until(() => voice.current.input?.handle);
    await voice.current.input.handle.ready;
    const session = voice.current;
    const delivered = await session.speech.offer({ kind: 'report', jobId: 'speaker-check', turn: session.speech.turn,
      line: { text: TEST_LINE }, prepare: () => voice.synthesize(session, TEST_LINE, 'en-IN'), signal: session.audio.signal });
    assert.equal(delivered, true);
    await until(() => voice.current.input?.handle);
    await voice.current.input.handle.ready;
    await wait(QUIET_CHECK_MS);
    assert.equal(transcripts, 0, 'No recorded speaker feedback should reach transcription in a quiet room');
    assert.equal(jobs, 0);
    console.log('SPEAKER_ECHO_GUARD_LIVE_OK', JSON.stringify({ output: speaker.name, played, transcripts, jobs, listeningResumed: true }));
  }
} finally {
  clearInterval(timer); await voice.close(); fs.rmSync(directory, { recursive: true, force: true }); nativeApp?.quit();
}
