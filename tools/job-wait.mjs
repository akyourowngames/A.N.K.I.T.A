import { waitForExit, jobSnapshot, clamp } from './_jobs.mjs';
export const name = 'job_wait';
export const description = 'Wait briefly for a job to exit and return incremental output. Default 1000ms, maximum 10000ms; still-running jobs remain alive. Prefer job_status for servers and continue other work.';
export const parameters = { type: 'object', properties: {
  job_id: { type: 'string' }, timeout_ms: { type: 'integer', minimum: 0, maximum: 10000 },
  since_offset: { type: 'integer', minimum: 0 }, max_bytes: { type: 'integer', minimum: 256, maximum: 65536 },
}, required: ['job_id'] };
export const readOnly = true;
export const needsApproval = false;
export async function run(args, ctx = {}) {
  const job = ctx.state?.jobs?.get(String(args.job_id));
  if (!job) return `Error: no background job "${args.job_id}".`;
  await waitForExit(job, clamp(args.timeout_ms, 1000, 0, 10000), ctx.signal);
  return JSON.stringify({ ...jobSnapshot(job, args), ...(ctx.signal?.aborted ? { wait_cancelled: true } : {}) });
}
