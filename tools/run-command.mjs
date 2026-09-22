import { spawn, spawnSync } from 'node:child_process';
import { JobOutput, clamp, jobsOf, jobSnapshot, notifyJob, waitForExit } from './_jobs.mjs';
export { waitForExit } from './_jobs.mjs';

export const name = 'run_command';
export const description = 'Run a shell command. Returns after yield_ms (default 1000) with a job ID if still running, so the conversation can continue. Use background:true for servers; job_status lists/reads jobs, job_input sends stdin, job_wait waits briefly, job_stop ends them. ' +
  (process.platform === 'win32' ? 'Uses PowerShell: use PowerShell syntax.' : 'Uses /bin/sh.');
export const parameters = { type: 'object', properties: {
  command: { type: 'string' }, background: { type: 'boolean', description: 'Return immediately with a job ID.' },
  yield_ms: { type: 'integer', description: 'Initial wait before returning a live job; default 1000, max 10000.' },
  timeout_ms: { type: 'integer', description: 'Optional execution deadline; 0/default means no automatic kill, max 600000.' },
  stdin: { type: 'string' },
  keep_stdin_open: { type: 'boolean', description: 'Keep input open after initial stdin; default true for background, false for supplied foreground stdin.' },
  env: { type: 'object', additionalProperties: { type: 'string' } },
  max_output_bytes: { type: 'integer', description: 'Retained output, default 65536, max 4 MiB.' },
}, required: ['command'] };

let shellExe;
function shell() {
  if (!shellExe) shellExe = process.platform === 'win32'
    ? (spawnSync('where', ['pwsh'], { windowsHide: true, stdio: 'ignore' }).status === 0 ? 'pwsh' : 'powershell.exe') : '/bin/sh';
  return shellExe;
}
export function strictEnabled() { return String(process.env.PS_STRICT ?? '1') !== '0'; }
function argvFor(command) {
  return process.platform === 'win32' ? ['-NoProfile', '-Command', (strictEnabled() ? "$ErrorActionPreference='Stop'; " : '') + command] : ['-c', command];
}
/** Terminate descendants before their parent; every POSIX command owns a group. */
export async function killTree(child) {
  if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return;
  if (process.platform === 'win32') {
    await new Promise(resolve => {
      const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' });
      const timer = setTimeout(() => { killer.kill(); resolve(); }, 5000);
      const done = () => { clearTimeout(timer); resolve(); };
      killer.once('error', done); killer.once('close', done);
    });
  } else { try { process.kill(-child.pid, 'SIGKILL'); } catch {} }
  try { child.kill('SIGKILL'); } catch {}
}
export function jobSummary(job) {
  return `job ${job.id}: ${job.done ? `done (exit ${job.code ?? '?'})` : job.stopped ? 'stopping' : 'running'} after ${(((job.endedAt || Date.now()) - job.startedAt) / 1000).toFixed(1)}s\n$ ${job.command}`;
}
export function approval(args) { return `$ ${args.command}${args.background ? '  (background job)' : '  (returns a job ID if still running)'}`; }

export async function run(args, ctx = {}) {
  if (typeof args.command !== 'string' || !args.command.trim()) return 'Error: command must be a non-empty string.';
  if (ctx.signal?.aborted) return 'Command cancelled by user.';
  const jobs = jobsOf(ctx);
  for (const [id, job] of jobs) if (jobs.size >= 100 && job.done) jobs.delete(id);
  if ([...jobs.values()].filter(j => !j.done).length >= 32) return 'Error: 32 jobs are already running. Stop one first.';
  const id = String(ctx.state._jobSeq = (ctx.state._jobSeq || 0) + 1);
  const cwd = ctx.cwd || process.cwd();
  const env = { ...process.env, ...Object.fromEntries(Object.entries(args.env || {}).map(([k, v]) => [k, String(v)])) };
  let child;
  try { child = spawn(shell(), argvFor(args.command), { cwd, env, windowsHide: true, detached: process.platform !== 'win32', stdio: ['pipe', 'pipe', 'pipe'] }); }
  catch (err) { return `Error: failed to spawn: ${err.message}`; }
  const job = { id, command: args.command, cwd, child, out: new JobOutput(clamp(args.max_output_bytes, 65536, 1024, 4 * 1024 * 1024)),
    startedAt: Date.now(), done: false, stopped: false, code: null, readOffset: 0, background: !!args.background };
  jobs.set(id, job);
  child.stdout.on('data', d => job.out.append(d)); child.stderr.on('data', d => job.out.append(d));
  child.stdin.on('error', () => {});
  let deadline;
  const finish = (code, signal, error) => {
    if (job.done) return;
    job.done = true; job.code = code; job.signal = signal; job.error = error; job.endedAt = Date.now();
    clearTimeout(deadline);
    if (job.background) notifyJob(ctx, 'finished', job);
  };
  child.once('error', err => finish(null, null, err.message));
  child.once('close', (code, signal) => finish(code, signal));
  const timeout = clamp(args.timeout_ms, 0, 0, 600000);
  if (timeout) deadline = setTimeout(() => { job.timedOut = true; job.stopped = true; void killTree(child); }, timeout);
  if (args.stdin !== undefined) {
    child.stdin.write(String(args.stdin));
    if (!(args.keep_stdin_open ?? !!args.background)) child.stdin.end();
  }
  const onAbort = () => { job.stopped = true; void killTree(child); };
  ctx.signal?.addEventListener('abort', onAbort, { once: true });
  if (args.background) notifyJob(ctx, 'started', job);
  else await waitForExit(job, clamp(args.yield_ms, 1000, 0, 10000), ctx.signal);
  ctx.signal?.removeEventListener('abort', onAbort);
  if (ctx.signal?.aborted) return `Command cancelled by user.\n${jobSummary(job)}`;
  if (job.done) {
    job.readOffset = job.out.total;
    return `exit code: ${job.code ?? -1}\n${jobSummary(job)}\n${job.error || job.out.toString() || '(no output)'}`;
  }
  if (!job.background) { job.background = true; notifyJob(ctx, 'started', job); }
  return `${jobSummary(job)}\n${JSON.stringify(jobSnapshot(job))}\nUse job_status/job_input/job_wait/job_stop. Continue other work; do not wait for servers to exit.`;
}
