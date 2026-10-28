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

test('a genuine request suspends the interrupted report instead of forcing it ahead of other results', async () => {
  const heard = [];
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, play: async (audio, { signal }) => {
    heard.push(audio); if (audio === 'A') await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
  } });
  const a = queue.offer(entry('A')); await tick(); const b = queue.offer(entry('B'));
  const turn = queue.interrupt(); queue.acceptTurn(turn); queue.resume(); await tick();
  assert.deepEqual(heard, ['A'], 'wait for the interruption decision, not an automatic replay');
  queue.finishTurn(turn); await b; await a;
  assert.deepEqual(heard, ['A', 'B']);
  assert.equal(queue.reportState().find(report => report.id === 'A').state, 'suspended');
  await queue.close();
});

test('a false interruption resumes only the unfinished cached sentence with one player', async () => {
  const heard = []; let active = 0, peak = 0, second = 0, preparations = 0;
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, play: async (audio, { signal }) => {
    active++; peak = Math.max(peak, active); heard.push(audio);
    if (audio === 'second' && second++ === 0) await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
    active--;
  } });
  const pending = queue.offer(entry('A', 'report', { parts: ['first', 'second'].map(text => ({ text, prepare: async () => { preparations++; return text; } })) }));
  await tick(); const turn = queue.interrupt(); await tick();
  assert.equal(queue.reportState()[0].completedText, 'first');
  await queue.falseInterruption(turn); await queue.drain(); await pending;
  assert.deepEqual(heard, ['first', 'second', 'second']); assert.equal(preparations, 2); assert.equal(peak, 1);
  await queue.close();
});

test('planner next dismisses the current speech and selects an actual queued result', async () => {
  const heard = [];
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, play: async (audio, { signal }) => {
    heard.push(audio); if (audio === 'A') await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
  } });
  void queue.offer(entry('A')); await tick(); const b = queue.offer(entry('B')), c = queue.offer(entry('C'));
  const turn = queue.interrupt(); queue.acceptTurn(turn); queue.resume();
  const result = await queue.controlReport('next', { turn }); await Promise.all([b, c]);
  assert.equal(result.id, 'B'); assert.deepEqual(heard, ['A', 'B', 'C']);
  assert.equal(queue.reportState().find(report => report.id === 'A').state, 'dismissed');
  await queue.close();
});

test('explicit resume keeps completed sentences while repeat deliberately starts the chosen report over', async () => {
  const heard = []; let second = 0;
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, play: async (audio, { signal }) => {
    heard.push(audio); if (audio === 'two' && second++ === 0) await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
  } });
  void queue.offer(entry('A', 'report', { parts: ['one', 'two'].map(text => ({ text, prepare: async () => text })) }));
  await tick(); const turn = queue.interrupt(); queue.acceptTurn(turn); queue.resume();
  await queue.controlReport('resume', { turn, id: 'A' }); await queue.drain();
  assert.deepEqual(heard, ['one', 'two', 'two']);
  await queue.controlReport('repeat', { turn, id: 'A' }); await queue.drain();
  assert.deepEqual(heard, ['one', 'two', 'two', 'one', 'two']); await queue.close();
});

test('a previous planner cannot change report selection after a newer interruption', async () => {
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, play: async () => {} });
  await queue.offer(entry('A')); const old = queue.interrupt(); queue.acceptTurn(old);
  const current = queue.interrupt(); queue.acceptTurn(current); queue.resume();
  await assert.rejects(queue.controlReport('repeat', { id: 'A', turn: old }), /older|stale/i);
  await queue.falseInterruption(old); assert.equal(queue.gatedTurn, current);
  queue.finishTurn(current); await queue.close();
});

test('an interrupt during the completed final sentence gap never repeats that finished report', async () => {
  const heard = [];
  const queue = new api.VoiceSpeechQueue({ gapMs: 100, play: async audio => { heard.push(audio); } });
  const a = queue.offer(entry('A')); await tick(); const turn = queue.interrupt();
  await queue.falseInterruption(turn); await a; await queue.drain();
  assert.deepEqual(heard, ['A']); assert.equal(queue.reportState()[0].state, 'delivered'); await queue.close();
});

test('late synthesis from a suspended report stays inaudible while next plays', async () => {
  const late = defer(), heard = [];
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, play: async audio => { heard.push(audio); } });
  const a = queue.offer(entry('A', 'report', { prepare: () => late.promise })); await tick();
  const b = queue.offer(entry('B')); const turn = queue.interrupt(); queue.acceptTurn(turn); queue.resume();
  await queue.controlReport('next', { turn }); late.resolve('obsolete A'); await Promise.all([a, b]);
  assert.deepEqual(heard, ['B']); await queue.close();
});

test('report memory expires old results and closing invalidates controls and retained audio', async () => {
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, historyLimit: 2, play: async () => {} });
  for (const id of ['A', 'B', 'C']) await queue.offer(entry(id));
  assert.deepEqual(queue.reportState().map(report => report.id), ['B', 'C']);
  const turn = queue.interrupt(); queue.acceptTurn(turn);
  await assert.rejects(queue.controlReport('repeat', { id: 'A', turn }), /not found|expired/i);
  await queue.close(); assert.deepEqual(queue.reportState(), []);
  await assert.rejects(queue.controlReport('next', { turn }), /ended|closed/i);
});

test('the next report sentence prepares during current playback instead of adding another synthesis gap', async () => {
  const release = defer(), entered = defer(), prepared = [];
  const queue = new api.VoiceSpeechQueue({ gapMs: 0, play: async audio => { if (audio === 'one') { entered.resolve(); await release.promise; } } });
  const report = queue.offer(entry('A', 'report', { parts: ['one', 'two'].map(text => ({ text, prepare: async () => { prepared.push(text); return text; } })) }));
  try { await entered.promise; await tick(); assert.deepEqual([...prepared], ['one', 'two']); }
  finally { release.resolve(); await report; await queue.close(); }
});
