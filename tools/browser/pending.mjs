import { BROWSER_ACTIONS } from './operations.mjs';

/** Bound browser work even when a transport never settles. Always detach listeners. */
export function waitForBrowser(work, { signal, timeoutMs = 30_000, onTimeout } = {}) {
  return new Promise((resolve, reject) => {
    const finish = (fn, value) => { clearTimeout(timer); signal?.removeEventListener('abort', cancel); fn(value); };
    const cancel = () => finish(reject, new Error('Browser action cancelled'));
    const timer = timeoutMs === null ? null : setTimeout(() => {
      finish(reject, new Error(`Browser request timed out after ${Math.round(timeoutMs / 1000)} seconds. Check the browser connection and try again.`));
      onTimeout?.();
    }, timeoutMs);
    signal?.addEventListener('abort', cancel, { once: true });
    Promise.resolve(work).then(value => finish(resolve, value), error => finish(reject, error));
    if (signal?.aborted) cancel();
  });
}

// Operation names also accepted as `action` (rewritten to act + op).
const ACT_OPS = new Set(['click', 'fill', 'type', 'press', 'select', 'hover', 'scroll', 'drag']);
// Display modes confused for connection modes (headless is a launch setting, not a mode).
const MODE_ALIAS = { headless: 'isolated', headful: 'isolated' };
const ACTION_ALIAS = { signin: 'login', sign_in: 'login' }; // Common sign-in spelling; secure path only.
const ACTION_TOKEN_SUFFIX = />+$/; // Step 5 live traces emitted a trailing token delimiter on otherwise valid actions.
const NORMALIZABLE_ACTIONS = new Set([...BROWSER_ACTIONS, 'batch', ...ACT_OPS, ...Object.keys(ACTION_ALIAS)]); // Existing facade protocol and aliases only.

/**
 * Forgiving argument shapes observed live: the model sends op names as
 * actions (`click` instead of `act`+`click`), `target` instead of `ref`, and
 * `headless` instead of a mode. Normalize to the canonical form both the tool
 * entry and the session manager accept, so one spelling works everywhere.
 * Pure and recursive over batch steps.
 */
export function normalizeBrowserArgs(args = {}) {
  const out = { ...args };
  if (typeof out.action === 'string') {
    const candidate = out.action.replace(ACTION_TOKEN_SUFFIX, '');
    if (NORMALIZABLE_ACTIONS.has(candidate)) out.action = candidate;
  }
  if (ACTION_ALIAS[out.action]) out.action = ACTION_ALIAS[out.action];
  if (ACT_OPS.has(out.action)) { out.op = out.op || out.action; out.action = 'act'; }
  if (out.target != null && out.ref == null) out.ref = out.target;
  if (out.to_target != null && out.to_ref == null) out.to_ref = out.to_target;
  if (MODE_ALIAS[out.mode]) out.mode = MODE_ALIAS[out.mode];
  // Automatic selection is the existing omitted-mode policy, including disabled-mode guards.
  if (out.mode === 'auto') delete out.mode;
  // Models use the same automatic-selection spelling for the active tab.
  // It must not become a literal tab ID or trigger a tab/ref invalidation.
  if (out.tab === 'auto') delete out.tab;
  if (Array.isArray(out.steps)) out.steps = out.steps.map(normalizeBrowserArgs);
  return out;
}
