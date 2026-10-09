import fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { CONFIG_DIR } from '../../src/core/config.mjs';
import { allowPrivateHosts, checkUrlPublic } from '../shared/_web.mjs';
import { BROWSER_ACTION_TIMEOUT_MS, BrowserReferenceError, CREDENTIAL_ATTRIBUTE, INTERACTIVE_ROLES, ISOLATED_REF_PATTERN, SNAPSHOT_LIMITS, SNAPSHOT_CONTEXT_CHARACTERS, SNAPSHOT_LIMIT_REACHED, assertFillControl, assertSelectControl, browserFields, browserRefMatches, browserScrollDelta, formFillFailure, inspectFillControl, recoverBrowserReference, withBrowserSnapshot } from './refs.mjs';
import { BROWSER_SCREENSHOT_DIRECTORY, BROWSER_SCREENSHOT_TYPE } from './screenshots.mjs';
import { credentialOrigin, credentialPage, credentialFields } from '../../src/integrations/browser-credentials.mjs';
import { JobNetworkGuard } from './job-network-guard.mjs';
import { executeBrowserOperation, formatBrowserResult } from './contracts.mjs';
import { createBrowserObservation, textObservation, TEXT_BROWSER_CAPABILITIES } from './observations.mjs';
import { extractPageText, pageTextResult, pageTextCaptureOptions, PAGE_TEXT_LIMITS } from './page-find.mjs';
import { BROWSER_GROUP_SELECTOR } from './refs.mjs';
import { inspectBrowserControls, BROWSER_REF_ATTRIBUTE, BROWSER_CONTROL_FLAGS, BROWSER_CONTROL_PREFIX, inspectBatchTarget, assertBatchTarget } from './refs.mjs';
import { captureSequenceGuard, validateSequence, SEQUENCE_FIELD_OPS, SEQUENCE_CHANGED, SEQUENCE_CONTROL_SELECTOR, SEQUENCE_GUARD_NODE_LIMIT, SEQUENCE_GUARD_LIMIT_REACHED } from './sequence.mjs';
import { BROWSER_NAVIGATION_ACTIONS, unknownBrowserAction, deferBatchSnapshot } from './operations.mjs';
import { browserDialog, dialogDecision, dialogText, BROWSER_DIALOG_GUIDANCE, BROWSER_DIALOG_INTERRUPTED } from './dialogs.mjs';
import { BrowserDownloads, selectedBrowserUpload, BROWSER_TRANSFER_ACTIONS } from './transfers.mjs';

// ARIA interaction roles: custom booking forms often use div-based comboboxes/options.
const ELEMENTS = ['a', 'button', 'summary', 'input', 'textarea', 'select', '[contenteditable="true"]', '[tabindex]', ...INTERACTIVE_ROLES.map(role => `[role="${role}"]`)].join(',');
const TEXT_ELEMENTS = 'h1,h2,h3,p,[role="status"],[role="alert"]';
// Fixed capture viewport (px): takeover input bounds derive from this.
const VIEWPORT = { width: 1280, height: 800 };
// Captures kept per workspace; older browser-*.png files beyond this are pruned.
const MAX_KEPT_SCREENSHOTS = 50;
const LOGIN_VERIFY_MS = 8000; // Milliseconds to observe a positive signed-in control after one submission.
const LOGIN_SUBMIT_NAME = /^(?:sign\s*in|log\s*in|login|continue|submit)$/i; // Only within a uniquely bound credential group.
const LOGIN_USERNAME_SELECTOR = 'input:not([type]),input[type="text"],input[type="email"],input[type="tel"]'; // Supported account controls.
const LOGIN_SCOPE_ATTRIBUTE = 'data-ankita-login-scope'; // Transient DOM binding; never a credential value.
const PAGE_RENDER_TIMEOUT_MS = 10_000; // Milliseconds: only wait when navigation returned an empty document.
const HTTP_ERROR_STATUS = 400; // HTTP client/server error boundary; goto alone does not reject these responses.
const NAVIGATION_TIMEOUT_MS = 20_000; // Milliseconds for foreground document navigation; scheduler owns job deadlines.
const SIGNED_IN_NAME = /\b(?:sign\s*out|log\s*out|logout)\b/i; // Positive evidence; disappearance of a password field is insufficient.
const SECURE_SUBMIT_GUARD = '__ankitaSecureSubmitGuard'; // Transient listener ownership on the bound form; never a credential value.
const JOB_DEBUG_ARGUMENT = '--remote-debugging-port=0'; // Own isolated Chromium picks a free local guard port.
const JOB_DEBUG_FILE = 'DevToolsActivePort'; // Chromium writes its discovered port and browser socket here.
const JOB_DEBUG_HOST = '127.0.0.1'; // Loopback-only job guard; never a user Chrome connection.
const UPLOAD_BINARY_MIME = 'application/octet-stream'; // Browser receives selected bytes without content inference or an extra model call.

function siteMatch(host, rule) {
  const clean = rule.trim().toLowerCase().replace(/^\*\./, '');
  return clean && (host === clean || host.endsWith(`.${clean}`));
}

export async function guardBrowserUrl(input, ctx = {}, navigation = true) {
  let url;
  try { url = new URL(String(input || '')); } catch { throw new Error('Enter a valid HTTP or HTTPS URL'); }
  if (!['http:', 'https:'].includes(url.protocol)) throw new Error('Only HTTP and HTTPS URLs can open in the browser');
  const host = url.hostname.toLowerCase();
  if (navigation) {
    await ctx.authorizeNavigation?.(url.href);
    const blocked = String(process.env.BROWSER_BLOCKLIST || '').split(',').filter(Boolean);
    const allowed = String(process.env.BROWSER_ALLOWLIST || '').split(',').filter(Boolean);
    blocked.push(...(ctx.settings?.blockedSites || []));
    const pluginAllowed = ctx.settings?.allowedSites || [];
    if (blocked.some(rule => siteMatch(host, rule))) throw new Error(`Site ${host} is blocked by a browser site rule`);
    if (allowed.length && !allowed.some(rule => siteMatch(host, rule))) throw new Error(`Site ${host} is outside BROWSER_ALLOWLIST`);
    if (pluginAllowed.length && !pluginAllowed.some(rule => siteMatch(host, rule))) throw new Error(`Site ${host} is outside this browser's allowed sites`);
  }
  const refusal = await checkUrlPublic(url.href, undefined, { allowPrivate: allowPrivateHosts(ctx) });
  if (refusal) throw new Error(refusal.replace(/^ERROR:\s*/, ''));
  return url.href;
}

/**
 * Unique capture path inside <cwd>/downloaded-images. The random suffix keeps
 * batch steps and parallel managers from colliding within the same
 * millisecond, and old captures beyond MAX_KEPT_SCREENSHOTS are pruned so the
 * folder does not grow forever. Only our own browser-*.png files are touched.
 */
export function screenshotFile(cwd) {
  const folder = path.join(cwd || process.cwd(), BROWSER_SCREENSHOT_DIRECTORY);
  fs.mkdirSync(folder, { recursive: true });
  try {
    const kept = fs.readdirSync(folder)
      .filter(name => /^browser-.*\.png$/.test(name))
      .map(name => ({ name, at: fs.statSync(path.join(folder, name)).mtimeMs }))
      .sort((a, b) => b.at - a.at);
    for (const stale of kept.slice(MAX_KEPT_SCREENSHOTS)) fs.rmSync(path.join(folder, stale.name), { force: true });
  } catch {}
  return path.join(folder, `browser-${Date.now()}-${randomUUID().slice(0, 8)}.png`);
}

export class PlaywrightBrowserAdapter {
  constructor({ profile = path.join(CONFIG_DIR, 'browser', 'playwright'), renderTimeoutMs = PAGE_RENDER_TIMEOUT_MS } = {}) {
    this.profile = profile;
    this.context = null;
    this.page = null;
    this.ids = new WeakMap();
    this.nextTab = 1;
    this.snapshotId = 0;
    this.refState = null;
    this.refIdentityKey = randomUUID(); // Per-adapter DOM symbol: node identity does not survive cloneNode or document replacement.
    this.checkedHosts = new Map();
    this.policyContext = null;
    this.policyKey = '';
    this.previewPending = null;
    this.renderTimeoutMs = renderTimeoutMs;
    this.pageErrors = new WeakMap();
    this.documents = new WeakMap();
    this.frameIds = new WeakMap();
    this.dialogs = new WeakMap(); // Native dialogs stay bound to their owned page, including during tab changes.
    this.dialogIds = new WeakMap(); // Native event identities prevent manual decisions from targeting replacement dialogs.
    this.downloads = new BrowserDownloads();
    this.acceptDownloads = false;
  }

  async #start(ctx) {
    ctx.signal?.throwIfAborted();
    await this.closePending;
    ctx.signal?.throwIfAborted();
    if (this.context) return;
    let chromium;
    try { ({ chromium } = await import('playwright')); }
    catch { throw new Error('Playwright is missing. Open Plugins → By Ankita to install it.'); }
    ctx.signal?.throwIfAborted();
    // Pre-flight the binary before launching: a missing download gets the
    // install remedy, while a present-but-broken binary keeps the launch error.
    if (!fs.existsSync(chromium.executablePath())) {
      throw new Error(`Chromium is not downloaded (missing ${chromium.executablePath()}). In the desktop app open Plugins → By Ankita to download it, or run \`npx playwright install chromium\`.`);
    }
    try {
      this.context = await chromium.launchPersistentContext(this.profile, {
        headless: ctx.settings.headless !== false,
        viewport: { ...VIEWPORT },
        acceptDownloads: ctx.config?.browserRuntimeV2 === true,
        serviceWorkers: 'block',
        ...(ctx.backgroundJob ? { args: [JOB_DEBUG_ARGUMENT] } : {}),
        timeout: 15_000,
      });
    } catch (error) {
      throw new Error(`Chromium could not start: ${error.message}. Open Plugins → By Ankita to download Chromium.`);
    }
    this.acceptDownloads = ctx.config?.browserRuntimeV2 === true;
    if (ctx.signal?.aborted) { await this.close(); ctx.signal.throwIfAborted(); }
    if (ctx.backgroundJob) {
      const [port, socketPath] = fs.readFileSync(path.join(this.profile, JOB_DEBUG_FILE), 'utf8').trim().split(/\r?\n/);
      if (!Number.isInteger(Number(port)) || Number(port) <= 0 || !socketPath?.startsWith('/devtools/browser/')) throw new Error('Isolated browser did not expose its job guard endpoint');
      this.jobGuard = new JobNetworkGuard(`ws://${JOB_DEBUG_HOST}:${port}${socketPath}`, async event => {
        const policy = this.policyContext || ctx;
        try {
          if (policy.signal?.aborted) throw new Error('Job stopped');
          if (['XHR', 'Fetch'].includes(event.resourceType)) await policy.authorizeRequest?.({ url: event.request.url, method: event.request.method });
          if (/^https?:/i.test(event.request.url)) await guardBrowserUrl(event.request.url, policy, event.resourceType === 'Document');
        } catch (error) { policy.onBrowserError?.(error); throw error; }
      }, error => { (this.policyContext || ctx).onBrowserError?.(error); void this.close().catch(() => {}); });
      await this.jobGuard.start();
    } else await this.context.route('**/*', async route => {
      const request = route.request();
      try {
        const url = request.url();
        if (!/^https?:/i.test(url)) return route.continue();
        const host = new URL(url).hostname;
        const policy = this.policyContext || ctx;
        const key = `${host}:${allowPrivateHosts(policy)}:${request.isNavigationRequest()}`;
        const cached = this.checkedHosts.get(key);
        // Job permissions apply to every navigation path and redirect, even on a cached host.
        if (request.isNavigationRequest() && policy.authorizeNavigation) await policy.authorizeNavigation(url);
        if (!cached || cached < Date.now()) {
          await guardBrowserUrl(url, policy, request.isNavigationRequest());
          this.checkedHosts.set(key, Date.now() + 30_000);
        }
        return route.continue();
      } catch { return route.abort('blockedbyclient'); }
    });
    for (const page of this.context.pages()) this.#register(page);
    this.context.on('page', page => this.#register(page));
  }

  #register(page) {
    if (this.ids.has(page)) return;
    this.ids.set(page, String(this.nextTab++));
    page.on('download', download => { if (this.acceptDownloads) this.downloads.capture(download, this.ids.get(page)); });
    page.on('dialog', dialog => {
      if (this.policyContext?.config?.browserRuntimeV2 !== true) { void dialog.dismiss().catch(() => {}); return; }
      this.dialogs.set(page, dialog);
      this.dialogIds.set(dialog, randomUUID());
      this.invalidate();
    });
    page.on('response', response => {
      if (response.request().isNavigationRequest() && response.frame() === page.mainFrame()) {
        if (response.status() >= HTTP_ERROR_STATUS) {
          const error = new Error(`Navigation refused: HTTP ${response.status()}. The site did not accept this browser request. Use Chrome local or take control; do not keep taking snapshots of the empty page.`);
          this.pageErrors.set(page, { url: response.url(), error, status: response.status() });
        } else this.pageErrors.delete(page);
      }
    });
    page.on('framenavigated', frame => { this.documents.set(frame, randomUUID()); if (frame === page.mainFrame() || [...(this.refState?.refs?.values() || [])].some(entry => entry.frame === frame)) this.invalidate(); });
    page.on('close', () => { if (this.page === page) this.page = this.context?.pages().find(p => !p.isClosed()) || null; this.invalidate(); });
  }

  #findTarget(tab) {
    const pages = this.context?.pages().filter(page => !page.isClosed()) || [];
    const found = tab ? pages.find(page => this.ids.get(page) === String(tab)) : this.page || pages[0];
    if (!found) throw new Error(tab ? `Tab ${tab} is closed` : 'No browser tab is open');
    return found;
  }

  #target(tab) { const found = this.#findTarget(tab); if (found !== this.page) this.invalidate(); this.page = found; return found; }

  async tabs() {
    return Promise.all((this.context?.pages() || []).filter(page => !page.isClosed()).map(async page => ({
      id: this.ids.get(page), url: page.url().slice(0, 500), title: this.dialogs.has(page) ? '' : (await page.title().catch(() => '')).slice(0, 160), active: page === this.page,
    })));
  }

  attention() {
    const dialog = this.page && this.dialogs.get(this.page);
    return dialog ? { dialog: browserDialog(dialog.type(), dialog.message(), this.ids.get(this.page), this.dialogIds.get(dialog)) } : null;
  }

  async #awaitAction(page, work) {
    if (this.policyContext?.config?.browserRuntimeV2 !== true) return work(); // Compatibility retains native automatic dismissal.
    if (this.dialogs.has(page)) throw new Error(BROWSER_DIALOG_GUIDANCE);
    let listener;
    const interruption = new Promise((_, reject) => { listener = () => reject(new Error(BROWSER_DIALOG_INTERRUPTED)); page.once('dialog', listener); });
    try { return await Promise.race([Promise.resolve().then(work), interruption]); }
    finally { page.off('dialog', listener); }
  }

  async #handleDialog(page, args, ctx) {
    if (ctx.config?.browserRuntimeV2 !== true) throw new Error('Explicit dialogs require the experimental runtime. Use take control.');
    const native = this.dialogs.get(page);
    const metadata = native && browserDialog(native.type(), native.message(), this.ids.get(page), this.dialogIds.get(native));
    const decision = dialogDecision(args, metadata);
    ctx.onBrowserDispatch?.({ phase: 'start', action: args.action });
    await (decision === 'accept' ? native.accept(args.prompt_text) : native.dismiss());
    if (this.dialogs.get(page) === native) this.dialogs.delete(page);
    ctx.onBrowserDispatch?.({ phase: 'complete', action: args.action });
    this.invalidate();
    return withBrowserSnapshot(`Dialog ${decision} completed. Read back the page outcome before continuing.`, () => this.#snapshot(page, false));
  }

  async #upload(page, args, ctx) {
    const entry = this.refState?.page === page && this.refState.refs.get(args.ref);
    const locator = await this.#resolveRef(page, String(args.ref || ''));
    const handle = await locator.elementHandle();
    const valid = node => node?.isConnected && node.tagName === 'INPUT' && node.type === 'file' && !node.disabled && !node.closest('[inert]');
    try {
      if (!handle || !await handle.evaluate(valid)) throw new Error('Upload requires an enabled file input from the current snapshot.');
      const file = await selectedBrowserUpload(args, ctx);
      ctx.signal?.throwIfAborted();
      if (this.page !== page || page.isClosed() || !entry || entry.documentId !== this.documents.get(entry.frame) || !await handle.evaluate(valid)) throw new Error('Browser target changed during file selection. Take a fresh snapshot before uploading.');
      ctx.onBrowserDispatch?.({ phase: 'start', action: 'upload' });
      await this.#awaitAction(page, async () => {
        await handle.setInputFiles({ name: file.name, mimeType: UPLOAD_BINARY_MIME, buffer: file.buffer });
        const selected = await handle.evaluate(node => [...node.files].map(file => ({ name: file.name, size: file.size })));
        if (selected.length !== 1 || selected[0].name !== file.name || selected[0].size !== file.bytes) throw new Error('The page did not confirm the selected file. Inspect it before retrying.');
      });
      ctx.onBrowserDispatch?.({ phase: 'complete', action: 'upload' });
      this.invalidate();
      return withBrowserSnapshot(`Selected ${JSON.stringify(file.name)} (${file.bytes} bytes). Verify any server submission separately.`, () => this.#snapshot(page, false));
    } finally { await handle?.dispose().catch(() => {}); }
  }

  async selectTab(tab) { const page = this.#target(tab); await page.bringToFront(); this.invalidate(); }

  #policy(ctx) {
    if (ctx.credentialSettings) ctx = { ...ctx, settings: ctx.credentialSettings() };
    const policyKey = JSON.stringify([ctx.settings?.allowedSites, ctx.settings?.blockedSites, allowPrivateHosts(ctx)]);
    if (policyKey !== this.policyKey) { this.checkedHosts.clear(); this.policyKey = policyKey; }
    this.policyContext = ctx;
    return ctx;
  }

  async #rendered(page, wait = false) {
    const previous = this.pageErrors.get(page);
    if (previous?.url === page.url() && previous.status >= HTTP_ERROR_STATUS) throw previous.error;
    const hasContent = () => {
      const visible = node => { const rect = node.getBoundingClientRect(); const style = getComputedStyle(node); return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none'; };
      return Boolean(document.body?.innerText.trim()) || [...document.querySelectorAll('input:not([type="hidden"]),button,select,textarea,img,canvas,svg,video,iframe')].some(visible);
    };
    if (await page.evaluate(hasContent)) { this.pageErrors.delete(page); return; }
    if (previous?.url === page.url()) throw previous.error;
    if (wait) {
      try { await page.waitForFunction(hasContent, null, { timeout: this.renderTimeoutMs }); return; }
      catch { /* Keep a typed load failure across snapshots and preview ticks. */ }
    }
    const error = new Error('Navigation failed: this page did not render any visible content. It may be blocked or its scripts failed. Use Chrome local or take control instead of repeating snapshots.');
    this.pageErrors.set(page, { url: page.url(), error });
    throw error;
  }

  async prepareCredentials(args, ctx) {
    ctx = this.#policy(ctx);
    const website = credentialOrigin(args.website || args.url);
    let page = this.context && this.#target(args.tab);
    if (!page || page.url() === 'about:blank') {
      await this.run({ action: 'open', url: credentialPage(args.website || args.url) }, ctx);
      page = this.#target();
    }
    await guardBrowserUrl(page.url(), ctx);
    if (credentialOrigin(page.url()) !== website) throw new Error('Login origin changed. Open the requested origin before requesting credentials.');
    return { page, website, tab: String(this.ids.get(page)) };
  }

  async credentialSnapshot(plan, ctx) {
    ctx.signal?.throwIfAborted();
    await guardBrowserUrl(plan.page.url(), this.#policy(ctx));
    return this.#snapshot(plan.page, false);
  }

  async fillCredentials(plan, args, value, ctx) {
    const fields = credentialFields(args.credential_fields);
    if (!fields.length) throw new Error('Select credential refs before filling');
    const { page, website } = plan, handles = [], frames = new Set();
    let submit;
    const check = async () => {
      ctx.signal?.throwIfAborted();
      if (ctx.credentialEnabled?.() === false) throw new Error('Playwright was disabled');
      await guardBrowserUrl(page.url(), this.#policy(ctx));
      if (credentialOrigin(page.url()) !== website) throw new Error('Login origin changed');
      for (const [index, handle] of handles.entries()) {
        const credential = fields[index].credential;
        if (!await handle.evaluate((node, { origin, credential }) => node.isConnected && location.origin === origin && node.tagName === 'INPUT' && !node.disabled && !node.readOnly && (credential === 'password' ? node.type === 'password' : ['text', 'email', 'tel'].includes(node.type)) && (!node.form || new URL(node.form.action || location.href, location.href).origin === origin), { origin: website, credential })) throw new Error('Selected credential control is unsafe or changed');
      }
      if (submit && !await submit.evaluate((node, origin) => node.isConnected && location.origin === origin && new URL(node.hasAttribute('formaction') ? node.formAction : node.form?.action || location.href, location.href).origin === origin, website)) throw new Error('Selected submit origin changed');
    };
    try {
      // Resolve every target before exposing values; bind nodes, never a
      // locator that could silently follow navigation to a replacement page.
      for (const field of fields) {
        const locator = await this.#resolveRef(page, String(field.ref || ''));
        if (!await locator.isVisible()) throw new Error('Selected credential control is not visible');
        const handle = await locator.elementHandle();
        if (!handle) throw new Error('Selected control changed');
        handles.push(handle); frames.add(await handle.ownerFrame());
      }
      if (args.submit_ref) submit = await (await this.#resolveRef(page, args.submit_ref)).elementHandle();
      await check();
      for (const frame of frames) await frame.evaluate(({ attribute, key, origin }) => {
        if (document[key]) return;
        document[key] = event => {
          const form = event.target;
          if (!form.querySelector(`[${attribute}="password"]`)) return;
          const button = event.submitter;
          const method = button?.hasAttribute('formmethod') ? button.formMethod : form.method;
          const action = button?.hasAttribute('formaction') ? button.formAction : form.action;
          if (method.toLowerCase() !== 'post' || location.origin !== origin || new URL(action || location.href, location.href).origin !== origin) event.preventDefault();
        };
        // Keep this guard for a later model click/Enter as well as this call.
        document.addEventListener('submit', document[key], true);
      }, { attribute: CREDENTIAL_ATTRIBUTE, key: SECURE_SUBMIT_GUARD, origin: website });
      for (const [index, handle] of handles.entries()) {
        await check();
        const credential = fields[index].credential;
        await handle.evaluate((node, { attribute, credential }) => node.setAttribute(attribute, credential), { attribute: CREDENTIAL_ATTRIBUTE, credential });
        await handle.fill(value[credential], { timeout: BROWSER_ACTION_TIMEOUT_MS });
        if (credential === 'password') ctx.onCredentialUsed?.();
      }
      await check();
      if (submit) await submit.click({ timeout: BROWSER_ACTION_TIMEOUT_MS });
      this.refState = null;
      return await this.credentialSnapshot(plan, ctx);
    } finally { await Promise.all([...handles, submit].filter(Boolean).map(handle => handle.dispose().catch(() => {}))); }
  }

  async prepareLogin(args, ctx) {
    ctx = this.#policy(ctx);
    const website = credentialOrigin(args.website || args.url);
    let page = this.context && this.#target(args.tab);
    if (!page || new URL(page.url()).origin !== website) {
      const url = await guardBrowserUrl(credentialPage(args.website || args.url), ctx);
      if (credentialOrigin(url) !== website) throw new Error('Login origin changed');
      await this.run({ action: 'open', url }, ctx);
      page = this.#target();
    }
    await guardBrowserUrl(page.url(), ctx);
    await this.#rendered(page, true);
    if (await this.verifyLogin({ page, website }, ctx, false)) return { page, website, authenticated: true };
    await this.#snapshot(page, false);
    const password = page.locator('input[type="password"]:visible');
    if (await password.count() !== 1 || await password.getAttribute('autocomplete') === 'new-password') throw new Error('An unambiguous login form is required');
    let scope = password.locator('xpath=ancestor::form[1]');
    const nativeForm = await scope.count() === 1;
    if (!nativeForm) {
      // JavaScript login widgets need not use <form>. Bind the smallest local
      // container with one account field, password and sign-in/Submit button.
      scope = password.locator('..');
      while (!['BODY', 'HTML'].includes(await scope.evaluate(node => node.tagName))) {
        if (await scope.locator(LOGIN_USERNAME_SELECTOR).filter({ visible: true }).count() === 1 && await scope.getByRole('button', { name: LOGIN_SUBMIT_NAME }).filter({ visible: true }).count() === 1) break;
        scope = scope.locator('..');
      }
      if (['BODY', 'HTML'].includes(await scope.evaluate(node => node.tagName))) throw new Error('An unambiguous local login group is required');
    } else if (!await scope.evaluate((element, origin) => new URL(element.action || location.href, location.href).origin === origin, website)) throw new Error('Login form must submit to this origin');
    const username = scope.locator(LOGIN_USERNAME_SELECTOR).filter({ visible: true });
    const submit = scope.getByRole('button', { name: LOGIN_SUBMIT_NAME }).filter({ visible: true });
    if (await username.count() !== 1 || await submit.count() !== 1) throw new Error('An unambiguous username and sign-in button are required');
    if (!await submit.evaluate((button, origin) => new URL(button.hasAttribute('formaction') ? button.formAction : button.form?.action || location.href, location.href).origin === origin, website)) throw new Error('Sign-in button must submit to this origin');
    const scopeId = randomUUID();
    await scope.evaluate((node, { attribute, id }) => node.setAttribute(attribute, id), { attribute: LOGIN_SCOPE_ATTRIBUTE, id: scopeId });
    const ref = control => control.getAttribute('data-ankita-ref');
    return { page, website, scopeId, nativeForm, username: await ref(username), password: await ref(password), submit: await ref(submit) };
  }

  async login(plan, value, ctx) {
    if (plan.authenticated) return true;
    const { page, website } = plan;
    const controls = [];
    let scope;
    try {
      // Bind actual nodes before filling: a navigation cannot re-resolve a
      // locator in a replacement document and send it the password.
      for (const ref of [plan.username, plan.password, plan.submit]) controls.push(await (await this.#resolveRef(page, ref)).elementHandle());
      scope = await page.locator(`[${LOGIN_SCOPE_ATTRIBUTE}="${plan.scopeId}"]`).elementHandle();
      if (!scope) throw new Error('Login group changed');
      await scope.evaluate((form, { origin, key }) => {
        const guard = event => {
          // SPA handlers still run, but native GET submission must never put
          // a password in the URL, tab metadata, history or server query logs.
          const button = event.submitter;
          const target = event.target;
          const method = button?.hasAttribute('formmethod') ? button.formMethod : target.method;
          const action = button?.hasAttribute('formaction') ? button.formAction : target.action;
          if (method.toLowerCase() !== 'post' || location.origin !== origin || new URL(action || location.href, location.href).origin !== origin) event.preventDefault();
        };
        form[key] = guard; form.addEventListener('submit', guard, true);
      }, { origin: website, key: SECURE_SUBMIT_GUARD });
      const check = async () => {
        ctx = this.#policy(ctx);
        ctx.signal?.throwIfAborted();
        if (ctx.credentialEnabled?.() === false) throw new Error('Playwright was disabled');
        await guardBrowserUrl(page.url(), ctx);
        if (credentialOrigin(page.url()) !== website) throw new Error('Login origin changed');
        for (const handle of controls) if (!handle || !await handle.evaluate((node, { origin, scope, native }) => node.isConnected && scope.isConnected && scope.contains(node) && location.origin === origin && (native ? node.form === scope && new URL(scope.action || location.href, location.href).origin === origin : !node.form), { origin: website, scope, native: plan.nativeForm })) throw new Error('Login form changed');
        if (!await controls[2].evaluate((button, origin) => new URL(button.hasAttribute('formaction') ? button.formAction : button.form?.action || location.href, location.href).origin === origin, website)) throw new Error('Sign-in button origin changed');
      };
      await check(); await controls[0].fill(value.username, { timeout: BROWSER_ACTION_TIMEOUT_MS });
      await check(); await controls[1].fill(value.password, { timeout: BROWSER_ACTION_TIMEOUT_MS });
      value.password = ''; // Drop the main-process plaintext as soon as filling finishes.
      await check(); await controls[2].click({ timeout: BROWSER_ACTION_TIMEOUT_MS });
      this.refState = null;
      return await this.verifyLogin(plan, ctx);
    } finally {
      await scope?.evaluate((form, key) => { if (form?.[key]) { form.removeEventListener('submit', form[key], true); delete form[key]; } }, SECURE_SUBMIT_GUARD).catch(() => {});
      await scope?.dispose().catch(() => {});
      await Promise.all(controls.map(handle => handle?.dispose().catch(() => {})));
    }
  }

  async verifyLogin({ page, website }, ctx, wait = true) {
    ctx.signal?.throwIfAborted();
    try {
      const evidence = page.getByRole('button', { name: SIGNED_IN_NAME }).or(page.getByRole('link', { name: SIGNED_IN_NAME })).filter({ visible: true });
      if (wait) await evidence.first().waitFor({ state: 'visible', timeout: LOGIN_VERIFY_MS });
      ctx.signal?.throwIfAborted();
      return credentialOrigin(page.url()) === website && await evidence.count() > 0 && await page.locator('input[type="password"]:visible').count() === 0;
    } catch { return false; }
  }

  async preflightBatch(steps, ctx = {}) {
    ctx = this.#policy(ctx);
    const page = this.#target(steps[0].tab);
    try {
      for (const step of steps) {
        const fields = step.action === 'fill_form' ? browserFields(step.fields) : [{ ref: step.ref, text: String(step.text ?? '') }];
        for (const field of fields) {
          ctx.signal?.throwIfAborted();
          const locator = await this.#resolveRef(page, field.ref);
          assertBatchTarget(await locator.evaluate(inspectBatchTarget), step, field, ISOLATED_REF_PATTERN, ctx.backgroundJob);
        }
      }
    } catch (error) { return recoverBrowserReference(formFillFailure(error, false), () => this.#snapshot(page, false)); }
  }

  async run(args, ctx) {
    ctx = this.#policy(ctx);
    const action = args.action;
    if (action === 'open') {
      const url = await guardBrowserUrl(args.url, ctx);
      await this.#start(ctx);
      const page = this.context.pages().find(candidate => candidate.url() === 'about:blank' && !candidate.isClosed()) || await this.context.newPage();
      this.#register(page);
      this.page = page;
      this.refState = null;
      ctx.onBrowserDispatch?.({ phase: 'start', action });
      await this.#awaitAction(page, () => page.goto(url, { waitUntil: 'domcontentloaded', timeout: ctx.backgroundJob ? 0 : NAVIGATION_TIMEOUT_MS }));
      ctx.onBrowserDispatch?.({ phase: 'complete', action });
      await guardBrowserUrl(page.url(), ctx);
      await this.#rendered(page, true);
      return withBrowserSnapshot(`Opened tab ${this.ids.get(page)}: ${(await page.title()).slice(0, 160)}\n${page.url().slice(0, 500)}`, () => this.#snapshot(page, false));
    }
    if (action === 'tabs') return this.tabs();
    const page = this.#target(args.tab);
    if (action === 'handle_dialog') return this.#handleDialog(page, args, ctx);
    if (this.dialogs.has(page)) {
      if (['snapshot', 'read', 'find'].includes(action)) return this.#snapshot(page, false);
      if (action !== 'close') throw new Error(BROWSER_DIALOG_GUIDANCE);
    }
    if (BROWSER_TRANSFER_ACTIONS.includes(action)) {
      if (ctx.config?.browserRuntimeV2 !== true) throw new Error('Browser transfers require the experimental runtime. Use take control.');
      if (action === 'upload') return this.#upload(page, args, ctx);
      if (!this.acceptDownloads) throw new Error('Restart the isolated browser with the experimental runtime before using downloads.');
      if (action === 'downloads') return JSON.stringify(this.downloads.list(this.ids.get(page)));
      if (action === 'cancel_download') return this.downloads.cancel(args.download_id, this.ids.get(page), ctx);
      this.transferResult = await this.downloads.save(args, this.ids.get(page), ctx);
      return this.transferResult.output;
    }
    if (this.pageErrors.has(page)) await this.#rendered(page);
    if (BROWSER_NAVIGATION_ACTIONS.includes(action)) {
      const url = action === 'navigate' ? await guardBrowserUrl(args.url, ctx) : null;
      this.invalidate();
      ctx.onBrowserDispatch?.({ phase: 'start', action });
      const options = { waitUntil: 'domcontentloaded', timeout: ctx.backgroundJob ? 0 : NAVIGATION_TIMEOUT_MS };
      const response = await this.#awaitAction(page, () => action === 'navigate' ? page.goto(url, options) : action === 'back' ? page.goBack(options) : page.goForward(options));
      if (response === null && action !== 'navigate') throw new Error('No document navigation was returned. Inspect the current URL before continuing.');
      ctx.onBrowserDispatch?.({ phase: 'complete', action });
      await guardBrowserUrl(page.url(), ctx);
      await this.#rendered(page, true);
      return withBrowserSnapshot(`Navigated tab ${this.ids.get(page)}: ${page.url().slice(0, SNAPSHOT_LIMITS.url)}`, () => this.#snapshot(page, false));
    }
    if (action === 'sequence') {
      if (ctx.config?.browserRuntimeV2 !== true) throw new Error('Guarded sequences require the experimental runtime. Use individual actions.');
      return this.#sequence(page, args, ctx);
    }
    if (action === 'snapshot') return this.#snapshot(page, args.filter === 'all', args.query);
    if (action === 'find' || action === 'read') {
      const sources = [];
      let remaining = PAGE_TEXT_LIMITS.source;
      let omittedFrames = page.frames().length > SNAPSHOT_LIMITS.frames;
      for (const frame of page.frames().slice(0, SNAPSHOT_LIMITS.frames)) {
        if (!remaining) { omittedFrames = true; break; }
        ctx.signal?.throwIfAborted();
        if (!this.frameIds.has(frame)) this.frameIds.set(frame, randomUUID());
        const source = await frame.evaluate(extractPageText, pageTextCaptureOptions(args, remaining)).catch(error => { if (frame === page.mainFrame()) throw error; return null; });
        if (!source) { omittedFrames = true; continue; }
        sources.push({ ...source, frameId: this.frameIds.get(frame), documentId: this.documents.get(frame) ?? null, tabId: this.ids.get(page) });
        remaining -= source.text.length;
      }
      const result = pageTextResult({ sources, args, previous: this.textResult });
      if (omittedFrames && !result.truncated) { result.truncated = true; result.output += '\nSome frame content was unavailable or exceeded the source limit.'; }
      this.textResult = result;
      this.observation = textObservation({ result, mode: 'isolated', tabId: this.ids.get(page), documentId: this.documents.get(page.mainFrame()) ?? null });
      return result.output;
    }
    if (action === 'act') {
      try { return await this.#act(page, args, !deferBatchSnapshot(ctx)); }
      catch (error) { return recoverBrowserReference(error, () => this.#snapshot(page, false)); }
    }
    if (action === 'fill_form') {
      let started = false;
      try {
        const fields = browserFields(args.fields);
        for (const field of fields) {
          const locator = await this.#resolveRef(page, field.ref);
          assertFillControl(await locator.evaluate(inspectFillControl, CREDENTIAL_ATTRIBUTE), field, ISOLATED_REF_PATTERN, ctx.backgroundJob);
        }
        for (const field of fields) {
          ctx.signal?.throwIfAborted();
          await this.#act(page, { op: 'fill', ...field }, false, null, () => { started = true; });
        }
        const receipt = `Filled ${fields.length} fields.`;
        return deferBatchSnapshot(ctx) ? receipt : withBrowserSnapshot(receipt, () => this.#snapshot(page, false));
      } catch (error) {
        return recoverBrowserReference(formFillFailure(error, started), () => this.#snapshot(page, false));
      }
    }
    if (action === 'screenshot') {
      const file = screenshotFile(ctx.cwd);
      await page.screenshot({ path: file, timeout: 10_000 });
      // A structured receipt: the desktop work-review surfaces it as an image
      // artifact, and the note stops the model from opening the PNG with the
      // text-only read_file tool (which correctly rejects binary files).
      let bytes = 0;
      try { bytes = fs.statSync(file).size; } catch {}
      return {
        type: BROWSER_SCREENSHOT_TYPE,
        path: file,
        bytes,
        note: `Screenshot saved to ${file} and shown in the work-review artifacts. It is a binary PNG: do not open it with read_file. Describe what the user can see, or use browser snapshot/read for page text.`,
      };
    }
    if (action === 'close') {
      const id = this.ids.get(page);
      ctx.onBrowserDispatch?.({ phase: 'start', action });
      await page.close();
      ctx.onBrowserDispatch?.({ phase: 'complete', action });
      this.refState = null;
      return `Closed tab ${id}`;
    }
    throw unknownBrowserAction(action);
  }

  async execute(args, ctx = {}) {
    return executeBrowserOperation(this, args, ctx, 'isolated', context => this.run(args, context));
  }

  async observe(args = {}, ctx = {}) {
    const result = await this.execute({ ...args, action: 'snapshot' }, ctx);
    if (result.error) throw new Error(String(formatBrowserResult(result)));
    return result.observation;
  }

  async #snapshot(page, all, query = '') {
    const dialog = this.dialogs.get(page);
    if (dialog) {
      this.refState = null;
      this.observation = createBrowserObservation({ mode: 'isolated', tabId: this.ids.get(page), url: page.url(), documentId: this.documents.get(page.mainFrame()) ?? null,
        capabilities: { ...TEXT_BROWSER_CAPABILITIES, documentIdentity: true, dialogs: true } });
      return dialogText(browserDialog(dialog.type(), dialog.message(), this.ids.get(page)));
    }
    const observationStarted = performance.now();
    const serial = ++this.snapshotId;
    const refs = new Map();
    const lines = [`# ${(await page.title()).slice(0, SNAPSHOT_LIMITS.label)} — ${page.url().slice(0, SNAPSHOT_LIMITS.url)}`];
    const allFrames = page.frames(), frames = allFrames.slice(0, SNAPSHOT_LIMITS.frames);
    let capturedFrames = 0; // Count successfully inspected frames from this capture's initial set, never a changing final frame count.
    let remaining = SNAPSHOT_LIMITS.elements;
    let characters = lines[0].length;
    let omitted = allFrames.length > frames.length;
    const contextChunks = [];
    for (const [frameIndex, frame] of frames.entries()) {
      if (!remaining || characters >= SNAPSHOT_LIMITS.characters) break;
      // Playwright CSS locators pierce open shadow roots; document.querySelectorAll does not.
      let entries;
      if (!this.documents.has(frame)) this.documents.set(frame, randomUUID());
      if (!this.frameIds.has(frame)) this.frameIds.set(frame, randomUUID());
      try {
        entries = await frame.locator(all ? `${ELEMENTS},${TEXT_ELEMENTS}` : ELEMENTS).evaluateAll((nodes, options) => {
          const result = [];
          const groups = new Map(); // Snapshot-local form/dialog groups; identities are not cross-document refs.
          const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
          for (const element of nodes) {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            const ancestors = [];
            // DOM closest stops at a shadow root; inherited hidden/inert state and semantic groups cross its host.
            for (let ancestor = element; ancestor; ancestor = ancestor.parentElement || ancestor.getRootNode().host) ancestors.push(ancestor);
            if (!rect.width || !rect.height || style.visibility === 'hidden' || ancestors.some(ancestor => ancestor.getAttribute('aria-hidden') === 'true')) continue;
            const root = element.getRootNode();
            const labelledBy = normalize(normalize(element.getAttribute('aria-labelledby')).split(' ').filter(Boolean)
              .map(id => root.getElementById?.(id)?.textContent || '').join(' '));
            const associated = [...(element.labels || [])].map(label => {
              const copy = label.cloneNode(true);
              for (const control of copy.querySelectorAll('input,textarea,select,button')) control.remove();
              return copy.textContent;
            }).join(' ');
            const accessible = normalize(labelledBy || element.getAttribute('aria-label') || associated);
            const secret = element.type === 'password' || element.getAttribute(options.credentialAttribute) === 'password';
            const label = accessible || normalize(element.getAttribute('placeholder') || element.innerText || element.getAttribute('title') || (secret ? '' : element.getAttribute('value')) || element.getAttribute('name'));
            if (options.query && !label.toLowerCase().includes(options.query)) continue;
            const tag = element.tagName.toLowerCase();
            const role = element.getAttribute('role') || tag;
            const ref = `${options.serial}-${options.frameIndex}-${result.length}`;
            const states = [];
            if (tag === 'input') states.push(`type=${secret ? 'password' : element.type}`);
            if (element.disabled || element.getAttribute('aria-disabled') === 'true') states.push('disabled');
            if (element.readOnly || element.getAttribute('aria-readonly') === 'true') states.push('readonly');
            if (element.checked || element.getAttribute('aria-checked') === 'true') states.push('checked');
            if (element.hasAttribute('aria-expanded')) states.push(`expanded=${element.getAttribute('aria-expanded')}`);
            if (element.value) states.push(`value=${secret ? '[hidden]' : normalize(element.value).slice(0, options.labelLimit)}`);
            element.setAttribute(options.refAttribute, ref);
            element[Symbol.for(options.identityKey)] = ref;
            const disabled = element.matches(':disabled') || element.getAttribute('aria-disabled') === 'true';
            const readonly = Boolean(element.readOnly) || element.getAttribute('aria-readonly') === 'true';
            const checked = Boolean(element.checked) || element.getAttribute('aria-checked') === 'true';
            const inert = ancestors.some(ancestor => ancestor.hasAttribute('inert'));
            const nonEditableInput = tag === 'input' && ['button', 'submit', 'reset', 'file', 'hidden', 'image'].includes(element.type);
            const editable = !disabled && !readonly && !inert && !nonEditableInput && (['input', 'textarea', 'select'].includes(tag) || element.isContentEditable);
            const hit = root.elementFromPoint?.(rect.x + rect.width / 2, rect.y + rect.height / 2);
            const actionable = !disabled && !inert && Boolean(hit && (hit === element || element.contains(hit)));
            const groupNode = ancestors.find(ancestor => ancestor.matches(options.groupSelector));
            if (groupNode && !groups.has(groupNode)) groups.set(groupNode, { id: `${options.serial}-${options.frameIndex}-group${groups.size}`,
              name: normalize(groupNode.getAttribute('aria-label') || groupNode.getAttribute('name') || groupNode.querySelector('legend')?.textContent).slice(0, options.labelLimit) });
            if (options.runtimeV2) {
              if (inert) states.push('inert');
              if (!actionable) states.push('actionable=false');
              if (groups.get(groupNode)?.name) states.push(`group=${JSON.stringify(groups.get(groupNode).name)}`);
            }
            const line = `[ref=${ref}] ${role} ${label.slice(0, options.labelLimit)}${states.length ? ` (${states.join(', ')})` : ''}`.trim();
            result.push({ ref, role, tag, label: (accessible || label).slice(0, options.labelLimit), labelled: Boolean(accessible), line,
              states: { disabled, readonly, checked, inert, ...(element.value ? { value: secret ? '[hidden]' : normalize(element.value).slice(0, options.labelLimit) } : {}), ...(element.hasAttribute('aria-expanded') ? { expanded: element.getAttribute('aria-expanded') === 'true' } : {}) }, editable, actionable, group: groups.get(groupNode) ?? null,
              opensTab: tag === 'a' && element.getAttribute('target') === '_blank' });
            if (result.length >= options.limit) break;
          }
          const pageText = document.body?.innerText || '';
          const context = options.query ? pageText.split('\n').filter(line => line.toLowerCase().includes(options.query)).join('\n') : pageText;
          const normalized = normalize(context);
          return { controls: result, context: normalized.slice(0, options.contextLimit), contextTruncated: normalized.length > options.contextLimit };
        }, { serial, frameIndex, identityKey: this.refIdentityKey, refAttribute: BROWSER_REF_ATTRIBUTE, limit: remaining, labelLimit: SNAPSHOT_LIMITS.label, contextLimit: SNAPSHOT_CONTEXT_CHARACTERS, query: String(query).trim().toLowerCase(), credentialAttribute: CREDENTIAL_ATTRIBUTE, groupSelector: BROWSER_GROUP_SELECTOR, runtimeV2: this.policyContext?.config?.browserRuntimeV2 === true });
        const targets = entries.controls.map(entry => `[${BROWSER_REF_ATTRIBUTE}="${entry.ref}"]`).join(',');
        const states = targets ? await frame.locator(targets).evaluateAll(inspectBrowserControls, { refAttribute: BROWSER_REF_ATTRIBUTE, limit: SNAPSHOT_LIMITS.elements }) : [];
        const byRef = new Map(states.map(state => [state.ref, state]));
        for (const entry of entries.controls) {
          const state = byRef.get(entry.ref);
          if (!state) continue;
          entry.states = { ...entry.states, ...state.states }; entry.editable = state.editable; entry.actionable = state.actionable;
          const flags = BROWSER_CONTROL_FLAGS.filter(flag => state.states[flag]);
          entry.line = `${BROWSER_CONTROL_PREFIX}${entry.line}${flags.length ? ` [${flags.join(', ')}]` : ''}`;
        }
        capturedFrames++;
      } catch (error) {
        if (frame === page.mainFrame()) throw error;
        omitted = true;
        lines.push('A child frame changed during the snapshot; inspect again if its controls are needed.');
        continue;
      }
      let groupId = null;
      for (const entry of entries.controls) {
        const group = entry.group && entry.group.id !== groupId ? `${BROWSER_CONTROL_PREFIX}group ${JSON.stringify(entry.group.name)}` : null;
        if (group) {
          if (characters + group.length >= SNAPSHOT_LIMITS.characters) { omitted = true; break; }
          lines.push(group); characters += group.length + 1;
        }
        groupId = entry.group?.id ?? null;
        if (entry.group) entry.line = `  ${entry.line}`;
        if (characters + entry.line.length >= SNAPSHOT_LIMITS.characters) { omitted = true; break; }
        refs.set(entry.ref, { ...entry, frame, url: frame.url(), frameId: this.frameIds.get(frame), documentId: this.documents.get(frame) });
        lines.push(entry.line); characters += entry.line.length + 1; remaining--;
      }
      omitted ||= entries.contextTruncated;
      if (entries.context) {
        contextChunks.push({ sourceUrl: frame.url(), frameId: this.frameIds.get(frame), start: 0, end: entries.context.length, text: entries.context, observationId: String(serial) });
        const context = `Visible page text (not action refs): ${entries.context}`;
        if (characters + context.length < SNAPSHOT_LIMITS.characters) { lines.push(context); characters += context.length + 1; }
        else omitted = true;
      }
    }
    this.refState = { serial, page, refs };
    if (!remaining || omitted) lines.push(SNAPSHOT_LIMIT_REACHED);
    const text = lines.join('\n');
    this.observation = createBrowserObservation({ mode: 'isolated', tabId: this.ids.get(page), url: page.url(), documentId: this.documents.get(page.mainFrame()),
      controls: [...refs.values()].map(entry => ({ ref: entry.ref, frameId: entry.frameId, role: entry.role, name: entry.label, states: entry.states, editable: entry.editable,
        actionable: entry.frame === page.mainFrame() || entry.actionable === false ? entry.actionable : null, group: entry.group })),
      context: contextChunks, omissions: { truncated: !remaining || omitted, frames: allFrames.length - capturedFrames }, capabilities: { ...TEXT_BROWSER_CAPABILITIES, documentIdentity: true, guardedSequences: this.policyContext?.config?.browserRuntimeV2 === true, dialogs: this.policyContext?.config?.browserRuntimeV2 === true,
        uploads: this.policyContext?.config?.browserRuntimeV2 === true, downloads: this.acceptDownloads } });
    this.observation.context = this.observation.context.map(chunk => ({ ...chunk, observationId: this.observation.id }));
    this.refState.observation = this.observation;
    if (this.operationTimings) this.operationTimings.observation = (this.operationTimings.observation || 0) + performance.now() - observationStarted;
    return this.policyContext?.config?.browserRuntimeV2 === true ? `${text}\nObservation: ${this.observation.id}` : text;
  }

  async #sequence(page, args, ctx) {
    const source = this.refState?.page === page ? this.refState.observation : null;
    const plan = validateSequence(args, source, source?.capabilities);
    const entries = plan.steps.map(step => this.refState.refs.get(step.ref));
    const handles = [];
    let scope;
    const pageCount = this.context.pages().length;
    const guardOptions = { selector: BROWSER_GROUP_SELECTOR, controlSelector: SEQUENCE_CONTROL_SELECTOR,
      limit: SNAPSHOT_LIMITS.elements, scanLimit: SEQUENCE_GUARD_NODE_LIMIT };
    const check = async (handle, entry, baseline) => {
      ctx.signal?.throwIfAborted();
      if (this.dialogs.has(page)) throw new Error(BROWSER_DIALOG_GUIDANCE);
      if (page !== this.page || page.isClosed() || this.documents.get(entry.frame) !== entry.documentId || this.context.pages().length !== pageCount) throw new Error(SEQUENCE_CHANGED);
      const state = await handle.evaluate(captureSequenceGuard, { ...guardOptions, scope });
      if (state.truncated) throw new Error(SEQUENCE_GUARD_LIMIT_REACHED);
      if (!state.valid || state.autocompleteOpen || (baseline && state.structure !== baseline)) throw new Error(SEQUENCE_CHANGED);
      return state.structure;
    };
    try {
      // Bind original nodes directly. The legacy unique-label fallback is intentionally unavailable in a chain.
      for (const [index, entry] of entries.entries()) {
        if (!entry || entry.frame.isDetached() || entry.documentId !== this.documents.get(entry.frame)) throw new Error(SEQUENCE_CHANGED);
        const marked = entry.frame.locator(`[data-ankita-ref="${plan.steps[index].ref}"]`);
        if (await marked.count() !== 1) throw new Error(SEQUENCE_CHANGED);
        const handle = await marked.elementHandle();
        if (!handle) throw new Error(SEQUENCE_CHANGED);
        handles.push(handle);
        if (!await handle.evaluate(browserRefMatches, { identityKey: this.refIdentityKey, ref: plan.steps[index].ref })) throw new Error(SEQUENCE_CHANGED);
      }
      scope = await handles[0].evaluateHandle(captureSequenceGuard, guardOptions);
      const baseline = await check(handles[0], entries[0]);
      for (const [index, handle] of handles.entries()) {
        await check(handle, entries[index], baseline);
        if (SEQUENCE_FIELD_OPS.includes(plan.steps[index].op)) assertFillControl(await handle.evaluate(inspectFillControl, CREDENTIAL_ATTRIBUTE), plan.steps[index], ISOLATED_REF_PATTERN, ctx.backgroundJob);
      }
      for (const [index, step] of plan.steps.entries()) {
        await check(handles[index], entries[index], baseline);
        await this.#act(page, step, false, handles[index]);
      }
      return withBrowserSnapshot(`Executed ${plan.steps.length} guarded steps. Verify the requested outcome on the current page.`, () => this.#snapshot(page, false));
    } catch (error) {
      this.invalidate();
      if (!ctx.signal?.aborted && !page.isClosed()) { try { error.message += `\nFresh snapshot:\n${await this.#snapshot(page, false)}`; } catch {} }
      throw error;
    } finally { await Promise.all([...handles, scope].filter(Boolean).map(handle => handle.dispose().catch(() => {}))); }
  }

  async #resolveRef(page, value) {
    const state = this.refState;
    const entry = state?.page === page && state.refs?.get(value);
    if (!ISOLATED_REF_PATTERN.test(value) || !entry || entry.frame.isDetached() || entry.frame.url() !== entry.url || this.documents.get(entry.frame) !== entry.documentId) throw new BrowserReferenceError(value, ISOLATED_REF_PATTERN);
    const marked = entry.frame.locator(`[${BROWSER_REF_ATTRIBUTE}="${value}"]`);
    if (await marked.count() !== 1 || !await marked.evaluate(browserRefMatches, { identityKey: this.refIdentityKey, ref: value })) throw new BrowserReferenceError(value, ISOLATED_REF_PATTERN);
    return marked;
  }

  async #act(page, args, snapshot = true, boundTarget = null, onDispatch = null) {
    const actionStarted = performance.now();
    const timeout = this.policyContext?.backgroundJob ? 0 : BROWSER_ACTION_TIMEOUT_MS; // Job execution/approval deadlines are owned by the scheduler.
    const ref = String(args.ref || '');
    const marked = boundTarget || await this.#resolveRef(page, ref);
    // Bind the native node before any metadata await; an auto-waiting Locator
    // must not follow a copied ref attribute onto a replacement during the action.
    const locator = boundTarget || await marked.elementHandle();
    try {
    if (!locator || (!boundTarget && !await locator.evaluate(browserRefMatches, { identityKey: this.refIdentityKey, ref }))) throw new BrowserReferenceError(ref, ISOLATED_REF_PATTERN);
    const op = String(args.op || 'click');
    const text = String(args.text ?? '');
    const dispatch = () => {
      this.policyContext?.signal?.throwIfAborted(); // A completed metadata await must not dispatch a late write after Stop returned.
      onDispatch?.(); // Host-owned form accounting starts at actual dispatch, after node and editability checks.
      this.policyContext?.onBrowserDispatch?.({ phase: 'start', action: 'act', op });
    };
    await this.#awaitAction(page, async () => {
    if (op === 'click') {
      // Observe a known new-tab target before dispatch; ordinary clicks incur no popup wait.
      const popupPending = this.refState?.refs.get(String(args.ref))?.opensTab
        ? page.waitForEvent('popup', { timeout: BROWSER_ACTION_TIMEOUT_MS }).catch(() => null) : null;
      dispatch(); await locator.click({ timeout });
      if (popupPending) {
        const popup = await popupPending;
        if (popup) {
          this.#register(popup);
          await popup.waitForLoadState('domcontentloaded', { timeout: BROWSER_ACTION_TIMEOUT_MS }).catch(() => {});
        }
      }
    }
    else if (op === 'fill') {
      const control = await locator.evaluate(inspectFillControl, CREDENTIAL_ATTRIBUTE);
      assertFillControl(control, { ref: args.ref, text }, ISOLATED_REF_PATTERN, this.policyContext?.backgroundJob);
      dispatch();
      if (control.tag === 'select') await locator.selectOption({ label: text }, { timeout });
      else if (['checkbox', 'radio'].includes(control.type)) {
        if (!['true', 'false'].includes(text)) throw new Error('Checkbox/radio values must be true or false.');
        await locator.setChecked(text === 'true', { timeout });
      } else await locator.fill(text, { timeout });
    }
    else if (op === 'type') {
      if (this.policyContext?.backgroundJob) assertFillControl(await locator.evaluate(inspectFillControl, CREDENTIAL_ATTRIBUTE), { ref: args.ref, text }, ISOLATED_REF_PATTERN, true);
      dispatch();
      await locator.type(text, { timeout });
    }
    else if (op === 'press') { dispatch(); await locator.press(text || 'Enter', { timeout }); }
    else if (op === 'select') {
      const control = await locator.evaluate(inspectFillControl, CREDENTIAL_ATTRIBUTE);
      assertSelectControl(control, ref, ISOLATED_REF_PATTERN);
      assertFillControl(control, { ref, text }, ISOLATED_REF_PATTERN, this.policyContext?.backgroundJob);
      dispatch(); await locator.selectOption({ label: text }, { timeout });
    }
    else if (op === 'hover') { dispatch(); await locator.hover({ timeout }); }
    else if (op === 'scroll') { dispatch(); await locator.scrollIntoViewIfNeeded({ timeout }); await page.mouse.wheel(0, browserScrollDelta(text)); }
    else if (op === 'drag') {
      const to = String(args.to_ref || '');
      const destination = await this.#resolveRef(page, to);
      dispatch(); await marked.dragTo(destination, { timeout });
    } else throw new Error(`Unsupported browser operation: ${op}`);
    });
    this.policyContext?.onBrowserDispatch?.({ phase: 'complete', action: 'act', op });
    if (this.operationTimings) this.operationTimings.action = (this.operationTimings.action || 0) + performance.now() - actionStarted;
    if (!snapshot) return `${op} complete.`;
    this.refState = null;
    return withBrowserSnapshot(`${op} complete.`, () => this.#snapshot(page, false));
    } finally { if (!boundTarget) await locator?.dispose().catch(() => {}); }
  }

  async preview(options = {}) {
    if (this.previewPending) return this.previewPending;
    this.previewPending = this.#preview(options).finally(() => { this.previewPending = null; });
    return this.previewPending;
  }

  async #preview(options = {}) {
    const page = this.#findTarget(options.tab);
    if (this.dialogs.has(page)) throw new Error(BROWSER_DIALOG_GUIDANCE);
    if (this.pageErrors.has(page)) await this.#rendered(page);
    const image = await page.screenshot({ type: 'jpeg', quality: 48, timeout: 1500 });
    return `data:image/jpeg;base64,${image.toString('base64')}`;
  }

  invalidate() { this.refState = null; this.observation = null; this.textResult = null; }

  async userInput(input = {}) {
    const page = this.#findTarget(input.tab);
    if (input.kind === 'click') {
      const x = Number(input.x), y = Number(input.y);
      if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0 || x > VIEWPORT.width || y > VIEWPORT.height) throw new Error('Invalid browser coordinates');
      await page.mouse.click(x, y);
    } else if (input.kind === 'text') await page.keyboard.type(String(input.text || '').slice(0, 1000));
    else if (input.kind === 'key') await page.keyboard.press(String(input.key || 'Escape').slice(0, 40));
    else if (input.kind === 'scroll') await page.mouse.wheel(0, Math.max(-1200, Math.min(1200, Number(input.deltaY) || 0)));
    else throw new Error('Unsupported browser input');
    this.invalidate();
  }

  async close() {
    if (this.closePending) return this.closePending;
    // Detach these owned resources before waiting; concurrent guard/scheduler cleanup shares one close.
    const guard = this.jobGuard, context = this.context;
    this.downloads.close(); this.acceptDownloads = false;
    this.jobGuard = null; this.context = null; this.page = null; this.invalidate();
    this.closePending = (async () => { await guard?.close(); await context?.close(); })().finally(() => { this.closePending = null; });
    return this.closePending;
  }
}
