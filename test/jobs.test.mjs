import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { run } from '../tools/run-command.mjs';
import { run as status } from '../tools/job-status.mjs';
import { cleanupJobs } from '../tools/index.mjs';

function fixture(t, source) {
  const cwd = fs.mkdtempSync(path.join(os.tmpdir(), 'ankita-jobs-'));
  const file = path.join(cwd, 'child.cjs');
  fs.writeFileSync(file, source);
  const quote = s => `'${s.replace(/'/g, process.platform === 'win32' ? "''" : "'\\''")}'`;
  const command = `${process.platform === 'win32' ? '& ' : ''}${quote(process.execPath)} ${quote(file)}`;
  const ctx = { cwd, state: { jobs: new Map() } };
  t.after(async () => { await cleanupJobs(ctx.state); fs.rmSync(cwd, { recursive: true, force: true }); });
  return { command, ctx };
}

test('commands yield a live job instead of blocking the turn until process exit', async t => {
  const { command, ctx } = fixture(t, "process.stdout.write('ready\\n'); setInterval(()=>{}, 1000)");
  const start = performance.now();
  const result = await run({ command, yield_ms: 100 }, ctx);
  assert.ok(performance.now() - start < 3000);
  assert.match(result, /job.*running|running.*job/s);
  assert.equal(ctx.state.jobs.size, 1);
  assert.equal([...ctx.state.jobs.values()][0].done, false);
});

test('job status can list all jobs and read only new bytes, with explicit replay/tail', async t => {
  const { command, ctx } = fixture(t, "console.log('first'); setTimeout(()=>console.log('second'), 300); setTimeout(()=>{}, 500)");
  await run({ command, background: true }, ctx);
  const id = [...ctx.state.jobs.keys()][0];
  const { run: wait } = await import('../tools/job-wait.mjs');
  await wait({ job_id: id, timeout_ms: 5000 }, ctx);
  const list = JSON.parse(status({}, ctx));
  assert.equal(list.jobs[0].id, id);
  const once = JSON.parse(status({ job_id: id, since_offset: 0 }, ctx));
  assert.match(once.output, /first.*second/s);
  const twice = JSON.parse(status({ job_id: id }, ctx));
  assert.equal(twice.output, '');
  assert.equal(twice.next_offset, once.next_offset);
  assert.match(JSON.parse(status({ job_id: id, tail: 1 }, ctx)).output, /second/);
});

test('job input writes stdin and EOF; background initial stdin is not lost', async t => {
  const { command, ctx } = fixture(t, "process.stdin.setEncoding('utf8'); process.stdin.on('data',s=>process.stdout.write('echo:'+s)); process.stdin.on('end',()=>process.exit(0));");
  await run({ command, background: true, stdin: 'initial\n' }, ctx);
  const id = [...ctx.state.jobs.keys()][0];
  const { run: input } = await import('../tools/job-input.mjs');
  const { run: wait } = await import('../tools/job-wait.mjs');
  assert.doesNotMatch(await input({ job_id: id, text: 'next\n', eof: true }, ctx), /^Error:/);
  const finished = JSON.parse(await wait({ job_id: id, timeout_ms: 5000, since_offset: 0 }, ctx));
  assert.equal(finished.state, 'done');
  assert.match(finished.output, /echo:initial/);
  assert.match(finished.output, /next/);
  assert.match(await input({ job_id: id, text: 'too late' }, ctx), /^Error:/);
});

test('incremental truncation reports skipped bytes with absolute cursors', async () => {
  const { JobOutput } = await import('../tools/_jobs.mjs');
  const out = new JobOutput(1024);
  out.append('x'.repeat(3000));
  out.append('END');
  const first = out.read(0, 100);
  assert.equal(first.offset, 1979);
  assert.equal(first.dropped, 1979);
  assert.equal(first.next_offset, 2079);
  const tail = out.read(first.next_offset, 2000);
  assert.ok(tail.output.endsWith('END'));
  assert.equal(tail.next_offset, 3003);
});

test('incremental reads preserve UTF-8 characters split across data events', async () => {
  const { JobOutput } = await import('../tools/_jobs.mjs');
  const out = new JobOutput(1024);
  const emoji = Buffer.from('🙂');
  out.append(emoji.subarray(0, 2));
  const first = out.read();
  assert.equal(first.output, '');
  assert.equal(first.next_offset, 0);
  out.append(emoji.subarray(2));
  assert.equal(out.read(first.next_offset).output, '🙂');
});

test('a yielded job survives cancellation of a later turn; job_wait cancellation does not kill it', async t => {
  const { command, ctx } = fixture(t, "setInterval(()=>{}, 1000)");
  const controller = new AbortController();
  ctx.signal = controller.signal;
  await run({ command, yield_ms: 50 }, ctx);
  const job = [...ctx.state.jobs.values()][0];
  controller.abort();
  const { run: wait } = await import('../tools/job-wait.mjs');
  const result = JSON.parse(await wait({ job_id: job.id, timeout_ms: 10000 }, ctx));
  assert.equal(result.wait_cancelled, true);
  assert.equal(job.stopped, false);
  assert.equal(job.done, false);
});

test('optional execution timeout terminates a job rather than imposing a default server lifetime', async t => {
  const { command, ctx } = fixture(t, "setInterval(()=>{}, 1000)");
  await run({ command, background: true, timeout_ms: 500 }, ctx);
  const job = [...ctx.state.jobs.values()][0];
  const { run: wait } = await import('../tools/job-wait.mjs');
  const result = JSON.parse(await wait({ job_id: job.id, timeout_ms: 8000 }, ctx));
  assert.equal(result.timed_out, true);
  assert.equal(job.done, true);
});
