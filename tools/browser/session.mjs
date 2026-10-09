import { BrowserPluginStore } from '../../src/integrations/browser-plugins.mjs';
import { PlaywrightBrowserAdapter } from './playwright.mjs';
import { ChromeBrowserAdapter } from './chrome.mjs';
import { waitForBrowser, normalizeBrowserArgs } from './pending.mjs';
import { browserNotice, browserNeedsConnection, browserPageFailed } from '../../src/integrations/browser-errors.mjs';
import { CREDENTIAL_WAIT_MS } from '../../src/integrations/browser-credentials.mjs';
import { BROWSER_ACTIONS, BROWSER_NAVIGATION_ACTIONS, MAX_BROWSER_BATCH_STEPS, primitiveBrowserCost, unknownBrowserAction, REF_BATCH_CONTEXT, independentRefBatch } from './operations.mjs';
import { browserActionResult, browserBatchResult, formatBrowserResult, browserRecoverySuffix } from './contracts.mjs';
import { browserProgress, browserActionPhase } from '../../desktop/shared/browser-progress.mjs';
import { BROWSER_DIALOG_CHANGED, browserDialog, dialogDecision } from './dialogs.mjs';

const VALID = new Set(BROWSER_ACTIONS);
const COLLECT_RESULT = Symbol('browserBatchCollector'); // Internal result ownership; one aggregate event per model batch call.
const OPERATION_STATE = Symbol('browserOperationState'); // Shared cancellation receipt state; never serialized to the page/model.
const LOGIN_OPERATION_MS = CREDENTIAL_WAIT_MS + 60_000; // User wait plus bounded browser actions, milliseconds.
const OPERATION_TIMEOUT_MS = 5 * 60_000; // Milliseconds for a foreground browser operation; jobs use their execution deadline.
const TAKEOVER_TIMEOUT_MS = 24 * 60 * 60_000; // Milliseconds: bounded foreground takeover wait, interrupted by Stop.
const TAB_METADATA_TIMEOUT_MS = 5000; // Milliseconds to update tab metadata after navigation.
const ADAPTER_CLOSE_TIMEOUT_MS = 4000; // Milliseconds for bounded adapter/queue shutdown.
const VIEW_METADATA_TTL_MS = 2000; // Milliseconds to reuse metadata between preview ticks.
const VIEW_PROBE_TIMEOUT_MS = 1500; // Milliseconds for the adapter's preview/tab probe.
const VIEW_REQUEST_TIMEOUT_MS = 1800; // Milliseconds for the outer preview request including adapter overhead.

/** One process-wide browser session. Calls are serialized so tab selection and refs cannot race. */
export class BrowserSessionManager {
  constructor({ store = new BrowserPluginStore().load(), isolatedFactory = options => new PlaywrightBrowserAdapter(options), chromeFactory = (mcp, options) => new ChromeBrowserAdapter(mcp, options), onEvent = () => {}, onResult = () => {}, credentials = null, scopeOptions = null, chromeQueue = { tail: Promise.resolve() } } = {}) {
    this.scopeOptions = scopeOptions;
    this.scopes = new Map();
    this.chromeQueue = chromeQueue;
    this.credentials = credentials;
    this.store = store;
    this.isolatedFactory = isolatedFactory;
    this.chromeFactory = chromeFactory;
    this.onEvent = onEvent;
    this.onResult = onResult;
    this.adapters = new Map();
    this.activeMode = null;
    this.tail = Promise.resolve();
    this.operations = new Set();
    this.viewPending = null;
    this.viewUpdated = 0;
    this.viewRevision = 0; // State generation: an earlier capture cannot publish into a newer operation/tab.
    this.previewError = false;
    this.previewUpdated = 0; // Timestamp in milliseconds of the last successful preview capture.
    this.previewTabId = null; // UI selection in a job scope never changes its worker's target or refs.
    this.paused = false;
    this.resume = null;
    this.pauseGate = null;
    this.last = { mode: null, status: 'idle', tabs: [], screenshot: null, step: '', notice: null };
  }

  createScope(scope, options = {}) {
    if (this.scopes.has(scope)) return this.scopes.get(scope);
    const child = new BrowserSessionManager({ store: this.store, credentials: this.credentials,
      isolatedFactory: this.isolatedFactory, chromeFactory: this.chromeFactory, chromeQueue: this.chromeQueue,
      scopeOptions: { ...options, scope, ownedTabs: true }, onEvent: state => this.onEvent(state, scope), onResult: result => this.onResult(result, scope) });
    this.scopes.set(scope, child);
    return child;
  }

  async closeScope(scope) {
    const child = this.scopes.get(scope);
    if (!child) return false;
    await child.close(); this.scopes.delete(scope); return true;
  }

  reportPhase(phase, threadId, args = null) {
    if (!this.activeMode || threadId !== this.activeThreadId) return false;
    this.last = { ...this.last, progress: browserProgress({ phase, args, previous: this.last.progress }) };
    this.onEvent(this.last, threadId);
    return true;
  }

  #publish(result, ctx) {
    if (ctx[COLLECT_RESULT]) { ctx[COLLECT_RESULT](result); return; }
    const operation = ctx[OPERATION_STATE];
    if (operation?.published) return;
    if (operation) operation.published = true;
    try { this.onResult(result, ctx.browserThreadId); } catch {}
    try { ctx.onBrowserActionResult?.(result); } catch {}
  }

  async run(args = {}, ctx = {}) {
    args = normalizeBrowserArgs(args);
    if (this.scopeOptions) {
      const selected = this.scopeOptions.mode;
      if (args.mode && args.mode !== selected) return 'Error: Browser mode is outside this routine permission. Edit its permissions before changing browser.';
      args = { ...args, mode: selected };
    }
    const parentSignal = ctx.signal;
    const controller = new AbortController();
    const cancel = () => controller.abort();
    ctx.signal?.addEventListener('abort', cancel, { once: true });
    if (ctx.signal?.aborted) cancel();
    const operation = { controller, threadId: ctx.browserThreadId, rootArgs: args, results: [], currentArgs: args, currentIndex: 0, completed: 0, dispatched: false, published: false };
    this.operations.add(operation);
    const onDispatch = ctx.onBrowserDispatch;
    ctx = { ...ctx, signal: controller.signal, credentialTurnSignal: parentSignal, cancelBrowserRequest: cancel, [OPERATION_STATE]: operation,
      onBrowserDispatch: event => {
        if (operation.published) return;
        if (event.phase === 'start') operation.dispatched = true;
        if (event.phase === 'complete') { operation.completed += event.count ?? 1; operation.dispatched = false; }
        onDispatch?.(event);
      } };
    const failureResult = error => browserActionResult({ action: operation.currentArgs.action, error, completed: operation.completed,
      dispatched: operation.dispatched, cost: primitiveBrowserCost(operation.currentArgs) });
    const publishFailure = error => {
      const result = failureResult(error);
      operation.results[operation.currentIndex] ||= result;
      const detailed = args.action === 'batch' && Array.isArray(args.steps) && args.steps.length <= MAX_BROWSER_BATCH_STEPS
        ? browserBatchResult(args, operation.results, null) : result;
      this.#publish(detailed, ctx);
      return formatBrowserResult(detailed);
    };
    const work = this.tail.then(async () => {
      try {
        if (args.action === 'batch') {
          if (!Array.isArray(args.steps) || !args.steps.length || args.steps.length > MAX_BROWSER_BATCH_STEPS) throw new Error(`A batch needs 1 to ${MAX_BROWSER_BATCH_STEPS} steps`);
          if (args.steps.some(step => normalizeBrowserArgs(step).action === 'login')) throw new Error('Use a separate browser login call so its secure sign-in card can receive input');
          if (args.steps.some(step => !VALID.has(normalizeBrowserArgs(step).action) || normalizeBrowserArgs(step).action === 'sequence')) throw new Error('A batch accepts supported individual operations, without nested batches or sequences.');
          const lines = [];
          const steps = args.steps.map(step => normalizeBrowserArgs({ mode: args.mode, tab: args.tab, ...step }));
          const refBatch = independentRefBatch(steps);
          for (const [index, step] of steps.entries()) {
            operation.currentIndex = index; operation.currentArgs = normalizeBrowserArgs(step); operation.completed = 0; operation.dispatched = false;
            const context = { ...ctx,
              ...(ctx.config?.browserRuntimeV2 === true ? { [COLLECT_RESULT]: result => { operation.results[index] = result; } } : {}),
              ...(refBatch ? { [REF_BATCH_CONTEXT]: { steps, index, deferSnapshot: index < steps.length - 1 } } : {}) };
            try {
              if (this.pauseGate) await waitForBrowser(this.pauseGate, { signal: ctx.signal, timeoutMs: TAKEOVER_TIMEOUT_MS });
              if (ctx.signal?.aborted) throw new Error('Browser action cancelled');
              lines.push(`${index + 1}. ${await this.#one(step, context)}`);
            } catch (error) {
              operation.results[index] ||= failureResult(error);
              ctx.onBrowserError?.(error); lines.push(`${index + 1}. Error: ${error.message}. Batch stopped.`); break;
            }
          }
          const output = lines.join('\n');
          if (ctx.config?.browserRuntimeV2 === true) {
            const aggregate = browserBatchResult(args, operation.results, output);
            this.#publish(aggregate, ctx);
            this.last = { ...this.last, progress: browserProgress({ phase: this.paused ? 'waiting-for-user' : aggregate.error ? 'recovering' : 'checking', args, result: aggregate }) };
            this.onEvent(this.last, ctx.browserThreadId);
          }
          return output;
        }
        if (this.pauseGate) await waitForBrowser(this.pauseGate, { signal: ctx.signal, timeoutMs: TAKEOVER_TIMEOUT_MS });
        if (ctx.signal?.aborted) throw new Error('Browser action cancelled');
        return await this.#one(args, ctx);
      } catch (error) { ctx.onBrowserError?.(error); return ctx.config?.browserRuntimeV2 === true && !operation.published ? publishFailure(error) : `Error: ${error.message}`; }
    });
    const finished = work.finally(() => { this.operations.delete(operation); parentSignal?.removeEventListener('abort', cancel); });
    this.tail = finished.then(() => {}, () => {});
    return waitForBrowser(finished, { signal: ctx.signal, timeoutMs: ctx.backgroundJob ? null : args.action === 'login' ? LOGIN_OPERATION_MS : OPERATION_TIMEOUT_MS, onTimeout: cancel })
      .catch(error => ctx.config?.browserRuntimeV2 === true && !operation.published ? publishFailure(error) : `Error: ${error.message}`);
  }

  async #one(args, ctx) {
    args = normalizeBrowserArgs(args);
    const action = String(args?.action || 'tabs');
    if (!VALID.has(action)) throw unknownBrowserAction(action);
    if (action === 'login') {
      if (args.mode === 'local') throw new Error('Secure login supports Playwright only. Use your Chrome window to sign in manually.');
      if (!this.credentials || ctx.browserCredentialAllowed !== true) throw new Error('Secure sign-in requires the desktop app. Sign in manually; never send a password in chat.');
      args = { ...args, mode: 'isolated' };
    }
    this.store.load();
    if (action === 'login' && !this.store.get('isolated').enabled) throw new Error('Enable Playwright Browser in Plugins before using secure sign-in');
    const preferred = args.mode || this.activeMode;
    if (preferred) this.store.get(preferred);
    const mode = preferred && this.store.get(preferred).enabled ? preferred : (this.store.get('isolated').enabled ? 'isolated' : this.store.get('local').enabled ? 'local' : preferred || 'isolated');
    if (preferred && mode !== preferred && (args.ref || args.tab || action === 'act' || action === 'fill_form' || action === 'sequence')) throw new Error('The previous browser is disabled. Open the page in the enabled browser and take a fresh snapshot; its tabs and refs are different.');
    const settings = { ...this.store.get(mode), ...(this.scopeOptions ? { headless: this.scopeOptions.headless !== false } : {}) };
    if (!settings.enabled) throw new Error(`Enable ${mode === 'local' ? 'Chrome local' : 'Playwright Browser'} in Plugins → By Ankita first`);
    let adapter = this.adapters.get(mode);
    if (!adapter) {
      adapter = mode === 'isolated' ? this.isolatedFactory(this.scopeOptions || undefined) : this.chromeFactory(ctx.mcp, this.scopeOptions || undefined);
      this.adapters.set(mode, adapter);
    }
    const needsLoginOrigin = action === 'login' && !args.website && !args.url;
    const beforeTabs = ctx.authorizeBrowser || needsLoginOrigin ? await adapter.tabs({ signal: ctx.signal }) : [];
    const current = args.tab ? beforeTabs.find(tab => String(tab.id) === String(args.tab)) : beforeTabs.find(tab => tab.active) || beforeTabs[0];
    // Missing login URL uses only this adapter's actual selected tab; explicit origins still bind exactly.
    if (needsLoginOrigin && current?.url) args = { ...args, website: current.url };
    await ctx.authorizeBrowser?.(args, { mode, url: args.url || args.website || current?.url || null });
    const changed = this.activeMode !== mode;
    const progressArgs = ctx[OPERATION_STATE]?.rootArgs || args;
    const progressPrefix = ctx[OPERATION_STATE]?.results.reduce((sum, result) => sum + (result?.steps?.filter(step => step.status === 'executed').length || 0), 0) || 0;
    this.#changeView();
    this.activeMode = mode;
    this.activeThreadId = ctx.browserThreadId;
    this.previewError = false;
    this.last = { ...this.last, ...(changed ? { tabs: [], screenshot: null } : {}), mode, status: 'working', step: action, notice: null,
      progress: browserProgress({ phase: browserActionPhase(args), args: progressArgs, completed: progressPrefix }) };
    this.onEvent(this.last, ctx.browserThreadId);
    let detailedResult = null;
    try {
      const context = { ...ctx, settings, credentialSettings: () => ({ ...this.store.load().get(mode), ...(this.scopeOptions ? { headless: this.scopeOptions.headless !== false } : {}) }), credentialEnabled: () => this.store.load().get(mode).enabled, credentialTakeover: async () => { await this.takeover(true); await waitForBrowser(this.pauseGate, { signal: ctx.signal, timeoutMs: CREDENTIAL_WAIT_MS }); } };
      this.manualContext = { config: ctx.config, settings }; // Host configuration only; never retain a turn's input, approval or signal.
      let completed = 0;
      context.onBrowserPhase = phase => this.reportPhase(phase, ctx.browserThreadId, progressArgs);
      context.onBrowserDispatch = event => {
        ctx.onBrowserDispatch?.(event);
        if (ctx.signal?.aborted || ctx[OPERATION_STATE]?.published) return;
        if (event.phase === 'complete') completed += event.count ?? 1;
        this.last = { ...this.last, progress: browserProgress({ phase: event.phase === 'complete' ? 'checking' : 'acting', args: progressArgs, completed: progressPrefix + completed }) };
        this.onEvent(this.last, ctx.browserThreadId);
      };
      const execute = async () => {
        if (action === 'login') return this.credentials.login(adapter, args, context);
        const batch = context[REF_BATCH_CONTEXT];
        if (batch && typeof adapter.preflightBatch === 'function') {
          context.onBrowserPhase('checking');
          await adapter.preflightBatch(batch.index === 0 ? batch.steps : [args], context);
        } else delete context[REF_BATCH_CONTEXT];
        const detailed = ctx.config?.browserRuntimeV2 === true && typeof adapter.execute === 'function';
        const result = await waitForBrowser(detailed ? adapter.execute({ ...args, action }, context) : adapter.run({ ...args, action }, context), { signal: ctx.signal, ...(ctx.backgroundJob ? { timeoutMs: null } : {}), onTimeout: ctx.cancelBrowserRequest });
        if (!detailed) return result;
        detailedResult = result;
        if (result.error) {
          const error = result.cause || new Error(result.error.message);
          error.message += browserRecoverySuffix(result);
          throw error;
        }
        return formatBrowserResult(result);
      };
      let result;
      if (mode === 'local') {
        const work = this.chromeQueue.tail.then(() => { ctx.signal?.throwIfAborted(); return execute(); });
        this.chromeQueue.tail = work.catch(() => {});
        result = await work;
      } else result = await execute();
      if (ctx.authorizeNavigation) for (const tab of await adapter.tabs({ signal: ctx.signal })) {
        if (tab.url && tab.url !== 'about:blank') await ctx.authorizeNavigation(tab.url);
      }
      ctx.signal?.throwIfAborted();
      const tabs = typeof adapter.tabs === 'function' && ['open', 'close', 'tabs', 'login', ...BROWSER_NAVIGATION_ACTIONS].includes(action) ? await waitForBrowser(adapter.tabs({ signal: ctx.signal }), { signal: ctx.signal, timeoutMs: TAB_METADATA_TIMEOUT_MS }) : this.last.tabs;
      const loginAttention = action === 'login' && result?.status === 'attention';
      if (detailedResult) this.#publish(detailedResult, ctx);
      this.#changeView();
      this.last = { ...this.last, mode, status: this.paused ? 'takeover' : loginAttention ? 'error' : 'ready', tabs, step: this.paused ? 'You are in control' : action, notice: loginAttention ? browserNotice(null, 'login') : null,
        progress: browserProgress({ phase: this.paused || loginAttention ? 'waiting-for-user' : 'checking', args: progressArgs,
          completed: progressPrefix + (detailedResult?.steps.filter(step => step.status === 'executed').length ?? completed),
          result: detailedResult ? { ...detailedResult, steps: null } : null }) };
      this.onEvent(this.last, ctx.browserThreadId);
      return typeof result === 'string' ? result : JSON.stringify(result);
    } catch (error) {
      if (detailedResult) {
        if (!detailedResult.error) {
          const failure = browserActionResult({ action, error, cost: detailedResult.steps.length,
            completed: detailedResult.steps.filter(step => step.status === 'executed').length, observation: detailedResult.observation, timings: detailedResult.timings });
          detailedResult = { ...failure, evidence: detailedResult.evidence, artifacts: detailedResult.artifacts, attention: detailedResult.attention };
        }
        this.#publish(detailedResult, ctx);
      }
      // Teardown is for a dead transport or an explicit Stop — not for a slow
      // call. A timed-out snapshot on a heavy page must not kill a healthy
      // connection (and, for Chrome, disconnect the shared MCP server); it only
      // invalidates interaction state so the next snapshot is fresh.
      const notice = browserNotice(error);
      this.#changeView();
      const transportDead = notice.kind === 'connection';
      if (ctx.signal?.aborted || transportDead) {
        if (mode === 'local' && this.scopes.size) adapter.invalidate?.();
        else await waitForBrowser(Promise.resolve(adapter.close?.()), { timeoutMs: ADAPTER_CLOSE_TIMEOUT_MS }).catch(() => {});
        this.adapters.delete(mode);
        this.last = { ...this.last, tabs: [], screenshot: null };
      } else {
        if (!error.preserveRefs) { try { adapter.invalidate?.(); } catch {} }
      }
      const cancelled = ctx.signal?.aborted && !/timed out/i.test(error.message);
      const pageFailed = browserPageFailed(notice);
      // The bounded live-view poll refreshes tab metadata. A failed navigation
      // must not wait on another transport request before releasing the queue.
      if (pageFailed) this.last = { ...this.last, screenshot: null };
      this.last = { ...this.last, status: cancelled ? 'stopped' : browserNeedsConnection(notice) || pageFailed ? 'error' : this.paused ? 'takeover' : 'ready', step: cancelled ? 'Browser action cancelled' : action, notice: cancelled ? null : notice,
        progress: browserProgress({ phase: cancelled ? 'stopped' : 'recovering', args: progressArgs,
          completed: progressPrefix + (detailedResult?.steps.filter(step => step.status === 'executed').length ?? 0),
          result: detailedResult ? { ...detailedResult, steps: null } : { status: 'failed' }, previous: this.last.progress }) };
      this.onEvent(this.last, ctx.browserThreadId);
      throw error;
    }
  }

  async view({ automation = false, minIntervalMs = 0 } = {}) {
    if (automation) {
      const adapter = this.activeMode && this.adapters.get(this.activeMode);
      if (!adapter) return { ...this.last, tabs: [], screenshot: null };
      const tabs = await waitForBrowser(adapter.tabs({ timeoutMs: VIEW_PROBE_TIMEOUT_MS }), { timeoutMs: VIEW_REQUEST_TIMEOUT_MS });
      const screenshot = tabs.length && typeof adapter.preview === 'function' ? await waitForBrowser(adapter.preview(), { timeoutMs: VIEW_REQUEST_TIMEOUT_MS }) : null;
      return { ...this.last, tabs, screenshot }; // Proof capture never reads/writes the UI selection cache.
    }
    if (this.viewPending) return this.viewPending;
    this.viewPending = this.#view(minIntervalMs).finally(() => { this.viewPending = null; });
    return this.viewPending;
  }

  #changeView() { this.viewRevision++; this.viewUpdated = 0; }

  #dialogView(adapter) {
    const dialog = adapter.attention?.()?.dialog;
    if (!dialog || (this.previewTabId && this.previewTabId !== dialog.tabId)) return null;
    const bounded = browserDialog(dialog.type, dialog.message, dialog.tabId, dialog.id);
    // Dialog text is private IPC view data; it never enters broadcast progress, this.last or history.
    return { ...this.last, dialog: bounded, notice: null,
      progress: browserProgress({ phase: 'waiting-for-user', result: { status: this.last.progress?.outcome, attention: { dialog: bounded } }, previous: this.last.progress }) };
  }

  async #view(minIntervalMs) {
    const revision = this.viewRevision;
    const adapter = this.activeMode && this.adapters.get(this.activeMode);
    if (!adapter) return this.last;
    if (!this.store.load().get(this.activeMode).enabled) return { ...this.last, status: 'stopped', step: 'Browser plugin is disabled', screenshot: null };
    let tabs = this.last.tabs;
    try {
      if (Date.now() - this.viewUpdated > VIEW_METADATA_TTL_MS && typeof adapter.tabs === 'function') {
        tabs = await waitForBrowser(adapter.tabs({ timeoutMs: VIEW_PROBE_TIMEOUT_MS }), { timeoutMs: VIEW_REQUEST_TIMEOUT_MS });
        this.viewUpdated = Date.now();
      }
      if (revision !== this.viewRevision) return this.last;
      if (this.previewTabId && !tabs.some(tab => String(tab.id) === this.previewTabId)) this.previewTabId = null;
      const dialogView = this.#dialogView(adapter);
      if (dialogView) return { ...dialogView, tabs };
      if (this.last.screenshot && Number.isFinite(minIntervalMs) && Date.now() - this.previewUpdated < minIntervalMs) return { ...this.last, tabs };
      const screenshot = typeof adapter.preview === 'function' && tabs.length ? await waitForBrowser(adapter.preview(this.previewTabId ? { tab: this.previewTabId } : {}), { timeoutMs: VIEW_REQUEST_TIMEOUT_MS }) : null;
      if (this.adapters.get(this.activeMode) !== adapter || revision !== this.viewRevision) return this.last;
      this.last = { ...this.last, ...(this.previewError && this.last.status === 'error' ? { status: this.paused ? 'takeover' : 'ready', step: this.paused ? 'You are in control' : 'Browser connected', notice: null } : {}), tabs: this.previewTabId ? tabs.map(tab => ({ ...tab, active: String(tab.id) === this.previewTabId })) : tabs, screenshot: screenshot || this.last.screenshot };
      this.previewError = false;
      if (screenshot) this.previewUpdated = Date.now();
      return this.last;
    } catch (error) {
      const dialogView = this.#dialogView(adapter);
      if (dialogView && this.adapters.get(this.activeMode) === adapter && revision === this.viewRevision) return dialogView;
      // A preview failure is visible but never launches Chrome or replays an action.
      // The last good frame is kept so one slow tick does not blank the preview.
      if (this.adapters.get(this.activeMode) === adapter && revision === this.viewRevision && this.last.status !== 'working') {
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
      this.last = { ...this.last, status: 'takeover', step: 'You are in control', progress: browserProgress({ phase: 'waiting-for-user', previous: this.last.progress }) };
      this.onEvent(this.last, this.activeThreadId);
    } else if (!enabled && this.paused) {
      this.paused = false;
      this.resume?.();
      this.pauseGate = null;
      this.resume = null;
      this.adapters.get(this.activeMode)?.invalidate?.();
      this.last = { ...this.last, status: 'ready', step: 'Handed back to Ankita', progress: browserProgress({ phase: 'checking', previous: this.last.progress }) };
      this.onEvent(this.last, this.activeThreadId);
    }
    return this.last;
  }

  async decideDialog(input = {}) {
    if (!this.paused) throw new Error('Take control before deciding a page dialog');
    const adapter = this.adapters.get(this.activeMode), dialog = adapter?.attention?.()?.dialog;
    if (!dialog?.id || input.id !== dialog.id || (this.previewTabId && this.previewTabId !== dialog.tabId)) throw new Error(BROWSER_DIALOG_CHANGED);
    const args = { action: 'handle_dialog', tab: dialog.tabId, dialog_id: input.id, decision: input.decision,
      ...(input.prompt_text !== undefined ? { prompt_text: input.prompt_text } : {}) };
    dialogDecision(args, dialog);
    const controller = new AbortController(), threadId = this.activeThreadId;
    const operation = { controller, threadId }; this.operations.add(operation);
    try {
      // Human control bypasses the paused model queue, like userInput; the native dialog identity owns this decision.
      const result = await waitForBrowser(Promise.resolve().then(async () => {
        controller.signal.throwIfAborted();
        if (this.adapters.get(this.activeMode) !== adapter || adapter.attention?.()?.dialog?.id !== input.id) throw new Error(BROWSER_DIALOG_CHANGED);
        return adapter.execute(args, { ...this.manualContext, signal: controller.signal });
      }), { signal: controller.signal, timeoutMs: OPERATION_TIMEOUT_MS, onTimeout: () => controller.abort() });
      controller.signal.throwIfAborted();
      if (result.error) throw new Error(result.error.message);
      this.#changeView();
      this.last = { ...this.last, status: 'takeover', notice: null,
        progress: browserProgress({ phase: 'waiting-for-user', args, result }) };
      this.onEvent(this.last, threadId);
      return this.view();
    } finally { this.operations.delete(operation); }
  }

  async userInput(input) {
    if (!this.paused) throw new Error('Take control before interacting with the browser');
    const adapter = this.adapters.get(this.activeMode);
    if (this.activeMode !== 'isolated' || !adapter?.userInput) throw new Error('Use the Chrome window directly while taking control');
    await adapter.userInput(this.previewTabId ? { ...input, tab: this.previewTabId } : input);
    return true;
  }

  async selectTab(tab) {
    const adapter = this.adapters.get(this.activeMode);
    if (!adapter?.selectTab) throw new Error('No browser tab is open');
    this.#changeView();
    if (this.scopeOptions?.independentPreview) {
      const tabs = await adapter.tabs({ timeoutMs: VIEW_PROBE_TIMEOUT_MS });
      if (!tabs.some(item => String(item.id) === String(tab))) throw new Error('This browser tab has closed');
      this.previewTabId = String(tab);
      this.last = { ...this.last, tabs: tabs.map(item => ({ ...item, active: String(item.id) === this.previewTabId })), screenshot: null };
      await this.viewPending;
    } else await adapter.selectTab(String(tab));
    const view = await this.view(); this.onEvent(this.last, this.activeThreadId); return view;
  }

  async close({ includeScopes = true } = {}) {
    if (includeScopes) await Promise.all([...this.scopes.keys()].map(scope => this.closeScope(scope)));
    this.#changeView();
    this.cancel(includeScopes ? undefined : this.activeThreadId || 'foreground');
    if (this.paused) await this.takeover(false);
    await Promise.all([...this.adapters.entries()].map(([mode, adapter]) => {
      if (!includeScopes && mode === 'local' && this.scopes.size) { adapter.invalidate?.(); return Promise.resolve(); }
      return waitForBrowser(Promise.resolve(adapter.close?.()), { timeoutMs: ADAPTER_CLOSE_TIMEOUT_MS }).catch(() => {});
    }));
    await waitForBrowser(this.tail, { timeoutMs: ADAPTER_CLOSE_TIMEOUT_MS }).catch(() => {});
    this.adapters.clear();
    this.activeMode = null;
    this.manualContext = null;
    this.previewTabId = null;
    this.last = { mode: null, status: 'idle', tabs: [], screenshot: null, step: '', notice: null };
    this.onEvent(this.last, this.activeThreadId);
  }

  cancel(threadId) {
    for (const [scope, child] of this.scopes) if (!threadId || scope === threadId) child.cancel();
    this.credentials?.clear?.(threadId);
    for (const operation of this.operations) if (!threadId || operation.threadId === threadId) operation.controller.abort();
    if (this.activeMode && (!threadId || threadId === this.activeThreadId)) this.reportPhase('stopped', this.activeThreadId);
    if (this.paused && (!threadId || threadId === this.activeThreadId)) {
      this.paused = false;
      this.resume?.(); this.resume = null; this.pauseGate = null;
      this.adapters.get(this.activeMode)?.invalidate?.();
      this.last = { ...this.last, status: 'stopped', step: 'Browser action cancelled' };
      this.onEvent(this.last, this.activeThreadId);
    }
  }
}
