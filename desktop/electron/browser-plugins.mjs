import { spawn } from 'node:child_process';
import { createRequire } from 'node:module';
import path from 'node:path';
import { BrowserPluginStore, BROWSER_FILE, CHROME_MCP_ID, browserPluginOverview, chromeMcpCommand, chromeInstallNeeded } from '../../src/integrations/browser-plugins.mjs';
import { McpStore } from '../../src/integrations/mcp-store.mjs';
import { MCP_FILE } from '../../src/core/config.mjs';
import { waitForBrowser } from '../../tools/browser/pending.mjs';

const require = createRequire(import.meta.url);

// Handshake budgets (ms): a warm connect only negotiates, while a first-ever
// connect also downloads the MCP package through npx.
const CHROME_WARM_INIT_TIMEOUT_MS = 25_000;
const CHROME_COLD_INSTALL_TIMEOUT_MS = 120_000;

/** Main-process boundary for setup and health. Browser execution lives in BrowserSessionManager. */
export class DesktopBrowserPlugins {
  constructor({ browserFile = BROWSER_FILE, mcpFile = MCP_FILE, mcp = null, approvals = null, onChange = () => {}, onProgress = () => {}, fetchImpl = fetch } = {}) {
    this.browserFile = browserFile;
    this.mcpFile = mcpFile;
    this.mcp = mcp;
    this.approvals = approvals;
    this.onChange = onChange;
    this.onProgress = onProgress;
    this.fetchImpl = fetchImpl;
    this.installing = null;
    this.connecting = null;
    this.connectionController = null;
  }

  store() { return new BrowserPluginStore(this.browserFile).load(); }
  async overview() { return browserPluginOverview(this.store(), this.mcp); }

  async setEnabled({ mode, enabled } = {}) {
    const settings = this.store().setEnabled(mode, enabled);
    if (mode === 'local') {
      if (!enabled) this.connectionController?.abort();
      const configured = new McpStore(this.mcpFile).load();
      if (configured.find(CHROME_MCP_ID)) configured.setEnabled(CHROME_MCP_ID, enabled);
      if (!enabled && this.mcp?.has?.(CHROME_MCP_ID)) await this.mcp.disconnect(CHROME_MCP_ID);
    }
    this.onChange();
    return settings;
  }

  async setHeadless({ headless } = {}) { const result = this.store().setHeadless(headless); this.onChange(); return result; }
  async changeSiteRule({ mode, kind, site, add } = {}) { const result = this.store().changeSiteRule(mode, kind, site, add); this.onChange(); return result; }

  async configureChrome({ connection = 'profile', port = 9222 } = {}) {
    const settings = this.store().setChromeMode(connection, port);
    const mcpStore = new McpStore(this.mcpFile).load();
    const old = mcpStore.find(CHROME_MCP_ID);
    const command = chromeMcpCommand(settings);
    if (!old || old.command !== command.command || JSON.stringify(old.args) !== JSON.stringify(command.args) || !old.hidden || !old.manualStart) {
      if (this.mcp?.has?.(CHROME_MCP_ID)) await this.mcp.disconnect(CHROME_MCP_ID);
      if (old) mcpStore.remove(CHROME_MCP_ID);
      mcpStore.add({ id: CHROME_MCP_ID, name: 'Chrome local', ...command, hidden: true, manualStart: true });
      if (!this.store().get('local').enabled) mcpStore.setEnabled(CHROME_MCP_ID, false);
    }
    this.onChange();
    return settings;
  }

  async startChrome({ signal, browserThreadId = 'browser-setup', reconnect = true } = {}) {
    signal?.throwIfAborted();
    if (!this.store().get('local').enabled) throw new Error('Enable Chrome local first');
    if (this.connecting) return waitForBrowser(this.connecting, { signal });
    const controller = new AbortController();
    const cancel = () => controller.abort();
    signal?.addEventListener('abort', cancel, { once: true });
    this.connectionController = controller;
    this.connecting = this.#connectChrome({ signal: controller.signal, browserThreadId, reconnect }).finally(() => {
      signal?.removeEventListener('abort', cancel); this.connecting = null; this.connectionController = null;
    });
    return this.connecting;
  }

  async #connectChrome({ signal, browserThreadId, reconnect }) {
    const plugin = this.store().get('local');
    if (!plugin.enabled) throw new Error('Enable Chrome local first');
    if (!this.mcp) throw new Error('MCP manager is unavailable');
    await this.configureChrome({ connection: plugin.connection, port: plugin.port });
    const store = new McpStore(this.mcpFile).load();
    const record = store.find(CHROME_MCP_ID);
    if (!store.isApproved(record)) {
      if (!this.approvals) throw new Error('Chrome connection needs approval in the desktop app');
      const cancelApproval = () => this.approvals.cancelThread(browserThreadId);
      signal.addEventListener('abort', cancelApproval, { once: true });
      let allowed;
      try {
        allowed = await waitForBrowser(this.approvals.request(browserThreadId, 'chrome-devtools-mcp', `Start Chrome browser connection\n\n${record.command} ${record.args.join(' ')}\n\nThis server can inspect and control Chrome. Chrome may ask for a second permission when attaching to your active session.`), { signal });
      } finally { signal.removeEventListener('abort', cancelApproval); this.approvals.cancelThread(browserThreadId); }
      signal.throwIfAborted();
      if (!allowed) throw new Error('Chrome connection was not approved');
      store.markApproved(CHROME_MCP_ID);
    }
    signal.throwIfAborted();
    if (!this.store().get('local').enabled) throw new Error('Chrome local was disabled');
    if (this.mcp.has(CHROME_MCP_ID) && !reconnect) return this.overview();
    if (this.mcp.has(CHROME_MCP_ID)) await this.mcp.disconnect(CHROME_MCP_ID);
    try {
      await this.mcp.connect({ id: record.id, command: record.command, args: record.args, env: record.env, hidden: true, signal, initTimeoutMs: chromeInstallNeeded(record.args) ? CHROME_COLD_INSTALL_TIMEOUT_MS : CHROME_WARM_INIT_TIMEOUT_MS, requestTimeoutMs: 15_000 });
      signal.throwIfAborted();
      if (!this.store().get('local').enabled) { await this.mcp.disconnect(CHROME_MCP_ID); throw new Error('Chrome local was disabled'); }
      store.markConnected(CHROME_MCP_ID, true);
      this.onChange();
    } catch (error) {
      store.markConnected(CHROME_MCP_ID, false, error.message);
      throw error;
    }
    return this.overview();
  }

  async testChromePort({ port = 9222 } = {}) {
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid Chrome debug port');
    const response = await this.fetchImpl(`http://127.0.0.1:${port}/json/version`, { signal: AbortSignal.timeout(3000) });
    if (!response.ok) throw new Error(`Chrome debug port returned HTTP ${response.status}`);
    const body = await response.json();
    return { browser: String(body.Browser || 'Chrome').slice(0, 100) };
  }

  async installChromium() {
    if (this.installing) return this.installing;
    const cli = path.join(path.dirname(require.resolve('playwright/package.json')), 'cli.js');
    const child = spawn(process.execPath, [cli, 'install', 'chromium'], {
      windowsHide: true,
      env: { ...process.env, ELECTRON_RUN_AS_NODE: '1' },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    this.installing = new Promise((resolve, reject) => {
      const progress = chunk => this.onProgress(String(chunk).slice(-300));
      child.stdout.on('data', progress);
      child.stderr.on('data', progress);
      child.on('error', reject);
      child.on('exit', code => code === 0 ? resolve(this.overview()) : reject(new Error(`Chromium download exited with code ${code}`)));
    }).finally(() => { this.installing = null; this.onChange(); });
    return this.installing;
  }
}
