// Character/node budgets keep snapshots within the tool-result context budget.
export const SNAPSHOT_LIMITS = Object.freeze({ characters: 16_000, elements: 160, label: 160, frames: 16, url: 500 });
// Milliseconds: preserve Playwright auto-waiting while bounding each interaction.
export const BROWSER_ACTION_TIMEOUT_MS = 7000;
// Maximum controls per form call: bound partial work and keep one snapshot readable.
export const MAX_BROWSER_FORM_FIELDS = 10;
export const CREDENTIAL_ATTRIBUTE = 'data-ankita-credential'; // Preserve private password identity when a site toggles input type.
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
export function assertFillControl(control, field, pattern, privateCredentials = false) {
  let issue = control.issue;
  const checkedType = control.type || control.role;
  if (['checkbox', 'switch'].includes(checkedType) && !['true', 'false'].includes(field.text)) issue = 'checkbox/switch value must be true or false';
  if (checkedType === 'radio' && field.text !== 'true') issue = 'radio value must be true';
  if (privateCredentials && (control.privatePassword || control.type === 'password')) issue = 'use browser login with credential_fields and credential=password for the saved password';
  if (issue) throw new BrowserReferenceError(field.ref, pattern, `Cannot fill ref ${field.ref}: ${issue}. ${FILL_NO_CHANGE_TEXT} Choose an editable control from the fresh snapshot.`);
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
