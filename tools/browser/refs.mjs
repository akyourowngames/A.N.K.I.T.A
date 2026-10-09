// Character/node budgets keep snapshots within the tool-result context budget.
export const SNAPSHOT_LIMITS = Object.freeze({ characters: 16_000, elements: 160, label: 160, frames: 16, url: 500 });
export const SNAPSHOT_CONTEXT_CHARACTERS = 2000; // Characters/frame: visible stock, price and validation text supplements controls without inventing actionable refs.
export const SNAPSHOT_LIMIT_REACHED = 'Snapshot limit reached. Use snapshot query to find a missing control by label.'; // Shared omission/recovery notice; bounded snapshots never silently drop content.
// Milliseconds: preserve Playwright auto-waiting while bounding each interaction.
export const BROWSER_ACTION_TIMEOUT_MS = 7000;
export const BROWSER_SCROLL_DISTANCE_PX = 550; // CSS pixels: preserve the existing wheel default on both backends.
// Maximum controls per form call: bound partial work and keep one snapshot readable.
export const MAX_BROWSER_FORM_FIELDS = 10;
export const CREDENTIAL_ATTRIBUTE = 'data-ankita-credential'; // Preserve private password identity when a site toggles input type.
export const BROWSER_GROUP_SELECTOR = 'form,[role="dialog"],[role="group"]'; // Form/widget ownership for observations and guarded actions.
export const FILL_NO_CHANGE_TEXT = 'No fields changed.'; // Shared pre-action receipt; removed once a mutation starts.
export const REF_GUIDANCE = 'Copy the opaque ref from [ref=...] verbatim. DOM IDs, selectors, role names and labels are not refs.';
export const ISOLATED_REF_PATTERN = /^\d+-\d+-\d+$/;
export const CHROME_REF_PATTERN = /^\d+-\d+$/;
// ARIA interaction roles used by both backends; static text is context, not an action target.
export const INTERACTIVE_ROLES = Object.freeze(['button', 'link', 'textbox', 'combobox', 'listbox', 'option', 'checkbox', 'radio', 'switch', 'menuitem', 'menuitemcheckbox', 'menuitemradio', 'tab', 'slider', 'spinbutton', 'treeitem', 'searchbox']);

export function browserFields(fields) {
  if (!Array.isArray(fields) || !fields.length || fields.length > MAX_BROWSER_FORM_FIELDS || fields.some(field => typeof field?.ref !== 'string' || typeof field?.text !== 'string')) {
    throw new Error(`fill_form needs 1 to ${MAX_BROWSER_FORM_FIELDS} fields, each with a ref and text string.`);
  }
  return fields;
}

export class BrowserReferenceError extends Error {
  constructor(ref, pattern, reason) {
    super(`${reason || (pattern.test(ref) ? 'Stale ref; the target changed or belongs to another snapshot.' : 'Unknown browser ref.')} ${REF_GUIDANCE}`);
    this.name = 'BrowserReferenceError';
    this.preserveRefs = false;
  }
}

/** A cloned DOM attribute or a same-named replacement cannot inherit an observed node's identity. */
export function browserRefMatches(element, { identityKey, ref }) {
  return element.isConnected && element[Symbol.for(identityKey)] === ref;
}

/** Serializable bounded control probe. Geometry is CSS pixels; private field values are never read. */
export function inspectBrowserControls(elements, options = {}) {
  return elements.slice(0, options.limit ?? elements.length).map(element => {
    const view = element.ownerDocument.defaultView, rect = element.getBoundingClientRect();
    const ancestors = [];
    for (let node = element; node; node = node.parentElement || node.getRootNode().host) ancestors.push(node);
    const hidden = !element.isConnected || !rect.width || !rect.height || getComputedStyle(element).visibility !== 'visible' ||
      ancestors.some(node => node.hidden || node.getAttribute('aria-hidden') === 'true');
    const inert = ancestors.some(node => node.hasAttribute('inert'));
    const disabled = element.matches(':disabled') || element.getAttribute('aria-disabled') === 'true';
    const readonly = Boolean(element.readOnly) || element.getAttribute('aria-readonly') === 'true';
    const offscreen = rect.bottom <= 0 || rect.right <= 0 || rect.top >= view.innerHeight || rect.left >= view.innerWidth;
    const x = (Math.max(0, rect.left) + Math.min(view.innerWidth, rect.right)) / 2;
    const y = (Math.max(0, rect.top) + Math.min(view.innerHeight, rect.bottom)) / 2;
    const ownsHit = hit => hit === element || element.contains(hit) || ancestors.some(node => node.shadowRoot && node === hit);
    const covered = !hidden && !offscreen && (!ownsHit(element.ownerDocument.elementFromPoint(x, y)) || !ownsHit(element.getRootNode().elementFromPoint?.(x, y)));
    const tag = element.tagName.toLowerCase();
    const editable = !hidden && !disabled && !readonly && !inert && (element.isContentEditable || ['textarea', 'select'].includes(tag) ||
      (tag === 'input' && !['button', 'submit', 'reset', 'file', 'hidden', 'image'].includes(element.type)));
    return { ref: options.refAttribute ? element.getAttribute(options.refAttribute) : null,
      states: { hidden, inert, disabled, readonly, offscreen, covered }, editable, actionable: !hidden && !inert && !disabled && !offscreen && !covered };
  });
}

export const BROWSER_REF_ATTRIBUTE = 'data-ankita-ref'; // Backend-private DOM marker; the non-clonable symbol remains authoritative.
export const BROWSER_CONTROL_FLAGS = Object.freeze(['hidden', 'inert', 'offscreen', 'covered']); // Readable state flags beyond ordinary form states.
export const BROWSER_CONTROL_PREFIX = '- '; // Markdown control-list marker; old opaque ref syntax remains unchanged.
export const BROWSER_CONTROL_FLAG_CHARACTERS = ` [${BROWSER_CONTROL_FLAGS.join(', ')}]`.length; // Characters: reserve the largest possible flag suffix before publishing a Chrome ref.

export function browserScrollDelta(text) {
  const delta = Number(text);
  return Number.isFinite(delta) && delta !== 0 ? delta : BROWSER_SCROLL_DISTANCE_PX;
}

/** Fixed host-owned scroll code; the observed native UID supplies the element, never a guessed selector. */
export function scrollBrowserControl(element, delta) {
  element.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  const view = element.ownerDocument.defaultView;
  for (let node = element; node; node = node.parentElement || node.getRootNode().host) {
    if (node.scrollHeight > node.clientHeight && /^(auto|scroll)$/.test(view.getComputedStyle(node).overflowY)) {
      node.scrollBy({ top: delta, left: 0, behavior: 'instant' });
      return { top: node.scrollTop };
    }
  }
  view.scrollBy({ top: delta, left: 0, behavior: 'instant' });
  return { top: view.scrollY };
}

/** Serializable, read-only DOM probe shared by both adapters; never reads field values. */
export function inspectFillControl(element, credentialAttribute, ariaControls = false) {
  // Native input types supported by the browser fill APIs, plus checked controls.
  const inputTypes = ['text', 'email', 'number', 'password', 'search', 'tel', 'url', 'date', 'time', 'datetime-local', 'month', 'week', 'range', 'color', 'checkbox', 'radio'];
  const tag = element.tagName.toLowerCase(), type = element.type || '';
  const role = element.getAttribute('role') || '';
  // Chrome MCP supports ARIA toggles and comboboxes with accessible option children.
  const customControl = ariaControls && (['checkbox', 'radio', 'switch'].includes(role) || (role === 'combobox' && element.querySelector('[role="option"]')));
  let issue = null;
  if (!element.isConnected) issue = 'detached';
  else if (element.matches(':disabled') || element.getAttribute('aria-disabled') === 'true') issue = 'disabled';
  else if (element.readOnly || element.getAttribute('aria-readonly') === 'true') issue = 'readonly';
  else if (!(customControl || element.isContentEditable || tag === 'textarea' || tag === 'select' || (tag === 'input' && inputTypes.includes(type)))) issue = 'not editable';
  return { tag, type, role, issue, privatePassword: type === 'password' || element.getAttribute(credentialAttribute) === 'password' };
}

/** Validate the whole batch before dispatching any write, without repeating mutations. */
export function assertFillControl(control, field, pattern, privateCredentials = false, noChangeText = FILL_NO_CHANGE_TEXT) {
  let issue = control.issue;
  const checkedType = control.type || control.role;
  if (['checkbox', 'switch'].includes(checkedType) && !['true', 'false'].includes(field.text)) issue = 'checkbox/switch value must be true or false';
  if (checkedType === 'radio' && field.text !== 'true') issue = 'radio value must be true';
  if (privateCredentials && (control.privatePassword || control.type === 'password')) issue = 'use browser login with credential_fields and credential=password for the saved password';
  if (issue) throw new BrowserReferenceError(field.ref, pattern, `Cannot fill ref ${field.ref}: ${issue}. ${noChangeText} Choose an editable control from the fresh snapshot.`);
}

const NATIVE_SELECT_GUIDANCE = 'Select needs a native <select> control. For a custom menu, use act click to open it, then click its observed option ref from the fresh snapshot.'; // Shared native/ARIA boundary: no mutation or guessed option lookup on custom widgets.
export function assertSelectControl(control, ref, pattern) {
  if (control.tag !== 'select') throw new BrowserReferenceError(ref, pattern, NATIVE_SELECT_GUIDANCE);
}

export const BATCH_TARGET_PROBE = `(element) => ({ fill: (${inspectFillControl.toString()})(element, ${JSON.stringify(CREDENTIAL_ATTRIBUTE)}, true), state: (${inspectBrowserControls.toString()})([element])[0]?.states })`; // Fixed read-only live target snapshot; never captures field values or rewrites refs.
export const BATCH_TARGETS_PROBE = `(...elements) => elements.map(${BATCH_TARGET_PROBE})`; // Chrome resolves current native UIDs in one bounded probe.
export const inspectBatchTarget = Function(`return (${BATCH_TARGET_PROBE});`)(); // Compile only the fixed repository-owned probe for Playwright's function serializer; no model/page strings enter code.
const BLOCKED_BATCH_STATES = ['hidden', 'inert', 'disabled', 'covered']; // Offscreen controls may use the native browser's automatic scroll.
export const BATCH_CHECK_NO_CHANGE_TEXT = 'This target check made no edits.'; // A read-only preflight may follow completed batch steps; never imply those writes were undone.
export function assertBatchTarget(probe, step, field, pattern, privateCredentials = false) {
  if (!probe?.fill || !probe.state) throw new BrowserReferenceError(field.ref, pattern, `Could not inspect this batch target. ${BATCH_CHECK_NO_CHANGE_TEXT}`);
  const blocked = BLOCKED_BATCH_STATES.find(state => probe.state[state]);
  if (blocked) throw new BrowserReferenceError(field.ref, pattern, `Batch target is ${blocked}. Inspect the current controls before editing. ${BATCH_CHECK_NO_CHANGE_TEXT}`);
  if (step.action === 'fill_form' || ['fill', 'select'].includes(step.op)) {
    if (step.op === 'select') assertSelectControl(probe.fill, field.ref, pattern);
    assertFillControl(probe.fill, field, pattern, privateCredentials, BATCH_CHECK_NO_CHANGE_TEXT);
  }
}

/** Once any write starts, later errors may describe partial work and must stop the job. */
export function formFillFailure(error, started) {
  if (started && error instanceof BrowserReferenceError) {
    error = new Error(error.message.replace(FILL_NO_CHANGE_TEXT, 'Earlier fields may have changed.'));
  }
  if (started) error.message += ' Form filling stopped; inspect current values before continuing. Do not repeat the batch.';
  return error;
}

/** Read-only recovery supplies fresh refs, never retries the failed mutation. */
export async function recoverBrowserReference(error, snapshot) {
  if (error instanceof BrowserReferenceError) {
    try { error.message += `\nFresh snapshot:\n${await snapshot()}`; error.preserveRefs = true; }
    catch { error.message += '\nRead browser snapshot before another interaction.'; }
  }
  throw error;
}

/** A snapshot failure must not turn an already completed action into a retry. */
export async function withBrowserSnapshot(receipt, snapshot) {
  try { return `${receipt}\nCurrent snapshot:\n${await snapshot()}`; }
  catch { return `${receipt}\nSnapshot unavailable. The action completed; do not repeat it. Read browser snapshot to inspect the result.`; }
}
