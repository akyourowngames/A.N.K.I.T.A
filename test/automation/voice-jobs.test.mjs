import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { VoiceTaskStore } from '../../src/automation/voice-task.mjs';
const api = await import('../../src/automation/voice-jobs.mjs').catch(() => ({}));
const defer = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const tick = () => new Promise(resolve => setImmediate(resolve));
const waiting = (work, signal) => signal.aborted ? Promise.resolve() : Promise.race([work, new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }))]);
function poolFor(t, options) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'voice-jobs-'));
  const pool = new api.VoiceJobs({ store: new VoiceTaskStore({ directory }), ...options });
  t.after(async () => { await pool.close(); fs.rmSync(directory, { recursive: true, force: true }); });
  return pool;
}

test('a cyclic resource wait retains its real cause when the worker aborts to release leases', async t => {
  const pool = poolFor(t, { run: async entry => {
    entry.cancelWorker = () => {};
    await pool.acquire(entry.id, [{ kind: 'shared', key: 'one', mode: 'write' }]);
    try {
      entry.failure = 'Cyclic voice resource wait detected. Retry after another job finishes.';
      throw new DOMException('Worker stopped for a resource cycle.', 'AbortError');
    } catch (error) { throw error; }
  } });
  const job = await pool.submit({ ownerId: 'owner', transcript: 'conflicting edit' });
  const result = await pool.waitFor(job.id, { ownerId: 'owner' });
  assert.equal(result.task.status, 'failed');
  assert.match(result.task.error, /Cyclic voice resource wait/);
});

test('second voice job finishes while the first stays blocked, with separate IDs and abort signals', async t => {
  const hold = defer(); const starts = [];
  const pool = poolFor(t, { run: async (job, { signal }) => {
    starts.push({ id: job.id, transcript: job.transcript, signal });
    if (job.transcript === 'First poem') await waiting(hold.promise, signal);
    return { text: `${job.transcript} ready.` };
  } });
  const first = await pool.submit({ ownerId: 'owner', transcript: 'First poem', context: { marker: 'first' } });
  const second = await pool.submit({ ownerId: 'owner', transcript: 'Second report', context: { marker: 'second' } });
  const result = await pool.waitFor(second.id, { ownerId: 'owner' });
  assert.equal(result.task.summary, 'Second report ready.');
  assert.equal(pool.list('owner').find(job => job.id === first.id).status, 'running');
  assert.notEqual(first.id, second.id); assert.notEqual(starts[0].signal, starts[1].signal);
  hold.resolve(); assert.equal((await pool.waitFor(first.id, { ownerId: 'owner' })).task.status, 'done');
});

test('individual cancellation leaves unrelated jobs running and results scoped to their owner', async t => {
  const pool = poolFor(t, { run: async (_job, { signal }) => {
    await new Promise(resolve => signal.addEventListener('abort', resolve, { once: true }));
    return { text: '', error: 'cancelled' };
  } });
  const one = await pool.submit({ ownerId: 'owner', transcript: 'One' });
  const two = await pool.submit({ ownerId: 'owner', transcript: 'Two' });
  assert.throws(() => pool.cancel(one.id, { ownerId: 'someone-else' }), /not found/i);
  assert.equal(pool.cancel(one.id, { ownerId: 'owner' }), true);
  assert.equal((await pool.waitFor(one.id, { ownerId: 'owner' })).task.status, 'cancelled');
  assert.equal(pool.list('owner').find(job => job.id === two.id).status, 'running');
  assert.deepEqual(pool.list('someone-else'), []);
});

test('capacity retains one control-only turn so voice can still inspect or stop busy jobs', async t => {
  const hold = defer(); const controls = [];
  const pool = poolFor(t, { concurrency: 1, run: async (job, { signal }) => {
    controls.push(job.controlOnly);
    if (!job.controlOnly) await waiting(hold.promise, signal);
    return { text: job.controlOnly ? 'Your first job is still running.' : 'Ready.' };
  } });
  const work = await pool.submit({ ownerId: 'owner', transcript: 'Long work' });
  const status = await pool.submit({ ownerId: 'owner', transcript: 'What is still running?' });
  assert.equal((await pool.waitFor(status.id, { ownerId: 'owner' })).task.status, 'done');
  assert.deepEqual(controls, [false, true]); hold.resolve(); await pool.waitFor(work.id, { ownerId: 'owner' });
});

test('voice-only job control waits for a real predecessor result, rejects self-wait and cross-owner access', async t => {
  const hold = defer(), consumerHold = defer();
  const pool = poolFor(t, { run: async (job, { signal }) => {
    await waiting(job.transcript === 'Research' ? hold.promise : consumerHold.promise, signal);
    return { text: `${job.transcript} verified.` };
  } });
  const research = await pool.submit({ ownerId: 'owner', transcript: 'Research' });
  const consumer = await pool.submit({ ownerId: 'owner', transcript: 'Save result' });
  const tool = pool.controlTool({ ownerId: 'owner', requesterId: consumer.id });
  await assert.rejects(tool.run({ action: 'wait', id: consumer.id }), /itself/i);
  const result = tool.run({ action: 'wait', id: research.id });
  await tick(); hold.resolve(); assert.match(await result, /Research verified/);
  assert.throws(() => pool.result(research.id, { ownerId: 'other' }), /not found/i);
  await assert.rejects(tool.run({ action: 'cancel', id: research.id, ownerId: 'other' }), /invalid/i);
  consumerHold.resolve(); await pool.waitFor(consumer.id, { ownerId: 'owner' });
});

test('tiny retention cannot remove an active job record when a parallel job finishes', async t => {
  const hold = defer();
  const pool = poolFor(t, { run: async (job, { signal }) => { if (job.transcript === 'Held') await waiting(hold.promise, signal); return { text: 'Done.' }; } });
  pool.store.limit = 1;
  const first = await pool.submit({ ownerId: 'owner', transcript: 'Held' });
  const second = await pool.submit({ ownerId: 'owner', transcript: 'Quick' });
  await pool.waitFor(second.id, { ownerId: 'owner' });
  assert.equal(pool.store.get(first.id).status, 'running'); hold.resolve(); await pool.waitFor(first.id, { ownerId: 'owner' });
});

test('an unfinished owned command retains its resource after the report, and stopping it frees the next job', async t => {
  const child = defer();
  const pool = poolFor(t, { run: async (job, { signal }) => {
    await pool.acquire(job.id, [{ kind: 'path', key: '/workspace/shared.txt', mode: 'write' }], { signal });
    if (job.transcript === 'Start command') job.resourceHold = { promise: child.promise, stop: async () => child.resolve() };
    return { text: `${job.transcript} done.` };
  } });
  pool.store.limit = 1;
  const first = await pool.submit({ ownerId: 'owner', transcript: 'Start command' });
  await pool.waitFor(first.id, { ownerId: 'owner' });
  assert.equal(pool.list('owner').find(job => job.id === first.id).resourcesHeld, true);
  const second = await pool.submit({ ownerId: 'owner', transcript: 'Next edit' });
  await tick(); assert.equal(pool.list('owner').find(job => job.id === second.id).status, 'waiting_for_resource');
  assert.equal(pool.store.get(first.id)?.resourcesHeld, true, 'a live command must retain its durable audit record');
  assert.equal(pool.cancel(first.id, { ownerId: 'owner' }), true);
  assert.equal((await pool.waitFor(second.id, { ownerId: 'owner' })).task.status, 'done');
  assert.notEqual(pool.list('owner').find(job => job.id === first.id)?.resourcesHeld, true, 'a stopped command may be evicted by the one-record history limit');
});

test('failed result observers and diagnostics cannot turn completed work into an unhandled rejection', async t => {
  const pool = poolFor(t, { run: async () => ({ text: 'Saved.' }), onComplete: async () => { throw new Error('Window closed'); }, onError: async () => { throw new Error('Diagnostic unavailable'); } });
  const job = await pool.submit({ ownerId: 'owner', transcript: 'Save' });
  assert.equal((await pool.waitFor(job.id, { ownerId: 'owner' })).task.status, 'done'); await tick();
});
