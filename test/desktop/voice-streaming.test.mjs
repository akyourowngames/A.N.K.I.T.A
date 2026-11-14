import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DesktopVoice } from '../../desktop/electron/voice.mjs';
import { synthesizeSarvamStream } from '../../src/channels/voice.mjs';
import { emptyVoiceState, voiceStatePatch } from '../../desktop/shared/voice.mjs';

const WAIT_MS = 2500; // Milliseconds: fixture deadline, without hardware or network waits.
const POLL_MS = 5; // Milliseconds: wait for actual service state transitions.
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const until = async check => { const end = Date.now() + WAIT_MS; while (!check()) { assert.ok(Date.now() < end, 'fixture state timed out'); await new Promise(resolve => setTimeout(resolve, POLL_MS)); } };
function harness(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-stream-desktop-'));
  const config = { provider: 'kilo', voiceProvider: 'baseten', basetenApiKey: 'fixture', sarvamApiKey: 'fixture',
    voiceWakeWord: false, voiceBargeIn: false, voiceHfpRouting: false, voiceSilenceMs: 800, voiceMaxUtteranceMs: 5000, voiceSpeechGapMs: 0 };
  const h = { inputs: [], chunks: [], buffered: [], events: [], closedBeforePlayback: false };
  const engine = { listTeammates: () => [{ id: 'owner' }], captureVoiceContext: () => ({}),
    runVoiceJob: async () => ({ text: 'The result is ready.', error: null }), deliverVoiceJob: async () => {} };
  const voice = new DesktopVoice({ engine, getConfig: () => config, directory, emit: event => h.events.push(event), io: {
    audioDeps: () => ({ ffmpeg: true, ffplay: true }), listMicrophones: async () => [{ name: 'Fixture input' }],
    listAudioDevices: async () => [], getDefaultRenderId: () => '', playbackIsolated: async () => false,
    openVoiceInput(options) { fs.writeFileSync(options.outFile, 'fixture'); const entry = { options, stopped: false, ready: Promise.resolve(), stop: async () => { entry.stopped = true; return true; } }; h.inputs.push(entry); return entry; },
    transcribeAudio: async () => ({ text: 'Give the result', languageCode: 'en-IN' }), narrate: async () => '',
    synthesizeSarvam: async ({ text, signal }) => { signal?.throwIfAborted(); h.buffered.push(text); return Buffer.from(text); },
    synthesizeSarvamStream,
    playMp3: async () => {}, stopPlayback: () => {},
    async playMp3Stream(source, { signal }) { h.closedBeforePlayback = h.inputs.every(input => input.stopped); for await (const chunk of source({ signal })) h.chunks.push(chunk.toString()); },
  } });
  h.voice = voice;
  h.say = async () => { await until(() => voice.snapshot().phase === 'listening'); const input = h.inputs.at(-1); input.options.onEvent({ type: 'silence_end', at: 1 }); input.options.onEvent({ type: 'silence_start', at: 2 }); };
  t.after(async () => { await voice.close(); fs.rmSync(directory, { recursive: true, force: true }); });
  return h;
}

test('desktop report consumes early cloud chunks with speaker protection and stops on session end', async t => {
  const tail = deferred(); let requestSignal;
  t.mock.method(globalThis, 'fetch', async (_url, init) => {
    requestSignal = init.signal;
    return new Response(new ReadableStream({ start(controller) {
      controller.enqueue(Buffer.from('early'));
      init.signal.addEventListener('abort', () => controller.error(init.signal.reason), { once: true });
      tail.promise.then(() => { if (!init.signal.aborted) { controller.enqueue(Buffer.from('late')); controller.close(); } });
    } }), { headers: { 'content-type': 'audio/mpeg' } });
  });
  const h = harness(t); await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.chunks.length || h.voice.snapshot().error);
  assert.deepEqual(h.chunks, ['early']);
  assert.equal(h.closedBeforePlayback, true, 'speaker playback must close all microphone captures');
  assert.equal(h.voice.snapshot().delivery?.mode, 'streaming');
  assert.ok(h.voice.snapshot().delivery.firstChunkMs >= 0);
  assert.equal(h.buffered.includes('The result is ready.'), false);
  await h.voice.end(); assert.equal(requestSignal.aborted, true); tail.resolve();
  assert.deepEqual(h.chunks, ['early']); assert.equal(h.voice.snapshot().active, false);
});

test('unsupported configured stream uses buffered report and exposes the fallback honestly', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 404 }));
  const h = harness(t); await h.voice.start({ threadId: 'owner' }); await h.say();
  await until(() => h.chunks.length || h.voice.snapshot().error);
  assert.deepEqual(h.chunks, ['The result is ready.']);
  assert.equal(h.voice.snapshot().delivery?.mode, 'buffered');
  assert.equal(h.voice.snapshot().delivery?.fallback, 'provider');
  assert.equal(h.voice.snapshot().error, null);
});

test('public delivery state rejects private data and invented timing values', () => {
  const state = voiceStatePatch(emptyVoiceState(), { delivery: { mode: 'streaming', fallback: 'secret-provider-error', firstChunkMs: -1, audio: 'private' } });
  assert.deepEqual(state.delivery, { mode: 'streaming', fallback: '', firstChunkMs: null });
});
