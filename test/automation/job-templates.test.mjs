import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { RoutineStore } from '../../src/automation/routines.mjs';
import { Daemon } from '../../src/automation/daemon.mjs';
import { DesktopScheduler } from '../../desktop/electron/scheduler.mjs';

const url = new URL('../../src/automation/templates.mjs', import.meta.url);
async function api() { assert.ok(fs.existsSync(url), 'scheduled task templates exist'); return import(url.href); }
function sandbox(t) { const root = fs.mkdtempSync(path.join(os.tmpdir(), 'routine-template-')); t.after(() => fs.rmSync(root, { recursive: true, force: true })); return root; }

test('templates list without writing and enable a configured read-only task through the real store', async t => {
  const { JOB_TEMPLATES, enableJobTemplate } = await api();
  assert.ok(JOB_TEMPLATES.length >= 3);
  const root = sandbox(t), file = path.join(root, 'state.json');
  const store = new RoutineStore(file).load();
  assert.equal(fs.existsSync(file), false);
  const job = enableJobTemplate(store, 'news-brief', { cron: 'daily at 09:15', topic: 'game development' });
  assert.equal(job.cron, '15 9 * * *');
  assert.match(job.prompt, /game development/);
  assert.equal(job.allow.interact, false);
  assert.equal(job.allow.login, false);
  assert.equal(new RoutineStore(file).load().findRoutine(job.id)?.enabled, true);
});

test('templates reject missing resource inputs, invalid schedules and unsupported channels before writes', async t => {
  const { enableJobTemplate } = await api();
  const file = path.join(sandbox(t), 'state.json'), store = new RoutineStore(file).load();
  for (const [id, options] of [['missing', {}], ['news-brief', {}], ['page-digest', { url: 'javascript:alert(1)' }], ['morning-brief', { cron: 'invalid' }], ['morning-brief', { channel: 'unknown' }]]) {
    assert.throws(() => enableJobTemplate(store, id, options));
    assert.equal(fs.existsSync(file), false);
  }
});

test('real offline CLI lists then enables a template in isolated state', async t => {
  await api();
  const root = sandbox(t), env = { ...process.env, CONFIG_DIR: root, PROVIDER: 'invalid-offline-provider' };
  const list = execFileSync(process.execPath, ['chat.mjs', 'jobs', 'templates'], { encoding: 'utf8', env, timeout: 10000 });
  assert.match(list, /news-brief/);
  assert.equal(fs.existsSync(path.join(root, 'state.json')), false);
  const enabled = execFileSync(process.execPath, ['chat.mjs', 'jobs', 'enable', 'morning-brief', '--cron', 'daily at 10:00'], { encoding: 'utf8', env, timeout: 10000 });
  assert.match(enabled, /Enabled/);
  assert.equal(new RoutineStore(path.join(root, 'state.json')).load().routines.length, 1);
});

test('log-only templates keep results local while notify templates use existing delivery', async () => {
  const { deliverTemplateResult } = await api();
  const calls = [];
  const adapters = { log: text => calls.push(['log', text]), deliver: text => { calls.push(['deliver', text]); return 'queued'; } };
  assert.equal(await deliverTemplateResult('Local result', { routine: { templateId: 'weekly-review', channel: 'log' } }, adapters), 'log');
  assert.deepEqual(calls, [['log', 'Local result']]);
  assert.equal(await deliverTemplateResult('Notify result', { routine: { templateId: 'morning-brief', channel: 'notify' } }, adapters), 'queued');
  assert.deepEqual(calls[1], ['deliver', 'Notify result']);
});

test('real daemon uses configured timezone and preserves the last successful digest across failure and reload', async t => {
  const { enableJobTemplate } = await api();
  const file = path.join(sandbox(t), 'state.json');
  const store = new RoutineStore(file).load();
  enableJobTemplate(store, 'page-digest', { url: 'https://example.test/page', cron: '0 8 * * *' });
  let at = new Date('2026-01-10T08:00:00Z'), attempts = 0;
  const delivered = [];
  const daemon = new Daemon({ store, config: { timeZone: 'UTC' }, client: {}, now: () => at,
    deliver: async text => delivered.push(text), runPrompt: async prompt => {
      attempts++;
      if (attempts === 1) return 'Baseline: version one.';
      if (attempts === 2) throw new Error('Temporary read failure');
      assert.match(prompt, /Baseline: version one/);
      assert.match(prompt, /historical.*untrusted/i);
      assert.doesNotMatch(prompt, /Temporary read failure/);
      return 'Changed: version two.';
    } });
  t.after(() => daemon.stop());
  for (let day = 10; day <= 12; day++) {
    at = new Date(Date.UTC(2026, 0, day, 8)); store.load();
    assert.equal(await daemon.runDueRoutines(), 1, 'runs at the configured UTC minute');
  }
  assert.equal(attempts, 3); assert.equal(delivered.length, 2);
  assert.match(store.load().routines[0].lastSuccessfulResult.text, /version two/);
  console.log('TEMPLATE_DAEMON_LIVE configuredTimezone=UTC attempts=3 successfulDigests=2 previousSuccessSurvivesFailure=true');
});

test('desktop execution and retained-receipt retry keep log-only templates local', async t => {
  const { enableJobTemplate } = await api();
  const root = sandbox(t), deliveries = [], failureNotifications = [];
  let fail = false;
  class Worker { constructor() { this.messages = []; } async send() { if (fail) throw new Error('Private failure'); return 'Private local briefing'; } cancel() {} }
  const owners = [{ id: 'owner', updatedAt: new Date().toISOString() }];
  const engine = { config: { timeZone: 'UTC' }, client: {}, AgentClass: Worker,
    emit: event => { if (event.type === 'routine-failed') failureNotifications.push(event); }, turns: new Map(),
    teammates: { list: () => owners, find: id => owners.find(owner => owner.id === id) },
    browserManager: { createScope: () => ({ view: async () => ({ tabs: [] }), cancel() {} }), closeScope: async () => {} },
    deliverRoutine: async receipt => { deliveries.push(receipt); return true; } };
  const scheduler = new DesktopScheduler({ engine, file: path.join(root, 'state.json'), sessionsDir: root });
  t.after(() => scheduler.stop());
  const job = enableJobTemplate(scheduler.store, 'morning-brief', { channel: 'log' });
  await scheduler.runNow(job.id); await scheduler.drain();
  assert.deepEqual(deliveries, [], 'no teammate or notification delivery');
  const file = path.join(scheduler.directory, fs.readdirSync(scheduler.directory)[0]);
  const receipt = JSON.parse(fs.readFileSync(file, 'utf8'));
  assert.equal(receipt.delivered, true, 'retained local receipt counts as delivered');
  fs.writeFileSync(file, JSON.stringify({ ...receipt, delivered: false }));
  await scheduler.retryDeliveries();
  assert.deepEqual(deliveries, [], 'retry preserves local-only delivery');
  assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).delivered, true);
  fail = true;
  await scheduler.runNow(job.id); await scheduler.drain();
  assert.deepEqual(failureNotifications, [], 'failed log-only jobs never reach the native failure-notification sink');
  assert.equal(scheduler.store.load().findRoutine(job.id).lastStatus, 'error');
  const missed = enableJobTemplate(scheduler.store, 'morning-brief', { channel: 'log' });
  scheduler.store.updateRoutine(missed.id, { createdAt: '2026-01-10T00:00:00Z' });
  scheduler.due(new Date('2026-01-11T09:00:00Z'));
  assert.equal(scheduler.store.load().findRoutine(missed.id).lastStatus, 'missed');
  assert.deepEqual(failureNotifications, [], 'missed log-only jobs stay local too');
  console.log('TEMPLATE_DESKTOP_LIVE logOnly=true worker=fixture scheduler=real initialDeliveries=0 retryDeliveries=0 retainedResult=true');
  console.log('TEMPLATE_FAILURE_LIVE failedNotifications=0 missedNotifications=0 nativeSink=fixture');
});
