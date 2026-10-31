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
    // Most existing tests exercise freely-listening voice; the wake-word ladder
    // has its own cases below and turns these on explicitly.
    voiceWakeWord: false, voiceStopWord: true,
    voiceSpeechGapMs: 0, voiceJobWaitUpdateMs: 100000, voiceJobSpeakMinIntervalMs: 0, voiceTaskLimit: 20, voiceSpeakMaxChars: 1200 };
  const h = { inputs: [], played: [], events: [], calls: [], transcripts: [], cancelled: 0, stops: 0, synth: [] };
  const engine = { turns: new Map(), listTeammates: () => [{ id: 'owner' }, { id: 'other' }],
    captureVoiceContext: () => ({}),
    async runVoiceJob(entry, options) {
      entry.cancelWorker = () => { h.cancelled++; };
      options.observer.approval = (tool, ask) => options.task.approval(tool, ask);
      return this.runVoiceTurn(entry.ownerId, entry.transcript, options.observer, entry, options);
    },
    async deliverVoiceJob() {},
    async runVoiceTurn(id, text, observer, entry, options) {
      h.calls.push({ id, text }); this.turns.set(id, true);
      try {
        if (run) return await run(observer, entry, options);
        const call = { id: 'write', function: { name: 'write_file', arguments: '{}' } };
        observer.onToolCall(call); observer.onToolResult(call, 'Created', { ok: true });
        return { text: 'Note ready. Saved it. Anything else?', error: null };
      } finally { this.turns.delete(id); }
    }, cancel() { h.cancelled++; },
  };
  const io = {
    audioDeps: () => ({ ffmpeg: true, ffplay: true }),
    listAudioDevices: () => [{ flow: 'render', id: 'fixture-output', name: 'Fixture speakers' }],
    getDefaultRenderId: () => 'fixture-output',
    playbackIsolated: async () => true,
    watchPlayback: async () => ({ isolated: true, stop: async () => {} }),
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

test('ending voice during device discovery resolves every pending start without an IPC abort error', async t => {
  const pending = defer(), h = harness(t);
  h.voice.io.listMicrophones = () => pending.promise;
  const first = h.voice.start({ threadId: 'owner' });
  const second = h.voice.start({ threadId: 'owner' });
  await h.voice.end();
  assert.equal((await first).active, false);
  assert.equal((await second).active, false);
  pending.resolve([{ name: 'Late microphone' }]);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.inputs.length, 0);
});

test('startup still reports real device errors', async t => {
  const h = harness(t);
  h.voice.io.listMicrophones = async () => { throw new Error('Device discovery failed'); };
  await assert.rejects(h.voice.start({ threadId: 'owner' }), /Device discovery failed/);
  assert.equal(h.voice.snapshot().phase, 'error');
});

test('asynchronous audio checks are awaited and End cancels a pending dependency probe', async t => {
  const pending = defer(), h = harness(t);
  h.voice.io.audioDeps = () => pending.promise;
  const starting = h.voice.start({ threadId: 'owner' });
  await h.voice.end();
  assert.equal((await starting).active, false);
  pending.resolve({ ffmpeg: true, ffplay: true });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.inputs.length, 0);
});

test('a routing operation finishing after End is restored before another session can use audio', async t => {
  const pending = defer(), h = harness(t);
  let restored = false;
  h.config.voiceOutputDevice = 'fixture-output';
  h.voice.io.usePlaybackDevice = () => pending.promise;
  const starting = h.voice.start({ threadId: 'owner' });
  await until(() => h.voice.current?.microphone);
  const ending = h.voice.end();
  pending.resolve({ restore: async () => { restored = true; } });
  await Promise.all([starting, ending]);
  assert.equal(restored, true); assert.equal(h.inputs.length, 0);
});

test('an unexpected audio AbortError remains visible while the session is live', async t => {
  const h = harness(t, { open: () => { throw new DOMException('Microphone access aborted unexpectedly', 'AbortError'); } });
  await h.voice.start({ threadId: 'owner' });
  await until(() => h.voice.snapshot().phase === 'error');
  assert.equal(h.voice.snapshot().active, false);
  assert.match(h.voice.snapshot().error, /Microphone access aborted/);
});

test('ending during acknowledgement preparation restores the output and suppresses the expected abort', async t => {
  const pending = defer(), h = harness(t, { synthesize: () => pending.promise });
  let restored = false;
  h.config.voiceOutputDevice = 'fixture-output';
  h.voice.io.usePlaybackDevice = () => ({ restore: () => { restored = true; } });
  const starting = h.voice.start({ threadId: 'owner' });
  await until(() => h.synth.length > 0);
  await h.voice.end();
  assert.equal((await starting).active, false); assert.equal(restored, true);
  pending.resolve(Buffer.from('late acknowledgement'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.played.length, 0);
});

test('speaker test failures restore the previous output and remain actionable', async t => {
  const h = harness(t, { play: async () => { throw new Error('Speaker unavailable'); } });
  let restored = false;
  h.config.voiceOutputDevice = 'fixture-output';
  h.voice.io.usePlaybackDevice = () => ({ restore: () => { restored = true; } });
  await assert.rejects(h.voice.testPlayback(), /Speaker unavailable/);
  assert.equal(restored, true); assert.equal(h.voice.preview, null);
});

test('speaker test uses saved output, checks playback and restores routing without submitting work', async t => {
  const h = harness(t), routes = [];
  h.config.voiceOutputDevice = 'fixture-output';
  h.voice.io.usePlaybackDevice = id => { routes.push(id); return { restore: () => routes.push('restored') }; };
  h.voice.io.playMp3 = async (_audio, options) => { assert.equal(options.rejectOnFailure, true); };
  assert.deepEqual(await h.voice.testPlayback(), { cancelled: false });
  assert.deepEqual(routes, ['fixture-output', 'restored']);
  assert.equal(h.calls.length, 0); assert.equal(h.inputs.length, 0);
  const status = await h.voice.status();
  assert.deepEqual(status.outputs, [{ id: 'fixture-output', name: 'Fixture speakers' }]);
  assert.equal(status.defaultOutput, 'Fixture speakers');
  assert.equal(status.outputDevice, 'fixture-output');
});

test('a selected output is used by the session and restored on end', async t => {
  const h = harness(t), routes = [];
  h.config.voiceOutputDevice = 'fixture-output';
  h.voice.io.usePlaybackDevice = id => { routes.push(id); return { restore: () => routes.push('restored') }; };
  await h.voice.start({ threadId: 'owner' });
  await assert.rejects(h.voice.testPlayback(), /End voice/);
  await h.voice.end();
  assert.deepEqual(routes, ['fixture-output', 'restored']);
});

test('ending a speaker test cancels synthesis, releases output and prevents late playback', async t => {
  const pending = defer(), h = harness(t, { synthesize: () => pending.promise });
  const preview = h.voice.testPlayback();
  await until(() => h.synth.length > 0);
  await assert.rejects(h.voice.start({ threadId: 'owner' }), /test/i);
  await h.voice.end();
  assert.deepEqual(await preview, { cancelled: true });
  pending.resolve(Buffer.from('late audio'));
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.played.length, 0);
});

test('same-session voice accepts a second request and reports it while the first job remains blocked', async t => {
  const first = defer();
  const h = harness(t, { run: () => h.calls.length === 1 ? first.promise : Promise.resolve({ text: 'Second note saved.' }) });
  await h.voice.start({ threadId: 'owner' }); await h.say('First slow poem');
  await until(() => h.calls.length === 1);
  await h.say('Second fast note');
  await until(() => h.played.includes('Second note saved.'));
  assert.equal(h.calls.length, 2);
  assert.ok(h.voice.snapshot().jobs.some(job => job.status === 'running'));
  first.resolve({ text: 'First poem saved.' });
  await until(() => h.played.includes('First poem saved.'));
  assert.equal(h.voice.snapshot().jobs.filter(job => job.status === 'done').length, 2);
});

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

test('speaker output closes capture before playback and ignores its own voice until listening resumes', async t => {
  const speaking = defer(), h = harness(t, { barge: true, play: async audio => {
    if (audio.toString().startsWith('Note ready')) await speaking.promise;
  } });
  h.voice.io.playbackIsolated = async () => false;
  try {
  await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.played.includes('Note ready.'));
  const input = h.inputs.at(-1);
  assert.equal(input.stopped, true, 'microphone must close before sound leaves speakers');
  const count = h.inputs.length;
  input.options.onEvent({ type: 'silence_end', at: 1 });
  input.options.onEvent({ type: 'silence_start', at: 2 });
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(h.inputs.length, count, 'no microphone reopening while the speaker is active');
  assert.equal(h.calls.length, 1, 'speech feedback must not delegate another job');
  speaking.resolve();
  await until(() => h.inputs.length > count);
  await h.say('A genuine second request');
  await until(() => h.calls.length === 2);
  assert.equal(h.calls[1].text, 'A genuine second request');
  } finally { speaking.resolve(); }
});

test('switching away from headphones interrupts playback and permanently enables speaker protection for this session', async t => {
  let changed, protectedPlays = 0, stopped = 0;
  const h = harness(t, { barge: true, play: async (audio, signal) => {
    if (!audio.toString().startsWith('Note ready')) return;
    if (h.voice.current.bargeIn) await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
    else { assert.equal(h.voice.current.input, null); protectedPlays++; }
  } });
  h.voice.io.watchPlayback = async callback => { changed = callback; return { isolated: true, stop: async () => { stopped++; } }; };
  await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.played.includes('Note ready.'));
  changed();
  await until(() => protectedPlays > 0);
  assert.equal(h.voice.current.bargeIn, false); assert.equal(h.calls.length, 1);
  await h.voice.end(); assert.equal(stopped, 1);
});

test('a headphone change invalidates an already pending transcript instead of treating feedback as a request', async t => {
  const pending = defer(); let changed;
  const h = harness(t, { barge: true, transcribe: () => pending.promise });
  h.voice.io.watchPlayback = async callback => { changed = callback; return { isolated: true, stop: async () => {} }; };
  await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.voice.snapshot().phase === 'transcribing');
  changed(); pending.resolve({ text: 'Old speaker feedback', languageCode: 'en-IN' });
  await until(() => h.inputs.length > 1);
  assert.equal(h.calls.length, 0);
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
  await until(() => h.played.includes('Saved it.'));
  assert.ok(h.played.includes('Note ready.'));
  assert.ok(h.played.indexOf('Note ready.') < h.played.indexOf('Saved it.'));
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
  await h.voice.end(); const capturesAtEnd = h.inputs.length; pending.resolve(Buffer.from('STALE AUDIO'));
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.ok(!h.played.includes('STALE AUDIO')); assert.equal(h.inputs.length, capturesAtEnd);
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

async function interruptSpeaking(h, text) {
  await new Promise(resolve => setTimeout(resolve, 420)); // Beyond the shared echo guard, while the fixture player is held.
  h.transcripts.push(text);
  const input = h.inputs.at(-1);
  input.options.onEvent({ type: 'silence_end', at: 1 });
  input.options.onEvent({ type: 'silence_start', at: 2 });
}

test('genuine new desktop request suspends the old report instead of replaying it', async t => {
  const contexts = [];
  const h = harness(t, { barge: true, run: async (_observer, entry) => {
    contexts.push(entry.context.speech);
    return { text: contexts.length === 1 ? 'First result. More details.' : 'Second answer.' };
  }, play: async (audio, signal) => {
    if (audio.toString().startsWith('First result')) await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
  } });
  await h.voice.start({ threadId: 'owner' }); await h.say('First task');
  await until(() => h.played.some(text => text.startsWith('First result')));
  await interruptSpeaking(h, 'Another question');
  await until(() => h.played.includes('Second answer.'));
  assert.ok(contexts.every(context => context?.queue && Number.isInteger(context.turn)));
  assert.equal(h.played.filter(text => text.startsWith('First result')).length, 1);
  assert.ok(!h.played.includes('More details.'));
  assert.equal(h.voice.current.speech.reportState().find(row => row.label === 'First task').state, 'suspended');
  assert.equal(h.voice.snapshot().jobs.filter(job => job.status === 'done').length, 2);
});

test('blank desktop interruption resumes the unfinished sentence without repeating delivered sentences', async t => {
  let transcriptions = 0, interrupted = false;
  const h = harness(t, { barge: true, run: async () => ({ text: 'First result. More details.' }),
    transcribe: async () => ({ text: ++transcriptions === 1 ? 'First task' : '' }),
    play: async (audio, signal) => {
      if (audio.toString() === 'More details.' && !interrupted) { interrupted = true; await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true })); }
    } });
  await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.played.includes('More details.'));
  await interruptSpeaking(h, '');
  await until(() => h.played.filter(text => text === 'More details.').length === 2);
  assert.equal(h.played.filter(text => text === 'First result.').length, 1);
  assert.equal(h.calls.length, 1);
});

test('speech selection skips redundant desktop confirmation but mixed work and failures remain audible', async t => {
  const outcomes = [{ text: 'Selection scheduled.', speechHandled: true },
    { text: 'Saved mixed work.', speechHandled: false }, { text: 'Selection scheduled.', error: 'Control failed.', speechHandled: true }];
  const h = harness(t, { run: async () => outcomes.shift() });
  await h.voice.start({ threadId: 'owner' }); await h.say('Next result');
  await until(() => h.voice.snapshot().task?.status === 'done');
  await h.say('Save a note too'); await until(() => h.played.includes('Saved mixed work.'));
  await h.say('Unavailable control'); await until(() => h.played.includes('Work did not finish.') && h.played.includes('Control failed.'));
  assert.ok(!h.played.includes('Selection scheduled.'));
  assert.ok(h.played.includes('Control failed.'));
});

test('older desktop completion cannot release a newer interruption hold', async t => {
  const old = defer(), newer = defer();
  const h = harness(t, { run: () => h.calls.length === 1 ? old.promise : newer.promise });
  await h.voice.start({ threadId: 'owner' }); await h.say('Old work'); await until(() => h.calls.length === 1);
  await h.say('New question'); await until(() => h.calls.length === 2);
  old.resolve({ text: 'Old completed.' });
  await until(() => h.voice.snapshot().jobs.some(job => job.summary === 'Old completed.'));
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.ok(!h.played.includes('Old completed.'));
  newer.resolve({ text: 'New answer.' });
  await until(() => h.played.includes('Old completed.'));
  assert.ok(h.played.indexOf('New answer.') < h.played.indexOf('Old completed.'));
});

test('manual desktop pause during a tentative interruption preserves the unfinished report', async t => {
  let held = false;
  const h = harness(t, { barge: true, run: async () => ({ text: 'First result. More details.' }), play: async (audio, signal) => {
    if (audio.toString() === 'More details.' && !held) { held = true; await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true })); }
  } });
  await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.played.includes('More details.'));
  await new Promise(resolve => setTimeout(resolve, 420));
  h.inputs.at(-1).options.onEvent({ type: 'silence_end', at: 1 });
  await h.voice.pause();
  await h.voice.resume();
  await until(() => h.played.filter(text => text === 'More details.').length === 2);
  assert.equal(h.played.filter(text => text === 'First result.').length, 1);
  assert.equal(h.calls.length, 1);
});

/* --------------------- attention ladder: standby + wake ------------------ */

const freeListening = config => { config.voiceWakeWord = false; };
const wakeLadder = (config, idleMs = 15000, standbyMs = 400) => { config.voiceWakeWord = true; config.voiceIdleMs = idleMs; config.voiceStandbyMs = standbyMs; };
const speakOnce = (h, text) => { h.transcripts.push(text); };
const sayInto = (h, text) => {
  speakOnce(h, text);
  const input = h.inputs.at(-1);
  input.options.onEvent({ type: 'silence_end', at: 1 }); input.options.onEvent({ type: 'silence_start', at: 2 });
};

test('a session with a wake word starts in standby, not freely listening', async t => {
  const h = harness(t);
  wakeLadder(h.config);
  await h.voice.start({ threadId: 'owner' });
  await until(() => h.voice.snapshot().phase === 'standby');
  assert.equal(h.calls.length, 0, 'starting voice is not a request');
});

test('standby closes the microphone after the quiet timeout without submitting anything', async t => {
  const h = harness(t);
  wakeLadder(h.config, 0);
  await h.voice.start({ threadId: 'owner' });
  await until(() => h.voice.snapshot().paused === true);
  assert.equal(h.voice.snapshot().active, true, 'auto-mute keeps the session, unlike End voice');
  assert.equal(h.voice.snapshot().phase, 'paused');
  assert.ok(h.inputs.at(-1).stopped, 'the microphone process is closed');
  assert.equal(h.calls.length, 0);
});

test('speech in standby that is not the wake word is dropped and never becomes a request', async t => {
  const h = harness(t);
  wakeLadder(h.config, 0, 100000);
  await h.voice.start({ threadId: 'owner' });
  await until(() => h.voice.snapshot().phase === 'standby');
  sayInto(h, 'write a note');
  await until(() => h.transcripts.length > 0);
  await new Promise(resolve => setTimeout(resolve, 60));
  assert.equal(h.calls.length, 0, 'no delegated request');
  assert.notEqual(h.voice.snapshot().caption, 'write a note', 'no user caption is shown');
  assert.equal(h.voice.snapshot().phase, 'standby', 'it stays asleep');
});

test('the wake word plus a request is handled from standby and returns to standby', async t => {
  const h = harness(t);
  // A long mic timeout keeps this test about the return-to-standby step only.
  wakeLadder(h.config, 0, 100000);
  await h.voice.start({ threadId: 'owner' });
  await until(() => h.voice.snapshot().phase === 'standby');
  sayInto(h, 'Hi Ankita, write a note');
  await until(() => h.calls.length === 1);
  assert.equal(h.calls[0].text, 'write a note', 'the wake prefix and greeting are not part of the request');
  await until(() => h.voice.snapshot().phase === 'standby');
  assert.ok(h.voice.snapshot().wakeCue > 0, 'the island saw the wake cue');
});

test('a bare wake word keeps listening for the configured window, then returns to standby', async t => {
  const h = harness(t);
  wakeLadder(h.config, 120);
  await h.voice.start({ threadId: 'owner' });
  await until(() => h.voice.snapshot().phase === 'standby');
  sayInto(h, 'Ankita');
  await until(() => h.voice.snapshot().phase === 'listening');
  assert.deepEqual(h.calls, [], 'the wake word is not a request');
  await until(() => h.voice.snapshot().phase === 'standby');
});

test('with no listening window, a bare wake word still wakes and shows the cue', async t => {
  const h = harness(t);
  wakeLadder(h.config, 0);
  await h.voice.start({ threadId: 'owner' });
  await until(() => h.voice.snapshot().phase === 'standby');
  sayInto(h, 'Ankita');
  await until(() => h.voice.snapshot().wakeCue > 0);
  assert.deepEqual(h.calls, [], 'the wake word is not a request');
  assert.equal(h.voice.snapshot().phase, 'standby', 'no free-listening window was configured');
});

test('the stop word cancels running work and confirms once', async t => {
  let release;
  const blocked = new Promise(resolve => { release = resolve; });
  // A job must publish a durable record before submit() returns, so the fixture
  // reports one real tool step and then blocks - the loop is free to listen again.
  const h = harness(t, { run: async observer => {
    const call = { id: 'read', function: { name: 'read_file', arguments: '{}' } };
    observer.onToolCall(call); observer.onToolResult(call, 'opened', { ok: true });
    await blocked;
    return { text: '', error: null };
  } });
  freeListening(h.config);
  try {
    await h.voice.start({ threadId: 'owner' }); await h.say('write a note');
    await until(() => h.calls.length === 1);
    await h.say('stop');
    await until(() => h.voice.snapshot().caption === 'Stopped.');
    assert.ok(h.cancelled >= 1, 'the running job is asked to cancel');
    assert.equal(h.calls.length, 1, 'the stop word itself is not submitted as a request');
  } finally { release(); }
});

test('with the wake word off, the microphone listens freely and closes after quiet', async t => {
  const h = harness(t);
  h.config.voiceWakeWord = false; h.config.voiceIdleMs = 40; h.config.voiceStandbyMs = 400;
  await h.voice.start({ threadId: 'owner' });
  await until(() => h.voice.snapshot().phase === 'listening');
  await until(() => h.voice.snapshot().paused === true);
  assert.equal(h.voice.snapshot().phase, 'paused', 'no standby rung when the wake word is off');
});

test('resume after auto-mute returns a wake-word session to standby', async t => {
  const h = harness(t);
  h.config.voiceWakeWord = true; h.config.voiceIdleMs = 0; h.config.voiceStandbyMs = 120;
  await h.voice.start({ threadId: 'owner' });
  await until(() => h.voice.snapshot().paused === true);
  h.config.voiceStandbyMs = 100000;
  await h.voice.resume();
  await until(() => h.voice.snapshot().phase === 'standby');
  await until(() => h.inputs.at(-1)?.stopped === false);
  assert.equal(h.voice.snapshot().paused, false);
  assert.equal(h.voice.snapshot().active, true);
  assert.ok(h.inputs.at(-1) && h.inputs.at(-1).stopped === false, 'a replacement microphone is open');
});
