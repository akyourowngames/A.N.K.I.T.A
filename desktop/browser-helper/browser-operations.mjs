import { pageOperation } from './page-operations.mjs';
import { keyEvents } from './keyboard.mjs';
import { isPageUrl } from './protocol.mjs';
import { CONTROL_DOM_LIMITS, CONTROL_SCOPE_ATTRIBUTE, CONTROL_STALE, CONTROL_DEBUG_VERSION, CONTROL_LOAD_POLL_MS, CONTROL_LOAD_TIMEOUT_MS, CONTROL_EXECUTOR_STATE } from './control-protocol.mjs';

/** Extension-only executor. Page code cannot call it or receive pairing credentials. */
export class ExtensionBrowserOperations {
  constructor(api = chrome) { this.api = api; this.owners = new Map(); this.revokedDebug = new Set(); this.attached = new Set();
    this.ready = this.restore();
    api.debugger?.onDetach.addListener((source, reason) => { this.attached.delete(source.tabId); if (reason === 'canceled_by_user') { this.revokedDebug.add(source.tabId); void this.persist(); } });
  }
  async restore() {
    const state = (await this.api.storage?.session?.get(CONTROL_EXECUTOR_STATE))?.[CONTROL_EXECUTOR_STATE];
    if (state) { this.owners = new Map(state.owners || []); this.revokedDebug = new Set(state.revoked || []); }
  }
  persist() {
    const state = { owners: [...this.owners], revoked: [...this.revokedDebug] };
    this.saving = (this.saving || Promise.resolve()).then(() => this.api.storage?.session?.set({ [CONTROL_EXECUTOR_STATE]: state }));
    return this.saving;
  }
  async allowDebugger() { await this.ready; this.revokedDebug.clear(); await this.persist(); }
  async idle(tabId, signal) {
    const deadline = Date.now() + CONTROL_LOAD_TIMEOUT_MS;
    while (Date.now() < deadline) { signal?.throwIfAborted(); const tab = await this.api.tabs.get(tabId); if (tab.status !== 'loading') return tab; await new Promise(resolve => setTimeout(resolve, CONTROL_LOAD_POLL_MS)); }
    throw Object.assign(new Error('The page is still loading. Inspect it before another action.'), { dispatched: true });
  }
  async execute(request, signal, beforeDispatch = async () => {}) {
    await this.ready; signal?.throwIfAborted();
    const check = async () => {
      signal?.throwIfAborted(); await beforeDispatch(); signal?.throwIfAborted();
      if (request.expectedUrl && (await this.api.tabs.get(Number(request.tab))).url !== request.expectedUrl) throw Object.assign(new Error(CONTROL_STALE), { dispatched: false });
      signal?.throwIfAborted();
    };
    const { action, scope, ownedTabs } = request;
    if (typeof scope !== 'string' || !scope) throw Object.assign(new Error('Browser task identity is missing'), { dispatched: false });
    if (action === 'tabs') return (await this.api.tabs.query({})).filter(tab => isPageUrl(tab.url) && (!ownedTabs || this.owners.get(tab.id) === scope)).map(tab => ({ id: String(tab.id), title: tab.title, url: tab.url, active: tab.active }));
    if (action === 'open') {
      if (!isPageUrl(request.url)) throw Object.assign(new Error('Only ordinary HTTP or HTTPS webpages can open'), { dispatched: false });
      await check(); const tab = await this.api.tabs.create({ url: request.url, active: false });
      this.owners.set(tab.id, scope); await this.persist(); await this.idle(tab.id, signal);
      return { tabId: String(tab.id) };
    }
    const tabId = Number(request.tab);
    if (!Number.isSafeInteger(tabId) || (ownedTabs && this.owners.get(tabId) !== scope)) throw Object.assign(new Error('This task does not own that browser tab'), { dispatched: false });
    const tab = await this.api.tabs.get(tabId);
    if (!isPageUrl(tab.url)) throw Object.assign(new Error('Browser settings and extension pages cannot be controlled'), { dispatched: false });
    if (request.expectedUrl && request.expectedUrl !== tab.url) throw Object.assign(new Error(CONTROL_STALE), { dispatched: false });
    if (action === 'close') { await check(); await this.api.tabs.remove(tabId); this.owners.delete(tabId); await this.persist(); return { ok: true }; }
    if (['navigate', 'back', 'forward'].includes(action)) {
      await check();
      if (action === 'navigate') { if (!isPageUrl(request.url)) throw Object.assign(new Error('Only HTTP and HTTPS navigation is supported'), { dispatched: false }); await this.api.tabs.update(tabId, { url: request.url }); }
      else await this.api.tabs[action === 'back' ? 'goBack' : 'goForward'](tabId);
      await this.idle(tabId, signal); return { tabId: String(tabId) };
    }
    if (action === 'screenshot') {
      return this.withDebugger(tabId, async () => {
        const result = await this.api.debugger.sendCommand({ tabId }, 'Page.captureScreenshot', { format: 'png' });
        return { data: result.data };
      }, check);
    }
    const invoke = async extra => {
      await check();
      const entries = await this.api.scripting.executeScript({ target: { tabId }, world: 'ISOLATED', func: pageOperation,
        args: [{ ...request, ...extra, limits: CONTROL_DOM_LIMITS, stateKey: CONTROL_SCOPE_ATTRIBUTE, staleMessage: CONTROL_STALE }] });
      const result = entries[0]?.result;
      if (!result) throw Object.assign(new Error('The page returned no observation'), { dispatched: false });
      if (result.error) throw Object.assign(new Error(result.error), { dispatched: result.dispatched === true });
      return result;
    };
    if (action === 'act' && (request.op === 'press' || request.trusted)) {
      let events;
      if (request.op === 'press') events = keyEvents(String(request.key || request.text || ''), (await this.api.runtime.getPlatformInfo()).os);
      return this.withDebugger(tabId, async () => {
        // Re-observe the target after attachment, which may have awaited user/browser work.
        const point = await invoke({ inspectTarget: true, focusTarget: request.op === 'press' });
        if (request.op === 'press') {
          await check(); await this.api.debugger.sendCommand({ tabId }, 'Input.dispatchKeyEvent', events[0]);
          // Release an already dispatched key even if Stop arrives, so a modifier cannot remain stuck.
          await this.api.debugger.sendCommand({ tabId }, 'Input.dispatchKeyEvent', events[1]);
        } else {
          await check();
          await this.api.debugger.sendCommand({ tabId }, 'Input.dispatchMouseEvent', { type: 'mousePressed', ...point, button: 'left', clickCount: 1 });
          await this.api.debugger.sendCommand({ tabId }, 'Input.dispatchMouseEvent', { type: 'mouseReleased', ...point, button: 'left', clickCount: 1 });
        }
        return { ok: true };
      }, check);
    }
    return invoke({});
  }
  async withDebugger(tabId, work, check) {
    if (this.revokedDebug.has(tabId)) throw Object.assign(new Error('You cancelled deeper browser control. Reconnect from the extension before using it again.'), { dispatched: false });
    await this.api.debugger.attach({ tabId }, CONTROL_DEBUG_VERSION); this.attached.add(tabId);
    try { await check(); return await work(); }
    finally { if (this.attached.delete(tabId)) await this.api.debugger.detach({ tabId }).catch(() => {}); }
  }
  async disconnect() { await Promise.all([...this.attached].map(tabId => this.api.debugger.detach({ tabId }).catch(() => {}))); this.attached.clear(); }
}
