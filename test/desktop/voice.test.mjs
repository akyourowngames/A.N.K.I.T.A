import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';

const module_ = await import('../../desktop/electron/voice.mjs').catch(() => ({}));
const WAIT_MS = 2500; // Fixture deadline; hardware/cloud are supplied as controlled IO.
const defer = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
async function until(check) {
  const end = Date.now() + WAIT_MS;
  while (!check()) { assert.ok(Date.now() < end, 'condition timed out'); await new Promise(resolve => setTimeout(resolve, 5)); }
}
function harness(t, { run, synthesize, barge = false, play, transcribe, open } = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'desktop-voice-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const config = { provider: 'kilo', voiceProvider: 'baseten', sarvamApiKey: 'fixture-speech', basetenApiKey: 'fixture-meta',
    sttProvider: 'sarvam', ttsProvider: 'sarvam', voiceSilenceMs: 800, voiceNoiseDb: -35, voiceBargeDb: -25,
    voiceMaxUtteranceMs: 5000, voiceBargeIn: barge, voiceHfpRouting: false,
    voiceSpeechGapMs: 0, voiceJobWaitUpdateMs: 100000, voiceJobSpeakMinIntervalMs: 0, voiceTaskLimit: 20, voiceSpeakMaxChars: 1200 };
  const h = { inputs: [], played: [], events: [], calls: [], transcripts: [], cancelled: 0, stops: 0, synth: [] };
  const engine = { turns: new Map(), listTeammates: () => [{ id: 'owner' }, { id: 'other' }],
    async runVoiceTurn(id, text, observer) {
      h.calls.push({ id, text }); this.turns.set(id, true);
      try {
        if (run) return await run(observer);
        const call = { id: 'write', function: { name: 'write_file', arguments: '{}' } };
        observer.onToolCall(call); observer.onToolResult(call, 'Created', { ok: true });
        return { text: 'Note ready. Saved it. Anything else?', error: null };
      } finally { this.turns.delete(id); }
    }, cancel() { h.cancelled++; },
  };
  const io = {
    audioDeps: () => ({ ffmpeg: true, ffplay: true }),
    listMicrophones: async () => [{ name: 'Fixture headset' }],
    openVoiceInput(options) {
      if (open) return open(options);
      fs.writeFileSync(options.outFile, 'fixture');
      const input = { options, stopped: false, ready: Promise.resolve(),
        async stop() { input.stopped = true; return true; } };
      h.inputs.push(input); return input;
    },
    transcribeAudio: async () => transcribe ? transcribe() : ({ text: h.transcripts.shift() || 'Write a note', languageCode: 'en-IN', confidence: 1 }),
    synthesizeSarvam: async options => { h.synth.push(options.text); return synthesize ? synthesize(options.text) : Buffer.from(options.text); },
    playMp3: async (audio, { signal } = {}) => { if (!signal?.aborted) { h.played.push(audio.toString()); await play?.(audio, signal); } },
    stopPlayback: () => { h.stops++; },
    narrate: async () => '',
  };
  h.voice = new module_.DesktopVoice({ engine, getConfig: () => config, emit: event => h.events.push(event), directory, io });
  h.directory = directory; h.engine = engine; h.config = config;
  h.say = async (text = 'Write a note') => {
    h.transcripts.push(text);
    await until(() => h.voice.snapshot().phase === 'listening');
    const input = h.inputs.at(-1);
    input.options.onEvent({ type: 'silence_end', at: 1 }); input.options.onEvent({ type: 'silence_start', at: 2 });
  };
  t.after(() => h.voice.close());
  return h;
}

test('barge-in stops current speech and submits the completed interruption exactly once', async t => {
  const h = harness(t, { barge: true, play: async (audio, signal) => {
    if (audio.toString().startsWith('Note ready')) await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
  } });
  await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.voice.snapshot().phase === 'speaking');
  await new Promise(resolve => setTimeout(resolve, 420));
  h.transcripts.push('Stop, make it shorter');
  const input = h.inputs.at(-1);
  input.options.onEvent({ type: 'silence_end', at: 1 });
  await new Promise(resolve => setTimeout(resolve, 10));
  input.options.onEvent({ type: 'silence_start', at: 2 });
  await until(() => h.calls.length === 2);
  assert.equal(h.calls[1].text, 'Stop, make it shorter');
  assert.equal(h.calls.length, 2);
});

test('cancel work cancels its engine turn and records cancellation', async t => {
  const pending = defer(); const h = harness(t, { run: () => pending.promise });
  await h.voice.start({ threadId: 'owner' }); await h.say(); await until(() => h.calls.length === 1);
  await h.voice.cancelWork(); assert.equal(h.cancelled, 1);
  pending.resolve({ text: 'Completed?', error: null });
  await until(() => h.voice.snapshot().task.status === 'cancelled');
});

test('a late transcript cannot submit into a replacement session', async t => {
  const pending = defer(); const h = harness(t, { transcribe: () => pending.promise });
  await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.voice.snapshot().phase === 'transcribing');
  await h.voice.end(); await h.voice.start({ threadId: 'other' });
  pending.resolve({ text: 'Stale request', languageCode: 'en-IN' });
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(h.calls.length, 0); assert.equal(h.voice.snapshot().threadId, 'other');
});

test('approval remains on its owning task and ending voice does not grant it', async t => {
  const permission = defer();
  const h = harness(t, { run: async observer => {
    const allowed = await observer.approval('write_file', () => permission.promise);
    return { text: allowed ? 'Saved.' : 'Permission denied.', error: null };
  } });
  await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.voice.snapshot().phase === 'approval');
  await h.voice.end(); await h.voice.start({ threadId: 'other' });
  permission.resolve(false);
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(h.voice.snapshot().threadId, 'other'); assert.equal(h.voice.snapshot().task, null);
  assert.ok(!h.played.includes('Saved.'));
});

test('empty transcript recaptures and deleting the owner closes its microphone', async t => {
  const h = harness(t, { transcribe: async () => ({ text: '' }) });
  await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.inputs.length === 2);
  assert.equal(h.calls.length, 0);
  await h.voice.ownerDeleted('owner');
  assert.equal(h.voice.snapshot().active, false); assert.ok(h.inputs.every(input => input.stopped));
});

test('a silent capture deadline does not send audio for transcription or delegate a request', async t => {
  let transcriptions = 0;
  const h = harness(t, { transcribe: async () => { transcriptions++; return { text: 'Hallucinated from silence' }; } });
  h.config.voiceMaxUtteranceMs = 20;
  await h.voice.start({ threadId: 'owner' });
  await until(() => h.inputs.length >= 2);
  assert.equal(transcriptions, 0); assert.equal(h.calls.length, 0);
});

test('device opening failure becomes a recoverable public error', async t => {
  const h = harness(t, { open: () => { throw new Error('Device unavailable'); } });
  await h.voice.start({ threadId: 'owner' });
  await until(() => h.voice.snapshot().phase === 'error');
  assert.equal(h.voice.snapshot().active, false); assert.match(h.voice.snapshot().error, /Device unavailable/);
});

test('pausing a microphone that is still starting preserves the session and resumes one replacement', async t => {
  let opens = 0;
  const h = harness(t, { open: options => {
    opens++;
    const child = new EventEmitter();
    let reject;
    const ready = opens === 1 ? new Promise((_resolve, fail) => { reject = fail; }) : Promise.resolve();
    const input = { child, options, ready, stopped: false, stop: async () => {
      input.stopped = true; reject?.(new Error('ffmpeg exited immediately (code 0)')); child.emit('close', 0); return false;
    } };
    h.inputs.push(input); return input;
  } });
  await h.voice.start({ threadId: 'owner' }); await until(() => opens === 1);
  await h.voice.pause(); await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(h.voice.snapshot().active, true); assert.equal(h.voice.snapshot().phase, 'paused');
  await h.voice.resume(); await until(() => h.voice.snapshot().phase === 'listening');
  assert.equal(opens, 2);
});

test('desktop checks player failures and retains a recoverable audio error', async t => {
  const h = harness(t, { play: async audio => { if (audio.toString().startsWith('Note ready')) throw new Error('Speech playback failed.'); } });
  const original = h.voice.io.playMp3;
  const policies = [];
  h.voice.io.playMp3 = (audio, options) => { policies.push(options.rejectOnFailure); return original(audio, options); };
  await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.voice.snapshot().phase === 'error');
  assert.equal(h.voice.snapshot().active, false); assert.match(h.voice.snapshot().error, /playback failed/);
  assert.ok(policies.length && policies.every(Boolean));
});

test('one desktop voice session drives real task observers and two-sentence playback', async t => {
  const h = harness(t);
  await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.played.includes('Note ready. Saved it.'));
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].id, 'owner');
  assert.equal(h.voice.snapshot().task.status, 'done');
  assert.equal(h.voice.snapshot().task.steps[0].state, 'done');
  assert.ok(!h.played.includes('Note ready. Saved it. Anything else?'));
  assert.ok(!JSON.stringify(h.events).includes('fixture-meta'));
});

test('main and island starting the same owner reuse one microphone; another owner cannot take it over', async t => {
  const h = harness(t);
  const first = await h.voice.start({ threadId: 'owner' });
  const second = await h.voice.start({ threadId: 'owner' });
  assert.equal(first.sessionId, second.sessionId);
  await until(() => h.inputs.length === 1);
  assert.equal(h.inputs[0].options.device, 'Fixture headset');
  await assert.rejects(h.voice.start({ threadId: 'other' }), /voice|conversation/i);
  assert.equal(h.inputs.length, 1);
});

test('simultaneous completion stays with each task and only the current session speaks', async t => {
  const first = defer(), second = defer();
  const h = harness(t, { run: () => h.calls.length === 1 ? first.promise : second.promise });
  await h.voice.start({ threadId: 'owner' }); await h.say('First poem');
  await until(() => h.calls.length === 1);
  const firstId = h.voice.snapshot().task.id;
  await h.voice.end();
  await h.voice.start({ threadId: 'other' }); await h.say('Second poem');
  await until(() => h.calls.length === 2);
  const secondId = h.voice.snapshot().task.id;
  first.resolve({ text: 'First poem saved.', error: null });
  second.resolve({ text: 'Second poem saved.', error: null });
  await until(() => h.played.includes('Second poem saved.'));
  assert.ok(!h.played.includes('First poem saved.'), 'an ended session cannot speak over its replacement');
  assert.notEqual(firstId, secondId);
  assert.equal(h.voice.snapshot().threadId, 'other');
  assert.equal(h.voice.snapshot().task.id, secondId);
  assert.equal(JSON.parse(fs.readFileSync(path.join(h.directory, `${firstId}.json`))).summary, 'First poem saved.');
  assert.equal(JSON.parse(fs.readFileSync(path.join(h.directory, `${secondId}.json`))).summary, 'Second poem saved.');
});

test('pause closes capture and resume opens exactly one replacement', async t => {
  const h = harness(t); await h.voice.start({ threadId: 'owner' });
  await until(() => h.voice.snapshot().phase === 'listening');
  await h.voice.pause(); assert.equal(h.voice.snapshot().paused, true);
  assert.equal(h.inputs[0].stopped, true);
  await h.voice.resume(); await until(() => h.inputs.length === 2);
  assert.equal(h.inputs.filter(input => !input.stopped).length, 1);
});

test('end voice closes audio but lets already delegated work finish on its original owner', async t => {
  const pending = defer(); const h = harness(t, { run: () => pending.promise });
  await h.voice.start({ threadId: 'owner' }); await h.say(); await until(() => h.calls.length === 1);
  await h.voice.end(); assert.equal(h.voice.snapshot().active, false); assert.equal(h.cancelled, 0);
  pending.resolve({ text: 'Work complete.', error: null });
  await until(() => fs.readdirSync(h.directory).some(file => JSON.parse(fs.readFileSync(path.join(h.directory, file))).status === 'done'));
  assert.ok(!h.played.includes('Work complete.'));
  assert.ok(h.inputs.every(input => input.stopped));
});

test('late synthesis after ending cannot play or reopen capture', async t => {
  const pending = defer();
  const h = harness(t, { synthesize: text => text.startsWith('Note ready') ? pending.promise : Buffer.from(text) });
  await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.synth.some(text => text.startsWith('Note ready')));
  await h.voice.end(); pending.resolve(Buffer.from('STALE AUDIO'));
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.ok(!h.played.includes('STALE AUDIO')); assert.equal(h.inputs.length, 1);
});

test('task failures stay audible and recorded rather than speaking only the model success claim', async t => {
  const h = harness(t, { run: async () => ({ text: 'Saved it.', error: 'Output limit reached.' }) });
  await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.played.some(text => text.startsWith('Work did not finish.')));
  assert.equal(h.voice.snapshot().task.status, 'failed');
  assert.ok(!h.played.includes('Saved it.'));
});

test('missing credentials and unknown threads fail before any microphone opens', async t => {
  const h = harness(t); h.config.sarvamApiKey = '';
  await assert.rejects(h.voice.start({ threadId: 'owner' }), /Sarvam/i);
  assert.equal(h.inputs.length, 0);
  h.config.sarvamApiKey = 'fixture-speech';
  await assert.rejects(h.voice.start({ threadId: 'missing' }), /conversation|teammate/i);
});
