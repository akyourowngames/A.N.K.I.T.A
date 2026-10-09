// Shared operation metadata: approval/read classification and primitive costs are protocol policy.
import { MAX_BROWSER_FORM_FIELDS } from './refs.mjs';
export const BROWSER_OPERATIONS = Object.freeze({
  open: { readOnly: false, approval: false }, snapshot: { readOnly: true, approval: false },
  navigate: { readOnly: false, approval: false }, back: { readOnly: false, approval: false }, forward: { readOnly: false, approval: false },
  act: { readOnly: false, approval: true }, fill_form: { readOnly: false, approval: true },
  sequence: { readOnly: false, approval: true },
  read: { readOnly: true, approval: false }, tabs: { readOnly: true, approval: false },
  find: { readOnly: true, approval: false },
  screenshot: { readOnly: true, approval: false }, close: { readOnly: false, approval: false },
  login: { readOnly: false, approval: true },
  handle_dialog: { readOnly: false, approval: true },
  upload: { readOnly: false, approval: true }, downloads: { readOnly: true, approval: false },
  download: { readOnly: false, approval: true }, cancel_download: { readOnly: false, approval: false },
});
export const BROWSER_ACTIONS = Object.freeze(Object.keys(BROWSER_OPERATIONS));
const BROWSER_ARGUMENT_GUIDANCE = 'Use native JSON arguments from the browser schema: action="snapshot" and query="Done" are separate fields, not markup inside action. Find page controls with browser snapshots, not local files.'; // Observed provider markup error: refuse execution and explain the canonical read-only recovery.
export function unknownBrowserAction(action) { return new Error(`Unknown browser action: ${action}. ${BROWSER_ARGUMENT_GUIDANCE}`); }
export const MAX_BROWSER_BATCH_STEPS = 10; // Primitive operations per foreground batch; bounded work before re-observation.
export const REF_BATCH_CONTEXT = Symbol('referenceBatchContext'); // Host-only transaction context; model arguments cannot suppress observations.
const REF_BATCH_OPERATIONS = new Set(['click', 'fill', 'select']); // Independent current-node operations; dynamic/keyboard/navigation plans retain ordinary snapshots.
const MIN_REF_BATCH_STEPS = 2; // Operations: deferring snapshots only benefits a batch with a later step.
export function independentRefBatch(steps) {
  if (steps.length < MIN_REF_BATCH_STEPS) return false;
  const modes = new Set(steps.map(step => step.mode || ''));
  const tabs = new Set(steps.map(step => String(step.tab || '')));
  if (modes.size !== 1 || tabs.size !== 1) return false;
  const seen = new Set();
  return steps.every(step => {
    if (step.action !== 'fill_form' && !(step.action === 'act' && REF_BATCH_OPERATIONS.has(step.op || 'click'))) return false;
    const refs = step.action === 'fill_form' ? (Array.isArray(step.fields) ? step.fields.map(field => field?.ref) : []) : [step.ref];
    if (!refs?.length) return false;
    return refs.every(ref => {
      if (typeof ref !== 'string' || !ref || seen.has(ref)) return false;
      seen.add(ref); return true;
    });
  });
}
export function deferBatchSnapshot(ctx) { return ctx?.[REF_BATCH_CONTEXT]?.deferSnapshot === true; }
export const BROWSER_BATCH_FAILURE_RE = /(?:^|\n)\d+\. Error:[\s\S]*\. Batch stopped\.(?:\s*\[(?:UNVERIFIED|verified:)[^\]]*\])*\s*$/; // Numbered manager receipts, including verification footer.
export const TOOL_FAILURE_PREFIX_RE = /^(?:Error\b|Not run:|The user denied|Action cancelled)/i; // Shared legacy tool error boundary.
export function browserBatchFailed(text) { return /^1\. /.test(String(text)) && BROWSER_BATCH_FAILURE_RE.test(String(text)); }
export function toolResultFailed(text) { return TOOL_FAILURE_PREFIX_RE.test(String(text)) || browserBatchFailed(text); }
export function primitiveBrowserCost(args = {}) {
  if (args.action === 'sequence' && Array.isArray(args.steps)) return Math.max(1, Math.min(MAX_BROWSER_BATCH_STEPS, args.steps.length));
  if (args.action === 'batch' && Array.isArray(args.steps)) return args.steps.slice(0, MAX_BROWSER_BATCH_STEPS).reduce((sum, step) => sum +
    (step?.action === 'batch' ? MAX_BROWSER_BATCH_STEPS : primitiveBrowserCost(step)), 0) || 1;
  return args.action === 'fill_form' && Array.isArray(args.fields) ? Math.max(1, Math.min(MAX_BROWSER_FORM_FIELDS, args.fields.length)) : 1;
}

// MCP operations that may dispatch page writes/navigation. Read-only retries never enter this set.
export const CHROME_DISPATCH_OPERATIONS = new Set(['new_page', 'navigate_page', 'close_page', 'click', 'fill', 'fill_form', 'type_text', 'press_key', 'hover', 'drag', 'handle_dialog']);
export const BROWSER_NAVIGATION_ACTIONS = Object.freeze(['navigate', 'back', 'forward']);
export const BROWSER_HISTORY_DIRECTIONS = Object.freeze({ back: -1, forward: 1 }); // Entries relative to the current native history index.
