import { BrowserPluginStore } from '../../src/integrations/browser-plugins.mjs';
import { PlaywrightBrowserAdapter } from './playwright.mjs';
import { ChromeBrowserAdapter } from './chrome.mjs';
import { waitForBrowser, normalizeBrowserArgs } from './pending.mjs';
import { browserNotice, browserNeedsConnection } from '../../src/integrations/browser-errors.mjs';

const VALID = new Set(['open', 'snapshot', 'act', 'fill_form', 'read', 'tabs', 'screenshot', 'close']);

/** One process-wide browser session. Calls are serialized so tab selection and refs cannot race. */
export class BrowserSessionManager {
  constructor({ store = new BrowserPluginStore().load(), isolatedFactory = () => new PlaywrightBrowserAdapter(), chromeFactory = mcp => new ChromeBrowserAdapter(mcp), onEvent = () => {} } = {}) {
    this.store = store;
    this.isolatedFactory = isolatedFactory;
    this.chromeFactory = chromeFactory;
    this.onEvent = onEvent;
    this.adapters = new Map();
    this.activeMode = null;
    this.tail = Promise.resolve();
    this.operations = new Set();
    this.viewPending = null;
    this.viewUpdated = 0;
    this.previewError = false;
    this.paused = false;
    this.resume = null;
    this.pauseGate = null;
    this.last = { mode: null, status: 'idle', tabs: [], screenshot: null, step: '', notice: null };
  }

  async run(args = {}, ctx = {}) {
    const parentSignal = ctx.signal;
    const controller = new AbortController();
    const cancel = () => controller.abort();
    ctx.signal?.addEventListener('abort', cancel, { once: true });
    if (ctx.signal?.aborted) cancel();
    const operation = { controller, threadId: ctx.browserThreadId };
    this.operations.add(operation);
    ctx = { ...ctx, signal: controller.signal, cancelBrowserRequest: cancel };
    const work = this.tail.then(async () => {
      try {
        if (args.action === 'batch') {
          if (!Array.isArray(args.steps) || !args.steps.length || args.steps.length > 10) throw new Error('A batch needs 1 to 10 steps');
          const lines = [];
          for (const [index, step] of args.steps.entries()) {
            if (this.pauseGate) await waitForBrowser(this.pauseGate, { signal: ctx.signal, timeoutMs: 24 * 60 * 60_000 });
            if (ctx.signal?.aborted) throw new Error('Browser action cancelled');
            try { lines.push(`${index + 1}. ${await this.#one({ mode: args.mode, ...step }, ctx)}`); }
            catch (error) { lines.push(`${index + 1}. Error: ${error.message}. Batch stopped.`); break; }
          }
          return lines.join('\n');
        }
        if (this.pauseGate) await waitForBrowser(this.pauseGate, { signal: ctx.signal, timeoutMs: 24 * 60 * 60_000 });
        if (ctx.signal?.aborted) throw new Error('Browser action cancelled');
        return await this.#one(args, ctx);
      } catch (error) { return `Error: ${error.message}`; }
    });
    const finished = work.finally(() => { this.operations.delete(operation); parentSignal?.removeEventListener('abort', cancel); });
    this.tail = finished.then(() => {}, () => {});
    return waitForBrowser(finished, { signal: ctx.signal, timeoutMs: 5 * 60_000, onTimeout: cancel }).catch(error => `Error: ${error.message}`);
  }

  async #one(args, ctx) {
    args = normalizeBrowserArgs(args);
    const action = String(args?.action || 'tabs');
    if (!VALID.has(action)) throw new Error(`Unknown browser action: ${action}`);
    this.store.load();
    const preferred = args.mode || this.activeMode;
    if (preferred) this.store.get(preferred);
    const mode = preferred && this.store.get(preferred).enabled ? preferred : (this.store.get('isolated').enabled ? 'isolated' : this.store.get('local').enabled ? 'local' : preferred || 'isolated');
    if (preferred && mode !== preferred && (args.ref || args.tab || action === 'act' || action === 'fill_form')) throw new Error('The previous browser is disabled. Open the page in the enabled browser and take a fresh snapshot; its tabs and refs are different.');
    const settings = this.store.get(mode);
    if (!settings.enabled) throw new Error(`Enable ${mode === 'local' ? 'Chrome local' : 'Playwright Browser'} in Plugins → By Ankita first`);
    let adapter = this.adapters.get(mode);
    if (!adapter) {
      adapter = mode === 'isolated' ? this.isolatedFactory() : this.chromeFactory(ctx.mcp);
      this.adapters.set(mode, adapter);
    }
    const changed = this.activeMode !== mode;
    this.activeMode = mode;
    this.activeThreadId = ctx.browserThreadId;
    this.previewError = false;
    this.last = { ...this.last, ...(changed ? { tabs: [], screenshot: null } : {}), mode, status: 'working', step: action, notice: null };
    this.onEvent(this.last, ctx.browserThreadId);
    try {
      const result = await waitForBrowser(adapter.run({ ...args, action }, { ...ctx, settings }), { signal: ctx.signal, onTimeout: ctx.cancelBrowserRequest });
      const tabs = typeof adapter.tabs === 'function' && ['open', 'close', 'tabs'].includes(action) ? await waitForBrowser(adapter.tabs({ signal: ctx.signal }), { signal: ctx.signal, timeoutMs: 5000 }) : this.last.tabs;
      this.last = { ...this.last, mode, status: this.paused ? 'takeover' : 'ready', tabs, step: this.paused ? 'You are in control' : action, notice: null };
      this.onEvent(this.last, ctx.browserThreadId);
      return typeof result === 'string' ? result : JSON.stringify(result);
    } catch (error) {
      // Teardown is for a dead transport or an explicit Stop — not for a slow
      // call. A timed-out snapshot on a heavy page must not kill a healthy
      // connection (and, for Chrome, disconnect the shared MCP server); it only
      // invalidates interaction state so the next snapshot is fresh.
      const notice = browserNotice(error);
      const transportDead = notice.kind === 'connection';
      if (ctx.signal?.aborted || transportDead) {
        await waitForBrowser(Promise.resolve(adapter.close?.()), { timeoutMs: 4000 }).catch(() => {});
        this.adapters.delete(mode);
        this.last = { ...this.last, tabs: [], screenshot: null };
      } else {
        if (!error.preserveRefs) { try { adapter.invalidate?.(); } catch {} }
      }
      const cancelled = ctx.signal?.aborted && !/timed out/i.test(error.message);
      this.last = { ...this.last, status: cancelled ? 'stopped' : browserNeedsConnection(notice) ? 'error' : this.paused ? 'takeover' : 'ready', step: cancelled ? 'Browser action cancelled' : action, notice: cancelled ? null : notice };
      this.onEvent(this.last, ctx.browserThreadId);
      throw error;
    }
  }

  async view() {
    if (this.viewPending) return this.viewPending;
    this.viewPending = this.#view().finally(() => { this.viewPending = null; });
    return this.viewPending;
  }

  async #view() {
    const adapter = this.activeMode && this.adapters.get(this.activeMode);
    if (!adapter) return this.last;
    if (!this.store.load().get(this.activeMode).enabled) return { ...this.last, status: 'stopped', step: 'Browser plugin is disabled', screenshot: null };
    let tabs = this.last.tabs;
    try {
      if (Date.now() - this.viewUpdated > 2000 && typeof adapter.tabs === 'function') {
        tabs = await waitForBrowser(adapter.tabs({ timeoutMs: 1500 }), { timeoutMs: 1800 });
        this.viewUpdated = Date.now();
      }
      const screenshot = typeof adapter.preview === 'function' && tabs.length ? await waitForBrowser(adapter.preview(), { timeoutMs: 1800 }) : null;
      if (this.adapters.get(this.activeMode) !== adapter) return this.last;
      this.last = { ...this.last, ...(this.previewError && this.last.status === 'error' ? { status: this.paused ? 'takeover' : 'ready', step: this.paused ? 'You are in control' : 'Browser connected', notice: null } : {}), tabs, screenshot: screenshot || this.last.screenshot };
      this.previewError = false;
      return this.last;
    } catch (error) {
      // A preview failure is visible but never launches Chrome or replays an action.
      // The last good frame is kept so one slow tick does not blank the preview.
      if (this.adapters.get(this.activeMode) === adapter && this.last.status !== 'working') {
        this.previewError = true;
        this.last = { ...this.last, status: 'error', step: 'Preview unavailable', notice: browserNotice(error, 'preview') };
      }
      return this.last;
    }
  }

  async takeover(enabled) {
    if (enabled && !this.paused) {
      this.paused = true;
      this.pauseGate = new Promise(resolve => { this.resume = resolve; });
      this.adapters.get(this.activeMode)?.invalidate?.();
      this.last = { ...this.last, status: 'takeover', step: 'You are in control' };
      this.onEvent(this.last, null);
    } else if (!enabled && this.paused) {
      this.paused = false;
      this.resume?.();
      this.pauseGate = null;
      this.resume = null;
      this.adapters.get(this.activeMode)?.invalidate?.();
      this.last = { ...this.last, status: 'ready', step: 'Handed back to Ankita' };
      this.onEvent(this.last, null);
    }
    return this.last;
  }

  async userInput(input) {
    if (!this.paused) throw new Error('Take control before interacting with the browser');
    const adapter = this.adapters.get(this.activeMode);
    if (this.activeMode !== 'isolated' || !adapter?.userInput) throw new Error('Use the Chrome window directly while taking control');
    await adapter.userInput(input);
    return true;
  }

  async selectTab(tab) {
    const adapter = this.adapters.get(this.activeMode);
    if (!adapter?.selectTab) throw new Error('No browser tab is open');
    await adapter.selectTab(String(tab));
    this.last = { ...this.last, tabs: await adapter.tabs() };
    return this.last;
  }

  async close() {
    this.cancel();
    if (this.paused) await this.takeover(false);
    await Promise.all([...this.adapters.values()].map(adapter => waitForBrowser(Promise.resolve(adapter.close?.()), { timeoutMs: 4000 }).catch(() => {})));
    await waitForBrowser(this.tail, { timeoutMs: 4000 }).catch(() => {});
    this.adapters.clear();
    this.activeMode = null;
    this.last = { mode: null, status: 'idle', tabs: [], screenshot: null, step: '', notice: null };
    this.onEvent(this.last, this.activeThreadId);
  }

  cancel(threadId) {
    for (const operation of this.operations) if (!threadId || operation.threadId === threadId) operation.controller.abort();
    if (this.paused && (!threadId || threadId === this.activeThreadId)) {
      this.paused = false;
      this.resume?.(); this.resume = null; this.pauseGate = null;
      this.adapters.get(this.activeMode)?.invalidate?.();
      this.last = { ...this.last, status: 'stopped', step: 'Browser action cancelled' };
      this.onEvent(this.last, this.activeThreadId);
    }
  }
}
