import { run as listJobs } from '../../tools/process/job-status.mjs';
import { run as sendInput } from '../../tools/process/job-input.mjs';
import { run as stopJob } from '../../tools/process/job-stop.mjs';
import { run as waitJob } from '../../tools/process/job-wait.mjs';
import { run as runCommand } from '../../tools/process/run-command.mjs';

export const JOB_COMMANDS = ['/jobs', '/job', '/input', '/eof', '/stop', '/wait', '/bg'];
export const isJobCommand = text => JOB_COMMANDS.includes(String(text).trim().split(/\s+/, 1)[0]);
export const runningJobCount = state => [...(state?.jobs?.values() || [])].filter(job => !job.done).length;
const singleLine = text => String(text).replace(/[\r\n\x1b]/g, ' ');
export function jobEventText(event) {
  return `[job ${event.id}] ${event.event === 'started' ? 'running in background' : `${event.state}, exit ${event.exit_code ?? event.signal ?? '?'}`} | ${singleLine(event.command).slice(0, 140)} | /job ${event.id}`;
}
function render(raw) {
  if (raw.startsWith('Error:')) return raw;
  const result = JSON.parse(raw);
  if (result.jobs) return result.jobs.length ? result.jobs.map(job => `[${job.id}] ${job.state}  pid ${job.pid ?? '-'}  ${singleLine(job.command)}`).join('\n') : 'No jobs in this session. Use /bg <command> to start one.';
  return `[job ${result.id}] ${result.state}${result.exit_code !== null ? `, exit ${result.exit_code}` : ''} | pid ${result.pid ?? '-'}\n${result.command}\n` +
    (result.dropped ? `[${result.dropped} earlier bytes no longer retained]\n` : '') + (result.output || '(no new output)') +
    `\n[next_offset=${result.next_offset}${result.more ? '; more output available' : ''}]`;
}
export async function runJobCommand(text, ctx) {
  const match = String(text).trim().match(/^(\/\S+)(?:\s+([\s\S]*))?$/);
  if (!match || !JOB_COMMANDS.includes(match[1])) return null;
  const [, command, rest = ''] = match;
  if (command === '/jobs') return render(listJobs({}, ctx));
  if (command === '/bg') return rest ? runCommand({ command: rest, background: true }, ctx) : 'Usage: /bg <command>';
  const args = rest.match(/^(\S+)(?:\s+([\s\S]*))?$/);
  if (!args) return `Usage: ${command} <job-id>${command === '/input' ? ' <text>' : ''}`;
  const [, job_id, value] = args;
  if (command === '/input') return value !== undefined ? sendInput({ job_id, text: value + '\n' }, ctx) : 'Usage: /input <job-id> <text>';
  if (command === '/eof') return sendInput({ job_id, eof: true }, ctx);
  if (command === '/stop') return stopJob({ job_id }, ctx);
  if (value !== undefined && !/^\d+$/.test(value)) return 'Offset/wait must be a nonnegative integer.';
  if (command === '/wait') return render(await waitJob({ job_id, ...(value !== undefined ? { timeout_ms: Number(value) } : {}) }, ctx));
  return render(listJobs({ job_id, ...(value !== undefined ? { since_offset: Number(value) } : {}) }, ctx));
}
