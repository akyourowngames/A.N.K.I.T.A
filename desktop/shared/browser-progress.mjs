import { primitiveBrowserCost } from '../../tools/browser/operations.mjs';
import { BROWSER_DIALOG_TYPES } from '../../tools/browser/dialogs.mjs';

export const BROWSER_PROGRESS_LIMITS = Object.freeze({ label: 96 }); // UTF-16 characters in public progress, independent of page/input content.
export const BROWSER_PREVIEW_POLL = Object.freeze({ active: 100, thumbnail: 2000, idle: 2000, failed: 1000, hidden: 2000 }); // Milliseconds: existing cadence shared with native window visibility and thumbnail polling.
export const BROWSER_PHASES = Object.freeze(['thinking', 'reading', 'acting', 'checking', 'recovering', 'waiting-for-user', 'stopped', 'finished']);
export const BROWSER_PHASE_TITLES = Object.freeze({ thinking: 'Thinking', reading: 'Reading', acting: 'Acting', checking: 'Checking', recovering: 'Recovering', 'waiting-for-user': 'Your turn', stopped: 'Stopped', finished: 'Finished' });
/** Transient page dialog text belongs only to the requesting panel, never its shared thumbnails. */
export function publicBrowserView(view) { const { dialog, ...publicView } = view; return publicView; }
const OUTCOMES = new Set(['unverified', 'executed', 'failed', 'partial', 'uncertain']);
const NEEDS_CHECK = new Set(['failed', 'partial', 'uncertain']);
const PHASE_LABELS = Object.freeze({ thinking: 'Planning the next step', reading: 'Reading the page', acting: 'Working on the page', checking: 'Checking the page', recovering: 'Checking what changed', 'waiting-for-user': 'Your help is needed', stopped: 'Stopped', finished: 'Browser steps finished' });
const ACTION_LABELS = Object.freeze({ open: 'Opening a page', navigate: 'Navigating', back: 'Going back', forward: 'Going forward', sequence: 'Completing the form', fill_form: 'Filling the form', upload: 'Selecting the upload', download: 'Saving the download', cancel_download: 'Canceling the download', handle_dialog: 'Handling the page dialog', close: 'Closing the tab', login: 'Signing in' });
const INTERACTION_LABELS = Object.freeze({ click: 'Using the selected control', fill: 'Filling a field', type: 'Entering text', press: 'Using the keyboard', select: 'Choosing an option', hover: 'Inspecting a control', scroll: 'Moving through the page', drag: 'Moving the selected item' });
const READING_ACTIONS = new Set(['snapshot', 'read', 'find', 'tabs', 'downloads', 'screenshot']);
export const browserActionPhase = args => READING_ACTIONS.has(args?.action) ? 'reading' : 'acting';

/** Public runtime state is allowlisted metadata, never raw arguments, errors, URLs or DOM text. */
export function browserProgress({ phase = 'thinking', args = null, completed, result = null, previous = null } = {}) {
  let selected = BROWSER_PHASES.includes(phase) ? phase : 'thinking';
  const outcome = OUTCOMES.has(result?.status) ? result.status : OUTCOMES.has(previous?.outcome) ? previous.outcome : 'unverified';
  const dialog = result ? result.attention?.dialog : previous?.attention?.kind === 'dialog' ? { type: previous.attention.dialogType } : null;
  const attention = selected !== 'stopped' && dialog ? { kind: 'dialog', dialogType: BROWSER_DIALOG_TYPES.includes(dialog.type) ? dialog.type : null } : null;
  if (attention) selected = 'waiting-for-user';
  else if (selected === 'finished' && NEEDS_CHECK.has(outcome)) selected = 'recovering';
  const total = args ? primitiveBrowserCost(args) : Number.isInteger(previous?.total) && previous.total > 0 ? previous.total : null;
  const observed = Array.isArray(result?.steps) ? result.steps.filter(step => step.status === 'executed').length : completed ?? (args ? 0 : previous?.completed) ?? 0;
  const count = Math.max(0, Math.min(total ?? 0, Number.isFinite(observed) ? Math.trunc(observed) : 0));
  const label = selected === 'acting' && args ? args.action === 'act' ? INTERACTION_LABELS[args.op] || PHASE_LABELS.acting : ACTION_LABELS[args.action] || PHASE_LABELS.acting : PHASE_LABELS[selected];
  return { phase: selected, label: label.slice(0, BROWSER_PROGRESS_LIMITS.label), completed: count, total, outcome,
    recoverable: selected !== 'stopped' && (NEEDS_CHECK.has(outcome) || selected === 'waiting-for-user'), goalVerified: false, attention };
}
