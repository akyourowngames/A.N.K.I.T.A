import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import childProcess from 'node:child_process';
import { syncBuiltinESMExports } from 'node:module';
import { Worker } from 'node:worker_threads';
import { once } from 'node:events';
import { Writable } from 'node:stream';
import { run, killTree, waitForExit } from '../../tools/process/run-command.mjs';
import { run as status } from '../../tools/process/job-status.mjs';
import { cleanupJobs } from '../../tools/index.mjs';

// Milliseconds: keep fixture jobs alive until their explicit test cleanup.
const IDLE_JOB_SOURCE = 'setInterval(()=>{}, 1000)';
const LAUNCHER_TERMINATION_TEST_TIMEOUT_MS = 20_000; // Milliseconds: bound native startup and tree termination in this regression.

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

test('Windows commands launch the resolved shell executable rather than its activation alias', { skip: process.platform !== 'win32' }, async t => {
  const { command, ctx } = fixture(t, IDLE_JOB_SOURCE);
  await run({ command, background: true }, ctx);
  const job = [...ctx.state.jobs.values()][0];
  await job.child.ready;
  const executable = job.child.shellExecutable;
  assert.ok(path.isAbsolute(executable), `shell launch must use the discovered executable: ${executable}`);
  assert.ok(fs.existsSync(executable), 'the discovered shell must exist');
});

test('native close keeps the launcher referenced until Stop acknowledges termination', { skip: process.platform !== 'win32', timeout: LAUNCHER_TERMINATION_TEST_TIMEOUT_MS }, async t => {
  const { command, ctx } = fixture(t, IDLE_JOB_SOURCE);
  await run({ command, background: true }, ctx);
  const job = [...ctx.state.jobs.values()][0];
  await job.child.ready;
  const pendingAtUnref = [];
  const unref = job.child.worker.unref.bind(job.child.worker);
  job.child.worker.unref = () => {
    pendingAtUnref.push(job.child.pending.size);
    return unref();
  };
  await killTree(job.child);
  await waitForExit(job, LAUNCHER_TERMINATION_TEST_TIMEOUT_MS);
  console.log(`launcher Stop: closed=${job.child.closed}, pending at unref=${pendingAtUnref.join(',')}`);
  assert.equal(job.done, true, 'the real native command must close');
  assert.ok(pendingAtUnref.length, 'the finished launcher must release its event-loop reference');
  assert.deepEqual(pendingAtUnref, [0], 'Stop acknowledgement must settle before the launcher releases its reference');
});

test('cold Windows shell startup cannot block the caller event loop', { skip: process.platform !== 'win32' }, async t => {
  // Milliseconds: reproduce a slow native CreateProcess without consuming CPU.
  const startupDelayMs = 500;
  const heartbeatBudgetMs = startupDelayMs / 2;
  const { command, ctx } = fixture(t, IDLE_JOB_SOURCE);
  const spawn = childProcess.spawn;
  childProcess.spawn = (executable, args, ...rest) => {
    if (args[1] === '-Command') {
      Atomics.wait(new Int32Array(new SharedArrayBuffer(Int32Array.BYTES_PER_ELEMENT)), 0, 0, startupDelayMs);
    }
    return spawn(executable, args, ...rest);
  };
  syncBuiltinESMExports();
  t.after(() => { childProcess.spawn = spawn; syncBuiltinESMExports(); });
  const started = performance.now();
  const heartbeat = new Promise(resolve => setTimeout(() => resolve(performance.now() - started), 0));
  const result = await run({ command, yield_ms: 100 }, ctx);
  assert.match(result, /job.*running|running.*job/s);
  assert.ok(await heartbeat < heartbeatBudgetMs, 'native shell creation must not stall the caller heartbeat');
});

test('a launcher shell-spawn failure remains a failed job with its original error', { skip: process.platform !== 'win32' }, async t => {
  const { command, ctx } = fixture(t, IDLE_JOB_SOURCE);
  // A deliberately removed cwd exercises a real native launch failure in the
  // worker, rather than replacing the launcher or its result with a mock.
  ctx.cwd = path.join(ctx.cwd, 'missing-working-directory');
  await run({ command }, ctx);
  const job = [...ctx.state.jobs.values()][0];
  assert.equal(job.done, true);
  assert.match(job.error, /ENOENT/);
  assert.equal(JSON.parse(status({ job_id: job.id }, ctx)).state, 'failed');
});

test('tool modules can be imported by an unrelated worker without launching a job', async t => {
  const moduleUrl = new URL('../../tools/index.mjs', import.meta.url).href;
  const worker = new Worker(`import(${JSON.stringify(moduleUrl)}).then(()=>require('node:worker_threads').parentPort.postMessage('imported'));`, { eval: true });
  t.after(() => worker.terminate());
  assert.deepEqual(await once(worker, 'message'), ['imported']);
});

test('blocked launcher stdin preserves the job_input deadline without finishing the job', { skip: process.platform !== 'win32' }, async t => {
  const blockedBytes = 4 * 1024 * 1024; // Bytes: exceed native pipe capacity while the fixture never reads stdin.
  const { command, ctx } = fixture(t, "console.log('ready');setInterval(()=>{},1000)");
  await run({ command, background: true }, ctx);
  const job = [...ctx.state.jobs.values()][0];
  await once(job.child.stdout, 'data');
  let acknowledged = false;
  job.child.stdin.write(Buffer.alloc(blockedBytes), () => { acknowledged = true; });
  const { run: input } = await import('../../tools/process/job-input.mjs');
  assert.match(await input({ job_id: job.id, text: 'pending', eof: true }, ctx), /not accepting input/);
  assert.equal(acknowledged, false, 'native write callback must remain pending while the pipe is blocked');
  assert.equal(job.child.stdin.writableFinished, false, 'EOF callback must wait for pending native writes');
  assert.equal(job.done, false, 'a blocked stdin write must not finish a running job');
});

test('job input cancelled before launcher readiness never writes to stdin', async () => {
  const controller = new AbortController();
  let written = false;
  const stdin = new Writable({ write: (data, encoding, done) => { written = true; done(); } });
  const job = { id: 'pending-launch', done: false, child: { ready: new Promise(() => {}), stdin } };
  const ctx = { signal: controller.signal, state: { jobs: new Map([[job.id, job]]) } };
  const { run: input } = await import('../../tools/process/job-input.mjs');
  const result = input({ job_id: job.id, text: 'cancelled' }, ctx);
  controller.abort();
  assert.match(await result, /cancelled/i);
  assert.equal(written, false);
});

test('unexpected launcher termination cleans up the verified native process tree', { skip: process.platform !== 'win32', timeout: 20000 }, async t => {
  const { command, ctx } = fixture(t, "console.log('native:'+process.pid);setInterval(()=>{},1000)");
  await run({ command, background: true }, ctx);
  const job = [...ctx.state.jobs.values()][0];
  await job.child.ready;
  await job.child.identityReady;
  if (!/native:/.test(job.out.toString())) await once(job.child.stdout, 'data');
  const nativePid = Number(job.out.toString().match(/native:(\d+)/)?.[1]);
  assert.ok(nativePid);
  const alive = () => { try { process.kill(nativePid, 0); return true; } catch { return false; } };
  t.after(() => { if (alive()) { try { process.kill(nativePid); } catch {} } });
  await job.child.worker.terminate();
  await waitForExit(job, 5000);
  console.log(`launcher crash: job.done=${job.done}, native alive=${alive()}`);
  assert.equal(alive(), false, 'launcher failure must not orphan its native command');
  assert.equal(job.done, true);
  assert.match(job.error, /launcher exited unexpectedly/i);
});

test('launcher crash cleanup refuses a changed root identity and missing identity', { skip: process.platform !== 'win32' }, async t => {
  const { command, ctx } = fixture(t, IDLE_JOB_SOURCE);
  await run({ command, background: true }, ctx);
  const job = [...ctx.state.jobs.values()][0];
  const snapshot = await job.child.identityReady;
  const { cleanupFailedLauncher } = await import('../../tools/shared/_job-tree.mjs');
  await assert.rejects(cleanupFailedLauncher(job.child, { ...snapshot, identity: 'different-creation-identity' }), /identity changed/);
  assert.doesNotThrow(() => process.kill(job.child.pid, 0), 'identity mismatch must leave the current PID alive');
  await assert.rejects(cleanupFailedLauncher(job.child, undefined), /without.*identity/);
});

test('launcher Stop cleans inherited pipes after its shell exits', { skip: process.platform !== 'win32', timeout: 20000 }, async t => {
  const { command, ctx } = fixture(t, "const leaf=require('child_process').spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:['ignore','inherit','inherit'],detached:true,windowsHide:true});console.log('leaf:'+leaf.pid);leaf.unref();setInterval(()=>{},1000)");
  await run({ command, background: true }, ctx);
  const job = [...ctx.state.jobs.values()][0];
  const exited = once(job.child, 'exit');
  await once(job.child.stdout, 'data');
  // Force the shell leader to exit while its descendant retains inherited
  // output handles; PowerShell normally waits for those handles itself.
  process.kill(job.child.pid);
  await exited;
  const leaf = Number(job.out.toString().match(/leaf:(\d+)/)?.[1]);
  assert.ok(leaf, 'fixture descendant PID must reach the owner');
  const alive = () => { try { process.kill(leaf, 0); return true; } catch { return false; } };
  t.after(() => { if (alive()) { try { process.kill(leaf); } catch {} } });
  assert.equal(alive(), true);
  assert.equal(job.done, false, 'inherited pipes keep close pending after shell exit');
  await killTree(job.child);
  await waitForExit(job, 5000);
  assert.equal(alive(), false);
  assert.equal(job.done, true);
});

test('the launcher drains stdout and stderr before reporting the shell exit code', async t => {
  const retainedBytes = 131072; // Bytes: exceed pipe-buffer size to exercise final stream flushing.
  const payloadBytes = retainedBytes / 2;
  const { command, ctx } = fixture(t, `process.stdout.write('x'.repeat(${payloadBytes}));process.stderr.write('final-stderr');process.exitCode=7;`);
  // Propagate the native child's status explicitly: PowerShell -Command would
  // otherwise map a failed native command to its own generic failure status.
  const shellCommand = process.platform === 'win32' ? `${command}; exit $LASTEXITCODE` : command;
  await run({ command: shellCommand, background: true, max_output_bytes: retainedBytes }, ctx);
  const job = [...ctx.state.jobs.values()][0];
  const { run: wait } = await import('../../tools/process/job-wait.mjs');
  const result = JSON.parse(await wait({ job_id: job.id, timeout_ms: 5000, since_offset: 0, max_bytes: retainedBytes }, ctx));
  assert.equal(result.state, 'done');
  assert.equal(result.exit_code, 7);
  assert.equal(job.out.toString().match(/x/g)?.length, payloadBytes);
  assert.match(job.out.toString(), /final-stderr/);
});

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
  const { run: wait } = await import('../../tools/process/job-wait.mjs');
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
  const { run: input } = await import('../../tools/process/job-input.mjs');
  const { run: wait } = await import('../../tools/process/job-wait.mjs');
  assert.doesNotMatch(await input({ job_id: id, text: 'next\n', eof: true }, ctx), /^Error:/);
  const finished = JSON.parse(await wait({ job_id: id, timeout_ms: 5000, since_offset: 0 }, ctx));
  assert.equal(finished.state, 'done');
  assert.match(finished.output, /echo:initial/);
  assert.match(finished.output, /next/);
  assert.match(await input({ job_id: id, text: 'too late' }, ctx), /^Error:/);
});

test('incremental truncation reports skipped bytes with absolute cursors', async () => {
  const { JobOutput } = await import('../../tools/shared/_jobs.mjs');
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
  const { JobOutput } = await import('../../tools/shared/_jobs.mjs');
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
  const { run: wait } = await import('../../tools/process/job-wait.mjs');
  const result = JSON.parse(await wait({ job_id: job.id, timeout_ms: 10000 }, ctx));
  assert.equal(result.wait_cancelled, true);
  assert.equal(job.stopped, false);
  assert.equal(job.done, false);
});

test('optional execution timeout terminates a job rather than imposing a default server lifetime', async t => {
  const { command, ctx } = fixture(t, "setInterval(()=>{}, 1000)");
  await run({ command, background: true, timeout_ms: 500 }, ctx);
  const job = [...ctx.state.jobs.values()][0];
  const { run: wait } = await import('../../tools/process/job-wait.mjs');
  const result = JSON.parse(await wait({ job_id: job.id, timeout_ms: 8000 }, ctx));
  assert.equal(result.timed_out, true);
  assert.equal(job.done, true);
});
