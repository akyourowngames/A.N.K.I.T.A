import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { playMp3 } from '../../src/channels/voice.mjs';

function player({ code = 0, error, cancel = false } = {}) {
  return () => {
    const child = new EventEmitter();
    child.kill = () => { queueMicrotask(() => child.emit('close', null, 'SIGKILL')); };
    if (!cancel) queueMicrotask(() => error ? child.emit('error', error) : child.emit('close', code));
    return child;
  };
}
test('strict voice playback rejects unexpected player exits and spawn errors', async () => {
  const audio = Buffer.from('fixture mp3');
  await assert.rejects(playMp3(audio, { rejectOnFailure: true, spawnImpl: player({ code: 1 }) }), /play speech|playback/i);
  await assert.rejects(playMp3(audio, { rejectOnFailure: true, spawnImpl: player({ error: new Error('No output device') }) }), /play speech|playback/i);
  await assert.rejects(playMp3(audio, { rejectOnFailure: true, spawnImpl: () => { throw new Error('Spawn failed'); } }), /play speech|playback/i);
});
test('successful playback, legacy best-effort and intentional cancellation still resolve', async () => {
  const audio = Buffer.from('fixture mp3');
  await playMp3(audio, { rejectOnFailure: true, spawnImpl: player() });
  await playMp3(audio, { spawnImpl: player({ code: 1 }) });
  const controller = new AbortController();
  await playMp3(audio, { rejectOnFailure: true, signal: controller.signal, spawnImpl: (...args) => {
    const child = player({ cancel: true })(...args); queueMicrotask(() => controller.abort()); return child;
  } });
});
