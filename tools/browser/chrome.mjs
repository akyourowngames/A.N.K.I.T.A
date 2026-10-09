import fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import { CHROME_MCP_ID } from '../../src/integrations/browser-plugins.mjs';
import { guardBrowserUrl, screenshotFile } from './playwright.mjs';
import { waitForBrowser } from './pending.mjs';
import { BrowserReferenceError, CHROME_REF_PATTERN, CREDENTIAL_ATTRIBUTE, FILL_NO_CHANGE_TEXT, BATCH_CHECK_NO_CHANGE_TEXT, INTERACTIVE_ROLES, SNAPSHOT_LIMITS, SNAPSHOT_LIMIT_REACHED, assertFillControl, assertSelectControl, browserFields, browserScrollDelta, formFillFailure, inspectFillControl, recoverBrowserReference, scrollBrowserControl, withBrowserSnapshot } from './refs.mjs';
import { BROWSER_SCREENSHOT_TYPE } from './screenshots.mjs';
import { browserObservation, executeBrowserOperation, formatBrowserResult } from './contracts.mjs';
import { CHROME_DISPATCH_OPERATIONS, BROWSER_NAVIGATION_ACTIONS, BROWSER_HISTORY_DIRECTIONS, unknownBrowserAction, deferBatchSnapshot } from './operations.mjs';
import { createBrowserObservation, textObservation, TEXT_BROWSER_CAPABILITIES } from './observations.mjs';
import { extractPageText, pageTextResult, pageTextCaptureOptions, PAGE_TEXT_LIMITS } from './page-find.mjs';
import { SEQUENCE_UNSUPPORTED } from './sequence.mjs';
import { chromeDialog, dialogDecision, dialogText, BROWSER_DIALOG_GUIDANCE, BROWSER_DIALOG_INTERRUPTED } from './dialogs.mjs';
import { BROWSER_TRANSFER_ACTIONS, CHROME_TRANSFER_UNSUPPORTED } from './transfers.mjs';
import { inspectBrowserControls, BROWSER_CONTROL_FLAGS, BROWSER_CONTROL_PREFIX, BROWSER_CONTROL_FLAG_CHARACTERS, BATCH_TARGETS_PROBE, assertBatchTarget } from './refs.mjs';


// Read-only actions safe to run twice: a retry only re-lists tabs and re-reads,
// never replays a mutation or creates a second tab.
const CHEAP_RETRY_ACTIONS = new Set(['snapshot', 'read', 'tabs', 'screenshot']);
// A stale tab selection (closed tab, empty cache), as opposed to a dead transport.
const STALE_TAB_ERROR = /no chrome tab is open|no such page|page .*closed|tab .*closed|not found/i;
const CHROME_SNAPSHOT_NODE = /^([ \t]*)uid=([^\s]+)\s+(\S+)(.*)$/; // Native MCP line prefix only; UID-looking page labels are data.
const CHROME_CONTROL_STATE_LIMIT = 16; // Native UID resolutions/observation: enrich likely current targets without an expensive 160-element probe. Targeted snapshots cover later controls.
const CHROME_INTERACTIVE_ROLES = new Set([...INTERACTIVE_ROLES, 'disclosuretriangle']); // Chrome AX's native role for the clickable summary of a details element.
// Fixed internal focus function: resolve the registered UID without triggering
// a click. Shadow-root activeElement also covers controls inside open roots.
const FOCUS_KEY_TARGET = '(element) => { element.focus(); return element.getRootNode().activeElement === element; }';
// MCP evaluate_script returns its JSON value inside a fenced response.
const FOCUS_CONFIRMED = /```json\s*true\s*```/;
const KEY_TARGET_FOCUS_ERROR = 'Browser target could not receive keyboard focus; inspect the current controls before continuing.';
// Fixed read-only function, UID-bound by MCP; inspect every target in one round trip.
const INSPECT_FILL_TARGETS = `(...elements) => elements.map(element => (${inspectFillControl.toString()})(element, ${JSON.stringify(CREDENTIAL_ATTRIBUTE)}, true))`;
const MCP_JSON_RESULT = /```json\s*([\s\S]*?)\s*```/; // MCP's documented JSON result envelope.
const INTERRUPTED_FILL_RESULT = /\bopened a dialog\b|\bremaining elements were not filled\b/i; // Upstream can report partial writes without throwing.
const NAVIGATION_REFUSED = /^Unable to navigate\b/m; // Native MCP reports navigation failures as receipt text rather than throwing.
function historyTarget(direction) {
  const history = globalThis.navigation;
  return history?.entries()?.find(entry => entry.index === history.currentEntry.index + direction)?.url || null;
}

/** Uses the existing MCP transport; never opens a CDP socket from Ankita. */
export class ChromeBrowserAdapter {
  constructor(mcp, { ensureConnected, ownedTabs = false } = {}) {
    this.ownedTabs = ownedTabs ? new Set() : null;
    this.mcp = mcp;
    this.ensureConnected = ensureConnected;
    this.pageId = null;
    this.epoch = 0;
    this.refs = new Map();
    this.refPageId = null;
    this.cachedTabs = [];
    this.previewPending = null;
    this.connection = null;
    this.dialogs = new Map(); // Only native MCP attention is stored, scoped to its page ID.
  }

  #ready() {
    if (!this.mcp?.has?.(CHROME_MCP_ID)) throw new Error('Chrome is not connected. Open Plugins → By Ankita and start the Chrome connection.');
  }

  #capabilities() {
    // Runtime catalogue discovery is authoritative when available; lightweight legacy transports have no catalogue.
    const pageText = typeof this.mcp?.findTool !== 'function' || Boolean(this.mcp.findTool(`mcp__${CHROME_MCP_ID}__evaluate_script`));
    return { ...TEXT_BROWSER_CAPABILITIES, pageTextSearch: pageText, chunkedRead: pageText,
      dialogs: typeof this.mcp?.findTool === 'function' && Boolean(this.mcp.findTool(`mcp__${CHROME_MCP_ID}__handle_dialog`)) };
  }

  attention() { const dialog = this.dialogs.get(this.pageId); return dialog ? { dialog } : null; }

  #rememberDialog(pageId, dialog) {
    const previous = this.dialogs.get(Number(pageId));
    // MCP supplies no native event identity: retain a token only while its same attention remains observed.
    const same = previous?.type === dialog.type && previous?.message === dialog.message;
    this.dialogs.set(Number(pageId), { ...dialog, id: same ? previous.id : randomUUID() });
    this.invalidate();
  }

  async #call(name, args = {}, ctx = {}) {
    this.#ready();
    const options = { signal: ctx.signal, timeoutMs: ctx.timeoutMs || 15_000 };
    if (CHROME_DISPATCH_OPERATIONS.has(name)) {
      this.textResult = null;
      ctx.onBrowserDispatch?.({ phase: 'start', action: name });
    }
    const result = await waitForBrowser(this.mcp.callTool(`mcp__${CHROME_MCP_ID}__${name}`, args, options), options);
    if (args.pageId !== undefined && (CHROME_DISPATCH_OPERATIONS.has(name) || name === 'take_snapshot')) {
      const dialog = chromeDialog(String(result), args.pageId);
      if (dialog) this.#rememberDialog(args.pageId, dialog);
      else if (name === 'take_snapshot' && !String(result).startsWith('Error:')) this.dialogs.delete(Number(args.pageId));
    }
    if (String(result).startsWith('Error:')) throw new Error(result);
    return String(result);
  }

  async tabs(ctx = {}) {
    if (!this.mcp?.has?.(CHROME_MCP_ID)) {
      if (this.cachedTabs.length) throw new Error('Chrome connection was lost. The next browser request will reconnect automatically.');
      return [];
    }
    const text = await this.#call('list_pages', {}, ctx);
    const tabs = [];
    for (const line of text.split('\n')) {
      const titled = /^\s*(\d+)\s*:\s*(.+?)\s*\((https?:\/\/[^\s)]+)\)(.*)$/.exec(line);
      const plain = titled ? null : /^\s*(\d+)\s*:\s*(https?:\/\/\S+|about:\S+)(.*)$/.exec(line);
      const match = titled || plain;
      if (match) tabs.push({
        id: match[1], url: (titled ? match[3] : match[2]).slice(0, 500),
        title: (titled ? match[2] : '').slice(0, 160),
        active: Number(match[1]) === this.pageId || (!this.pageId && /\[selected\]/.test(titled ? match[4] : match[3])),
      });
    }
    this.allTabs = tabs;
    const selected = tabs.find(tab => text.split('\n').some(line => new RegExp(`^\\s*${tab.id}\\s*:`).test(line) && line.includes('[selected]')));
    if (selected) {
      const dialog = chromeDialog(text, selected.id);
      if (dialog) this.#rememberDialog(selected.id, dialog);
      // list_pages is global: absence of page-specific attention cannot prove a dialog closed.
    }
    this.cachedTabs = this.ownedTabs ? tabs.filter(tab => this.ownedTabs.has(Number(tab.id))) : tabs;
    return this.cachedTabs;
  }

  async #page(tab, ctx = {}) {
    if (this.ownedTabs && tab != null && !this.ownedTabs.has(Number(tab))) throw new Error('Tab is not owned by this browser job');
    if (tab != null && Number(tab) !== this.pageId) { this.invalidate(); this.pageId = Number(tab); }
    if (!Number.isInteger(this.pageId)) {
      const tabs = this.cachedTabs.length ? this.cachedTabs : await this.tabs(ctx);
      if (!tabs.length) throw new Error('No Chrome tab is open');
      this.pageId = Number((tabs.find(item => item.active) || tabs[0]).id);
    }
    return this.pageId;
  }

  async #snapshotResult(raw, pageId, args = {}, ctx = {}) {
    this.refs.clear(); this.epoch++; this.refPageId = pageId;
    let characters = 0;
    let index = 0;
    let omittedControls = 0, omittedText = false;
    const lines = [], controls = [];
    // Characters: reserve the shared recovery notice and its newline without publishing partial refs.
    const contentBudget = SNAPSHOT_LIMITS.characters - SNAPSHOT_LIMIT_REACHED.length - 1;
    for (const line of raw.split('\n')) {
      if (args.query && !line.toLowerCase().includes(String(args.query).toLowerCase())) continue;
      const node = line.match(CHROME_SNAPSHOT_NODE);
      const interactive = node && CHROME_INTERACTIVE_ROLES.has(node[3].toLowerCase());
      if (interactive && index >= SNAPSHOT_LIMITS.elements) { omittedControls++; continue; }
      const ref = interactive ? `${this.epoch}-${index + 1}` : null;
      const projected = node ? `${node[1]}${BROWSER_CONTROL_PREFIX}${ref ? `[ref=${ref}] ` : ''}${node[3]}${node[4]}` : line;
      const reserved = projected.length + (interactive ? BROWSER_CONTROL_FLAG_CHARACTERS : 0) + 1;
      if (characters + reserved > contentBudget) {
        omittedText = true;
        if (interactive) omittedControls++;
        continue;
      }
      lines.push(projected); characters += reserved;
      if (!interactive) continue;
      index++;
      this.refs.set(ref, node[2]);
      let name = node[4].trim();
      const quoted = /^"(?:\\.|[^"\\])*"/.exec(name);
      if (quoted) { try { name = JSON.parse(quoted[0]); } catch {} }
      // Native UID owns the target. DOM/actionability unavailable from text remains explicitly unknown.
      controls.push({ ref, frameId: null, role: node[3], name: name.slice(0, SNAPSHOT_LIMITS.label), states: {}, editable: null, actionable: null });
    }
    if (controls.length && typeof this.mcp?.findTool === 'function' && this.#capabilities().pageTextSearch) {
      try {
        const targets = [...this.refs.values()].slice(0, CHROME_CONTROL_STATE_LIMIT);
        const result = await this.#call('evaluate_script', { pageId, function: `(...elements) => (${inspectBrowserControls.toString()})(elements)`, args: targets }, ctx);
        const states = JSON.parse(MCP_JSON_RESULT.exec(result)?.[1] || result);
        if (Array.isArray(states) && states.length === targets.length) {
          for (const [index, state] of states.entries()) {
            if (!state?.states || typeof state.actionable !== 'boolean' || typeof state.editable !== 'boolean') continue;
            const control = controls[index]; Object.assign(control, state);
            control.ref = [...this.refs.keys()][index];
            const flags = BROWSER_CONTROL_FLAGS.filter(flag => state.states[flag]);
            if (flags.length) { const lineIndex = lines.findIndex(line => line.trimStart().startsWith(`${BROWSER_CONTROL_PREFIX}[ref=${control.ref}] `)); if (lineIndex >= 0) lines[lineIndex] += ` [${flags.join(', ')}]`; }
          }
        }
      } catch { /* A missing native UID/state probe stays unknown; it never replays an action. */ }
    }
    const truncated = omittedText || omittedControls > 0;
    if (truncated) lines.push(SNAPSHOT_LIMIT_REACHED);
    const text = lines.join('\n');
    const transitional = browserObservation({ output: text, mode: 'local', tabId: pageId });
    this.observation = createBrowserObservation({ mode: 'local', tabId: pageId, url: this.cachedTabs.find(tab => Number(tab.id) === pageId)?.url || transitional?.url || '',
      controls, omissions: { truncated, controls: omittedControls }, capabilities: this.#capabilities() });
    return text;
  }

  #uid(ref, pageId) {
    const value = String(ref || '');
    const uid = this.refs.get(value);
    if (!uid || this.refPageId !== pageId || !value.startsWith(`${this.epoch}-`)) throw new BrowserReferenceError(value, CHROME_REF_PATTERN);
    return uid;
  }

  async #validateFill(fields, pageId, ctx, nativeSelect = false) {
    const uids = fields.map(field => this.#uid(field.ref, pageId));
    const result = await this.#call('evaluate_script', { pageId, function: INSPECT_FILL_TARGETS, args: uids }, ctx);
    let controls;
    try { controls = JSON.parse(MCP_JSON_RESULT.exec(result)?.[1]); } catch {}
    if (!Array.isArray(controls) || controls.length !== fields.length || controls.some(control => typeof control?.tag !== 'string' || !Object.hasOwn(control, 'issue'))) throw new Error(`Chrome could not validate the fill targets. ${FILL_NO_CHANGE_TEXT}`);
    controls.forEach((control, index) => {
      if (nativeSelect) assertSelectControl(control, fields[index].ref, CHROME_REF_PATTERN);
      assertFillControl(control, fields[index], CHROME_REF_PATTERN, ctx?.backgroundJob);
    });
    return uids;
  }

  async #actionResult(receipt, result, pageId, ctx, count = 1) {
    if (INTERRUPTED_FILL_RESULT.test(result) || this.dialogs.has(pageId)) throw new Error(BROWSER_DIALOG_INTERRUPTED);
    ctx.onBrowserDispatch?.({ phase: 'complete', count, action: 'act' });
    if (deferBatchSnapshot(ctx)) return receipt; // Keep the native UID snapshot until the last independent batch step; node resolution still checks the actual target.
    this.refs.clear(); this.epoch++;
    if (/uid=\S+/.test(result)) return `${receipt}\nCurrent snapshot:\n${await this.#snapshotResult(result, pageId, {}, ctx)}`;
    return withBrowserSnapshot(receipt, () => this.#runOnce({ action: 'snapshot', tab: String(pageId) }, ctx));
  }

  async selectTab(tab) {
    if (this.ownedTabs && !this.ownedTabs.has(Number(tab))) throw new Error('Tab is not owned by this browser job');
    this.pageId = Number(tab);
    await this.#call('select_page', { pageId: this.pageId, bringToFront: true });
    this.invalidate();
  }

  async preflightBatch(steps, ctx = {}) {
    const pageId = await this.#page(steps[0].tab, ctx);
    try {
      const targets = steps.flatMap(step => (step.action === 'fill_form' ? browserFields(step.fields) : [{ ref: step.ref, text: String(step.text ?? '') }]).map(field => ({ step, field })));
      const uids = targets.map(({ field }) => this.#uid(field.ref, pageId));
      const result = await this.#call('evaluate_script', { pageId, function: BATCH_TARGETS_PROBE, args: uids }, ctx);
      let probes;
      try { probes = JSON.parse(MCP_JSON_RESULT.exec(result)?.[1]); } catch {}
      if (!Array.isArray(probes) || probes.length !== targets.length) throw new BrowserReferenceError(targets[0].field.ref, CHROME_REF_PATTERN, BATCH_CHECK_NO_CHANGE_TEXT);
      for (const [index, target] of targets.entries()) assertBatchTarget(probes[index], target.step, target.field, CHROME_REF_PATTERN, ctx.backgroundJob);
    } catch (error) { return recoverBrowserReference(formFillFailure(error, false), () => this.#runOnce({ action: 'snapshot', tab: String(pageId) }, ctx)); }
  }

  async run(args, ctx) {
    try {
      return await this.#runOnce(args, ctx);
    } catch (error) {
      const dialog = this.dialogs.get(this.pageId);
      if (dialog && ['snapshot', 'read', 'find'].includes(args.action)) return this.#dialogObservation(dialog);
      if (error instanceof BrowserReferenceError) return recoverBrowserReference(error, () => this.#runOnce({ action: 'snapshot', tab: args.tab }, ctx));
      // Cheap retry, once, for read-only actions whose tab went stale: refresh
      // the tab list and re-resolve instead of tearing down the connection.
      if (!CHEAP_RETRY_ACTIONS.has(args?.action) || !STALE_TAB_ERROR.test(error?.message || '')) throw error;
      this.invalidate();
      this.pageId = null;
      this.cachedTabs = [];
      return await this.#runOnce(args, ctx);
    }
  }

  #dialogObservation(dialog) {
    this.observation = createBrowserObservation({ mode: 'local', tabId: dialog.tabId, url: this.cachedTabs.find(tab => tab.id === dialog.tabId)?.url || '', capabilities: this.#capabilities() });
    return dialogText(dialog);
  }

  async execute(args, ctx = {}) {
    return executeBrowserOperation(this, args, ctx, 'local', context => this.run(args, context));
  }

  async observe(args = {}, ctx = {}) {
    const result = await this.execute({ ...args, action: 'snapshot' }, ctx);
    if (result.error) throw new Error(String(formatBrowserResult(result)));
    return result.observation;
  }

  async #runOnce(args, ctx) {
    ctx ||= {};
    if (args.action === 'sequence') throw new Error(SEQUENCE_UNSUPPORTED);
    // Fail fast with the actionable message when there is no connection and no
    // way to establish one on demand: tab resolution below would otherwise mask
    // a missing connection as an empty tab list.
    if (!this.mcp?.has?.(CHROME_MCP_ID) && typeof this.ensureConnected !== 'function') this.#ready();
    // Probe before an action. Only this read can be retried: mutations are never replayed.
    const newlyConnected = !this.mcp?.has?.(CHROME_MCP_ID);
    if (newlyConnected) {
      this.invalidate(); this.pageId = null; this.cachedTabs = []; this.dialogs.clear();
      if (this.ensureConnected) await this.ensureConnected(ctx);
    }
    const connection = this.mcp?.servers?.get(CHROME_MCP_ID)?.client;
    if (connection && connection !== this.connection) {
      this.invalidate(); this.pageId = null; this.cachedTabs = []; this.dialogs.clear(); this.connection = connection;
    }
    try { await this.tabs({ ...ctx, timeoutMs: newlyConnected ? 15_000 : 5000 }); }
    catch (error) {
      if (ctx.signal?.aborted || !this.ensureConnected || !/connection|not connected|disconnected|closed|exited|timed out|connect.*Chrome|browser.*not.*running/i.test(error.message)) throw error;
      this.invalidate(); this.pageId = null; this.cachedTabs = [];
      await this.ensureConnected({ ...ctx, reconnect: true });
      this.connection = this.mcp?.servers?.get(CHROME_MCP_ID)?.client || null;
      await this.tabs({ ...ctx, timeoutMs: 5000 });
    }
    const call = (name, values) => this.#call(name, values, ctx);
    const action = args.action;
    if (BROWSER_TRANSFER_ACTIONS.includes(action)) throw new Error(CHROME_TRANSFER_UNSUPPORTED);
    if (action === 'open') {
      const url = await guardBrowserUrl(args.url, ctx);
      const before = new Set((this.allTabs || []).map(tab => tab.id));
      const result = await call('new_page', { url });
      ctx.onBrowserDispatch?.({ phase: 'complete', action });
      this.epoch++;
      this.refs.clear();
      await this.tabs(ctx);
      const tab = this.allTabs.find(item => !before.has(item.id) && item.url === url) || this.allTabs.find(item => !before.has(item.id));
      if (this.ownedTabs && !tab) throw new Error('Chrome did not return a newly created job tab');
      if (tab && this.ownedTabs) { this.ownedTabs.add(Number(tab.id)); await this.tabs(ctx); }
      if (tab) this.pageId = Number(tab.id);
      return withBrowserSnapshot(result, () => this.#runOnce({ action: 'snapshot' }, ctx));
    }
    if (action === 'tabs') return this.cachedTabs;
    const pageId = await this.#page(args.tab, ctx);
    if (action === 'handle_dialog') {
      if (!this.#capabilities().dialogs) throw new Error('This Chrome connection does not support native dialog handling. Use take control.');
      if (!this.dialogs.has(pageId)) { try { await call('take_snapshot', { pageId }); } catch (error) { if (!this.dialogs.has(pageId)) throw error; } }
      const decision = dialogDecision(args, this.dialogs.get(pageId));
      const result = await call('handle_dialog', { pageId, action: decision, ...(args.prompt_text !== undefined ? { promptText: args.prompt_text } : {}) });
      this.dialogs.delete(pageId);
      this.invalidate();
      ctx.onBrowserDispatch?.({ phase: 'complete', action });
      return withBrowserSnapshot(`${result}\nRead back the page outcome before continuing.`, () => this.#runOnce({ action: 'snapshot', tab: String(pageId) }, ctx));
    }
    const dialog = this.dialogs.get(pageId);
    if (dialog) {
      if (['snapshot', 'read', 'find'].includes(action)) {
        // This page-specific probe also detects a decision made manually outside Ankita.
        try { await call('take_snapshot', { pageId }); } catch (error) { if (!this.dialogs.has(pageId)) throw error; }
        if (this.dialogs.has(pageId)) return this.#dialogObservation(this.dialogs.get(pageId));
      }
      else if (action !== 'close') throw new Error(BROWSER_DIALOG_GUIDANCE);
    }
    if (BROWSER_NAVIGATION_ACTIONS.includes(action)) {
      if (typeof this.mcp?.findTool === 'function' && !this.mcp.findTool(`mcp__${CHROME_MCP_ID}__navigate_page`)) throw new Error('This Chrome connection does not support native navigation.');
      if (action === 'navigate') await guardBrowserUrl(args.url, ctx);
      else if (ctx.authorizeNavigation || ctx.settings?.allowedSites?.length || ctx.settings?.blockedSites?.length || process.env.BROWSER_ALLOWLIST || process.env.BROWSER_BLOCKLIST) {
        const raw = await call('evaluate_script', { pageId, function: `() => (${historyTarget.toString()})(${BROWSER_HISTORY_DIRECTIONS[action]})` });
        let target; try { target = JSON.parse(MCP_JSON_RESULT.exec(raw)?.[1] || raw); } catch {}
        if (typeof target !== 'string' || !target) throw new Error('Chrome cannot prove the history destination under this navigation policy. Use navigate with an approved URL.');
        await guardBrowserUrl(target, ctx);
      }
      this.invalidate();
      const result = await call('navigate_page', { pageId, type: action === 'navigate' ? 'url' : action,
        ...(action === 'navigate' ? { url: args.url } : {}), handleBeforeUnload: 'dismiss' });
      if (NAVIGATION_REFUSED.test(result)) throw new Error(result);
      ctx.onBrowserDispatch?.({ phase: 'complete', action });
      await this.tabs(ctx);
      const current = this.cachedTabs.find(tab => Number(tab.id) === pageId);
      if (current?.url) await guardBrowserUrl(current.url, ctx);
      return withBrowserSnapshot(result, () => this.#runOnce({ action: 'snapshot', tab: String(pageId) }, ctx));
    }
    if (action === 'find' || action === 'read') {
      if (!this.#capabilities().pageTextSearch) throw new Error('This Chrome connection does not support bounded page text capture. Use snapshot or take control.');
      const raw = await call('evaluate_script', { pageId, function: `() => (${extractPageText.toString()})(${JSON.stringify(pageTextCaptureOptions(args))})` });
      let source;
      try { source = JSON.parse(MCP_JSON_RESULT.exec(raw)?.[1] || raw); } catch {}
      if (!source || typeof source.text !== 'string' || typeof source.sourceUrl !== 'string' || typeof source.truncated !== 'boolean') throw new Error('Chrome returned invalid page text data');
      const result = pageTextResult({ sources: [{ ...source, frameId: null, tabId: pageId, documentId: null }], args, previous: this.textResult });
      result.output += '\nChrome text capture covers the main document; child-frame text is not captured by this adapter.';
      this.textResult = result;
      this.observation = textObservation({ result, mode: 'local', tabId: pageId, capabilities: this.#capabilities() });
      return result.output;
    }
    if (action === 'snapshot' || action === 'read') {
      const raw = await call('take_snapshot', { pageId });
      return this.#snapshotResult(raw, pageId, args, ctx);
    }
    if (action === 'fill_form') {
      const fields = browserFields(args.fields);
      const uids = await this.#validateFill(fields, pageId, ctx);
      const elements = fields.map((field, index) => ({ uid: uids[index], value: field.text }));
      let result;
      try { result = await call('fill_form', { pageId, elements, includeSnapshot: !deferBatchSnapshot(ctx) }); }
      catch (error) { throw formFillFailure(error, true); }
      return this.#actionResult(`Filled ${fields.length} fields.`, result, pageId, ctx, fields.length);
    }
    if (action === 'act') {
      const ref = String(args.ref || '');
      const uid = this.#uid(ref, pageId);
      const op = String(args.op || 'click');
      let result;
      const act = (name, values) => call(name, { pageId, ...values, includeSnapshot: !deferBatchSnapshot(ctx) });
      if (op === 'click') result = await act('click', { uid });
      else if (op === 'fill' || op === 'select') {
        await this.#validateFill([{ ref, text: String(args.text ?? '') }], pageId, ctx, op === 'select');
        result = await act('fill', { uid, value: String(args.text ?? '') });
      }
      else if (op === 'type') {
        if (ctx.backgroundJob) await this.#validateFill([{ ref, text: String(args.text ?? '') }], pageId, ctx);
        await call('click', { pageId, uid });
        // type_text has no includeSnapshot parameter; read the next refs only
        // after this keyboard mutation succeeds, without replaying the text.
        result = await call('type_text', { pageId, text: String(args.text ?? '') });
      } else if (op === 'press') {
        const focused = await call('evaluate_script', { pageId, function: FOCUS_KEY_TARGET, args: [uid] });
        if (!FOCUS_CONFIRMED.test(focused)) throw new Error(KEY_TARGET_FOCUS_ERROR);
        result = await act('press_key', { key: String(args.text || 'Enter') });
      }
      else if (op === 'hover') result = await act('hover', { uid });
      else if (op === 'scroll') {
        ctx.signal?.throwIfAborted();
        ctx.onBrowserDispatch?.({ phase: 'start', action: 'act', op });
        result = await call('evaluate_script', { pageId, function: `(element) => (${scrollBrowserControl.toString()})(element, ${browserScrollDelta(args.text)})`, args: [uid] });
      }
      else if (op === 'drag') {
        const to_uid = this.#uid(args.to_ref, pageId);
        result = await act('drag', { from_uid: uid, to_uid });
      } else throw new Error(`Chrome does not support ${op} through this tool`);
      // Upstream can include the resulting snapshot in the mutation response: one
      // MCP round trip instead of probing/listing and taking a second snapshot.
      return this.#actionResult(`${op} complete.`, result, pageId, ctx);
    }
    if (action === 'screenshot') {
      const file = screenshotFile(ctx.cwd);
      const temporary = path.join(os.tmpdir(), `ankita-browser-shot-${randomUUID()}.png`);
      try {
        await call('take_screenshot', { pageId, filePath: temporary });
        fs.copyFileSync(temporary, file);
      } finally { fs.rmSync(temporary, { force: true }); }
      // Structured receipt shared with the isolated backend: surfaced as an
      // image artifact by the desktop work-review; never open with read_file.
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
      await call('close_page', { pageId });
      this.dialogs.delete(pageId);
      ctx.onBrowserDispatch?.({ phase: 'complete', action });
      this.ownedTabs?.delete(pageId);
      this.pageId = null;
      this.refs.clear();
      this.epoch++;
      return `Closed Chrome tab ${pageId}`;
    }
    throw unknownBrowserAction(action);
  }

  async preview(options = {}) {
    if (this.previewPending) return this.previewPending;
    this.previewPending = this.#preview(options).finally(() => { this.previewPending = null; });
    return this.previewPending;
  }

  async #preview(options = {}) {
    this.#ready();
    // Refresh the tab list first: background view ticks run with no other
    // action, so a tab the user closed in real Chrome must not poison every
    // preview until the next explicit call. A cached pageId absent from the
    // fresh list is dropped so the active tab is used instead.
    const tabs = await this.tabs({ timeoutMs: options.timeoutMs || 1500 });
    if (!tabs.some(tab => Number(tab.id) === this.pageId)) this.pageId = null;
    const pageId = await this.#page();
    this.#ready();
    const shotTimeout = { timeoutMs: options.timeoutMs || 1500 };
    const result = await waitForBrowser(this.mcp.callToolResult(`mcp__${CHROME_MCP_ID}__take_screenshot`, { pageId, format: 'jpeg', quality: 45 }, shotTimeout), shotTimeout);
    if (result.isError) throw new Error(result.text || 'Chrome preview failed');
    const image = result.raw?.content?.find(item => item.type === 'image');
    if (!image?.data || !['image/jpeg', 'image/png', 'image/webp'].includes(image.mimeType)) throw new Error('Chrome returned no preview image');
    return `data:${image.mimeType};base64,${image.data}`;
  }

  invalidate() { this.refs.clear(); this.epoch++; this.observation = null; this.textResult = null; }

  async close() {
    this.dialogs.clear();
    if (this.ownedTabs) {
      for (const pageId of this.ownedTabs) await this.#call('close_page', { pageId }).catch(() => {});
      this.ownedTabs.clear(); this.invalidate(); this.pageId = null; this.cachedTabs = [];
      return;
    }
    this.refs.clear();
    this.pageId = null;
    this.cachedTabs = [];
    if (this.mcp?.has?.(CHROME_MCP_ID)) await this.mcp.disconnect(CHROME_MCP_ID);
  }
}
