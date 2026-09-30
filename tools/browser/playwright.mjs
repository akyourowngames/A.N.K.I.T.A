import fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { CONFIG_DIR } from '../../src/core/config.mjs';
import { allowPrivateHosts, checkUrlPublic } from '../shared/_web.mjs';
import { BROWSER_ACTION_TIMEOUT_MS, BrowserReferenceError, CREDENTIAL_ATTRIBUTE, INTERACTIVE_ROLES, ISOLATED_REF_PATTERN, SNAPSHOT_LIMITS, assertFillControl, browserFields, formFillFailure, inspectFillControl, recoverBrowserReference, withBrowserSnapshot } from './refs.mjs';
import { BROWSER_SCREENSHOT_DIRECTORY, BROWSER_SCREENSHOT_TYPE } from './screenshots.mjs';
import { credentialOrigin, credentialPage, credentialFields } from '../../src/integrations/browser-credentials.mjs';
import { JobNetworkGuard } from './job-network-guard.mjs';

// ARIA interaction roles: custom booking forms often use div-based comboboxes/options.
const ELEMENTS = ['a', 'button', 'input', 'textarea', 'select', '[contenteditable="true"]', '[tabindex]', ...INTERACTIVE_ROLES.map(role => `[role="${role}"]`)].join(',');
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
const SIGNED_IN_NAME = /\b(?:sign\s*out|log\s*out|logout)\b/i; // Positive evidence; disappearance of a password field is insufficient.
const SECURE_SUBMIT_GUARD = '__ankitaSecureSubmitGuard'; // Transient listener ownership on the bound form; never a credential value.
const JOB_DEBUG_ARGUMENT = '--remote-debugging-port=0'; // Own isolated Chromium picks a free local guard port.
const JOB_DEBUG_FILE = 'DevToolsActivePort'; // Chromium writes its discovered port and browser socket here.
const JOB_DEBUG_HOST = '127.0.0.1'; // Loopback-only job guard; never a user Chrome connection.

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
    this.checkedHosts = new Map();
    this.policyContext = null;
    this.policyKey = '';
    this.previewPending = null;
    this.renderTimeoutMs = renderTimeoutMs;
    this.pageErrors = new WeakMap();
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
        acceptDownloads: false,
        serviceWorkers: 'block',
        ...(ctx.backgroundJob ? { args: [JOB_DEBUG_ARGUMENT] } : {}),
        timeout: 15_000,
      });
    } catch (error) {
      throw new Error(`Chromium could not start: ${error.message}. Open Plugins → By Ankita to download Chromium.`);
    }
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
    page.on('response', response => {
      if (response.request().isNavigationRequest() && response.frame() === page.mainFrame()) {
        if (response.status() >= HTTP_ERROR_STATUS) {
          const error = new Error(`Navigation refused: HTTP ${response.status()}. The site did not accept this browser request. Use Chrome local or take control; do not keep taking snapshots of the empty page.`);
          this.pageErrors.set(page, { url: response.url(), error, status: response.status() });
        } else this.pageErrors.delete(page);
      }
    });
    page.on('framenavigated', frame => { if (frame === page.mainFrame() || [...(this.refState?.refs?.values() || [])].some(entry => entry.frame === frame)) this.refState = null; });
    page.on('close', () => { if (this.page === page) this.page = this.context?.pages().find(p => !p.isClosed()) || null; this.refState = null; });
  }

  #findTarget(tab) {
    const pages = this.context?.pages().filter(page => !page.isClosed()) || [];
    const found = tab ? pages.find(page => this.ids.get(page) === String(tab)) : this.page || pages[0];
    if (!found) throw new Error(tab ? `Tab ${tab} is closed` : 'No browser tab is open');
    return found;
  }

  #target(tab) { const found = this.#findTarget(tab); this.page = found; return found; }

  async tabs() {
    return Promise.all((this.context?.pages() || []).filter(page => !page.isClosed()).map(async page => ({
      id: this.ids.get(page), url: page.url().slice(0, 500), title: (await page.title().catch(() => '')).slice(0, 160), active: page === this.page,
    })));
  }

  async selectTab(tab) { const page = this.#target(tab); await page.bringToFront(); this.refState = null; }

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
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: ctx.backgroundJob ? 0 : 20_000 });
      await guardBrowserUrl(page.url(), ctx);
      await this.#rendered(page, true);
      return withBrowserSnapshot(`Opened tab ${this.ids.get(page)}: ${(await page.title()).slice(0, 160)}\n${page.url().slice(0, 500)}`, () => this.#snapshot(page, false));
    }
    if (action === 'tabs') return this.tabs();
    const page = this.#target(args.tab);
    if (this.pageErrors.has(page)) await this.#rendered(page);
    if (action === 'snapshot') return this.#snapshot(page, args.filter === 'all', args.query);
    if (action === 'read') return (await page.locator('body').innerText({ timeout: 7000 })).slice(0, 12_000);
    if (action === 'act') {
      try { return await this.#act(page, args); }
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
          started = true;
          await this.#act(page, { op: 'fill', ...field }, false);
        }
        return withBrowserSnapshot(`Filled ${fields.length} fields.`, () => this.#snapshot(page, false));
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
      await page.close();
      this.refState = null;
      return `Closed tab ${id}`;
    }
    throw new Error(`Unknown browser action: ${action}`);
  }

  async #snapshot(page, all, query = '') {
    const serial = ++this.snapshotId;
    const refs = new Map();
    const lines = [`${(await page.title()).slice(0, SNAPSHOT_LIMITS.label)} — ${page.url().slice(0, SNAPSHOT_LIMITS.url)}`];
    const frames = page.frames().slice(0, SNAPSHOT_LIMITS.frames);
    let remaining = SNAPSHOT_LIMITS.elements;
    let characters = lines[0].length;
    let omitted = page.frames().length > frames.length;
    for (const [frameIndex, frame] of frames.entries()) {
      if (!remaining || characters >= SNAPSHOT_LIMITS.characters) break;
      // Playwright CSS locators pierce open shadow roots; document.querySelectorAll does not.
      let entries;
      try {
        entries = await frame.locator(all ? `${ELEMENTS},${TEXT_ELEMENTS}` : ELEMENTS).evaluateAll((nodes, options) => {
          const result = [];
          const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
          for (const element of nodes) {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            if (!rect.width || !rect.height || style.visibility === 'hidden' || element.closest('[aria-hidden="true"]')) continue;
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
            if (element.checked || element.getAttribute('aria-checked') === 'true') states.push('checked');
            if (element.hasAttribute('aria-expanded')) states.push(`expanded=${element.getAttribute('aria-expanded')}`);
            if (element.value) states.push(`value=${secret ? '[hidden]' : normalize(element.value).slice(0, options.labelLimit)}`);
            const line = `[ref=${ref}] ${role} ${label.slice(0, options.labelLimit)}${states.length ? ` (${states.join(', ')})` : ''}`.trim();
            element.setAttribute('data-ankita-ref', ref);
            result.push({ ref, role, tag, label: accessible || label, labelled: Boolean(accessible), line });
            if (result.length >= options.limit) break;
          }
          return result;
        }, { serial, frameIndex, limit: remaining, labelLimit: SNAPSHOT_LIMITS.label, query: String(query).trim().toLowerCase(), credentialAttribute: CREDENTIAL_ATTRIBUTE });
      } catch (error) {
        if (frame === page.mainFrame()) throw error;
        lines.push('A child frame changed during the snapshot; inspect again if its controls are needed.');
        continue;
      }
      for (const entry of entries) {
        if (characters + entry.line.length >= SNAPSHOT_LIMITS.characters) { omitted = true; break; }
        refs.set(entry.ref, { ...entry, frame, url: frame.url() });
        lines.push(entry.line); characters += entry.line.length + 1; remaining--;
      }
    }
    this.refState = { serial, page, refs };
    if (!remaining || omitted) lines.push('Snapshot limit reached. Use snapshot query to find a missing control by label.');
    return lines.join('\n');
  }

  async #resolveRef(page, value) {
    const state = this.refState;
    const entry = state?.page === page && state.refs?.get(value);
    if (!ISOLATED_REF_PATTERN.test(value) || !entry || entry.frame.isDetached() || entry.frame.url() !== entry.url) throw new BrowserReferenceError(value, ISOLATED_REF_PATTERN);
    const marked = entry.frame.locator(`[data-ankita-ref="${value}"]`);
    if (await marked.count() === 1) return marked;
    // Re-resolve only a registered control in its original frame, with an exact unique name.
    // Playwright performs its normal visibility/actionability checks on the locator.
    let fallback;
    if (entry.labelled && ['input', 'textarea', 'select'].includes(entry.tag)) fallback = entry.frame.getByLabel(entry.label, { exact: true });
    else if (INTERACTIVE_ROLES.includes(entry.role) || ['button', 'a'].includes(entry.tag)) fallback = entry.frame.getByRole(entry.tag === 'a' ? 'link' : entry.role, { name: entry.label, exact: true });
    if (!entry.label || !fallback || await fallback.count() !== 1) throw new BrowserReferenceError(value, ISOLATED_REF_PATTERN);
    return fallback;
  }

  async #act(page, args, snapshot = true) {
    const timeout = this.policyContext?.backgroundJob ? 0 : BROWSER_ACTION_TIMEOUT_MS; // Job execution/approval deadlines are owned by the scheduler.
    const locator = await this.#resolveRef(page, String(args.ref || ''));
    const op = String(args.op || 'click');
    const text = String(args.text ?? '');
    if (op === 'click') await locator.click({ timeout });
    else if (op === 'fill') {
      const control = await locator.evaluate(inspectFillControl, CREDENTIAL_ATTRIBUTE);
      assertFillControl(control, { ref: args.ref, text }, ISOLATED_REF_PATTERN, this.policyContext?.backgroundJob);
      if (control.tag === 'select') await locator.selectOption({ label: text }, { timeout });
      else if (['checkbox', 'radio'].includes(control.type)) {
        if (!['true', 'false'].includes(text)) throw new Error('Checkbox/radio values must be true or false.');
        await locator.setChecked(text === 'true', { timeout });
      } else await locator.fill(text, { timeout });
    }
    else if (op === 'type') {
      if (this.policyContext?.backgroundJob) assertFillControl(await locator.evaluate(inspectFillControl, CREDENTIAL_ATTRIBUTE), { ref: args.ref, text }, ISOLATED_REF_PATTERN, true);
      await locator.pressSequentially(text, { timeout });
    }
    else if (op === 'press') await locator.press(text || 'Enter', { timeout });
    else if (op === 'select') await locator.selectOption({ label: text }, { timeout });
    else if (op === 'hover') await locator.hover({ timeout });
    else if (op === 'scroll') { await locator.scrollIntoViewIfNeeded({ timeout }); await page.mouse.wheel(0, Number(text) || 550); }
    else if (op === 'drag') {
      const to = String(args.to_ref || '');
      await locator.dragTo(await this.#resolveRef(page, to), { timeout });
    } else throw new Error(`Unsupported browser operation: ${op}`);
    if (!snapshot) return `${op} complete.`;
    this.refState = null;
    return withBrowserSnapshot(`${op} complete.`, () => this.#snapshot(page, false));
  }

  async preview(options = {}) {
    if (this.previewPending) return this.previewPending;
    this.previewPending = this.#preview(options).finally(() => { this.previewPending = null; });
    return this.previewPending;
  }

  async #preview(options = {}) {
    const page = this.#findTarget(options.tab);
    if (this.pageErrors.has(page)) await this.#rendered(page);
    const image = await page.screenshot({ type: 'jpeg', quality: 48, timeout: 1500 });
    return `data:image/jpeg;base64,${image.toString('base64')}`;
  }

  invalidate() { this.refState = null; }

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
    this.refState = null;
  }

  async close() {
    if (this.closePending) return this.closePending;
    // Detach these owned resources before waiting; concurrent guard/scheduler cleanup shares one close.
    const guard = this.jobGuard, context = this.context;
    this.jobGuard = null; this.context = null; this.page = null; this.refState = null;
    this.closePending = (async () => { await guard?.close(); await context?.close(); })().finally(() => { this.closePending = null; });
    return this.closePending;
  }
}
