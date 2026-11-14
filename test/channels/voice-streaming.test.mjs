import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { Writable } from 'node:stream';
import * as voice from '../../src/channels/voice.mjs';

const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const options = { apiKey: 'fixture', model: 'fixture-model', speaker: 'fixture-voice', languageCode: 'en-IN', text: 'A short fixture.' };

test('Sarvam yields audio before the response ends and retains the configured contract', async t => {
  const tail = deferred(); let ended = false, request;
  t.mock.method(globalThis, 'fetch', async (url, init) => {
    request = { url, init };
    return new Response(new ReadableStream({ start(controller) {
      controller.enqueue(Buffer.from('first'));
      tail.promise.then(() => { ended = true; controller.enqueue(Buffer.from('last')); controller.close(); });
    } }), { headers: { 'content-type': 'audio/mpeg' } });
  });
  assert.equal(typeof voice.synthesizeSarvamStream, 'function');
  const stream = voice.synthesizeSarvamStream(options);
  assert.equal((await stream.next()).value.toString(), 'first');
  assert.equal(ended, false, 'first bytes must be usable before the remaining audio exists');
  assert.equal(request.url, `${voice.SARVAM_TTS_URL}/stream`);
  assert.equal(request.init.headers[voice.SARVAM_AUTH_HEADER], options.apiKey);
  assert.deepEqual(JSON.parse(request.init.body), { text: options.text, model: options.model, speaker: options.speaker, language_code: options.languageCode, output_audio_codec: 'mp3' });
  tail.resolve();
  assert.equal((await stream.next()).value.toString(), 'last');
  assert.equal((await stream.next()).done, true);
});

test('stream request abort and unsupported endpoint remain distinguishable', async t => {
  assert.equal(typeof voice.synthesizeSarvamStream, 'function');
  const cancel = new AbortController();
  t.mock.method(globalThis, 'fetch', async (_url, { signal }) => {
    return new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
  });
  const stream = voice.synthesizeSarvamStream({ ...options, signal: cancel.signal });
  const first = stream.next(); cancel.abort();
  await assert.rejects(first, { name: 'AbortError' });
  t.mock.method(globalThis, 'fetch', async () => new Response('', { status: 404 }));
  await assert.rejects(voice.synthesizeSarvamStream(options).next(), error => error.code === 'VOICE_STREAM_UNSUPPORTED');
});

test('stdin playback forwards the first bytes while synthesis is still pending', async () => {
  assert.equal(typeof voice.playMp3Stream, 'function');
  const tail = deferred(), started = deferred(), writes = []; let args;
  const child = new EventEmitter();
  child.kill = () => { child.emit('close', null); };
  child.stdin = new Writable({ write(chunk, _encoding, done) { writes.push(chunk.toString()); started.resolve(); done(); } });
  child.stdin.on('finish', () => child.emit('close', 0));
  async function* chunks() { yield Buffer.from('first'); await tail.promise; yield Buffer.from('last'); }
  const playing = voice.playMp3Stream(chunks(), { rejectOnFailure: true, spawnImpl: (_binary, supplied) => { args = supplied; return child; } });
  await started.promise;
  assert.deepEqual(writes, ['first']); assert.ok(args.includes('pipe:0'));
  tail.resolve(); await playing; assert.deepEqual(writes, ['first', 'last']);
});

test('stream player cancellation aborts the producer and never writes late bytes', async () => {
  assert.equal(typeof voice.playMp3Stream, 'function');
  const cancel = new AbortController(), started = deferred(), writes = []; let producerSignal;
  const child = new EventEmitter(); child.kill = () => child.emit('close', null);
  child.stdin = new Writable({ write(chunk, _encoding, done) { writes.push(chunk.toString()); started.resolve(); done(); } });
  const playing = voice.playMp3Stream(async function* ({ signal }) {
    producerSignal = signal; yield Buffer.from('first');
    await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
    if (!signal.aborted) yield Buffer.from('late');
  }, { signal: cancel.signal, spawnImpl: () => child, rejectOnFailure: true });
  await started.promise; cancel.abort(); await playing;
  assert.equal(producerSignal.aborted, true); assert.deepEqual(writes, ['first']);
});

test('a failed stream stops its native player and reports failure instead of hanging', async () => {
  const child = new EventEmitter(); let killed = false;
  child.kill = () => { killed = true; child.emit('close', null); };
  child.stdin = new Writable({ write(_chunk, _encoding, done) { done(); } });
  await assert.rejects(voice.playMp3Stream(async function* () { yield Buffer.from('first'); throw new Error('broken source'); },
    { spawnImpl: () => child, rejectOnFailure: true }), /Could not play speech/);
  assert.equal(killed, true);
});

test('an already cancelled buffered synthesis never calls the cloud', async t => {
  let requests = 0;
  t.mock.method(globalThis, 'fetch', async () => { requests++; return Response.json({ audios: ['fixture'] }); });
  const cancel = new AbortController(); cancel.abort();
  await assert.rejects(voice.synthesizeSarvam({ ...options, signal: cancel.signal }), { name: 'AbortError' });
  assert.equal(requests, 0);
});
