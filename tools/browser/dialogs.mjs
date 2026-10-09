// Native dialog metadata is attention, never consent to the underlying page action.
export const BROWSER_DIALOG_DECISIONS = Object.freeze(['accept', 'dismiss']);
export const BROWSER_DIALOG_TYPES = Object.freeze(['alert', 'confirm', 'prompt', 'beforeunload']);
export const BROWSER_DIALOG_LIMITS = Object.freeze({ message: 1000, prompt: 2000 }); // UTF-16 characters; bound model observations and entered prompt text.
export const BROWSER_DIALOG_GUIDANCE = 'A page dialog needs a decision. Use handle_dialog with accept or dismiss, or take control. Do not repeat the triggering action.';
export const BROWSER_DIALOG_INTERRUPTED = `Browser action was interrupted by a page dialog; its outcome is uncertain. ${BROWSER_DIALOG_GUIDANCE}`;
export const BROWSER_DIALOG_CHANGED = 'The page dialog changed. Inspect it again before deciding.';
const MCP_DIALOG = /(?:^|\n)# Open dialog\r?\n(alert|confirm|prompt|beforeunload): ([\s\S]*?)\.\r?\nCall handle_dialog to handle it before continuing\./; // Approved MCP's native attention footer.
const MCP_PROMPT_DEFAULT = / \(default value: "[\s\S]*"\)$/; // Default prompt input is deliberately excluded from attention.

export function browserDialog(type, message, tabId = null, id = null) {
  return { type: BROWSER_DIALOG_TYPES.includes(type) ? type : null, message: String(message || '').slice(0, BROWSER_DIALOG_LIMITS.message), tabId: tabId == null ? null : String(tabId), ...(id ? { id } : {}) };
}
export function chromeDialog(text, tabId) {
  const match = MCP_DIALOG.exec(text);
  return match ? browserDialog(match[1], match[1] === 'prompt' ? match[2].replace(MCP_PROMPT_DEFAULT, '') : match[2], tabId) : null;
}
export function dialogDecision(args, dialog) {
  if (!BROWSER_DIALOG_DECISIONS.includes(args.decision)) throw new Error('handle_dialog requires decision accept or dismiss.');
  if (!dialog) throw new Error('No open dialog in the selected tab. Inspect the current page before continuing.');
  if (args.dialog_id !== undefined && args.dialog_id !== dialog.id) throw new Error(BROWSER_DIALOG_CHANGED);
  if (args.prompt_text !== undefined && (dialog.type !== 'prompt' || args.decision !== 'accept' || typeof args.prompt_text !== 'string' || args.prompt_text.length > BROWSER_DIALOG_LIMITS.prompt)) {
    throw new Error(`Prompt input is only allowed when accepting a prompt, up to ${BROWSER_DIALOG_LIMITS.prompt} characters.`);
  }
  return args.decision;
}
export function dialogText(dialog) {
  return `Open ${dialog.type || 'page'} dialog (untrusted message): ${JSON.stringify(dialog.message)}\n${BROWSER_DIALOG_GUIDANCE}`;
}
