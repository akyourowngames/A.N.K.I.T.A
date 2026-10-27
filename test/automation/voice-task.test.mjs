import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const api = await import('../../src/automation/voice-task.mjs').catch(() => ({}));
const call = (id, name = 'read_file') => ({ id, function: { name, arguments: '{"path":"unused"}' } });
function storeFor(t, options = {}) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-task-'));
  t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  return new api.VoiceTaskStore({ directory, ...options });
}

test('a voice task records actual tool steps and survives a new store instance', async t => {
  const store = storeFor(t);
  const changes = [];
  const { task } = await api.runVoiceTask({ store, transcript: 'Workspace kholo', language: 'hi-IN', confidence: 0.9,
    onUpdate: record => changes.push(structuredClone(record)), run: async observer => {
      assert.equal(store.list()[0].status, 'running');
      observer.onToolCall(call('read'));
      observer.onToolCall(call('write', 'write_file'));
      observer.onToolResult(call('write', 'write_file'), 'Written.');
      observer.onToolResult(call('read'), 'Contents.');
      return { text: 'Workspace tayyar hai.', error: null };
    } });
  assert.equal(task.status, 'done');
  assert.equal(task.transcript, 'Workspace kholo');
  assert.equal(task.language, 'hi-IN');
  assert.equal(task.confidence, 0.9);
  assert.deepEqual(task.steps.map(step => step.state), ['done', 'done']);
  assert.equal(task.steps[1].label, 'Write · write_file');
  assert.ok(task.endedAt >= task.startedAt);
  assert.deepEqual(new api.VoiceTaskStore({ directory: store.directory }).get(task.id), task);
  assert.deepEqual(changes.map(record => record.status).filter((status, i, all) => status !== all[i - 1]), ['queued', 'running', 'done']);
});

test('approval stays authoritative and its waiting status is persisted before asking', async t => {
  const store = storeFor(t);
  const { task } = await api.runVoiceTask({ store, transcript: 'Make a file', run: async (observer, task) => {
    observer.onToolCall(call('write', 'write_file'));
    const allowed = await task.approval('write_file', async () => {
      assert.equal(store.get(task.record.id).status, 'waiting_for_approval');
      return false;
    });
    assert.equal(allowed, false);
    assert.equal(task.record.status, 'running');
    observer.onToolResult(call('write'), 'The user denied this action.');
    return { text: 'Permission was declined.' };
  } });
  assert.equal(task.status, 'failed');
  assert.equal(task.steps[0].state, 'failed');
  assert.match(task.summary, /declined/);
});

for (const [name, run, expected] of [
  ['planner failure', async () => { throw new Error('Baseten 403'); }, 'failed'],
  ['empty reply', async () => ({ text: '' }), 'failed'],
  ['cancelled turn', async observer => { observer.onToolCall(call('pending')); return { error: 'cancelled', text: '' }; }, 'cancelled'],
]) test(`${name} keeps the transcript and does not become done`, async t => {
  const store = storeFor(t);
  const { task } = await api.runVoiceTask({ store, transcript: 'Saved words', run });
  assert.equal(task.status, expected);
  assert.equal(store.get(task.id).transcript, 'Saved words');
  assert.ok(task.error);
  assert.ok(task.steps.every(step => step.state !== 'running'));
});

test('job files redact configured secrets and never persist raw tool arguments or results', async t => {
  const secret = 'fixture-opaque-credential';
  const store = storeFor(t, { secrets: [secret] });
  const { task } = await api.runVoiceTask({ store, transcript: `Read ${secret}`, run: async observer => {
    const item = call('read'); item.function.arguments = JSON.stringify({ token: secret });
    observer.onToolCall(item); observer.onToolResult(item, secret);
    return { text: `Read ${secret}` };
  } });
  const saved = fs.readFileSync(path.join(store.directory, `${task.id}.json`), 'utf8');
  assert.ok(!saved.includes(secret));
  assert.ok(!saved.includes('arguments'));
  assert.ok(!saved.includes('result'));
  assert.match(saved, /REDACTED/);
  assert.equal(store.get('../outside'), null);
});

test('credential-shaped speech and reports stay valid JSON after redaction', async t => {
  const store = storeFor(t);
  const { task } = await api.runVoiceTask({ store, transcript: 'Set password=abc', run: async () => ({ text: 'My token: xyz' }) });
  assert.equal(task.status, 'done');
  assert.equal(task.transcript, 'Set password=[REDACTED]');
  assert.equal(task.summary, 'My token: [REDACTED]');
  assert.deepEqual(store.get(task.id), task);
});

test('retention bounds saved records and ignores malformed or unrelated files', async t => {
  const store = storeFor(t, { limit: 2 });
  fs.writeFileSync(path.join(store.directory, 'broken.json'), '{');
  fs.writeFileSync(path.join(store.directory, 'unrelated.txt'), 'keep');
  for (let i = 0; i < 4; i++) await api.runVoiceTask({ store, transcript: `request ${i}`, run: async () => ({ text: 'Done.' }) });
  assert.equal(store.list().length, 2);
  assert.ok(fs.existsSync(path.join(store.directory, 'unrelated.txt')));
});

test('speech drops overlapping and too-frequent progress, drains before the final report', async () => {
  let now = 0; let release;
  const spoken = [];
  const speech = api.createStepSpeech({ now: () => now, minIntervalMs: 2500, speak: text => {
    spoken.push(text); return new Promise(resolve => { release = resolve; });
  } });
  assert.equal(speech.offer('First'), true);
  assert.equal(speech.offer('Overlap'), false);
  release(); await speech.drain();
  now = 2499; assert.equal(speech.offer('Too soon'), false);
  now = 2500; assert.equal(speech.offer('Second'), true);
  const drain = speech.drain(); release(); await drain;
  assert.deepEqual(spoken, ['First', 'Second']);
});

test('speech failure cannot fail a successful task and late progress is not queued', async t => {
  const store = storeFor(t);
  const { task } = await api.runVoiceTask({ store, transcript: 'Read', speak: async () => { throw new Error('speaker offline'); },
    run: async observer => { observer.onToolCall(call('a')); observer.onToolResult(call('a'), 'Okay'); return { text: 'Done.' }; } });
  assert.equal(task.status, 'done');
});

test('a stalled progress synthesis cannot delay task completion or cancellation', { timeout: 1000 }, async t => {
  const store = storeFor(t);
  for (const error of [null, 'cancelled']) {
    let signal;
    const { task } = await api.runVoiceTask({ store, transcript: 'Read', speak: (_line, options) => {
      signal = options.signal;
      return new Promise(() => {});
    }, run: async observer => {
      observer.onToolCall(call('a'));
      observer.onToolResult(call('a'), 'Read.');
      return { text: error ? '' : 'Done.', error };
    } });
    assert.ok(signal.aborted);
    assert.equal(task.status, error ? 'cancelled' : 'done');
  }
});

test('approval and completion invalidate in-flight progress audio', async t => {
  const store = storeFor(t);
  const signals = [];
  const { task } = await api.runVoiceTask({ store, transcript: 'Write', speak: async (_line, { signal }) => { signals.push(signal); },
    run: async (observer, task) => {
      observer.onToolCall(call('write', 'write_file'));
      await task.approval('write_file', async () => {
        assert.equal(signals[0].aborted, true, 'stale step synthesis cannot interrupt the approval');
        return true;
      });
      observer.onToolResult(call('write'), 'Written');
      return { text: 'Done.' };
    } });
  assert.equal(task.status, 'done');
  assert.ok(signals.every(signal => signal.aborted));
});

test('an audit write failure notifies the caller to stop tools', async t => {
  const store = storeFor(t);
  const save = store.save.bind(store);
  let stopped = false;
  store.save = record => {
    if (record.steps.length && !stopped) throw new Error('disk full');
    return save(record);
  };
  const { task } = await api.runVoiceTask({ store, transcript: 'Read', onTrackingError: () => { stopped = true; }, run: async observer => {
    assert.throws(() => observer.onToolCall(call('read')), /disk full/);
    assert.ok(stopped);
    return { text: 'Pretend done' };
  } });
  assert.equal(task.status, 'failed');
  assert.match(task.error, /disk full/);
});

test('terminal task command lists saved voice tasks and shows steps separately from process jobs', async t => {
  const store = storeFor(t);
  assert.match(api.voiceTaskCommand('/task', store), /No voice tasks/);
  const { task } = await api.runVoiceTask({ store, transcript: 'Read a file', run: async observer => {
    observer.onToolCall(call('a')); observer.onToolResult(call('a'), 'ok'); return { text: 'Read it.' };
  } });
  assert.match(api.voiceTaskCommand('/task', store), new RegExp(task.id));
  assert.match(api.voiceTaskCommand(`/task ${task.id}`, store), /Read · read_file/);
  assert.match(api.voiceTaskCommand('/task missing', store), /No voice task/);
  assert.match(api.voiceTaskCommand('/task a b', store), /Usage/);
  assert.ok(!api.renderVoiceTask({ ...task, transcript: '\x1b[2Jbad\r\nline' }).includes('\x1b'));
});

test('a storage failure stops the request before any tool executes', async t => {
  const store = storeFor(t);
  fs.rmSync(store.directory, { recursive: true });
  fs.writeFileSync(store.directory, 'not a directory');
  let ran = false;
  await assert.rejects(api.runVoiceTask({ store, transcript: 'Do work', run: async () => { ran = true; return { text: 'Done' }; } }));
  assert.equal(ran, false);
});

test('a failed task cannot speak a model-generated success claim as its whole report', () => {
  assert.match(api.voiceTaskReport({ status: 'failed', error: 'Permission declined.', summary: 'Everything is ready.' }), /^Work did not finish/);
  assert.equal(api.voiceTaskReport({ status: 'cancelled', summary: 'Done' }), 'Cancelled.');
  assert.equal(api.voiceTaskReport({ status: 'done', summary: 'Ready.' }), 'Ready.');
});

test('the core verification verdict can fail a step even without an error prefix', async t => {
  const store = storeFor(t);
  const { task } = await api.runVoiceTask({ store, transcript: 'Write', run: async observer => {
    observer.onToolCall(call('a', 'write_file'));
    observer.onToolResult(call('a'), '{"ok":false}', { ok: false });
    return { text: 'Done.' };
  } });
  assert.equal(task.status, 'failed');
  assert.equal(task.steps[0].state, 'failed');
});
