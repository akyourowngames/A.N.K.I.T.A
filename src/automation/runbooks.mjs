import fs from 'node:fs';
import path from 'node:path';
import { cronFire, describeCron } from './cron.mjs';
import { redact } from '../security/secret-scrubber.mjs';
import { JOB_SUMMARY_MAX_CHARS, routineOutcomeAt } from './job-policy.mjs';

const RECENT_RUN_LIMIT = 5; // Outcomes displayed per one-page runbook.
const RECEIPT_MAX_BYTES = 2 * 1024 * 1024; // Skip oversized transcripts; only summary metadata is needed.
const RECOVERY_STEPS = Object.freeze({
  error: 'Review the last result and correct the task resource or provider settings before running again.',
  timeout: 'Review the last proof before retrying. Check the task timeout and simplify the work if needed.',
  interrupted: 'Review the last proof; an action may have completed before the app stopped. Resume only the remaining work.',
  'needs-input': 'Supply the requested sign-in or human input in the foreground, then resume the task.',
  budget: 'Review usage and the daily task limits before re-enabling the task.',
  missed: 'Check scheduler ownership and sleep/wake timing. Run now only if the result is still useful.',
}); // Guidance is keyed to scheduler outcomes, not guesses about a specific failure.
const line = text => String(text || '').replace(/\s+/g, ' ').replace(/\|/g, '\\|').slice(0, JOB_SUMMARY_MAX_CHARS);
const validRun = run => run && Number.isFinite(Date.parse(run.at)) && typeof run.status === 'string';

function retainedRuns(routine, runsDir) {
  const savedHistory = Array.isArray(routine.runHistory) ? routine.runHistory : [];
  const runs = savedHistory.filter(validRun);
  let unreadable = savedHistory.length - runs.length;
  if (runsDir && fs.existsSync(runsDir)) {
    const root = fs.realpathSync(runsDir);
    for (const name of fs.readdirSync(runsDir).filter(name => name.startsWith(`${routine.id}-`) && name.endsWith('.json'))) {
      try {
        const file = path.join(runsDir, name);
        if (path.dirname(fs.realpathSync(file)) !== root || fs.statSync(file).size > RECEIPT_MAX_BYTES) throw new Error('unreadable receipt');
        const saved = JSON.parse(fs.readFileSync(file, 'utf8'));
        if (saved.routineId !== routine.id) continue;
        if (!Number.isFinite(Date.parse(saved.at)) || typeof saved.status !== 'string') throw new Error('invalid receipt metadata');
        runs.push(saved);
      } catch { unreadable++; }
    }
  }
  const at = routineOutcomeAt(routine);
  const current = { at, status: routine.lastStatus, summary: routine.lastSummary };
  if (validRun(current) && !runs.some(run => Date.parse(run.at) === Date.parse(at) && run.status === current.status)) runs.push(current);
  const unique = new Map(runs.map(run => [`${run.runId || ''}:${run.at}:${run.status}`, run]));
  return { runs: [...unique.values()].sort((a, b) => String(b.at).localeCompare(String(a.at))).slice(0, RECENT_RUN_LIMIT), unreadable };
}

export function jobRunbook(routine, { now = new Date(), timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone, runsDir } = {}) {
  if (!routine) throw new Error('Task not found');
  const next = routine.runAt ? new Date(routine.runAt) : routine.enabled ? cronFire(routine.cron, now, timeZone) : null;
  const history = retainedRuns(routine, runsDir);
  const allow = routine.allow || {};
  const status = routine.pausedReason || routine.lastStatus || history.runs[0]?.status;
  const report = [
    `# Task runbook: ${line(routine.name)}`, '',
    `Task ID: ${line(routine.id)}`,
    `Schedule: ${describeCron(routine.cron)} (${line(timeZone)})`,
    `Next run: ${next && Number.isFinite(next.getTime()) ? next.toISOString() : routine.enabled ? 'unavailable' : 'paused'}`,
    `Delivery: ${line(routine.channel || 'configured notifications')}`,
    `Permissions: read=${Boolean(allow.read)}, interact=${Boolean(allow.interact)}, login=${Boolean(allow.login)}, browser=${line(allow.mode || 'isolated')}`,
    `Sites: ${(allow.sites || []).map(line).join(', ') || 'no site-specific rules'}`, '',
    '## What it does', '', String(routine.prompt || '').replace(/^/gm, '    '), '',
    '## Recent outcomes', '',
    ...history.runs.map(run => `- ${line(run.at)} — ${line(run.status)}${Number.isFinite(run.tokens) ? ` · ${run.tokens} tokens` : ''}${Number.isFinite(run.activeMs) ? ` · ${run.activeMs} ms` : ''}: ${line(run.text || run.summary)}`),
    ...(history.runs.length ? [] : ['No retained runs. This task may not have run yet.']),
    ...(history.unreadable ? [`${history.unreadable} unreadable retained receipts were skipped.`] : []), '',
    '## Recovery', '', RECOVERY_STEPS[status] || 'Review the task details and last result before choosing to run it again.',
    'Check that the scheduler is running, the task is enabled and the configured provider/delivery channel is available. Runbook generation never retries or changes the task.',
  ].join('\n');
  return redact(report);
}
