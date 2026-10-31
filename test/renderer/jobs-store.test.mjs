import test from 'node:test';
import assert from 'node:assert/strict';
import { initialState, reducer } from '../../desktop/renderer/src/state/store.ts';

const job = { id: 'job-1', name: 'Daily read', cron: '* * * * *', cronLabel: 'Every minute', prompt: 'Read', threadId: 'owner', deliveryThreadId: 'owner', allow: { read: true, interact: true, login: false, sites: [], mode: 'isolated' }, budget: { maxRunsPerDay: 1, maxTokensPerDay: 1, maxMinutesPerDay: 1 }, timeoutMs: 1, headless: true, onNewRequest: 'pause-ask', enabled: true, ownerMissing: false, pausedReason: null, nextRunAt: null, nextRunIn: null, timeZone: 'UTC', running: false, step: 0, scope: null, needsApproval: false, lastStatus: null, lastSummary: null };
const event = (payload) => reducer({ ...initialState, jobs: [job] }, { type: 'event', event: payload });

test('live run events update the job row without touching chat', () => {
  const started = event({ type: 'routine-run-start', routineId: 'job-1', threadId: 'owner', runId: 'r1', scope: 'job:job-1' });
  assert.equal(started.jobs[0].running, true);
  assert.equal(started.jobs[0].scope, 'job:job-1');
  assert.deepEqual(started.threads, {}, 'a run start adds no chat message');

  const stepped = reducer(started, { type: 'event', event: { type: 'routine-run-step', routineId: 'job-1', threadId: 'owner', runId: 'r1', step: 3 } });
  assert.equal(stepped.jobs[0].step, 3);
  assert.deepEqual(stepped.threads, {});

  const ended = reducer(stepped, { type: 'event', event: { type: 'routine-run-end', routineId: 'job-1', threadId: 'owner', runId: 'r1', status: 'ok' } });
  assert.equal(ended.jobs[0].running, false);
  assert.equal(ended.jobs[0].lastStatus, 'ok');
  assert.deepEqual(ended.threads, {});
});

test('a queued result appears in the waiting list, deduplicated, and a refresh replaces it', () => {
  const queued = event({ type: 'routine-queued', routineId: 'job-1', threadId: 'owner', runId: 'r1', detail: 'Daily read' });
  assert.equal(queued.deliveries.owner.length, 1);
  assert.equal(queued.deliveries.owner[0].name, 'Daily read', 'the event detail supplies the title');
  assert.deepEqual(queued.threads, {}, 'queuing never posts into chat');

  const again = reducer(queued, { type: 'event', event: { type: 'routine-queued', routineId: 'job-1', threadId: 'owner', runId: 'r1', detail: 'Daily read' } });
  assert.equal(again.deliveries.owner.length, 1, 'the same run is not listed twice');

  const refreshed = reducer(again, { type: 'event', event: { type: 'routine-delivery-state', threadId: 'owner', pending: [] } });
  assert.deepEqual(refreshed.deliveries.owner, [], 'the scheduler refresh clears a delivered result');
});

test('the waiting list is per teammate so one busy chat does not hide another', () => {
  const state = event({ type: 'routine-queued', routineId: 'job-1', threadId: 'other', runId: 'r9', detail: 'Other read' });
  assert.equal(state.deliveries.other.length, 1);
  assert.equal(state.deliveries.owner, undefined);
});
