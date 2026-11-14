import test from 'node:test';
import assert from 'node:assert/strict';
import { VoiceSpeechQueue } from '../../src/automation/voice-speech-queue.mjs';
import { createVoiceReportSpeech } from '../../src/core/voice-session.mjs';

const helper = await import('../../src/channels/voice-stream-clip.mjs').catch(() => ({}));
const collect = async source => { const chunks = []; for await (const chunk of source) chunks.push(chunk); return Buffer.concat(chunks).toString(); };

test('speech preparation needs only the first chunk, replays completed clips and restarts interrupted clips', async () => {
  assert.equal(typeof helper.prepareVoiceStreamClip, 'function');
  let calls = 0; const original = new AbortController();
  const clip = await helper.prepareVoiceStreamClip({ signal: original.signal,
    stream: async function* ({ signal }) { calls++; yield Buffer.from('first'); signal.throwIfAborted(); yield Buffer.from('last'); } });
  assert.equal(calls, 1);
  original.abort();
  assert.equal(await collect(clip.open({ signal: new AbortController().signal })), 'firstlast');
  assert.equal(calls, 2, 'an interrupted prefetched response must be reopened');
  assert.equal(await collect(clip.open({ signal: new AbortController().signal })), 'firstlast');
  assert.equal(calls, 2, 'completed audio can be repeated without a network request');
});

test('unsupported streams use explicit buffering but partial failure never repeats speech', async () => {
  assert.equal(typeof helper.prepareVoiceStreamClip, 'function');
  let buffered = 0;
  const clip = await helper.prepareVoiceStreamClip({ stream: async function* () { throw Object.assign(new Error('unsupported'), { code: 'VOICE_STREAM_UNSUPPORTED' }); },
    buffer: async () => { buffered++; return Buffer.from('fallback'); } });
  assert.equal(clip.mode, 'buffered'); assert.equal(clip.fallback, 'provider');
  assert.equal(await collect(clip.open({})), 'fallback'); assert.equal(buffered, 1);
  const partial = await helper.prepareVoiceStreamClip({ stream: async function* () { yield Buffer.from('first'); throw new Error('lost stream'); },
    buffer: async () => { buffered++; return Buffer.from('wrong'); } });
  await assert.rejects(collect(partial.open({})), /lost stream/); assert.equal(buffered, 1);
});

test('report prefetch opens the next stream during current playback and repeat uses complete cached audio', async () => {
  let release, playbackStarted; const barrier = new Promise(resolve => { release = resolve; });
  const started = new Promise(resolve => { playbackStarted = resolve; });
  const requests = [], played = [];
  const queue = new VoiceSpeechQueue({ gapMs: 0, play: async (audio, { signal }) => {
    for await (const chunk of audio.open({ signal })) { played.push(chunk.toString()); playbackStarted(); if (played.length === 1) await barrier; }
  } });
  const report = createVoiceReportSpeech({ jobId: 'stream-report', text: 'First sentence. Second sentence.',
    synthesize: (text, { signal }) => helper.prepareVoiceStreamClip({ signal, stream: async function* () { requests.push(text); yield Buffer.from(text); } }) });
  const offered = queue.offer(report); await started;
  // Let the next sentence preparation promise run while the first player is blocked.
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(requests, ['First sentence.', 'Second sentence.']);
  assert.deepEqual(played, ['First sentence.']);
  release(); assert.equal(await offered, true);
  await queue.controlReport('repeat', { id: 'stream-report', turn: queue.turn }); await queue.drain();
  assert.deepEqual(played, ['First sentence.', 'Second sentence.', 'First sentence.', 'Second sentence.']);
  assert.equal(requests.length, 2); await queue.close();
});

test('native playback cancellation aborts a separately prefetched request', async () => {
  const preparation = new AbortController(), playback = new AbortController(); let networkSignal;
  const clip = await helper.prepareVoiceStreamClip({ signal: preparation.signal, stream: async function* ({ signal }) {
    networkSignal = signal; yield Buffer.from('first');
    await new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
  } });
  const audio = clip.open({ signal: playback.signal }); await audio.next();
  const pending = audio.next(); playback.abort();
  await assert.rejects(pending, { name: 'AbortError' });
  assert.equal(networkSignal.aborted, true); assert.equal(preparation.signal.aborted, false);
});
