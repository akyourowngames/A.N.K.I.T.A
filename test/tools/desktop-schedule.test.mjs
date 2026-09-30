import test from 'node:test';
import assert from 'node:assert/strict';
import { run } from '../../tools/automation/schedule.mjs';
import { get } from '../../tools/index.mjs';
import { Agent } from '../../src/core/agent.mjs';

test('the scheduling schema exposes concrete update fields and their types to the model', async () => {
  const { parameters } = await import('../../tools/automation/schedule.mjs');
  const patch = parameters.properties.patch;
  assert.equal(patch.properties?.cron?.type, 'string');
  assert.equal(patch.properties?.prompt?.type, 'string');
  assert.equal(patch.properties?.enabled?.type, 'boolean');
  assert.equal(patch.properties?.budget?.properties?.maxTokensPerDay?.type, 'number');
  assert.equal(patch.additionalProperties, false);
});
test('desktop chat creation activates an owned autonomous job and returns a structured task card', async () => {
  let captured;
  const scheduler = { add: (input, options) => { captured = { input, options }; return { id: 'job', name: input.name, cron: '0 9 * * *' }; } };
  const result = await run({ action: 'add', name: 'Post', cron: 'daily 09:00', prompt: 'Post' }, { scheduler, scheduleThreadId: 'owner' });
  assert.equal(captured?.input.threadId, 'owner'); assert.notEqual(captured.options?.draft, true);
  assert.equal(captured.input.browserPolicy, 'autonomous');
  assert.ok(captured.input.requestKey);
  assert.equal(JSON.parse(result).job.id, 'job');
  assert.equal(JSON.parse(result).action, 'add');
  const agent = new Agent({ client: {}, config: { tools: true, desktopBackgroundJobs: true }, skillsEnabled: false });
  assert.ok(agent.specParts().core.some(spec => spec.function.name === 'schedule'));
});
test('desktop updates and run-now use normal scheduler paths without opening a form', async () => {
  const calls = [];
  const scheduler = { update: (id, patch) => { calls.push([id, patch]); return { id }; }, runNow: async id => { calls.push(['run', id]); return { queued: true }; }, list: () => [{ id: 'job' }] };
  assert.equal(JSON.parse(await run({ action: 'update', id: 'job', patch: { cron: 'daily 10:00' } }, { scheduler })).job.id, 'job');
  assert.equal(JSON.parse(await run({ action: 'run', id: 'job' }, { scheduler })).queued, true);
  assert.deepEqual(calls, [['job', { cron: 'daily 10:00' }], ['run', 'job']]);
});
test('schedule_status is registered and reads the desktop scheduler without changing it', async () => {
  assert.ok(get('schedule_status'));
  const value = await get('schedule_status').run({}, { scheduler: { status: () => [{ id: 'job', lastStatus: 'ok' }] }, scheduleThreadId: 'owner' });
  assert.match(value, /job/);
});

test('run by a model-supplied task name returns the canonical job receipt', async () => {
  const job = { id: 'canonical-job', name: 'Morning report' }, calls = [];
  const scheduler = { list: () => [job], runNow: async id => { calls.push(id); return { queued: true }; } };
  const result = JSON.parse(await run({ action: 'run', id: ' MORNING REPORT ' }, { scheduler }));
  assert.equal(result.job?.id, job.id); assert.deepEqual(calls, [job.id]);
});

test('model task names resolve within the owning conversation and ambiguous names are rejected', async () => {
  const jobs = [{ id: 'chief-job', name: 'Morning briefing', threadId: 'chief' }, { id: 'research-job', name: 'Morning briefing', threadId: 'research' }];
  const calls = [], scheduler = { list: thread => jobs.filter(job => !thread || job.threadId === thread), update: (id, patch) => { calls.push(id); return { ...jobs.find(job => job.id === id), ...patch }; } };
  const result = JSON.parse(await run({ action: 'update', id: 'Morning briefing', patch: { prompt: 'Research task' } }, { scheduler, scheduleThreadId: 'research' }));
  assert.equal(result.job.threadId, 'research'); assert.deepEqual(calls, ['research-job']);
  jobs.push({ id: 'second-research-job', name: 'Morning briefing', threadId: 'research' });
  assert.match(await run({ action: 'update', id: 'Morning briefing', patch: {} }, { scheduler, scheduleThreadId: 'research' }), /ambiguous/i);
  assert.equal(calls.length, 1);
});

test('an explicit none project stays detached regardless of casing or whitespace', async () => {
  let captured;
  const scheduler = { add: input => { captured = input; return input; } };
  await run({ action: 'add', name: 'Detached', cron: '@daily', prompt: 'Check', project: ' NONE ' }, { scheduler, scheduleThreadId: 'chief' });
  assert.equal(captured.projectDetached, true); assert.equal(captured.projectId, null);
});

test('flat model updates normalize into a patch and empty or conflicting updates never claim success', async () => {
  const calls = [], scheduler = { list: () => [{ id: 'job', name: 'Report' }], update: (id, patch) => { calls.push(patch); return { id, ...patch }; } };
  const result = JSON.parse(await run({ action: 'update', id: 'job', cron: 'weekdays 10:30' }, { scheduler }));
  assert.equal(result.job.cron, 'weekdays 10:30');
  assert.match(await run({ action: 'update', id: 'job' }, { scheduler }), /fields to update/i);
  assert.match(await run({ action: 'update', id: 'job', cron: '@daily', patch: { cron: '@hourly' } }, { scheduler }), /conflicting/i);
  assert.equal(calls.length, 1);
});
