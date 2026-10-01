import { COMPOSIO_FILE, MCP_TIERS_FILE } from '../../src/core/config.mjs';
import { ComposioStore } from '../../src/integrations/composio-store.mjs';
import { connectionMode, listToolkits, connectedServices, authorize, removeAccount, removeService, canonicalSlug } from '../../src/integrations/composio.mjs';
import { connectComposio } from '../../src/integrations/composio-oauth.mjs';
import { TierPolicy, TIER_AUTO, TIER_ALWAYS, TIER_LABELS } from '../../src/integrations/mcp-tiers.mjs';
import { deprecationNotice } from '../../src/integrations/composio-deprecation.mjs';

export const name = 'composio';
export const description = 'Manage connected apps such as Gmail, Slack, Notion, Calendar, Drive and GitHub. Actions: status, list, accounts, search, connect, disconnect, reload, tiers, allow, always, deny. This tool only manages connections; app actions run through the MCP approval tiers, so sending or deleting always asks first.';
export const parameters = {
  type: 'object',
  properties: {
    action: { type: 'string', description: 'status, list, accounts, search, connect, disconnect, reload, tiers, allow, always, or deny' },
    service: { type: 'string', description: 'App slug, e.g. gmail or slack' },
    query: { type: 'string', description: 'Search text for app catalog' },
    alias: { type: 'string', description: 'Optional account alias when connecting' },
    accountId: { type: 'string', description: 'Optional account ID to disconnect only that account' },
    tool: { type: 'string', description: 'Action slug for a tier change, e.g. GMAIL_SEND_EMAIL' },
  },
  required: ['action'],
};

/**
 * Management only - and even management is not uniformly safe.
 *
 * Listing connections reads state and can run unprompted, which is the split
 * this tool's old blanket `needsApproval = false` got wrong: it also covered
 * *execution*. Execution never happens here; it happens through
 * `mcp__composio__*` and the tier gate. The one management action that can
 * weaken protection is a tier change, so those ask. In particular a model must
 * not be able to grant itself tier 0 on Gmail.
 */
const TIER_MUTATIONS = new Set(['allow', 'always', 'deny']);
export const needsApproval = (args = {}) => TIER_MUTATIONS.has(String(args.action || 'status').toLowerCase());

/**
 * Never auto-approvable, even with auto-approve on.
 *
 * `needsApproval` is enough in an interactive chat, but auto-approve skips it -
 * and an unattended scheduled job has this tool. Without this, a job could call
 * `allow`/`always` and persist a lower tier that quietly applies to every later
 * interactive session. Loosening protection needs a human in the loop.
 */
export const neverAutoApprove = (args = {}) => TIER_MUTATIONS.has(String(args.action || 'status').toLowerCase());

function context(ctx) {
  return { ...(ctx.config || {}), composioStore: ctx.composioStore || new ComposioStore(COMPOSIO_FILE).load() };
}

/** Prefer the live manager's policy so the CLI and a running daemon cannot diverge. */
function policyFor(ctx) {
  return ctx.mcp?.tiers || new TierPolicy(MCP_TIERS_FILE);
}
const SERVER_ID = 'composio';

export async function run(args = {}, ctx = {}) {
  const cfg = context(ctx);
  const fetchImpl = ctx.fetchImpl || fetch;
  const action = String(args.action || 'status').toLowerCase();
  if (action === 'status') {
    const mode = connectionMode(cfg);
    if (mode === 'unavailable') return 'Connected apps are not configured. Set COMPOSIO_API_KEY or COMPOSIO_BROKER_URL, then use /composio reload.';
    const services = await connectedServices(cfg, fetchImpl);
    const connected = Object.entries(services).filter(([, s]) => s.connected).map(([slug]) => slug);
    const line = `Connected apps: ${mode}; MCP ${ctx.mcp?.has('composio') ? 'live' : 'idle'}; services: ${connected.join(', ') || '(none)'}.`;
    const notice = deprecationNotice(mode);
    return notice ? `${line}\n${notice}` : line;
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
    // Keyless sign-in: with no API key there is nothing for `authorize()` to use,
    // so the desktop host supplies a browser sign-in instead. Pick the apps
    // inside Composio when the browser opens.
    const oauth = ctx.mcp?.composioOauth;
    if (connectionMode(cfg) === 'unavailable' && oauth) {
      try {
        const { grant } = await connectComposio({ ...oauth, apps: [canonicalSlug(args.service)], onStatus: () => {} });
        if (ctx.mcp.has('composio')) await ctx.mcp.disconnect('composio');
        const record = await ctx.mcp.ensureComposio(ctx.config || {}, cfg.composioStore, fetchImpl, ctx.mcp.composioOauth);
        return record
          ? `Signed in as ${args.service} through Composio Connect. MCP is live with ${record.tools.length} tool(s); the token is in the OS vault. Write access still asks first.`
          : `Signed in (grant ${grant.grantId}), but the MCP endpoint did not mount. Try action=reload.`;
      } catch (cause) {
        return `Error: Composio sign-in did not finish (${cause.message}). The link can be retried with action=connect.`;
      }
    }
    if (connectionMode(cfg) === 'unavailable') return 'Error: no Composio sign-in is available in this host. Set COMPOSIO_API_KEY, or use the desktop app for keyless sign-in.';
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
  if (action === 'tiers') {
    const policy = policyFor(ctx);
    const { explicit, blocklist, stats } = policy.describe(SERVER_ID);
    return [
      `Approval tiers for ${SERVER_ID}: ${explicit.length} override(s), ${blocklist.length} blocked.`,
      explicit.length ? explicit.map(rule => `  ${rule.name}: tier ${rule.tier} (${rule.label})`).join('\n') : '  No overrides; read-only tools run, everything else asks.',
      blocklist.length ? `Blocked: ${blocklist.join(', ')}` : null,
      `Decisions so far: ${stats.allowed} approved, ${stats.asked} pending/ask-once, ${stats.denied} denied.`,
    ].filter(Boolean).join('\n');
  }
  if (action === 'allow' || action === 'always' || action === 'deny') {
    const tool = String(args.tool || '').trim();
    const service = String(args.service || '').trim().toLowerCase();
    if (action === 'deny' && !tool) return 'Error: deny needs a specific tool slug; refusing to blocklist a whole app.';
    if (!tool && !service) return 'Error: give a service (e.g. gmail) or a tool slug (e.g. GMAIL_SEND_EMAIL).';
    const policy = policyFor(ctx);
    if (action === 'deny') {
      policy.block(SERVER_ID, tool);
      return `Blocked ${tool}: calls are refused without running (tier 3).`;
    }
    const tier = action === 'allow' ? TIER_AUTO : TIER_ALWAYS;
    const key = tool || `app:${service}`;
    policy.setTier(SERVER_ID, key, tier);
    return `${key} is now tier ${tier} (${TIER_LABELS[tier]}).`;
  }
  return `Error: unknown Composio action "${action}".`;
}
