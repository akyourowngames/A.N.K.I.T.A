import fs from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { guardBrowserUrl, screenshotFile } from './playwright.mjs';
import { executeBrowserOperation, formatBrowserResult, BASE_BROWSER_CAPABILITIES } from './contracts.mjs';
import { createBrowserObservation } from './observations.mjs';
import { BROWSER_SCREENSHOT_TYPE } from './screenshots.mjs';
import { browserFields, browserScrollDelta } from './refs.mjs';
import { isProtectedBrowserPage } from './protected-pages.mjs';
import { BROWSER_EXTENSION_MCP_ID, BROWSER_EXTENSION_TOOL, CONTROL_STALE, CONTROL_DOM_LIMITS } from '../../desktop/browser-helper/control-protocol.mjs';

const MCP_TOOL = `mcp__${BROWSER_EXTENSION_MCP_ID}__${BROWSER_EXTENSION_TOOL}`;
const EXTENSION_CAPABILITIES = Object.freeze({ ...BASE_BROWSER_CAPABILITIES, documentIdentity: true });
const REF_REQUIRED_OPS = new Set(['click', 'fill', 'type', 'select', 'press', 'check', 'uncheck', 'hover']);

/** Existing browser facade, new transport. No connection approval or retry is added per action. */
export class ExtensionBrowserAdapter {
  constructor(mcp, { ensureConnected, ownedTabs = false, scope = randomUUID(), protectedPage = null } = {}) {
    Object.assign(this, { mcp, ensureConnected, ownedTabs, scope, protectedPage });
    this.currentTab = null; this.refs = new Map(); this.documentId = null; this.observation = null;
  }
  async request(operation, ctx = {}) {
    ctx.signal?.throwIfAborted(); await this.ensureConnected?.(ctx);
    const reply = await this.mcp.callToolResult(MCP_TOOL, { operation: { ...operation, scope: this.scope, ownedTabs: this.ownedTabs } }, { signal: ctx.signal });
    let parsed;
    try { parsed = JSON.parse(reply.text); } catch { throw new Error('The browser extension returned an unreadable result'); }
    if (reply.isError || parsed.error) throw Object.assign(new Error(parsed.error?.message || 'Browser extension action failed'), { dispatched: parsed.error?.dispatched === true });
    return parsed.result;
  }
  async tabs(options = {}) {
    const tabs = await this.request({ action: 'tabs' }, options);
    return tabs.filter(tab => !isProtectedBrowserPage(tab.url, this.protectedPage)).map(tab => ({ ...tab, active: String(tab.id) === this.currentTab || (!this.currentTab && tab.active) }));
  }
  async target(args, ctx) {
    const tabs = await this.tabs(ctx);
    const tab = args.tab ? tabs.find(item => String(item.id) === String(args.tab)) : tabs.find(item => String(item.id) === this.currentTab) || tabs.find(item => item.active) || tabs[0];
    if (!tab) throw new Error('This browser tab is closed or belongs to another task. Open a page and take a fresh snapshot.');
    await guardBrowserUrl(tab.url, { ...ctx, protectedBrowserPage: this.protectedPage });
    if (this.currentTab !== String(tab.id)) this.invalidate();
    this.currentTab = String(tab.id); return tab;
  }
  invalidate() { this.refs.clear(); this.documentId = null; this.observation = null; }
  async capture(tab, ctx, query) {
    const result = await this.request({ action: 'snapshot', tab: tab.id, expectedUrl: tab.url, query }, ctx);
    await guardBrowserUrl(result.url, { ...ctx, protectedBrowserPage: this.protectedPage });
    this.refs = new Map(result.controls.map(control => [control.ref, control])); this.documentId = result.documentId;
    this.observation = createBrowserObservation({ mode: 'local', tabId: tab.id, url: result.url, documentId: result.documentId,
      controls: result.controls, context: [{ text: result.text }], omissions: { frames: null, truncated: result.controls.length >= CONTROL_DOM_LIMITS.controls || result.text.length >= CONTROL_DOM_LIMITS.text }, capabilities: EXTENSION_CAPABILITIES });
    return `Current snapshot:\n${result.title} — ${result.url}\n${result.controls.map(control => `[ref=${control.ref}] ${control.role} ${control.name}${control.disabled ? ' (disabled)' : ''}`).join('\n')}\n\n${result.text}\n\nObservation covers the main document; embedded frame controls require opening that page separately.`;
  }
  async run(args, ctx) { return formatBrowserResult(await this.execute(args, ctx)); }
  execute(args, ctx) { return executeBrowserOperation(this, args, ctx, 'local', context => this.work(args, context)); }
  async work(args, ctx) {
    if (ctx.backgroundJob && ctx.authorizeRequest) throw new Error('Extension control does not support scheduled-job network isolation yet. Choose private Chromium or the existing Chrome connection for this routine.');
    const action = args.action || 'tabs';
    if (action === 'tabs') return JSON.stringify(await this.tabs(ctx));
    if (action === 'open') {
      const url = await guardBrowserUrl(args.url, { ...ctx, protectedBrowserPage: this.protectedPage });
      ctx.onBrowserDispatch?.({ phase: 'start' });
      const result = await this.request({ action, url }, ctx);
      ctx.onBrowserDispatch?.({ phase: 'complete' }); this.invalidate(); this.currentTab = result.tabId;
      return this.capture(await this.target({ tab: result.tabId }, ctx), ctx);
    }
    const tab = await this.target(args, ctx);
    if (action === 'snapshot') return this.capture(tab, ctx, args.query);
    if (action === 'read' || action === 'find') {
      const result = await this.request({ action: 'read', tab: tab.id, expectedUrl: tab.url }, ctx);
      this.invalidate();
      const text = action === 'find' ? result.text.split('\n').filter(line => line.toLowerCase().includes(String(args.query || '').toLowerCase())).join('\n') : result.text;
      return `${result.title} — ${result.url}\n${text || 'No matching text in the captured main document.'}${result.text.length >= CONTROL_DOM_LIMITS.text ? '\nText capture limit reached.' : ''}`;
    }
    if (action === 'screenshot') {
      const result = await this.request({ action, tab: tab.id, expectedUrl: tab.url }, ctx), bytes = Buffer.from(result.data, 'base64'), file = screenshotFile(ctx.cwd);
      await fs.writeFile(file, bytes); return { type: BROWSER_SCREENSHOT_TYPE, path: file, bytes: bytes.length };
    }
    const operation = { ...args, tab: tab.id, expectedUrl: tab.url };
    if (action === 'navigate') operation.url = await guardBrowserUrl(args.url, { ...ctx, protectedBrowserPage: this.protectedPage });
    if (action === 'act' || action === 'fill_form') {
      if (!this.documentId) throw new Error(CONTROL_STALE);
      if (action === 'fill_form') operation.fields = browserFields(args.fields);
      const refs = action === 'fill_form' ? operation.fields.map(field => field.ref) : args.ref ? [args.ref] : [];
      if ((!refs.length && REF_REQUIRED_OPS.has(args.op || 'click')) || refs.some(ref => !this.refs.has(ref))) throw new Error('Use a current observed reference from a fresh snapshot.');
      operation.documentId = this.documentId;
      if ((args.op || 'click') === 'click') for (const ref of refs) {
        const control = this.refs.get(ref);
        if (control.href || control.formAction) await guardBrowserUrl(control.href || control.formAction, { ...ctx, protectedBrowserPage: this.protectedPage });
      }
      if (args.op === 'scroll') operation.deltaY = browserScrollDelta(args.text);
    } else if (!['navigate', 'back', 'forward', 'close'].includes(action)) throw new Error(`The browser extension does not support ${action}. Use supported page operations or take control in Chrome.`);
    ctx.onBrowserDispatch?.({ phase: 'start' });
    const result = await this.request(operation, ctx);
    ctx.onBrowserDispatch?.({ phase: 'complete', count: action === 'fill_form' ? operation.fields.length : 1 });
    this.invalidate();
    if (action === 'close') { this.currentTab = null; return 'Closed the browser tab.'; }
    return this.capture(await this.target({ tab: tab.id }, ctx), ctx);
  }
  async selectTab(tab) { const tabs = await this.tabs(); if (!tabs.some(item => String(item.id) === String(tab))) throw new Error('This tab is unavailable'); this.currentTab = String(tab); this.invalidate(); }
  // Passive preview never attaches a debugger or switches the user's active tab.
  async preview() { return null; }
  async close() { this.invalidate(); this.currentTab = null; }
}
