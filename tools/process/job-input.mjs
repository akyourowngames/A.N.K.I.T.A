export const name = 'job_input';
export const description = 'Send text to a running job\'s stdin; include a newline to submit a line. eof:true closes stdin after writing. Pipes support line-based prompts; full-screen terminal programs require a separate terminal.';
export const parameters = { type: 'object', properties: { job_id: { type: 'string' }, text: { type: 'string' }, eof: { type: 'boolean' } }, required: ['job_id'] };
export const approval = args => `Send input to job ${args.job_id}${args.eof ? ' and close stdin' : ''}:\n${String(args.text || '')}`;
const STDIN_WRITE_TIMEOUT_MS = 1000; // Milliseconds: retain the native-write deadline after the process has spawned.
const INPUT_CANCELLED_ERROR = 'Input cancelled';
const STDIN_CLOSED_RESPONSE = 'Error: job stdin is closed.'; // Preserve the existing job_input response for every closed-pipe check.
export async function run(args, ctx = {}) {
  const job = ctx.state?.jobs?.get(String(args.job_id));
  if (!job) return `Error: no background job "${args.job_id}".`;
  const stdin = job.child?.stdin;
  if (job.done || !stdin?.writable || stdin.writableEnded) return STDIN_CLOSED_RESPONSE;
  if (args.text === undefined && !args.eof) return 'Error: provide text or eof:true.';
  const text = String(args.text || '');
  if (Buffer.byteLength(text) > 65536) return 'Error: stdin is limited to 65536 bytes per call.';
  if (ctx.signal?.aborted) return 'Error: input cancelled.';
  try {
    if (job.child.ready) {
      // Direct ChildProcess creation previously completed before callers could
      // send input. A queued worker launch must reach that same point before
      // starting the native pipe-write budget, while cancellation stays live.
      let abort;
      try {
        await new Promise((resolve, reject) => {
          abort = () => reject(new Error(INPUT_CANCELLED_ERROR));
          ctx.signal?.addEventListener('abort', abort, { once: true });
          job.child.ready.then(resolve, reject);
        });
      } finally { ctx.signal?.removeEventListener('abort', abort); }
      if (ctx.signal?.aborted) throw new Error(INPUT_CANCELLED_ERROR);
      if (job.done || !stdin.writable || stdin.writableEnded) return STDIN_CLOSED_RESPONSE;
    }
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => done(new Error('Job is not accepting input')), STDIN_WRITE_TIMEOUT_MS);
      const abort = () => done(new Error(INPUT_CANCELLED_ERROR));
      const done = err => { clearTimeout(timer); ctx.signal?.removeEventListener('abort', abort); err ? reject(err) : resolve(); };
      ctx.signal?.addEventListener('abort', abort, { once: true });
      stdin.write(text, done);
      if (args.eof) stdin.end();
    });
    return `Sent ${Buffer.byteLength(text)} bytes to job ${job.id}${args.eof ? '; stdin closed' : ''}.`;
  } catch (err) { return `Error: ${err.message}. Input may have been queued; check job_status before retrying.`; }
}
