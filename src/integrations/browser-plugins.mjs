import fs from 'node:fs';
import path from 'node:path';
import { CONFIG_DIR } from '../core/config.mjs';
import { writeTextFile } from '../../tools/shared/_shared.mjs';
import { resolveNpxBin } from './mcp-client.mjs';

export const BROWSER_FILE = path.join(CONFIG_DIR, 'browser.json');
export const CHROME_MCP_ID = 'ankita-chrome';
export const CHROME_MCP_VERSION = '1.10.1';
export const BROWSER_PLUGINS = Object.freeze({
  isolated: { id: 'ankita-playwright', name: 'Playwright Browser', description: 'A private Chromium for Ankita', mode: 'isolated' },
  local: { id: 'ankita-chrome', name: 'Chrome local', description: 'Chrome for browsing and debugging', mode: 'local' },
});

const initial = () => ({ version: 1, plugins: {
  isolated: { enabled: false, headless: true, allowedSites: [], blockedSites: [] },
  local: { enabled: false, connection: 'profile', port: 9222, allowedSites: [], blockedSites: [] },
} });

function siteRule(value) {
  const rule = String(value || '').trim().toLowerCase();
  const host = rule.replace(/^\*\./, '');
  if (rule.length > 253 || !/^[a-z0-9-]+(?:\.[a-z0-9-]+)*$/.test(host) || host.split('.').some(label => label.startsWith('-') || label.endsWith('-'))) throw new Error('Enter a domain such as example.com or *.example.com');
  return rule;
}

function siteRules(input) {
  if (!Array.isArray(input)) return [];
  return [...new Set(input.filter(item => typeof item === 'string').slice(0, 100).flatMap(item => { try { return [siteRule(item)]; } catch { return []; } }))];
}

export class BrowserPluginStore {
  constructor(file = BROWSER_FILE) { this.file = file; this.data = initial(); }

  load() {
    try {
      const raw = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      const defaults = initial();
      for (const mode of ['isolated', 'local']) {
        const input = raw?.plugins?.[mode];
        if (input && typeof input === 'object') {
          defaults.plugins[mode].enabled = input.enabled === true;
          defaults.plugins[mode].allowedSites = siteRules(input.allowedSites);
          defaults.plugins[mode].blockedSites = siteRules(input.blockedSites);
          if (mode === 'isolated') defaults.plugins.isolated.headless = input.headless !== false;
          else {
            defaults.plugins.local.connection = ['profile', 'port', 'active'].includes(input.connection) ? input.connection : 'profile';
            defaults.plugins.local.port = Number.isInteger(input.port) && input.port >= 1 && input.port <= 65535 ? input.port : 9222;
          }
        }
      }
      this.data = defaults;
    } catch { this.data = initial(); }
    return this;
  }

  save() {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    writeTextFile(this.file, JSON.stringify(this.data, null, 2), '\n');
    return this;
  }

  get(mode) {
    if (!Object.hasOwn(this.data.plugins, mode)) throw new Error(`Unknown browser mode: ${mode}`);
    const value = this.data.plugins[mode];
    return { ...value, allowedSites: [...value.allowedSites], blockedSites: [...value.blockedSites] };
  }

  setEnabled(mode, enabled) {
    this.load();
    this.get(mode);
    this.data.plugins[mode].enabled = enabled === true;
    return this.save().get(mode);
  }

  setChromeMode(connection, port = 9222) {
    if (!['profile', 'port', 'active'].includes(connection)) throw new Error('Invalid Chrome connection mode');
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('Invalid Chrome debug port');
    this.load();
    this.data.plugins.local.connection = connection;
    this.data.plugins.local.port = port;
    return this.save().get('local');
  }

  setHeadless(headless) {
    this.load();
    this.data.plugins.isolated.headless = headless === true;
    return this.save().get('isolated');
  }

  changeSiteRule(mode, kind, site, add) {
    if (!['allow', 'block'].includes(kind)) throw new Error('Unknown site rule');
    this.load();
    this.get(mode);
    const rule = siteRule(site);
    const key = kind === 'allow' ? 'allowedSites' : 'blockedSites';
    const values = this.data.plugins[mode][key];
    this.data.plugins[mode][key] = add ? [...new Set([...values, rule])].slice(0, 100) : values.filter(value => value !== rule);
    return this.save().get(mode);
  }
}

export function chromeMcpCommand(settings) {
  const args = ['-y', `chrome-devtools-mcp@${CHROME_MCP_VERSION}`, '--no-usage-statistics', '--no-performance-crux'];
  if (settings.connection === 'active') args.push('--autoConnect');
  else if (settings.connection === 'port') args.push(`--browserUrl=http://127.0.0.1:${settings.port}`);
  return { command: 'npx', args };
}

/**
 * Whether connecting will have to download the MCP package first: the first
 * positional arg is the package spec, and a missing npx-cache entry means a
 * cold install. The resolver is injectable so tests do not touch the disk.
 */
export function chromeInstallNeeded(args = [], resolve = resolveNpxBin) {
  const spec = (Array.isArray(args) ? args : []).find(arg => typeof arg === 'string' && !arg.startsWith('-'));
  return !spec || !resolve(spec);
}

export async function browserPluginOverview(store = new BrowserPluginStore().load(), mcp = null) {
  const isolated = store.get('isolated');
  let playwright = null;
  let browserExecutable = '';
  try {
    playwright = await import('playwright');
    browserExecutable = playwright.chromium.executablePath();
  } catch {}
  const installed = Boolean(playwright && browserExecutable && fs.existsSync(browserExecutable));
  const local = store.get('local');
  return {
    isolated: { ...BROWSER_PLUGINS.isolated, ...isolated, ready: installed, reason: installed ? '' : playwright ? 'Download Chromium to finish setup' : 'Install Playwright to finish setup' },
    local: { ...BROWSER_PLUGINS.local, ...local, ready: Boolean(mcp?.has?.(CHROME_MCP_ID)), reason: mcp?.has?.(CHROME_MCP_ID) ? '' : 'Start Chrome DevTools connection' },
  };
}
