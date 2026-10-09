import { MAX_BROWSER_BATCH_STEPS } from './operations.mjs';
import { normalizeBrowserArgs } from './pending.mjs';

// Initial supported chain: related field edits, with an optional final form-completion boundary.
export const SEQUENCE_FIELD_OPS = Object.freeze(['fill', 'select']);
export const SEQUENCE_BOUNDARY_OPS = Object.freeze(['click', 'press']);
export const SEQUENCE_CHANGED = 'Sequence target or form changed. Remaining steps were not run; inspect a fresh snapshot before continuing.';
export const SEQUENCE_GUARD_LIMIT_REACHED = 'The form exceeds the guarded-sequence inspection limit. Use individual actions with fresh observations.'; // Shared refusal guidance for a capped native form/ancestor probe.
export const SEQUENCE_UNSUPPORTED = 'This browser does not support guarded sequences. Use individual actions with fresh observations.';
const SEQUENCE_KEYS = new Set(['action', 'op', 'ref', 'text', 'tab', 'mode']); // Typed primitives; no nested tools or private login arguments.
export const SEQUENCE_CONTROL_SELECTOR = 'input,textarea,select,button,[contenteditable="true"],[role="combobox"],[role="option"]'; // Native field/boundary structure; values are deliberately excluded.
export const SEQUENCE_GUARD_NODE_LIMIT = 4096; // Element nodes per form probe, plus one overflow sentinel: bound framework/shadow walks and refuse oversized chains before dispatch.

export function validateSequence(args, observation, capabilities) {
  if (capabilities?.guardedSequences !== true) throw new Error(SEQUENCE_UNSUPPORTED);
  if (!observation || args.observation_id !== observation.id) throw new Error('Sequence needs the current snapshot observation_id. Take a fresh snapshot.');
  if (args.tab != null && String(args.tab) !== observation.tabId) throw new Error('Sequence belongs to a different tab.');
  if (!Array.isArray(args.steps) || !args.steps.length || args.steps.length > MAX_BROWSER_BATCH_STEPS) throw new Error(`Sequence needs 1 to ${MAX_BROWSER_BATCH_STEPS} steps.`);
  const controls = new Map(observation.controls.map(control => [control.ref, control]));
  const steps = args.steps.map(normalizeBrowserArgs);
  for (const [index, step] of steps.entries()) {
    if (Object.keys(step).some(key => !SEQUENCE_KEYS.has(key)) || step.action !== 'act' || ![...SEQUENCE_FIELD_OPS, ...SEQUENCE_BOUNDARY_OPS].includes(step.op)) throw new Error('Sequence accepts typed act fill/select steps and an optional final click/press; no nested batches or login.');
    if ((step.tab != null && String(step.tab) !== observation.tabId) || (step.mode && step.mode !== observation.mode)) throw new Error('Sequence cannot cross tab or browser ownership.');
    const control = controls.get(step.ref);
    if (!control || control.actionable === false || (SEQUENCE_FIELD_OPS.includes(step.op) && control.editable !== true)) throw new Error('Sequence target is missing, covered or not editable. Inspect the current controls.');
    if (SEQUENCE_FIELD_OPS.includes(step.op) && typeof step.text !== 'string') throw new Error('Sequence field text must be a string.');
    if (SEQUENCE_BOUNDARY_OPS.includes(step.op) && index !== steps.length - 1) throw new Error('Navigation, submission and dialog boundaries must be the final sequence step.');
  }
  return { observation, steps };
}

/** Serializable bounded native guard. Without scope, bind the same composed owner used by every recheck. */
export function captureSequenceGuard(element, { scope, selector, controlSelector, limit, scanLimit }) {
  const ancestors = [];
  for (let node = element; node; node = node.parentElement || node.getRootNode().host) {
    ancestors.push(node);
    if (ancestors.length > scanLimit) break;
  }
  const group = ancestors.length <= scanLimit
    ? element.form || ancestors.find(node => node.matches(selector)) || element.ownerDocument.body : null;
  if (scope === undefined) return group;
  const unavailable = ancestors.some(node => node.hasAttribute('inert') || node.hidden || node.getAttribute('aria-hidden') === 'true');
  if (!element.isConnected || !scope?.isConnected || group !== scope || unavailable) return { valid: false, truncated: ancestors.length > scanLimit };
  const roots = [scope], nodes = [];
  if (scope.shadowRoot) roots.push(scope.shadowRoot);
  let inspectedNodes = 0, bounded = true;
  scan: for (const root of roots) {
    const walker = element.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      if (++inspectedNodes > scanLimit) { bounded = false; break scan; }
      if (node.shadowRoot) roots.push(node.shadowRoot);
      if (!node.matches(controlSelector)) continue;
      nodes.push(node);
      if (nodes.length > limit) { bounded = false; break scan; }
    }
  }
  const structure = nodes.map(node => [node.tagName, node.type, node.id, node.name, node.disabled, node.readOnly,
    node.getAttribute('role'), node.getAttribute('aria-disabled'), node.getAttribute('aria-readonly'), node.getAttribute('aria-expanded'), node.getAttribute('list'), node.getAttribute('formaction')]);
  return { valid: bounded, truncated: !bounded,
    structure: JSON.stringify([scope.tagName, scope.getAttribute('action'), scope.getAttribute('method'), structure]),
    autocompleteOpen: nodes.some(node => node.getAttribute('role') === 'combobox' && node.getAttribute('aria-expanded') === 'true'), inspectedNodes };
}
