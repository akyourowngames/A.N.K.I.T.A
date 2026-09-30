import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import * as cron from '../../src/automation/cron.mjs';
import { RoutineStore } from '../../src/automation/routines.mjs';

function store(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'desktop-routines-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return new RoutineStore(path.join(dir, 'state.json'));
}
test('legacy routine loads with background permission and budget defaults after every reload', t => {
  const s = store(t);
  fs.writeFileSync(s.file, JSON.stringify({ routines: [{ id: 'old', name: 'Old', cron: '@daily', prompt: 'Read' }] }));
  s.load();
  assert.deepEqual(s.routines[0].allow, { read: true, interact: true, login: false, sites: [], mode: 'isolated' });
  assert.equal(s.routines[0].threadId, null);
  assert.ok(s.routines[0].timeoutMs > 0);
  assert.ok(s.routines[0].budget.maxRunsPerDay > 0);
  s.setRoutineEnabled('old', true);
  assert.equal(new RoutineStore(s.file).load().routines[0].spend.runs, 0);
});
test('add and update retain a verbatim prompt and routine-scoped permissions', t => {
  const s = store(t);
  const prompt = '  Post today.\nKeep my format.  ';
  const r = s.addRoutine({ name: 'Post', cron: 'weekdays 09:00', prompt, threadId: 'owner', allow: { sites: ['https://example.com/*'], login: true } });
  assert.equal(r.prompt, prompt);
  assert.equal(r.threadId, 'owner');
  s.updateRoutine(r.id, { allow: { interact: false }, pausedReason: 'budget' });
  const updated = s.findRoutine(r.id);
  assert.equal(updated.allow.login, true);
  assert.equal(updated.allow.interact, false);
  assert.equal(updated.pausedReason, 'budget');
  assert.throws(() => s.updateRoutine(r.id, { cron: 'bad' }), /schedule/);
});
test('cron matching uses the configured timezone rather than host timezone', () => {
  assert.equal(cron.matchCron('0 9 * * *', new Date('2026-09-27T13:00:00Z'), 'America/New_York'), true);
  assert.equal(cron.matchCron('0 9 * * *', new Date('2026-09-27T03:30:00Z'), 'Asia/Kolkata'), true);
  assert.equal(cron.matchCron('0 9 * * *', new Date('2026-09-27T09:00:00Z'), 'Asia/Kolkata'), false);
});
test('next and previous fires handle skipped and repeated DST hours as real instants', () => {
  assert.equal(typeof cron.cronFire, 'function');
  assert.equal(cron.cronFire('30 2 * * *', new Date('2026-03-08T06:59:00Z'), 'America/New_York', 1).toISOString(), '2026-03-09T06:30:00.000Z');
  assert.equal(cron.cronFire('30 1 * * *', new Date('2026-11-01T05:31:00Z'), 'America/New_York', 1).toISOString(), '2026-11-01T06:30:00.000Z');
  assert.equal(cron.cronFire('0 9 * * *', new Date('2026-09-27T04:00:00Z'), 'Asia/Kolkata', -1).toISOString(), '2026-09-27T03:30:00.000Z');
});

test('annual, leap-day and impossible schedules are bounded without blocking the desktop', () => {
  const probeTimeoutMs = 1500; // Includes process startup; old minute-by-minute search exceeds this gate.
  const script = `import { cronFire } from ${JSON.stringify(new URL('../../src/automation/cron.mjs', import.meta.url).href)};
    console.log(cronFire('@yearly', new Date('2026-01-02T00:00:00Z'), 'UTC').toISOString());
    console.log(cronFire('0 0 29 2 *', new Date('2025-03-01T00:00:00Z'), 'UTC').toISOString());
    console.log(cronFire('0 0 31 2 *', new Date('2026-01-01T00:00:00Z'), 'UTC'));`;
  const result = spawnSync(process.execPath, ['--input-type=module', '-e', script], { timeout: probeTimeoutMs, encoding: 'utf8' });
  assert.equal(result.error, undefined); assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /2027-01-01.*\n2028-02-29.*\nnull/s);
});
