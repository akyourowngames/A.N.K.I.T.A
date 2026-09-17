import { killTree, waitForExit } from "./run-command.mjs";

export const name = "job_stop";
export const description = "Stop a background job started with run_command background:true.";

export const parameters = {
  type: "object",
  properties: {
    job_id: { type: "string", description: "The job id returned when the job was started." },
  },
  required: ["job_id"],
};

export const needsApproval = false;

export async function run(args, ctx = {}) {
  const job = ctx.state?.jobs?.get?.(String(args.job_id));
  if (!job) return `Error: no background job "${args.job_id}".`;
  if (job.done) return `job ${job.id} already finished (exit ${job.code ?? "?"}).`;
  job.stopped = true;
  killTree(job.child);
  await waitForExit(job, 5000);
  return job.done
    ? `stopped job ${job.id} (exit ${job.code ?? "?"})`
    : `stop requested for job ${job.id}, still exiting`;
}
