import fs from 'node:fs';
import { randomUUID } from 'node:crypto';
import os from 'node:os';
import path from 'node:path';
import { CHROME_MCP_ID } from '../../src/integrations/browser-plugins.mjs';
import { guardBrowserUrl, screenshotFile } from './playwright.mjs';
import { waitForBrowser } from './pending.mjs';
import { BrowserReferenceError, CHROME_REF_PATTERN, INTERACTIVE_ROLES, SNAPSHOT_LIMITS, browserFields, recoverBrowserReference, withBrowserSnapshot } from './refs.mjs';
import { BROWSER_SCREENSHOT_TYPE } from './screenshots.mjs';


// Read-only actions safe to run twice: a retry only re-lists tabs and re-reads,
// never replays a mutation or creates a second tab.
const CHEAP_RETRY_ACTIONS = new Set(['snapshot', 'read', 'tabs', 'screenshot']);
// A stale tab selection (closed tab, empty cache), as opposed to a dead transport.
const STALE_TAB_ERROR = /no chrome tab is open|no such page|page .*closed|tab .*closed|not found/i;
// Fixed internal focus function: resolve the registered UID without triggering
// a click. Shadow-root activeElement also covers controls inside open roots.
const FOCUS_KEY_TARGET = '(element) => { element.focus(); return element.getRootNode().activeElement === element; }';
// MCP evaluate_script returns its JSON value inside a fenced response.
const FOCUS_CONFIRMED = /```json\s*true\s*```/;
const KEY_TARGET_FOCUS_ERROR = 'Browser target could not receive keyboard focus; inspect the current controls before continuing.';

/** Uses the existing MCP transport; never opens a CDP socket from Ankita. */
export class ChromeBrowserAdapter {
  constructor(mcp, { ensureConnected } = {}) {
    this.mcp = mcp;
    this.ensureConnected = ensureConnected;
    this.pageId = null;
    this.epoch = 0;
    this.refs = new Map();
    this.refPageId = null;
    this.cachedTabs = [];
    this.previewPending = null;
    this.connection = null;
  }

  #ready() {
    if (!this.mcp?.has?.(CHROME_MCP_ID)) throw new Error('Chrome is not connected. Open Plugins → By Ankita and start the Chrome connection.');
  }

  async #call(name, args = {}, ctx = {}) {
    this.#ready();
    const options = { signal: ctx.signal, timeoutMs: ctx.timeoutMs || 15_000 };
    const result = await waitForBrowser(this.mcp.callTool(`mcp__${CHROME_MCP_ID}__${name}`, args, options), options);
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
    this.cachedTabs = tabs;
    return tabs;
  }

  async #page(tab, ctx = {}) {
    if (tab != null) this.pageId = Number(tab);
    if (!Number.isInteger(this.pageId)) {
      const tabs = this.cachedTabs.length ? this.cachedTabs : await this.tabs(ctx);
      if (!tabs.length) throw new Error('No Chrome tab is open');
      this.pageId = Number((tabs.find(item => item.active) || tabs[0]).id);
    }
    return this.pageId;
  }

  #snapshotResult(raw, pageId, args = {}) {
    this.refs.clear(); this.epoch++; this.refPageId = pageId;
    let characters = 0;
    let index = 0;
    // Include complete lines; only actual controls get actionable refs.
    return raw.split('\n').filter(line => {
      if (args.query && !line.toLowerCase().includes(String(args.query).toLowerCase())) return false;
      characters += line.length + 1;
      return characters <= SNAPSHOT_LIMITS.characters;
    }).map(line => line.replace(/uid=([^\s]+)\s+(\S+)/g, (_match, uid, role) => {
      if (!INTERACTIVE_ROLES.includes(role.toLowerCase())) return role;
      const ref = `${this.epoch}-${++index}`;
      this.refs.set(ref, uid);
      return `[ref=${ref}] ${role}`;
    })).join('\n');
  }

  #uid(ref, pageId) {
    const value = String(ref || '');
    const uid = this.refs.get(value);
    if (!uid || this.refPageId !== pageId || !value.startsWith(`${this.epoch}-`)) throw new BrowserReferenceError(value, CHROME_REF_PATTERN);
    return uid;
  }

  #actionResult(receipt, result, pageId, ctx) {
    this.refs.clear(); this.epoch++;
    if (/uid=\S+/.test(result)) return `${receipt}\nCurrent snapshot:\n${this.#snapshotResult(result, pageId)}`;
    return withBrowserSnapshot(receipt, () => this.#runOnce({ action: 'snapshot', tab: String(pageId) }, ctx));
  }

  async selectTab(tab) {
    this.pageId = Number(tab);
    await this.#call('select_page', { pageId: this.pageId, bringToFront: true });
    this.refs.clear(); this.epoch++;
  }

  async run(args, ctx) {
    try {
      return await this.#runOnce(args, ctx);
    } catch (error) {
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

  async #runOnce(args, ctx) {
    ctx ||= {};
    // Fail fast with the actionable message when there is no connection and no
    // way to establish one on demand: tab resolution below would otherwise mask
    // a missing connection as an empty tab list.
    if (!this.mcp?.has?.(CHROME_MCP_ID) && typeof this.ensureConnected !== 'function') this.#ready();
    // Probe before an action. Only this read can be retried: mutations are never replayed.
    const newlyConnected = !this.mcp?.has?.(CHROME_MCP_ID);
    if (newlyConnected) {
      this.invalidate(); this.pageId = null; this.cachedTabs = [];
      if (this.ensureConnected) await this.ensureConnected(ctx);
    }
    const connection = this.mcp?.servers?.get(CHROME_MCP_ID)?.client;
    if (connection && connection !== this.connection) {
      this.invalidate(); this.pageId = null; this.cachedTabs = []; this.connection = connection;
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
    if (action === 'open') {
      const url = await guardBrowserUrl(args.url, ctx);
      const result = await call('new_page', { url });
      this.epoch++;
      this.refs.clear();
      const tabs = await this.tabs(ctx);
      const tab = tabs.find(item => item.url === url) || tabs.at(-1);
      if (tab) this.pageId = Number(tab.id);
      return withBrowserSnapshot(result, () => this.#runOnce({ action: 'snapshot' }, ctx));
    }
    if (action === 'tabs') return this.cachedTabs;
    const pageId = await this.#page(args.tab, ctx);
    if (action === 'snapshot' || action === 'read') {
      const raw = await call('take_snapshot', { pageId });
      return this.#snapshotResult(raw, pageId, args);
    }
    if (action === 'fill_form') {
      const fields = browserFields(args.fields);
      const elements = fields.map(field => ({ uid: this.#uid(field.ref, pageId), value: field.text }));
      const result = await call('fill_form', { pageId, elements, includeSnapshot: true });
      return this.#actionResult(`Filled ${fields.length} fields.`, result, pageId, ctx);
    }
    if (action === 'act') {
      const ref = String(args.ref || '');
      const uid = this.#uid(ref, pageId);
      const op = String(args.op || 'click');
      let result;
      const act = (name, values) => call(name, { pageId, ...values, includeSnapshot: true });
      if (op === 'click') result = await act('click', { uid });
      else if (op === 'fill' || op === 'select') result = await act('fill', { uid, value: String(args.text ?? '') });
      else if (op === 'type') {
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
      this.pageId = null;
      this.refs.clear();
      this.epoch++;
      return `Closed Chrome tab ${pageId}`;
    }
    throw new Error(`Unknown browser action: ${action}`);
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

  invalidate() { this.refs.clear(); this.epoch++; }

  async close() {
    this.refs.clear();
    this.pageId = null;
    this.cachedTabs = [];
    if (this.mcp?.has?.(CHROME_MCP_ID)) await this.mcp.disconnect(CHROME_MCP_ID);
  }
}
