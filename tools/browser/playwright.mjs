import fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { CONFIG_DIR } from '../../src/core/config.mjs';
import { allowPrivateHosts, checkUrlPublic } from '../shared/_web.mjs';
import { BROWSER_ACTION_TIMEOUT_MS, BrowserReferenceError, INTERACTIVE_ROLES, ISOLATED_REF_PATTERN, SNAPSHOT_LIMITS, browserFields, recoverBrowserReference, withBrowserSnapshot } from './refs.mjs';
import { BROWSER_SCREENSHOT_DIRECTORY, BROWSER_SCREENSHOT_TYPE } from './screenshots.mjs';

// ARIA interaction roles: custom booking forms often use div-based comboboxes/options.
const ELEMENTS = ['a', 'button', 'input', 'textarea', 'select', '[contenteditable="true"]', '[tabindex]', ...INTERACTIVE_ROLES.map(role => `[role="${role}"]`)].join(',');
const TEXT_ELEMENTS = 'h1,h2,h3,p,[role="status"],[role="alert"]';
// Fixed capture viewport (px): takeover input bounds derive from this.
const VIEWPORT = { width: 1280, height: 800 };
// Captures kept per workspace; older browser-*.png files beyond this are pruned.
const MAX_KEPT_SCREENSHOTS = 50;

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
  constructor({ profile = path.join(CONFIG_DIR, 'browser', 'playwright') } = {}) {
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
  }

  async #start(ctx) {
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
        timeout: 15_000,
      });
    } catch (error) {
      throw new Error(`Chromium could not start: ${error.message}. Open Plugins → By Ankita to download Chromium.`);
    }
    if (ctx.signal?.aborted) { await this.close(); ctx.signal.throwIfAborted(); }
    await this.context.route('**/*', async route => {
      const request = route.request();
      try {
        const url = request.url();
        if (!/^https?:/i.test(url)) return route.continue();
        const host = new URL(url).hostname;
        const policy = this.policyContext || ctx;
        const key = `${host}:${allowPrivateHosts(policy)}:${request.isNavigationRequest()}`;
        const cached = this.checkedHosts.get(key);
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
    page.on('framenavigated', frame => { if (frame === page.mainFrame() || [...(this.refState?.refs?.values() || [])].some(entry => entry.frame === frame)) this.refState = null; });
    page.on('close', () => { if (this.page === page) this.page = this.context?.pages().find(p => !p.isClosed()) || null; this.refState = null; });
  }

  #target(tab) {
    const pages = this.context?.pages().filter(page => !page.isClosed()) || [];
    const found = tab ? pages.find(page => this.ids.get(page) === String(tab)) : this.page || pages[0];
    if (!found) throw new Error(tab ? `Tab ${tab} is closed` : 'No browser tab is open');
    this.page = found;
    return found;
  }

  async tabs() {
    return Promise.all((this.context?.pages() || []).filter(page => !page.isClosed()).map(async page => ({
      id: this.ids.get(page), url: page.url().slice(0, 500), title: (await page.title().catch(() => '')).slice(0, 160), active: page === this.page,
    })));
  }

  async selectTab(tab) { const page = this.#target(tab); await page.bringToFront(); this.refState = null; }

  async run(args, ctx) {
    const policyKey = JSON.stringify([ctx.settings?.allowedSites, ctx.settings?.blockedSites, allowPrivateHosts(ctx)]);
    if (policyKey !== this.policyKey) { this.checkedHosts.clear(); this.policyKey = policyKey; }
    this.policyContext = ctx;
    const action = args.action;
    if (action === 'open') {
      const url = await guardBrowserUrl(args.url, ctx);
      await this.#start(ctx);
      const page = this.context.pages().find(candidate => candidate.url() === 'about:blank' && !candidate.isClosed()) || await this.context.newPage();
      this.#register(page);
      this.page = page;
      this.refState = null;
      await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20_000 });
      await guardBrowserUrl(page.url(), ctx);
      return withBrowserSnapshot(`Opened tab ${this.ids.get(page)}: ${(await page.title()).slice(0, 160)}\n${page.url().slice(0, 500)}`, () => this.#snapshot(page, false));
    }
    if (action === 'tabs') return this.tabs();
    const page = this.#target(args.tab);
    if (action === 'snapshot') return this.#snapshot(page, args.filter === 'all', args.query);
    if (action === 'read') return (await page.locator('body').innerText({ timeout: 7000 })).slice(0, 12_000);
    if (action === 'act') {
      try { return await this.#act(page, args); }
      catch (error) { return recoverBrowserReference(error, () => this.#snapshot(page, false)); }
    }
    if (action === 'fill_form') {
      try {
        const fields = browserFields(args.fields);
        for (const field of fields) await this.#resolveRef(page, field.ref);
        for (const field of fields) {
          ctx.signal?.throwIfAborted();
          await this.#act(page, { op: 'fill', ...field }, false);
        }
        return withBrowserSnapshot(`Filled ${fields.length} fields.`, () => this.#snapshot(page, false));
      } catch (error) {
        error.message += ' Form filling stopped; inspect current values before continuing.';
        return recoverBrowserReference(error, () => this.#snapshot(page, false));
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
            const label = accessible || normalize(element.getAttribute('placeholder') || element.innerText || element.getAttribute('title') || (element.type === 'password' ? '' : element.getAttribute('value')));
            if (options.query && !label.toLowerCase().includes(options.query)) continue;
            const tag = element.tagName.toLowerCase();
            const role = element.getAttribute('role') || tag;
            const ref = `${options.serial}-${options.frameIndex}-${result.length}`;
            const states = [];
            if (element.disabled || element.getAttribute('aria-disabled') === 'true') states.push('disabled');
            if (element.checked || element.getAttribute('aria-checked') === 'true') states.push('checked');
            if (element.hasAttribute('aria-expanded')) states.push(`expanded=${element.getAttribute('aria-expanded')}`);
            if (element.value) states.push(`value=${element.type === 'password' ? '[hidden]' : normalize(element.value).slice(0, options.labelLimit)}`);
            const line = `[ref=${ref}] ${role} ${label.slice(0, options.labelLimit)}${states.length ? ` (${states.join(', ')})` : ''}`.trim();
            element.setAttribute('data-ankita-ref', ref);
            result.push({ ref, role, tag, label: accessible || label, labelled: Boolean(accessible), line });
            if (result.length >= options.limit) break;
          }
          return result;
        }, { serial, frameIndex, limit: remaining, labelLimit: SNAPSHOT_LIMITS.label, query: String(query).trim().toLowerCase() });
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
    const locator = await this.#resolveRef(page, String(args.ref || ''));
    const op = String(args.op || 'click');
    const text = String(args.text ?? '');
    if (op === 'click') await locator.click({ timeout: BROWSER_ACTION_TIMEOUT_MS });
    else if (op === 'fill') {
      const control = await locator.evaluate(element => ({ tag: element.tagName.toLowerCase(), type: element.type }));
      if (control.tag === 'select') await locator.selectOption({ label: text }, { timeout: BROWSER_ACTION_TIMEOUT_MS });
      else if (['checkbox', 'radio'].includes(control.type)) {
        if (!['true', 'false'].includes(text)) throw new Error('Checkbox/radio values must be true or false.');
        await locator.setChecked(text === 'true', { timeout: BROWSER_ACTION_TIMEOUT_MS });
      } else await locator.fill(text, { timeout: BROWSER_ACTION_TIMEOUT_MS });
    }
    else if (op === 'type') await locator.pressSequentially(text, { timeout: BROWSER_ACTION_TIMEOUT_MS });
    else if (op === 'press') await locator.press(text || 'Enter', { timeout: BROWSER_ACTION_TIMEOUT_MS });
    else if (op === 'select') await locator.selectOption({ label: text }, { timeout: BROWSER_ACTION_TIMEOUT_MS });
    else if (op === 'hover') await locator.hover({ timeout: BROWSER_ACTION_TIMEOUT_MS });
    else if (op === 'scroll') { await locator.scrollIntoViewIfNeeded({ timeout: BROWSER_ACTION_TIMEOUT_MS }); await page.mouse.wheel(0, Number(text) || 550); }
    else if (op === 'drag') {
      const to = String(args.to_ref || '');
      await locator.dragTo(await this.#resolveRef(page, to), { timeout: BROWSER_ACTION_TIMEOUT_MS });
    } else throw new Error(`Unsupported browser operation: ${op}`);
    if (!snapshot) return `${op} complete.`;
    this.refState = null;
    return withBrowserSnapshot(`${op} complete.`, () => this.#snapshot(page, false));
  }

  async preview() {
    if (this.previewPending) return this.previewPending;
    this.previewPending = this.#preview().finally(() => { this.previewPending = null; });
    return this.previewPending;
  }

  async #preview() {
    const page = this.#target();
    const image = await page.screenshot({ type: 'jpeg', quality: 48, timeout: 1500 });
    return `data:image/jpeg;base64,${image.toString('base64')}`;
  }

  invalidate() { this.refState = null; }

  async userInput(input = {}) {
    const page = this.#target();
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

  async close() { await this.context?.close(); this.context = null; this.page = null; this.refState = null; }
}
