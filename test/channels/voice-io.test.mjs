import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import childProcess from 'node:child_process';
import { EventEmitter } from 'node:events';
import { syncBuiltinESMExports } from 'node:module';
import { convertAudio, playMp3, stopPlayback, transcribeGroq } from '../../src/channels/voice.mjs';

function mockPlayer(t, onSpawn) {
  t.mock.method(childProcess, 'spawn', (_command, args) => {
    const child = new EventEmitter();
    child.stderr = new EventEmitter();
    child.kill = () => { queueMicrotask(() => child.emit('close', -1)); return true; };
    Promise.resolve().then(() => onSpawn(args, child)).catch(error => child.emit('error', error));
    return child;
  });
  syncBuiltinESMExports();
  t.after(() => { t.mock.restoreAll(); syncBuiltinESMExports(); stopPlayback(); });
}

function forbidBlockingAudio(t) {
  t.mock.method(fs, 'writeFileSync', () => { throw new Error('blocking audio write'); });
  t.mock.method(fs, 'readFileSync', () => { throw new Error('blocking audio read'); });
}

test('conversion awaits audio files and removes both temporary files', async t => {
  const input = Buffer.from('source audio');
  const output = Buffer.from('converted audio');
  let source, destination;
  mockPlayer(t, async (args, child) => {
    source = args[args.indexOf('-i') + 1]; destination = args.at(-1);
    assert.deepEqual(await fs.promises.readFile(source), input);
    await fs.promises.writeFile(destination, output);
    child.emit('close', 0);
  });
  forbidBlockingAudio(t);
  assert.deepEqual(await convertAudio(input), output);
  await assert.rejects(fs.promises.access(source), { code: 'ENOENT' });
  await assert.rejects(fs.promises.access(destination), { code: 'ENOENT' });
});

test('conversion removes partial output when ffmpeg fails', async t => {
  let source, destination;
  mockPlayer(t, async (args, child) => {
    source = args[args.indexOf('-i') + 1]; destination = args.at(-1);
    await fs.promises.writeFile(destination, 'partial output');
    child.stderr.emit('data', Buffer.from('invalid audio'));
    child.emit('close', 1);
  });
  await assert.rejects(convertAudio(Buffer.from('bad audio')), /ffmpeg exited 1: invalid audio/);
  await assert.rejects(fs.promises.access(source), { code: 'ENOENT' });
  await assert.rejects(fs.promises.access(destination), { code: 'ENOENT' });
});

test('playback starts after audio is written and cleans up after exit', async t => {
  const audio = Buffer.from('mp3 audio');
  let temporary;
  mockPlayer(t, async (args, child) => {
    temporary = args.at(-1);
    assert.deepEqual(await fs.promises.readFile(temporary), audio);
    child.emit('close', 0);
  });
  forbidBlockingAudio(t);
  await playMp3(audio);
  await assert.rejects(fs.promises.access(temporary), { code: 'ENOENT' });
});

test('Stop during an audio write prevents playback from starting', async t => {
  let release;
  const writing = new Promise(resolve => { release = resolve; });
  t.mock.method(fs.promises, 'writeFile', () => writing);
  let spawned = false;
  mockPlayer(t, (_args, child) => { spawned = true; child.emit('close', 0); });
  const playback = playMp3(Buffer.from('audio'));
  stopPlayback();
  release();
  await playback;
  assert.equal(spawned, false);
});

test('an aborted signal during an audio write prevents playback', async t => {
  let release;
  const writing = new Promise(resolve => { release = resolve; });
  t.mock.method(fs.promises, 'writeFile', () => writing);
  let spawned = false;
  mockPlayer(t, (_args, child) => { spawned = true; child.emit('close', 0); });
  const controller = new AbortController();
  const playback = playMp3(Buffer.from('audio'), { signal: controller.signal });
  controller.abort(); release();
  await playback;
  assert.equal(spawned, false);
});

test('aborting active playback kills the player and removes its audio file', async t => {
  const controller = new AbortController();
  let temporary, kills = 0;
  mockPlayer(t, (args, child) => {
    temporary = args.at(-1);
    const kill = child.kill;
    child.kill = () => { kills++; return kill(); };
    controller.abort();
  });
  await playMp3(Buffer.from('audio'), { signal: controller.signal });
  assert.equal(kills, 1);
  await assert.rejects(fs.promises.access(temporary), { code: 'ENOENT' });
});

test('transcription reads audio asynchronously and uploads its bytes', async t => {
  const directory = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'voice-io-'));
  t.after(async () => { t.mock.restoreAll(); await fs.promises.rm(directory, { recursive: true, force: true }); });
  const wavPath = path.join(directory, 'mic.wav');
  const audio = Buffer.from('recorded wav');
  await fs.promises.writeFile(wavPath, audio);
  forbidBlockingAudio(t);
  t.mock.method(globalThis, 'fetch', async (_url, options) => {
    assert.deepEqual(Buffer.from(await options.body.get('file').arrayBuffer()), audio);
    return new Response(JSON.stringify({ text: ' hello ' }), { headers: { 'content-type': 'application/json' } });
  });
  assert.equal(await transcribeGroq({ apiKey: 'test', wavPath }), 'hello');
});
