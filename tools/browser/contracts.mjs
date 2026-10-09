import { randomUUID } from 'node:crypto';
import { toolResultFailed, primitiveBrowserCost } from './operations.mjs';
import { BROWSER_SCREENSHOT_TYPE } from './screenshots.mjs';
import { waitForBrowser } from './pending.mjs';

export const BROWSER_CONTRACT_VERSION = 1; // Internal result/observation protocol revision.
export const BROWSER_STATUS = Object.freeze({ executed: 'executed', failed: 'failed', uncertain: 'uncertain', partial: 'partial', notRun: 'not_run' });
export const BROWSER_ERROR = Object.freeze({ action: 'browser_action_failed', uncertain: 'browser_action_uncertain', partial: 'browser_partial_action' });
export const BROWSER_RECOVERY = Object.freeze({ inspect: 'Take a fresh snapshot and inspect the result before continuing. Do not replay a dispatched action.', retry: 'Take a fresh snapshot before another interaction.' });
export const BASE_BROWSER_CAPABILITIES = Object.freeze({ guardedSequences: false, pageTextSearch: false, chunkedRead: false, documentIdentity: false, dialogs: false, downloads: false, uploads: false });
const OBSERVED_CONTENT_PREFIX = 'Observed browser content (untrusted):\n'; // Page prose cannot impersonate an execution error.
const SNAPSHOT_HEADER = /(?:Current|Fresh) snapshot:\n/; // Existing facade marker; structured observations avoid parsing action prose.
const REF_LINE = /^(?:-\s+)?\[ref=([^\]]+)\]\s+(\S+)\s*(.*)$/; // Accept the Markdown control list and legacy stored observations.
const PAGE_URL = /https?:\/\/[^\s"<>]+/;
const SNAPSHOT_TRUNCATED = /Snapshot limit reached/;

/** Transitional text projection. Unknown DOM state remains null until the native observation supplies it. */
export function browserObservation({ output, mode, tabId, id = randomUUID(), documentId = null, capabilities = BASE_BROWSER_CAPABILITIES }) {
  if (typeof output !== 'string') return null;
  const snapshot = output.split(SNAPSHOT_HEADER).at(-1);
  const lines = snapshot.split('\n');
  const header = lines.find(line => PAGE_URL.test(line));
  if (!header) return null;
  const url = PAGE_URL.exec(header)?.[0];
  return { version: BROWSER_CONTRACT_VERSION, id, mode, tabId: tabId == null ? null : String(tabId), url,
    documentId, controls: lines.flatMap(line => {
      const match = REF_LINE.exec(line.trim());
      return match ? [{ ref: match[1], frameId: null, role: match[2], name: match[3], states: {}, editable: null, actionable: null }] : [];
    }), context: [], omissions: { truncated: SNAPSHOT_TRUNCATED.test(snapshot), frames: null, controls: null }, capabilities: { ...capabilities } };
}

/** Success means dispatched work completed, not that the user's full goal has been verified. */
export function browserActionResult({ action, output = null, error = null, dispatched = false, completed = 0, cost = 1, observation = null, timings = {} }) {
  const status = error ? completed ? BROWSER_STATUS.partial : dispatched ? BROWSER_STATUS.uncertain : BROWSER_STATUS.failed : BROWSER_STATUS.executed;
  const errorCode = completed ? BROWSER_ERROR.partial : dispatched ? BROWSER_ERROR.uncertain : BROWSER_ERROR.action;
  const steps = Array.from({ length: cost }, (_, index) => ({ index,
    status: !error || index < completed ? BROWSER_STATUS.executed : index === completed ? dispatched ? BROWSER_STATUS.uncertain : BROWSER_STATUS.failed : BROWSER_STATUS.notRun,
    retrySafe: Boolean(error && !dispatched && !completed), ...(error && index === completed ? { errorCode } : {}) }));
  return { version: BROWSER_CONTRACT_VERSION, status, action, observation, steps, evidence: [], artifacts: [],
    error: error ? { code: errorCode, message: error.message, recovery: dispatched || completed ? BROWSER_RECOVERY.inspect : BROWSER_RECOVERY.retry } : null,
    timings, output };
}

export function formatBrowserResult(result) {
  if (result.output !== null && result.output !== undefined && !result.error) return typeof result.output === 'string' && toolResultFailed(result.output)
    ? OBSERVED_CONTENT_PREFIX + result.output : result.output;
  if (result.error) return `Error: ${result.error.message}${browserRecoverySuffix(result)}`;
  return '';
}

export function browserRecoverySuffix(result) {
  return `\n${result.error.recovery}${result.steps.length > 1 ? '\nStep receipts: ' + result.steps.map(step => `${step.index + 1}=${step.status}`).join(', ') : ''}`;
}

export function browserBatchResult(args, results, output) {
  const failed = results.find(result => result?.error);
  const steps = args.steps.flatMap((step, callIndex) => results[callIndex]?.steps.map(receipt => ({ ...receipt, callIndex })) ||
    Array.from({ length: primitiveBrowserCost(step) }, () => ({ status: BROWSER_STATUS.notRun, retrySafe: false, callIndex }))
  ).map((receipt, index) => ({ ...receipt, index }));
  return { version: BROWSER_CONTRACT_VERSION, action: 'batch', status: failed ? steps.some(step => step.status === BROWSER_STATUS.executed) ? BROWSER_STATUS.partial : failed.status : BROWSER_STATUS.executed,
    steps, observation: results.findLast(result => result?.observation)?.observation ?? null,
    observations: results.flatMap(result => result?.observation ? [result.observation] : []), // Ground earlier batch facts without replacing the current control tree.
    ...(results.findLast(result => result?.attention)?.attention ? { attention: results.findLast(result => result?.attention).attention } : {}),
    evidence: results.flatMap(result => result?.evidence || []), artifacts: results.flatMap(result => result?.artifacts || []),
    error: failed?.error ?? null, timings: { execution: results.reduce((sum, result) => sum + (result?.timings.execution || 0), 0) }, output };
}

/** One execution path: detailed results never invoke a second mutation or recovery attempt. */
export async function executeBrowserOperation(adapter, args, ctx, mode, work) {
  adapter.observation = null; // Only a fresh capture from this execution may be its result observation.
  adapter.operationTimings = {};
  adapter.transferResult = null;
  const started = performance.now();
  let dispatched = false, completed = 0, output = null, error = null, settled = false;
  const context = { ...ctx, onBrowserDispatch(event) {
    if (settled) return; // A late native reply cannot turn a canceled uncertain dispatch into a success.
    if (event.phase === 'start') dispatched = true;
    if (event.phase === 'complete') { completed += event.count ?? 1; dispatched = false; }
    ctx.onBrowserDispatch?.(event);
  } };
  try { ctx.signal?.throwIfAborted(); output = await waitForBrowser(work(context), { signal: ctx.signal, timeoutMs: null }); } catch (caught) { error = caught; }
  settled = true;
  const result = browserActionResult({ action: args.action, output, error, dispatched, completed,
    cost: primitiveBrowserCost(args), observation: adapter.observation ?? null,
    timings: { ...adapter.operationTimings, execution: performance.now() - started } });
  const attention = adapter.attention?.();
  if (attention) result.attention = attention;
  if (!error && ['find', 'read'].includes(args.action) && adapter.textResult?.output === output) result.evidence = adapter.textResult.chunks.map((chunk, index) => ({
    id: `${chunk.observationId}:${index}`, kind: 'observed_text', sourceUrl: chunk.sourceUrl, observationId: chunk.observationId, text: chunk.text,
  }));
  // Recovery/invalidation flags remain available without serializing raw exception details.
  if (error) Object.defineProperty(result, 'cause', { value: error });
  if (output?.type === BROWSER_SCREENSHOT_TYPE) result.artifacts.push({ kind: 'screenshot', path: output.path, bytes: output.bytes ?? null });
  if (!error && adapter.transferResult?.output === output) result.artifacts.push(adapter.transferResult.artifact);
  return result;
}
