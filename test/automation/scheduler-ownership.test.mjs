import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { LOCK_STALE_MS } from '../../src/automation/job-policy.mjs';
test('separate processes recover a dead owner without deleting a newly acquired lock', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'schedule-process-')), file = path.join(directory, 'scheduler.lock');
  const probe = spawn(process.execPath, ['-e', '']); const deadPid = probe.pid;
  await new Promise(resolve => probe.once('exit', resolve));
  fs.writeFileSync(file, JSON.stringify({ pid: deadPid, token: 'dead-owner', heartbeat: Date.now() - LOCK_STALE_MS * 2 }));
  const moduleUrl = new URL('../../src/automation/scheduler-ownership.mjs', import.meta.url).href;
  const code = `import fs from 'node:fs'; import { SchedulerOwnership } from ${JSON.stringify(moduleUrl)};
    const file = process.argv[1], owner = new SchedulerOwnership(file);
    const unlink = fs.unlinkSync;
    fs.unlinkSync = target => { if (target === file) Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, Number(process.argv[2])); return unlink(target); };
    process.on('message', async message => {
      if (message === 'start') { try { await owner.acquire(); process.send('acquired'); } catch { process.send('refused'); } }
      if (message === 'stop') { owner.release(); process.exit(); }
    }); process.send('ready');`;
  const children = Array.from({ length: 4 }, (_, index) => spawn(process.execPath, ['--input-type=module', '-e', code, file, String(100 + index * 150)], { stdio: ['ignore', 'ignore', 'inherit', 'ipc'] }));
  t.after(() => { for (const child of children) child.kill(); fs.rmSync(directory, { recursive: true, force: true }); });
  const next = child => new Promise((resolve, reject) => { child.once('message', resolve); child.once('error', reject); });
  await Promise.all(children.map(next));
  const outcomes = children.map(next); for (const child of children) child.send('start');
  const results = await Promise.all(outcomes);
  assert.equal(results.filter(value => value === 'acquired').length, 1, `Exclusive owner: ${results.join(', ')}`);
  for (const child of children) child.send('stop');
  await Promise.all(children.map(child => new Promise(resolve => child.once('exit', resolve))));
});
test('stale truncated lock recovers exclusively and heartbeat uses an atomic replacement', async t => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'schedule-recovery-')); t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
  const file = path.join(directory, 'scheduler.lock'); fs.writeFileSync(file, '');
  const past = new Date(Date.now() - LOCK_STALE_MS * 2); fs.utimesSync(file, past, past);
  const { SchedulerOwnership } = await import('../../src/automation/scheduler-ownership.mjs');
  const a = new SchedulerOwnership(file), b = new SchedulerOwnership(file);
  const results = await Promise.allSettled([a.acquire(), b.acquire()]);
  assert.equal(results.filter(result => result.status === 'fulfilled').length, 1);
  const owner = results[0].status === 'fulfilled' ? a : b;
  assert.equal(owner.heartbeat(), true); assert.equal(JSON.parse(fs.readFileSync(file, 'utf8')).token, owner.token); owner.release();
});
test('ownership refuses a live owner and cooperative takeover never permits two owners', async t => {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'schedule-owner-')), 'scheduler.lock');
  t.after(() => fs.rmSync(path.dirname(file), { recursive: true, force: true }));
  assert.ok(fs.existsSync(new URL('../../src/automation/scheduler-ownership.mjs', import.meta.url)));
  const { SchedulerOwnership } = await import('../../src/automation/scheduler-ownership.mjs');
  const desktop = new SchedulerOwnership(file, { host: 'desktop' });
  await desktop.acquire();
  const cli = new SchedulerOwnership(file, { host: 'cli', takeoverWaitMs: 100 });
  await assert.rejects(cli.acquire(), /desktop scheduler owns routines/);
  const takeover = cli.acquire({ takeover: true });
  await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(desktop.heartbeat(), false);
  desktop.release();
  await takeover;
  assert.equal(cli.heartbeat(), true);
  assert.equal(desktop.release(), false);
  cli.release();
});
