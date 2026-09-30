import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { ApprovalRegistry } from '../../desktop/electron/approvals.mjs';

async function fixture(t, send = async () => 'Read complete.') {
  assert.ok(fs.existsSync(new URL('../../desktop/electron/scheduler.mjs', import.meta.url)), 'DesktopScheduler exists');
  const { DesktopScheduler } = await import('../../desktop/electron/scheduler.mjs');
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'desktop-jobs-'));
  const events = [], delivered = [], workers = [];
  let now = new Date('2026-09-27T09:00:00Z');
  const owners = [{ id: 'owner', name: 'Owner', persona: '', updatedAt: now.toISOString() }];
  class Worker {
    constructor(options) { Object.assign(this, options); this.messages = []; workers.push(this); }
    send(prompt, hooks) { return send.call(this, prompt, hooks); }
    cancel() { this.cancelledFlag = true; }
  }
  const engine = { config: { tools: true, timeZone: 'UTC' }, client: {}, AgentClass: Worker,
    emit: e => events.push(e), turns: new Map(), teammates: { list: () => owners, find: id => owners.find(x => x.id === id) },
    approvals: new ApprovalRegistry(e => events.push({ type: 'approval-request', ...e })),
    browserManager: { createScope: () => ({ view: async () => ({ tabs: [], screenshot: null }), cancel() {} }), closeScope: async () => {} },
    deliverRoutine: async receipt => { delivered.push(receipt); return true; },
  };
  const scheduler = new DesktopScheduler({ engine, file: path.join(dir, 'state.json'), sessionsDir: dir, now: () => now, approvalTimeoutMs: 30 });
  t.after(async () => { await scheduler.stop(); fs.rmSync(dir, { recursive: true, force: true }); });
  const add = patch => scheduler.add({ name: 'Read', cron: '* * * * *', prompt: 'Read the page', threadId: 'owner', ...patch });
  return { scheduler, engine, add, events, delivered, workers, owners, dir, clock: value => { now = new Date(value); } };
}
test('fresh worker carries nominal time, verbatim prompt and delivers once to the owner', async t => {
  let observed;
  const f = await fixture(t, async function(prompt) { observed = prompt; return 'Finished reading.'; });
  const r = f.add({ prompt: '  Read today.  ' });
  await f.scheduler.runNow(r.id); await f.scheduler.drain();
  assert.match(observed, /attempt 1/); assert.ok(observed.endsWith('  Read today.  '));
  assert.equal(f.delivered.length, 1); assert.equal(f.delivered[0].threadId, 'owner');
  assert.equal(f.scheduler.list()[0].lastStatus, 'ok');
  assert.equal(f.workers[0].config.backgroundJob, true, 'Execution prompt must be selected for real workers');
  assert.notEqual(f.workers[0], f.engine.agents?.get('owner'));
});

test('completion jobs finish after cumulative input tokens exceed the old daily ceiling', async t => {
  let read = false;
  const f = await fixture(t, async function(_prompt, hooks) {
    hooks.onUsage({ prompt_tokens: 63000, completion_tokens: 472, total_tokens: 63472 });
    await this.toolContext.authorizeBrowser({ action: 'read' }, { mode: 'isolated', url: 'https://example.com/profile' });
    read = true;
    return 'Observed 71 followers.';
  });
  const job = f.add({ browserPolicy: 'autonomous', budget: { maxRunsPerDay: 2, maxTokensPerDay: 60000, maxMinutesPerDay: 10 } });
  await f.scheduler.runNow(job.id); await f.scheduler.drain();
  assert.equal(read, true); assert.equal(f.delivered[0].status, 'ok');
  assert.equal(f.scheduler.list()[0].enabled, true); assert.equal(f.scheduler.list()[0].spend.tokens, 63472);
  assert.equal(f.workers[0].config.backgroundExecutionPolicy, 'complete');
});

test('completion jobs ignore execution ceilings while progressing and remain manually stoppable', async t => {
  let finish, started;
  const began = new Promise(resolve => { started = resolve; });
  const f = await fixture(t, function() { started(); return new Promise(resolve => { finish = resolve; }); });
  const job = f.add({ timeoutMs: 20, budget: { maxRunsPerDay: 1, maxTokensPerDay: 1, maxMinutesPerDay: 1 } });
  f.scheduler.store.updateRoutine(job.id, { spend: { day: '2026-09-27', runs: 8, tokens: 90000, minutes: 90 } });
  await f.scheduler.runNow(job.id);
  await Promise.race([began, new Promise(resolve => setTimeout(resolve, 50))]);
  assert.equal(f.workers.length, 1, 'A completion job starts despite prior daily usage');
  await new Promise(resolve => setTimeout(resolve, 40));
  assert.equal(f.scheduler.runs.has(job.id), true);
  assert.equal(f.scheduler.stopRun(job.id), true); await f.scheduler.drain(); finish('Late answer');
  assert.equal(f.delivered[0].status, 'stopped'); assert.equal(f.workers[0].cancelledFlag, true);
});

test('a manually requested completion run on a paused task reports actual success without resuming its cron', async t => {
  const f = await fixture(t);
  const job = f.add({ enabled: false });
  f.scheduler.store.updateRoutine(job.id, { pausedReason: 'budget', spend: { day: '2026-09-27', tokens: 100000 } });
  await f.scheduler.runNow(job.id); await f.scheduler.drain();
  assert.equal(f.delivered[0].status, 'ok'); assert.equal(f.scheduler.list()[0].enabled, false);
});

test('a fresh worker compares against the last successful result even after a failed run and reload', async t => {
  let calls = 0;
  const f = await fixture(t, async function(prompt) {
    if (++calls === 1) return 'Followers: 71. First recorded reading.';
    if (calls === 2) throw new Error('Temporary site failure');
    assert.match(prompt, /Previous successful result/);
    assert.match(prompt, /Followers: 71/); assert.doesNotMatch(prompt, /Temporary site failure/);
    return 'Followers: 72. Change: +1.';
  });
  const job = f.add();
  for (let attempt = 0; attempt < 3; attempt++) { await f.scheduler.runNow(job.id); await f.scheduler.drain(); f.scheduler.store.load(); }
  assert.equal(calls, 3); assert.equal(f.delivered[2].status, 'ok');
  assert.match(f.scheduler.list()[0].lastSuccessfulResult.text, /Change: \+1/);
});

test('a forced tool-loop termination produces an incomplete job receipt without replaying the task', async t => {
  let executions = 0;
  const f = await fixture(t, async function() { executions++; this.terminationReason = 'tool round budget spent'; return 'I started the task.'; });
  const job = f.add(); await f.scheduler.runNow(job.id); await f.scheduler.drain();
  assert.equal(executions, 1); assert.equal(f.delivered.length, 1);
  assert.equal(f.delivered[0].status, 'error'); assert.match(f.delivered[0].text, /before completion/);
});

test('model mutations resolve duplicate task names only within the owning teammate', async t => {
  const f = await fixture(t), { run } = await import('../../tools/automation/schedule.mjs');
  f.owners.push({ id: 'research', name: 'Research', persona: '' });
  const chief = f.add({ name: 'Morning briefing', prompt: 'Chief task' });
  const research = f.add({ name: 'Morning briefing', prompt: 'Research task', threadId: 'research' });
  const updated = JSON.parse(await run({ action: 'update', id: 'Morning briefing', patch: { prompt: 'Updated research task' } }, { scheduler: f.scheduler, scheduleThreadId: 'research' }));
  assert.equal(updated.job.id, research.id);
  assert.equal(f.scheduler.list().find(job => job.id === chief.id).prompt, 'Chief task');
  assert.equal(f.scheduler.list('research')[0].prompt, 'Updated research task');
  const removed = JSON.parse(await run({ action: 'remove', id: 'Morning briefing' }, { scheduler: f.scheduler, scheduleThreadId: 'research' }));
  assert.equal(removed.job.id, research.id); assert.equal(f.scheduler.list().length, 1);
  assert.equal(f.scheduler.list()[0].id, chief.id);
});
test('model creation is idempotent across reload and conflicting reuse is rejected', async t => {
  const f = await fixture(t);
  const first = f.add({ requestKey: 'create-post', browserPolicy: 'autonomous', description: 'Checks the daily post' });
  assert.equal(f.add({ requestKey: 'create-post', browserPolicy: 'autonomous', description: 'Checks the daily post' }).id, first.id);
  assert.equal(f.scheduler.list().length, 1);
  assert.throws(() => f.add({ requestKey: 'create-post', prompt: 'Different task' }), /request key/i);
  assert.throws(() => f.add({ requestKey: 'create-post', browserPolicy: 'autonomous', description: 'Checks the daily post', timeoutMs: 60000 }), /request key/i);
  assert.throws(() => f.add({ browserPolicy: 'anything' }), /browserPolicy/);
  assert.throws(() => f.scheduler.update(first.id, { kind: 'anything' }), /kind/);
});
test('autonomous browser jobs can navigate, click and use saved login without site dialogs', async t => {
  const f = await fixture(t); const r = f.add({ browserPolicy: 'autonomous' });
  const run = { routineId: r.id, active: true, grants: new Set() };
  for (const action of ['open', 'act', 'login']) assert.equal(await f.scheduler.authorize(run, { action }, { mode: 'isolated', url: 'https://new-site.example/sign-in' }), true);
  assert.equal(f.events.filter(e => e.type === 'approval-request').length, 0);
  await assert.rejects(f.scheduler.authorize(run, { action: 'open' }, { mode: 'local', url: 'https://new-site.example' }), /mode/);
});
test('a ref rejected before interaction can recover; a model can stop for foreground MFA', async t => {
  const f = await fixture(t, async function(_prompt, hooks) {
    this.toolContext.onBrowserError(Object.assign(new Error('Stale ref; fresh snapshot'), { name: 'BrowserReferenceError' }));
    hooks.onToolResult({ function: { name: 'browser' } }, 'Error: Stale ref; fresh snapshot');
    assert.notEqual(this.cancelledFlag, true);
    return 'Recovered with a fresh ref';
  });
  const r = f.add({ browserPolicy: 'autonomous' }); await f.scheduler.runNow(r.id); await f.scheduler.drain();
  assert.equal(f.delivered[0].status, 'ok');
  const { run } = await import('../../tools/automation/schedule.mjs');
  let message;
  await run({ action: 'needs_input', reason: 'An authenticator code is required' }, { backgroundJob: true, requireForeground: text => { message = text; } });
  assert.match(message, /authenticator/);
});
test('heartbeat skips a busy teammate and suppresses a quiet model response', async t => {
  const f = await fixture(t, async () => 'HEARTBEAT_OK');
  const r = f.add({ kind: 'heartbeat', cron: '* * * * *' });
  f.scheduler.store.updateRoutine(r.id, { createdAt: '2026-09-27T08:00:00Z' });
  f.engine.turns.set('owner', Promise.resolve());
  await f.scheduler.tick(); await f.scheduler.drain(); assert.equal(f.workers.length, 0);
  f.engine.turns.clear(); f.clock('2026-09-27T09:01:00Z');
  await f.scheduler.tick(); await f.scheduler.drain();
  assert.equal(f.workers.length, 1); assert.equal(f.delivered.length, 0);
  assert.equal(f.scheduler.list()[0].lastStatus, 'quiet');
});

test('jobs use fresh owner project context and heartbeat briefing without borrowing foreground state', async t => {
  const f = await fixture(t, async function() {
    assert.equal(this.projectId, 'project'); assert.match(this.project, /Open tasks: finish report/);
    assert.match(this.config.systemExtra, /Owner instructions/); assert.match(this.config.systemExtra, /Watch overdue tasks/);
    return 'HEARTBEAT_OK';
  });
  f.owners[0].persona = 'Owner instructions'; f.engine.config.briefingPrompt = 'Watch overdue tasks';
  f.engine.contextForJob = () => ({ projectId: 'project', project: 'Open tasks: finish report', workspacePath: null });
  const r = f.add({ kind: 'heartbeat' }); await f.scheduler.runNow(r.id); await f.scheduler.drain();
  assert.equal(f.scheduler.list()[0].lastStatus, 'quiet'); assert.equal(f.delivered.length, 0);
});

test('concurrent initialization acquires ownership once and invalid limits are rejected', async t => {
  const f = await fixture(t); let acquisitions = 0, release;
  const gate = new Promise(resolve => { release = resolve; });
  f.scheduler.ownership = { acquire: async () => { acquisitions++; await gate; }, heartbeat: () => true, release() {} };
  const first = f.scheduler.start(), second = f.scheduler.start();
  await new Promise(resolve => setImmediate(resolve)); release();
  await Promise.all([first, second]); assert.equal(acquisitions, 1);
  assert.throws(() => f.add({ timeoutMs: -1 }), /positive/);
  assert.throws(() => f.add({ budget: { maxRunsPerDay: 0 } }), /positive/);
});

test('locked desktop refuses visible jobs and login permission can be granted per step', async t => {
  const f = await fixture(t, async function() {
    assert.equal(this.browserCredentialAllowed, true);
    return 'Ready';
  });
  const r = f.add({ allow: { sites: ['https://example.com/*'] }, headless: false });
  f.scheduler.foregroundAvailable = false;
  const run = { routineId: r.id, runId: 'lock', threadId: 'owner', grants: new Set(), active: true };
  await assert.rejects(f.scheduler.authorize(run, { action: 'snapshot' }, { mode: 'isolated', url: 'https://example.com/' }), error => error.jobStatus === 'skipped-needs-foreground');
  f.scheduler.foregroundAvailable = true;
  await f.scheduler.runNow(r.id); await f.scheduler.drain(); assert.equal(f.workers.length, 1);
});
test('catch-up executes once inside window and records missed outside it', async t => {
  const f = await fixture(t); const r = f.add({ cron: '0 9 * * *' });
  f.scheduler.store.updateRoutine(r.id, { createdAt: '2026-09-26T00:00:00Z' });
  f.clock('2026-09-27T09:12:00Z'); await f.scheduler.tick(); await f.scheduler.drain();
  assert.equal(f.delivered.length, 1); assert.match(f.delivered[0].text, /late/);
  await f.scheduler.tick(); await f.scheduler.drain(); assert.equal(f.delivered.length, 1);
  f.clock('2026-09-28T10:00:00Z'); await f.scheduler.tick(); await f.scheduler.drain();
  assert.equal(f.scheduler.list()[0].lastStatus, 'missed'); assert.equal(f.workers.length, 1);
});
test('run-now is single flight and foreground chat remains independent', async t => {
  let finish; const f = await fixture(t, () => new Promise(resolve => { finish = resolve; }));
  const r = f.add(); await f.scheduler.runNow(r.id);
  await new Promise(resolve => setImmediate(resolve));
  assert.match((await f.scheduler.runNow(r.id)).notice, /already running/);
  f.engine.turns.set('owner', Promise.resolve());
  f.clock('2026-09-27T09:01:00Z'); await f.scheduler.tick();
  assert.equal(f.scheduler.list()[0].lastStatus, 'skipped-busy');
  finish('Done'); await f.scheduler.drain(); assert.equal(f.workers.length, 1);
});

test('job lifecycle resolves model-supplied names before checking active workers', async t => {
  let finish; const f = await fixture(t, () => new Promise(resolve => { finish = resolve; }));
  const r = f.add({ name: 'Morning brief' }); await f.scheduler.runNow(r.name);
  await new Promise(resolve => setImmediate(resolve));
  assert.throws(() => f.scheduler.remove(r.name), /Stop the running job/);
  assert.match((await f.scheduler.runNow(r.name)).notice, /already running/);
  assert.equal(f.workers.length, 1); assert.equal(f.scheduler.stopRun(r.name), true);
  finish('Stopped'); await f.scheduler.drain(); assert.equal(f.scheduler.list()[0].lastStatus, 'stopped');
});
test('approval is inline, scoped to one routine, expires, and never enables global auto approve', async t => {
  const f = await fixture(t); const r = f.add();
  const run = { routineId: r.id, runId: 'approval-test', threadId: 'owner', step: 1, grants: new Set(), active: true };
  f.scheduler.approvalTimeoutMs = 1000; // Persisting the card can exceed a 30 ms deadline on a busy Windows disk.
  const decision = f.scheduler.authorize(run, { action: 'open', url: 'https://example.com' }, { mode: 'isolated', url: 'https://example.com' });
  await new Promise(resolve => setImmediate(resolve));
  const card = f.events.find(x => x.type === 'approval-request'); assert.equal(card.routineId, r.id);
  assert.ok(f.scheduler.store.findRoutine(r.id).pendingApproval);
  f.scheduler.respondApproval(card.requestId, 'always'); await decision;
  assert.deepEqual(f.scheduler.list()[0].allow.sites, ['https://example.com/*']);
  assert.equal(f.engine.config.autoApprove, undefined);
  f.scheduler.approvalTimeoutMs = 30; // The separate expiry branch uses its short test deadline.
  const timeout = f.scheduler.authorize({ ...run, runId: 'expired', grants: new Set() }, { action: 'open' }, { mode: 'isolated', url: 'https://other.example' });
  await assert.rejects(timeout, /no approval/i);
  assert.equal(f.scheduler.list()[0].enabled, true);
  assert.equal(f.scheduler.list()[0].pendingApproval, null);
});
test('first browser error stops the worker without replay and transcript omits page bodies and filled values', async t => {
  const f = await fixture(t, async function(_prompt, hooks) {
    const call = { id: 'call', function: { name: 'browser', arguments: JSON.stringify({ action: 'fill_form', fields: [{ ref: 'ref', text: 'never-persist-this' }] }) } };
    hooks.onToolCall(call); hooks.onToolResult(call, 'Error: disconnected raw-page-body'); return 'Wrong success';
  });
  const r = f.add(); await f.scheduler.runNow(r.id); await f.scheduler.drain();
  assert.equal(f.workers.length, 1); assert.equal(f.workers[0].cancelledFlag, true);
  assert.equal(f.scheduler.list()[0].lastStatus, 'error');
  const files = fs.readdirSync(path.join(f.dir, 'jobs')).filter(x => x.endsWith('.json'));
  const audit = fs.readFileSync(path.join(f.dir, 'jobs', files[0]), 'utf8');
  assert.doesNotMatch(audit, /never-persist-this|raw-page-body/);
});
test('allow this step never grants later writes when the routine is read-only', async t => {
  const f = await fixture(t); const r = f.add({ allow: { interact: false, sites: ['https://example.com/*'] } });
  const run = { routineId: r.id, runId: 'one-step', threadId: 'owner', step: 1, grants: new Set(), active: true };
  const args = { action: 'act', op: 'click', ref: 'opaque' }, context = { mode: 'isolated', url: 'https://example.com/post' };
  const first = f.scheduler.authorize(run, args, context);
  await new Promise(resolve => setImmediate(resolve));
  f.scheduler.respondApproval(f.events.find(e => e.type === 'approval-request').requestId, 'yes'); await first;
  await assert.rejects(f.scheduler.authorize(run, args, context), /no approval/);
  assert.equal(f.scheduler.list()[0].allow.interact, false);
});
test('timeout settles even an uncooperative provider', async t => {
  const f = await fixture(t, () => new Promise(() => {}));
  const r = f.add({ executionPolicy: 'bounded', timeoutMs: 20 }); await f.scheduler.runNow(r.id); await f.scheduler.drain();
  assert.equal(f.scheduler.list()[0].lastStatus, 'timeout'); assert.equal(f.workers[0].cancelledFlag, true);
});

test('proof URLs exclude tokens and cleanup failure still settles the visible run', async t => {
  const f = await fixture(t);
  f.engine.browserManager.createScope = () => ({ view: async () => ({ tabs: [{ active: true, url: 'https://user:secret@example.com/done?token=never-persist-this#secret' }] }), cancel() {} });
  const r = f.add(); await f.scheduler.runNow(r.id); await f.scheduler.drain();
  assert.equal(f.delivered[0].proof.url, 'https://example.com/done');
  f.engine.browserManager.closeScope = async () => { throw new Error('cleanup failed'); };
  await f.scheduler.runNow(r.id); await f.scheduler.drain();
  assert.equal(f.scheduler.runs.size, 0); assert.equal(f.events.filter(event => event.type === 'routine-run-end').length, 2);
});

test('a delivered proof captures the worker page even when the watched tab differs', async t => {
  const f = await fixture(t);
  f.engine.browserManager.createScope = () => ({ cancel() {}, view: async ({ automation } = {}) => ({ tabs: [{ active: true, url: `https://example.com/${automation ? 'completed' : 'watched'}` }], screenshot: null }) });
  const job = f.add(); await f.scheduler.runNow(job.id); await f.scheduler.drain();
  assert.equal(f.delivered[0].proof.url, 'https://example.com/completed');
});
test('budget exhaustion auto-pauses and day rollover never auto-resumes', async t => {
  const f = await fixture(t, async function(_prompt, hooks) { hooks.onUsage({ total_tokens: 11 }); return 'Done'; });
  const r = f.add({ executionPolicy: 'bounded', budget: { maxTokensPerDay: 10 } }); await f.scheduler.runNow(r.id); await f.scheduler.drain();
  assert.equal(f.scheduler.list()[0].lastStatus, 'stopped-budget');
  assert.equal(f.scheduler.list()[0].enabled, false);
  f.clock('2026-09-28T09:00:00Z'); await f.scheduler.tick();
  assert.equal(f.scheduler.list()[0].enabled, false); assert.equal(f.scheduler.list()[0].spend.tokens, 0);
});

test('reported token budget stops before the next browser mutation', async t => {
  let mutation = false;
  const f = await fixture(t, async function(_prompt, hooks) {
    hooks.onUsage({ total_tokens: 11 });
    await this.toolContext.authorizeBrowser({ action: 'act', op: 'click' }, { mode: 'isolated', url: 'https://example.com/' });
    mutation = true; return 'Wrong';
  });
  const r = f.add({ executionPolicy: 'bounded', budget: { maxTokensPerDay: 10 }, allow: { sites: ['https://example.com/*'] } });
  await f.scheduler.runNow(r.id); await f.scheduler.drain();
  assert.equal(mutation, false); assert.equal(f.scheduler.list()[0].lastStatus, 'stopped-budget');
});
test('orphan falls back and unknown owner mutations reject', async t => {
  const f = await fixture(t); const r = f.add();
  assert.throws(() => f.add({ threadId: 'missing' }), /Teammate not found/);
  assert.throws(() => f.scheduler.update(r.id, { threadId: 'missing' }), /Teammate not found/);
  f.owners.splice(0, 1, { id: 'fallback', name: 'Fallback' });
  await f.scheduler.runNow(r.id); await f.scheduler.drain();
  assert.equal(f.delivered[0].threadId, 'fallback'); assert.equal(f.scheduler.list()[0].ownerMissing, true);
  f.scheduler.update(r.id, { threadId: 'fallback' }); assert.equal(f.scheduler.list()[0].ownerMissing, false);
});

test('chat activates a requested job and foreground cancellation preserves routine approvals', async t => {
  const f = await fixture(t); const r = f.scheduler.add({ name: 'Draft', cron: '@daily', prompt: 'Post', threadId: 'owner', allow: { login: true } }, { draft: true });
  const { run } = await import('../../tools/automation/schedule.mjs');
  const answer = await run({ action: 'enable', id: r.id }, { scheduler: f.scheduler });
  assert.equal(JSON.parse(answer).job.enabled, true); assert.equal(f.scheduler.list()[0].draft, false);
  let settled = false;
  const job = f.engine.approvals.request('owner', 'browser', 'job', { routineId: r.id }).then(value => { settled = true; return value; });
  const foreground = f.engine.approvals.request('owner', 'browser', 'foreground');
  f.engine.approvals.cancelThread('owner'); await foreground; await new Promise(resolve => setImmediate(resolve));
  assert.equal(settled, false);
  f.engine.approvals.respond([...f.engine.approvals.pending.keys()][0], 'yes'); assert.equal(await job, true);
});

test('background jobs reject Chrome while foreground Chrome remains independent', async t => {
  const f = await fixture(t);
  assert.throws(() => f.add({ allow: { mode: 'local' } }), /isolated Chromium/);
  const r = f.add(); f.scheduler.store.updateRoutine(r.id, { allow: { mode: 'local' } });
  await f.scheduler.runNow(r.id); await f.scheduler.drain();
  assert.equal(f.workers.length, 0); assert.equal(f.scheduler.list()[0].lastStatus, 'skipped-needs-foreground');
});
