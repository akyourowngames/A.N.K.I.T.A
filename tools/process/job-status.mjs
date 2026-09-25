import { jobInfo, jobSnapshot } from '../shared/_jobs.mjs';

export const name = "job_status";
export const description =
  "List jobs (omit job_id), or read incremental output. Default resumes the last cursor; since_offset replays bytes, tail returns recent lines. Reports dropped bytes when output rolled over.";

export const parameters = {
  type: "object",
  properties: {
    job_id: { type: "string", description: "The job id returned when the job was started." },
    since_offset: { type: 'integer', minimum: 0 },
    tail: { type: 'integer', minimum: 1, maximum: 1000 },
    max_bytes: { type: 'integer', minimum: 256, maximum: 65536 },
  },
};

export const readOnly = true;
export const needsApproval = false;

export function run(args, ctx = {}) {
  if (!args.job_id) return JSON.stringify({ jobs: [...(ctx.state?.jobs?.values() || [])].map(jobInfo) });
  const job = ctx.state?.jobs?.get?.(String(args.job_id));
  if (!job) return `Error: no background job "${args.job_id}". Start one with run_command background:true.`;
  return JSON.stringify(jobSnapshot(job, args));
}
