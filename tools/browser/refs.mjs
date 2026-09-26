// Character/node budgets keep snapshots within the tool-result context budget.
export const SNAPSHOT_LIMITS = Object.freeze({ characters: 16_000, elements: 160, label: 160, frames: 16, url: 500 });
// Milliseconds: preserve Playwright auto-waiting while bounding each interaction.
export const BROWSER_ACTION_TIMEOUT_MS = 7000;
// Maximum controls per form call: bound partial work and keep one snapshot readable.
export const MAX_BROWSER_FORM_FIELDS = 10;
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
  constructor(ref, pattern) {
    super(`${pattern.test(ref) ? 'Stale ref; the target changed or belongs to another snapshot.' : 'Unknown browser ref.'} ${REF_GUIDANCE}`);
    this.name = 'BrowserReferenceError';
    this.preserveRefs = false;
  }
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
