import test from 'node:test';
import assert from 'node:assert/strict';
const api = await import('../../src/automation/voice-speech-queue.mjs').catch(() => ({}));
const tick = () => new Promise(resolve => setImmediate(resolve));
const defer = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const entry = (key, kind = 'report', extra = {}) => ({ key, jobId: key.split(':')[0], kind, prepare: async () => key, ...extra });

test('simultaneous completed reports have one player and keep their own order/identity', async () => {
  let active = 0, peak = 0; const heard = [];
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, play: async audio => {
    active++; peak = Math.max(peak, active); heard.push(audio); await tick(); active--;
  } });
  assert.deepEqual(await Promise.all([queue.offer(entry('poem')), queue.offer(entry('research'))]), [true, true]);
  assert.equal(peak, 1); assert.deepEqual(heard, ['poem', 'research']); await queue.close();
});

test('only latest queued progress survives and a report takes precedence', async () => {
  const first = defer(); const heard = [];
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, play: async audio => { heard.push(audio); if (audio === 'first') await first.promise; } });
  const running = queue.offer(entry('first')); await tick();
  const obsolete = queue.offer(entry('poem:old', 'progress'));
  const latest = queue.offer(entry('poem:new', 'progress'));
  const report = queue.offer(entry('poem:done'));
  first.resolve(); await Promise.all([running, obsolete, latest, report]);
  assert.deepEqual(heard, ['first', 'poem:done']); await queue.close();
});

test('a late ignored synthesis cannot play after its signal ends', async () => {
  const synthesis = defer(), controller = new AbortController(); const heard = [];
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, play: async audio => { heard.push(audio); } });
  const old = queue.offer(entry('old', 'progress', { prepare: () => synthesis.promise, signal: controller.signal }));
  await tick(); controller.abort(); assert.equal(await old, false);
  const current = queue.offer(entry('current')); synthesis.resolve('stale'); await current;
  assert.deepEqual(heard, ['current']); await queue.close();
});

test('user interruption pauses output and can resume a report without stopping its job', async () => {
  const heard = []; let first = true;
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, stop: () => {}, play: async (audio, { signal }) => {
    heard.push(audio);
    if (first) { first = false; await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true })); }
  } });
  const report = queue.offer(entry('poem')); await tick(); queue.interrupt({ requeueReports: true });
  await tick(); assert.deepEqual(heard, ['poem']); queue.resume(); assert.equal(await report, true);
  assert.deepEqual(heard, ['poem', 'poem']); await queue.close();
});

test('closing voice removes pending reports and waits for the owned player to stop', async () => {
  const heard = [];
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, play: async (audio, { signal }) => {
    heard.push(audio); await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
  } });
  const first = queue.offer(entry('first')); await tick(); const second = queue.offer(entry('second'));
  await queue.close(); assert.deepEqual(await Promise.all([first, second]), [false, false]);
  assert.deepEqual(heard, ['first']); assert.equal(await queue.offer(entry('late')), false);
});

test('duplicate completion notifications cannot repeat a spoken job report', async () => {
  const heard = [];
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, play: async audio => { heard.push(audio); await tick(); } });
  assert.deepEqual(await Promise.all([queue.offer(entry('poem:done')), queue.offer(entry('poem:duplicate'))]), [true, false]);
  assert.equal(await queue.offer(entry('poem:late-duplicate')), false);
  assert.deepEqual(heard, ['poem:done']); await queue.close();
});
