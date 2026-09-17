import { jobSummary } from "./run-command.mjs";

export const name = "job_status";
export const description =
  "Read a background job started with run_command background:true. Returns whether it is " +
  "running or done plus the output collected so far.";

export const parameters = {
  type: "object",
  properties: {
    job_id: { type: "string", description: "The job id returned when the job was started." },
  },
  required: ["job_id"],
};

export const readOnly = true;
export const needsApproval = false;

export function run(args, ctx = {}) {
  const job = ctx.state?.jobs?.get?.(String(args.job_id));
  if (!job) return `Error: no background job "${args.job_id}". Start one with run_command background:true.`;
  const output = job.out.toString() || "(no output yet)";
  return `${jobSummary(job)}\n${output}`;
}
