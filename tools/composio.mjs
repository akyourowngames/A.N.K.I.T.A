import { COMPOSIO_FILE } from '../src/config.mjs';
import { ComposioStore } from '../src/composio-store.mjs';
import { connectionMode, listToolkits, connectedServices, authorize, removeAccount, removeService } from '../src/composio.mjs';

export const name = 'composio';
export const description = 'Manage connected apps such as Gmail, Slack, Notion, Calendar, Drive and GitHub. Actions: status, list, accounts, search, connect, disconnect, reload. Connected app actions run without an approval prompt.';
export const parameters = {
  type: 'object',
  properties: {
    action: { type: 'string', description: 'status, list, accounts, search, connect, disconnect, or reload' },
    service: { type: 'string', description: 'App slug, e.g. gmail or slack' },
    query: { type: 'string', description: 'Search text for app catalog' },
    alias: { type: 'string', description: 'Optional account alias when connecting' },
    accountId: { type: 'string', description: 'Optional account ID to disconnect only that account' },
  },
  required: ['action'],
};
export const needsApproval = false;

function context(ctx) {
  return { ...(ctx.config || {}), composioStore: ctx.composioStore || new ComposioStore(COMPOSIO_FILE).load() };
}

export async function run(args = {}, ctx = {}) {
  const cfg = context(ctx);
  const fetchImpl = ctx.fetchImpl || fetch;
  const action = String(args.action || 'status').toLowerCase();
  if (action === 'status') {
    const mode = connectionMode(cfg);
    if (mode === 'unavailable') return 'Connected apps are not configured. Set COMPOSIO_API_KEY or COMPOSIO_BROKER_URL, then use /composio reload.';
    const services = await connectedServices(cfg, fetchImpl);
    const connected = Object.entries(services).filter(([, s]) => s.connected).map(([slug]) => slug);
    return `Connected apps: ${mode}; MCP ${ctx.mcp?.has('composio') ? 'live' : 'idle'}; services: ${connected.join(', ') || '(none)'}.`;
  }
  if (action === 'list' || action === 'search') {
    const { cards, nextCursor } = await listToolkits(cfg, { query: action === 'search' ? args.query || args.service || '' : '' }, fetchImpl);
    return cards.length
      ? cards.slice(0, 50).map(c => `${c.slug}: ${c.label}${c.blurb ? ` — ${c.blurb}` : ''}`).join('\n') + (nextCursor ? `\nMore available (cursor: ${nextCursor}).` : '')
      : 'No connected apps matched.';
  }
  if (action === 'accounts') {
    const services = await connectedServices(cfg, fetchImpl);
    const entries = Object.entries(services).filter(([slug]) => !args.service || slug === args.service);
    return entries.length ? entries.map(([slug, state]) =>
      `${slug}: ${state.status}; ${state.accounts?.length || 0} account(s)${state.accounts?.length ? `\n${state.accounts.map(a => `  ${a.id}${a.alias ? ` (${a.alias})` : ''}: ${a.status}`).join('\n')}` : ''}`
    ).join('\n') : 'No connected accounts.';
  }
  if (action === 'connect') {
    if (!args.service) return 'Error: service is required, e.g. gmail.';
    const { url } = await authorize(cfg, args.service, args.alias, fetchImpl);
    return `Open this link in your browser and finish authorization for ${args.service}: ${url}`;
  }
  if (action === 'disconnect') {
    if (!args.service) return 'Error: service is required.';
    const result = args.accountId
      ? await removeAccount(cfg, args.service, args.accountId, fetchImpl)
      : await removeService(cfg, args.service, fetchImpl);
    return `Disconnected ${result.removed || 0} account(s) from ${args.service}.`;
  }
  if (action === 'reload') {
    if (!ctx.mcp) return 'Error: no MCP manager is attached.';
    if (ctx.mcp.has('composio')) await ctx.mcp.disconnect('composio');
    const record = await ctx.mcp.ensureComposio(ctx.config || {}, cfg.composioStore, fetchImpl);
    return record ? `Connected Composio MCP (${record.tools.length} tools).` : 'Connected apps are not configured.';
  }
  return `Error: unknown Composio action "${action}".`;
}
