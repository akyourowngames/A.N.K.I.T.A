export const name = 'job_input';
export const description = 'Send text to a running job\'s stdin; include a newline to submit a line. eof:true closes stdin after writing. Pipes support line-based prompts; full-screen terminal programs require a separate terminal.';
export const parameters = { type: 'object', properties: { job_id: { type: 'string' }, text: { type: 'string' }, eof: { type: 'boolean' } }, required: ['job_id'] };
export const approval = args => `Send input to job ${args.job_id}${args.eof ? ' and close stdin' : ''}:\n${String(args.text || '')}`;
export async function run(args, ctx = {}) {
  const job = ctx.state?.jobs?.get(String(args.job_id));
  if (!job) return `Error: no background job "${args.job_id}".`;
  const stdin = job.child?.stdin;
  if (job.done || !stdin?.writable || stdin.writableEnded) return 'Error: job stdin is closed.';
  if (args.text === undefined && !args.eof) return 'Error: provide text or eof:true.';
  const text = String(args.text || '');
  if (Buffer.byteLength(text) > 65536) return 'Error: stdin is limited to 65536 bytes per call.';
  if (ctx.signal?.aborted) return 'Error: input cancelled.';
  try {
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => done(new Error('Job is not accepting input')), 1000);
      const abort = () => done(new Error('Input cancelled'));
      const done = err => { clearTimeout(timer); ctx.signal?.removeEventListener('abort', abort); err ? reject(err) : resolve(); };
      ctx.signal?.addEventListener('abort', abort, { once: true });
      stdin.write(text, done);
      if (args.eof) stdin.end();
    });
    return `Sent ${Buffer.byteLength(text)} bytes to job ${job.id}${args.eof ? '; stdin closed' : ''}.`;
  } catch (err) { return `Error: ${err.message}. Input may have been queued; check job_status before retrying.`; }
}
