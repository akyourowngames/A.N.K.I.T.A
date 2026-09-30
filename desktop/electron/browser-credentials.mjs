import { credentialOrigin, credentialFields, CREDENTIAL_WAIT_MS, CREDENTIAL_SELECTION_MESSAGE } from '../../src/integrations/browser-credentials.mjs';
const RETRY_MESSAGE = 'The selected credential controls changed or could not be filled. Inspect the fresh snapshot and choose their refs again; do not claim sign-in succeeded.';
const CANCEL_MESSAGE = 'Sign-in cancelled. No further login attempts were made.';
const PROMPT_MESSAGE = 'Enter credentials in the secure dialog, or take control to sign in manually.';
const SAVE_FAILURE_MESSAGE = 'Credentials could not be saved. Retry to sign in without saving, or take control. Your password was not filled.';
export class BrowserCredentials {
  constructor({ store, requests, emit }) { this.store = store; this.requests = requests; this.emit = emit; this.pending = new Map(); }
  clear(threadId) {
    for (const [key, entry] of this.pending) if (!threadId || entry.threadId === threadId) {
      this.pending.delete(key); clearTimeout(entry.timer);
      entry.signal?.removeEventListener('abort', entry.cancel);
      entry.value.password = '';
    }
  }
  async login(adapter, args, ctx) {
    if (ctx.browserCredentialAllowed !== true) throw new Error('Secure sign-in is available only in the desktop app. Open the desktop browser and sign in manually. Never send passwords in chat.');
    const website = credentialOrigin(args.website || args.url);
    let fields, invalidSelection = false;
    try { fields = credentialFields(args.credential_fields); }
    catch { invalidSelection = true; }
    const detail = { threadId: ctx.browserThreadId, callId: ctx.browserCallId, website, username: String(args.username || '') };
    const status = (state, message = '') => this.emit({ type: 'secure-store-status', ...detail, state, message });
    const receipt = (state, message) => { status(state, message); return { type: 'browser_login', website, username: detail.username, status: state, message }; };
    // Origin/tab preparation does not classify forms or select controls. The
    // model requests the dialog and supplies refs from its observed snapshot.
    const plan = await adapter.prepareCredentials(args, ctx);
    if (invalidSelection) return { ...receipt('attention', CREDENTIAL_SELECTION_MESSAGE), snapshot: await adapter.credentialSnapshot(plan, ctx) }; // Rejected schema selections have no credential side effect; let the model correct them.
    const key = JSON.stringify([ctx.browserThreadId, website, plan.tab]);
    let entry = this.pending.get(key);
    if (entry && (entry.page !== plan.page || (args.username && entry.value.username !== args.username))) { this.clear(ctx.browserThreadId); entry = null; }
    let saveAllowed = true, nextMessage = '';
    let value = entry?.value;
    if (!value) {
      try { await this.store.withCredentials({ website, username: args.username }, saved => { value = { username: saved.username, password: saved.password }; }); }
      catch { /* Locked, unavailable or damaged records require user input. */ }
    }
    if (!value && ctx.backgroundJob) throw Object.assign(new Error('Background login needs a saved credential. Open desktop and sign in first; no password dialog was opened.'), { jobStatus: 'skipped-needs-foreground' });
    while (!value && !ctx.signal?.aborted) {
      const message = nextMessage || PROMPT_MESSAGE;
      nextMessage = '';
      status('prompt', message);
      const response = await this.requests.request({ ...detail, canSave: saveAllowed && await this.store.available(), message }, ctx.signal);
      if (response.action === 'cancel') return receipt('cancelled', CANCEL_MESSAGE);
      if (response.action === 'takeover') {
        status('takeover', 'Complete sign-in in the browser, then hand control back.');
        await ctx.credentialTakeover?.();
        if (ctx.signal?.aborted) return receipt('cancelled', CANCEL_MESSAGE);
        return { ...receipt('filled', 'Control returned. Inspect the page to confirm sign-in and continue the original task.'), snapshot: await adapter.credentialSnapshot(plan, ctx) };
      }
      try {
        ctx.signal?.throwIfAborted();
        if (ctx.credentialEnabled?.() === false) return receipt('cancelled', 'The Playwright plugin was disabled. Nothing was filled.');
        if (response.save) {
          try { await this.store.save({ website, username: response.username, password: response.password }); }
          catch { saveAllowed = false; nextMessage = SAVE_FAILURE_MESSAGE; continue; }
          this.emit({ type: 'secure-store-changed' });
        }
        value = { username: response.username, password: response.password };
      } finally { response.password = ''; }
    }
    if (!value || ctx.signal?.aborted) { if (value) value.password = ''; return receipt('cancelled', CANCEL_MESSAGE); }
    if (!entry) {
      const signal = ctx.credentialTurnSignal || ctx.signal;
      entry = { value, page: plan.page, threadId: ctx.browserThreadId, signal };
      entry.cancel = () => this.clear(ctx.browserThreadId);
      entry.timer = setTimeout(entry.cancel, CREDENTIAL_WAIT_MS); entry.timer.unref?.();
      signal?.addEventListener('abort', entry.cancel, { once: true });
      this.pending.set(key, entry);
    }
    detail.username = value.username;
    if (!fields.length) return { ...receipt('available', 'Credentials are available privately. Choose username/password refs from this snapshot, call browser login with credential_fields and optional submit_ref, then inspect the result and continue. No fields have been filled.'), snapshot: await adapter.credentialSnapshot(plan, ctx) };
    status('working', 'Filling selected controls');
    try {
      // All targets are validated before the adapter receives any field value.
      const snapshot = await adapter.fillCredentials(plan, args, value, { ...ctx, onCredentialUsed: () => this.clear(ctx.browserThreadId) });
      if (fields.some(field => field.credential === 'password')) this.clear(ctx.browserThreadId);
      return { ...receipt('filled', 'Selected controls filled. Inspect this snapshot to decide the next step and confirm sign-in; continue the original task.'), snapshot };
    } catch {
      // Never return an adapter error that might quote an input value. One
      // failed selection returns control to the model, without a prompt loop.
      return { ...receipt('attention', RETRY_MESSAGE), snapshot: await adapter.credentialSnapshot(plan, ctx).catch(() => '') };
    }
  }
}
