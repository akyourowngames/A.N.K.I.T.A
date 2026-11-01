import { MCP_FILE } from '../../src/core/config.mjs';
import { McpStore, describeSource } from '../../src/integrations/mcp-store.mjs';
import { CHROME_MCP_ID } from '../../src/integrations/browser-plugins.mjs';
import { COMPUTER_MCP_ID } from '../../src/integrations/computer-use.mjs';
import { BROWSER_EXTENSION_MCP_ID } from '../browser-helper/control-protocol.mjs';
import { searchRegistry, collapseToLatest, commandFor, resolveServer, shortName } from '../../src/integrations/mcp-registry.mjs';

// Servers the app configures itself. They stay out of the user-managed list so
// the MCP page never offers to remove something a settings section owns.
const MANAGED_ELSEWHERE = new Set([CHROME_MCP_ID, BROWSER_EXTENSION_MCP_ID, COMPUTER_MCP_ID]);

const MAX_QUERY_CHARS = 100;
const MAX_ENV_VARS = 40;
const MAX_ENV_VALUE_CHARS = 4096;
const ENV_NAME = /^[A-Za-z_][A-Za-z0-9_]*$/;
const SEARCH_RESULT_LIMIT = 40;

const text = (value, max = 200) => String(value || '').slice(0, max);

function cleanEnv(input) {
  if (input === undefined || input === null) return {};
  if (typeof input !== 'object' || Array.isArray(input)) throw new Error('Environment variables must be an object');
  const entries = Object.entries(input);
  if (entries.length > MAX_ENV_VARS) throw new Error(`At most ${MAX_ENV_VARS} environment variables are allowed`);
  const out = {};
  for (const [name, value] of entries) {
    if (!ENV_NAME.test(name)) throw new Error(`"${name}" is not a valid environment variable name`);
    const raw = String(value ?? '');
    if (raw.length > MAX_ENV_VALUE_CHARS) throw new Error(`The value for ${name} is too long`);
    if (raw) out[name] = raw;
  }
  return out;
}

function publisherTitle(entry) {
  return entry?._meta?.['io.modelcontextprotocol.registry/publisher-provided']?.title || entry?.server?.name || '';
}

function candidateFor(entry) {
  const server = entry?.server;
  if (!server) return null;
  const info = commandFor(entry);
  const title = text(publisherTitle(entry), 120);
  if (info.error) {
    return {
      registryName: server.name, title, description: text(server.description, 240),
      version: server.version || '', command: '', args: [], env: [], usable: false, reason: info.error,
    };
  }
  return {
    registryName: info.registryName,
    title,
    description: text(info.description, 240),
    version: info.version,
    command: info.command,
    args: info.args,
    env: info.env.map(v => ({ name: v.name, description: text(v.description, 160), required: v.required, secret: v.secret, hasDefault: v.hasDefault })),
    usable: true,
    reason: '',
  };
}

/** The desktop's secret-free boundary around user-configured MCP servers. */
export class DesktopMcp {
  constructor({ storeFile = MCP_FILE, mcp = null, fetchImpl = fetch } = {}) {
    this.storeFile = storeFile;
    this.mcp = mcp;
    this.fetchImpl = fetchImpl;
  }

  store() { return new McpStore(this.storeFile).load(); }

  visibleServers() {
    return this.store().servers.filter(record => !record.hidden && !MANAGED_ELSEWHERE.has(record.id));
  }

  #view(record, store = this.store()) {
    return {
      id: record.id,
      name: text(record.name || record.id, 80),
      command: text(record.command, 120),
      args: (record.args || []).map(arg => text(arg, 200)),
      envKeys: Object.keys(record.env || {}),
      enabled: record.enabled !== false,
      approved: store.isApproved(record),
      connected: Boolean(this.mcp?.has?.(record.id)),
      lastError: record.lastError ? text(record.lastError, 300) : null,
      source: describeSource(record),
      tools: this.mcp?.servers?.get?.(record.id)?.tools?.map(tool => tool.name) || [],
      manualStart: record.manualStart === true,
    };
  }

  overview() {
    const store = this.store();
    return { servers: this.visibleServers().map(record => this.#view(record, store)) };
  }

  async search({ query } = {}) {
    if (typeof query !== 'string') throw new Error('Search text must be a string');
    const wanted = query.trim();
    if (!wanted) return { candidates: [] };
    if (wanted.length > MAX_QUERY_CHARS) throw new Error(`Search text is limited to ${MAX_QUERY_CHARS} characters`);

    const entries = await searchRegistry(wanted, { fetchImpl: this.fetchImpl });
    const candidates = collapseToLatest(entries)
      .map(candidateFor)
      .filter(Boolean)
      .sort((a, b) => Number(b.usable) - Number(a.usable))
      .slice(0, SEARCH_RESULT_LIMIT);
    return { candidates };
  }

  async installFromRegistry({ registryName, version, env, id } = {}) {
    const wanted = String(registryName || '').trim();
    if (!wanted) throw new Error('Choose a server from the search results first');
    const info = await resolveServer(wanted, { version, fetchImpl: this.fetchImpl });
    if (info.error) throw new Error(info.error);
    const record = this.store().add({
      id: typeof id === 'string' && id.trim() ? id.trim() : shortName(info.registryName),
      name: shortName(info.registryName),
      command: info.command,
      args: info.args,
      env: cleanEnv(env),
      source: { registryName: info.registryName, version: info.version, repository: info.repository },
    });
    return { record: this.#view(record), missingEnv: info.env.filter(v => v.required && !(record.env || {})[v.name]).map(v => v.name) };
  }

  installManual({ name, command, args, env } = {}) {
    const record = this.store().add({
      name: typeof name === 'string' && name.trim() ? name.trim() : undefined,
      command: typeof command === 'string' ? command.trim() : '',
      args: Array.isArray(args) ? args.map(String) : [],
      env: cleanEnv(env),
    });
    return { record: this.#view(record), missingEnv: [] };
  }

  async remove({ id } = {}) {
    const record = this.store().remove(id);
    if (!record) throw new Error('That MCP server is no longer configured');
    if (this.mcp?.has?.(record.id)) await this.mcp.disconnect(record.id).catch(() => {});
    return this.overview();
  }

  async setEnabled({ id, enabled } = {}) {
    if (typeof enabled !== 'boolean') throw new Error('Choose whether to enable this server');
    const store = this.store();
    const record = store.setEnabled(id, enabled);
    if (!record) throw new Error('That MCP server is no longer configured');
    if (!enabled && this.mcp?.has?.(record.id)) await this.mcp.disconnect(record.id).catch(() => {});
    return this.overview();
  }

  /** Starts one server after the window has shown its exact command. */
  async start({ id } = {}) {
    const store = this.store();
    const record = store.find(id);
    if (!record) throw new Error('That MCP server is no longer configured');
    if (!record.enabled) throw new Error('Enable this server before starting it');
    if (!this.mcp) throw new Error('The tool host is not ready yet');
    store.markApproved(record.id);
    try {
      if (this.mcp.has(record.id)) await this.mcp.disconnect(record.id);
      await this.mcp.connect({
        id: record.id,
        command: record.command,
        args: record.args,
        env: record.env,
        transport: record.transport,
        hidden: record.hidden === true,
        allowedTools: record.allowedTools,
        terminateTree: record.terminateTree,
      });
      store.markConnected(record.id, true, null);
    } catch (error) {
      store.markConnected(record.id, false, error.message);
      throw error;
    }
    return this.overview();
  }

  async stop({ id } = {}) {
    const record = this.store().find(id);
    if (!record) throw new Error('That MCP server is no longer configured');
    if (this.mcp?.has?.(record.id)) await this.mcp.disconnect(record.id);
    return this.overview();
  }

  /** Connects every approved, enabled server; used after a reload. */
  async refresh() {
    if (!this.mcp) throw new Error('The tool host is not ready yet');
    await this.mcp.reconcile(this.store());
    return this.overview();
  }
}
