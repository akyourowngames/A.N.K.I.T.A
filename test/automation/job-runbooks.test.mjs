import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { RoutineStore } from '../../src/automation/routines.mjs';
import { DesktopScheduler } from '../../desktop/electron/scheduler.mjs';

const url = new URL('../../src/automation/runbooks.mjs', import.meta.url);
async function api() { assert.ok(fs.existsSync(url), 'task runbooks exist'); return import(url.href); }
function setup(t) { const root = fs.mkdtempSync(path.join(os.tmpdir(), 'job-runbook-')); t.after(() => fs.rmSync(root, { recursive: true, force: true })); const store = new RoutineStore(path.join(root, 'state.json')).load(); const job = store.addRoutine({ name: 'Daily summary', cron: 'daily at 09:00', prompt: 'Read project notes', channel: 'log' }); return { root, store, job }; }

test('runbook shows definition, actual next run, permissions, last five outcomes and recovery steps', async t => {
  const { jobRunbook } = await api();
  const { store, job } = setup(t);
  for (let index = 0; index < 7; index++) store.markRoutineRun(job.id, { at: new Date(Date.UTC(2026, 0, index + 1)).toISOString(), status: 'error', summary: `failure ${index}` });
  const text = jobRunbook(store.load().findRoutine(job.id), { now: new Date('2026-01-10T06:00:00Z'), timeZone: 'UTC' });
  assert.match(text, /2026-01-10T09:00:00.000Z/);
  assert.match(text, /Read project notes/);
  assert.match(text, /failure 6/);
  assert.doesNotMatch(text, /failure 0|failure 1/);
  assert.match(text, /Review the last result/);
});

test('runbook reads matching retained desktop receipts and redacts secrets', async t => {
  const { jobRunbook } = await api();
  const { root, job } = setup(t);
  const runsDir = path.join(root, 'jobs'); fs.mkdirSync(runsDir);
  const secret = `ghp_${'sample-token'.replace(/-/g, '').repeat(4)}`;
  fs.writeFileSync(path.join(runsDir, `${job.id}-one.json`), JSON.stringify({ routineId: job.id, runId: 'one', at: '2026-01-10T00:00:00Z', status: 'timeout', text: `api_key=${secret} password=very-secret-value`, tokens: 23, activeMs: 500 }));
  fs.writeFileSync(path.join(runsDir, `${job.id}-wrong.json`), JSON.stringify({ routineId: 'other-job', at: '2026-01-11T00:00:00Z', text: 'unrelated receipt' }));
  fs.writeFileSync(path.join(runsDir, `${job.id}-corrupt.json`), 'bad json');
  const text = jobRunbook(job, { runsDir, timeZone: 'UTC' });
  assert.match(text, /timeout/);
  assert.match(text, /23 tokens/);
  assert.doesNotMatch(text, /very-secret-value|unrelated receipt/);
  assert.ok(!text.includes(secret));
  assert.match(text, /1 unreadable/);
});

test('paused and never-run tasks have honest state and unknown ids fail through real offline CLI', async t => {
  const { jobRunbook } = await api();
  const { root, store, job } = setup(t);
  store.setRoutineEnabled(job.id, false);
  assert.match(jobRunbook(store.load().findRoutine(job.id)), /Next run: paused/);
  assert.match(jobRunbook(job), /No retained runs/);
  const env = { ...process.env, CONFIG_DIR: root, PROVIDER: 'invalid-offline-provider' };
  const output = execFileSync(process.execPath, ['chat.mjs', 'runbook', job.id], { encoding: 'utf8', env, timeout: 10000 });
  assert.match(output, /Daily summary/);
  assert.throws(() => execFileSync(process.execPath, ['chat.mjs', 'runbook', 'missing'], { encoding: 'utf8', env, timeout: 10000 }), /Task not found/);
});

test('CLI run outcomes survive reload and stay bounded', t => {
  const { store, job } = setup(t);
  for (let index = 0; index < 50; index++) store.markRoutineRun(job.id, { status: 'ok', summary: `result ${index}` });
  const saved = store.load().findRoutine(job.id);
  assert.ok(saved.runHistory?.length > 0, 'persistent recent outcomes exist');
  assert.ok(saved.runHistory.length < 50);
  assert.equal(saved.runHistory.at(-1).summary, 'result 49');
});

test('runbook merges the latest skipped outcome without relabeling an older result when claimed', async t => {
  const { jobRunbook } = await api();
  const { store, job } = setup(t);
  store.markRoutineRun(job.id, { at: '2026-01-09T08:00:00Z', status: 'ok', summary: 'Previous completed result' });
  store.updateRoutine(job.id, { lastFireAt: '2026-01-10T08:00:00Z', lastStatus: 'missed', lastSummary: 'Latest missed fire' });
  let report = jobRunbook(store.load().findRoutine(job.id), { timeZone: 'UTC' });
  assert.match(report, /2026-01-10T08:00:00Z.*missed.*Latest missed fire/);
  assert.match(report, /Previous completed result/);
  store.claimRoutine(job.id, '2026-01-11T08:00:00Z');
  report = jobRunbook(store.load().findRoutine(job.id), { timeZone: 'UTC' });
  assert.doesNotMatch(report, /2026-01-11T08:00:00Z.*missed/);
  assert.match(report, /2026-01-10T08:00:00Z.*missed/);
});

test('malformed persisted history is skipped without losing valid outcomes', async t => {
  const { jobRunbook } = await api();
  const { job } = setup(t);
  job.runHistory = [null, {}, { at: 'bad date', status: 'ok' }, { at: '2026-01-10T08:00:00Z', status: 'ok', summary: 'Valid result' }];
  const report = jobRunbook(job);
  assert.match(report, /Valid result/);
  assert.match(report, /3 unreadable/);
});

test('a real desktop completion taking time appears once in the runbook', async t => {
  const { jobRunbook } = await api();
  const { root } = setup(t);
  let at = new Date('2026-01-10T08:00:00Z');
  class Worker { constructor() { this.messages = []; } async send() { at = new Date('2026-01-10T08:00:05Z'); return 'Completed one reading'; } cancel() {} }
  const owners = [{ id: 'owner', updatedAt: at.toISOString() }];
  const engine = { config: { timeZone: 'UTC' }, client: {}, AgentClass: Worker, emit() {}, turns: new Map(),
    teammates: { list: () => owners, find: id => owners.find(owner => owner.id === id) },
    browserManager: { createScope: () => ({ view: async () => ({ tabs: [] }), cancel() {} }), closeScope: async () => {} },
    deliverRoutine: async () => true };
  const scheduler = new DesktopScheduler({ engine, file: path.join(root, 'desktop-state.json'), sessionsDir: root, now: () => at });
  t.after(() => scheduler.stop());
  const job = scheduler.add({ name: 'Read once', threadId: 'owner', cron: '0 8 * * *', prompt: 'Read the page' });
  await scheduler.runNow(job.id); await scheduler.drain();
  const report = jobRunbook(scheduler.store.load().findRoutine(job.id), { now: at, timeZone: 'UTC', runsDir: scheduler.directory });
  assert.equal((report.match(/^- /gm) || []).length, 1, 'state and receipt represent one execution');
  assert.match(report, /2026-01-10T08:00:05.000Z.*Completed one reading/);
  console.log('RUNBOOK_DESKTOP_LIVE started=08:00:00 completed=08:00:05 distinctRuns=1 displayedOutcomes=1');
});

test('legacy desktop results dedupe before and after an update or in-flight claim', async t => {
  const { jobRunbook } = await api();
  const { root, store, job } = setup(t);
  const runsDir = path.join(root, 'jobs'); fs.mkdirSync(runsDir);
  const receipt = { runId: 'legacy', routineId: job.id, at: '2026-01-10T08:00:05Z', status: 'ok', text: 'Legacy completed reading' };
  fs.writeFileSync(path.join(runsDir, `${job.id}-legacy.json`), JSON.stringify(receipt));
  const legacy = { ...job, lastRun: '2026-01-10T08:00:00Z', lastFireAt: '2026-01-10T08:00:00Z', lastStatus: 'ok', lastSummary: receipt.text, lastReceipt: receipt };
  const check = routine => assert.equal((jobRunbook(routine, { runsDir, timeZone: 'UTC' }).match(/^- /gm) || []).length, 1);
  check(legacy);
  store.data.routines = [legacy]; store.save();
  store.updateRoutine(job.id, { enabled: true }); check(store.load().findRoutine(job.id));
  store.claimRoutine(job.id, '2026-01-11T08:00:00Z'); check(store.load().findRoutine(job.id));
});
