import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { McpManager } from '../../src/integrations/mcp-manager.mjs';
import {
  TierPolicy, resolveTier, heuristicTier, enclosedActions, splitSlug, describeCall,
  TIER_AUTO, TIER_ASK, TIER_ALWAYS, TIER_DENY,
  COMPOSIO_SEARCH_TOOLS, COMPOSIO_MULTI_EXECUTE_TOOL, COMPOSIO_MANAGE_CONNECTIONS,
} from '../../src/integrations/mcp-tiers.mjs';

const tempFile = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'mcp-tiers-')), 'mcp-tiers.json');
const metaTool = (name) => ({ name, annotations: {} });

/** Composio as it really connects: one meta-tool, trusted, no annotations. */
function composioManager(policy = new TierPolicy()) {
  const manager = new McpManager({ tiers: policy });
  manager.servers.set('composio', {
    id: 'composio', transport: 'http', url: 'https://connect.composio.dev/mcp', trusted: true, alwaysOn: true,
    tools: [metaTool(COMPOSIO_SEARCH_TOOLS), metaTool(COMPOSIO_MULTI_EXECUTE_TOOL), metaTool(COMPOSIO_MANAGE_CONNECTIONS)],
  });
  return manager;
}

/* ------------------------------- heuristics ----------------------------- */

test('only an explicit read-only hint is auto-allowed, and heuristics never deny', () => {
  assert.equal(heuristicTier({ tool: { annotations: { readOnlyHint: true } } }), TIER_AUTO);
  assert.equal(heuristicTier({ tool: { name: 'gmail_get_profile', annotations: {} } }), TIER_ASK, 'unknown means ask');
  for (const verb of ['GMAIL_SEND_EMAIL', 'github_delete_repo', 'notion_publish_page', 'stripe_create_payment']) {
    assert.equal(heuristicTier({ tool: { name: verb, annotations: {} } }), TIER_ALWAYS, `${verb} must always ask`);
  }
  // The migration guarantee: tier 3 is unreachable without an explicit blocklist.
  for (const toolName of ['mcp__x__GMAIL_SEND_EMAIL', 'mcp__x__anything_at_all', 'mcp__x__delete_everything']) {
    assert.notEqual(resolveTier({ serverId: 'x', toolName, tool: metaTool(toolName) }).tier, TIER_DENY);
  }
});

/* ----------------------------- meta-tool parsing ------------------------ */

test('a meta-tool is judged by the worst action it encloses', () => {
  const read = resolveTier({ serverId: 'composio', toolName: COMPOSIO_MULTI_EXECUTE_TOOL, tool: metaTool(COMPOSIO_MULTI_EXECUTE_TOOL), args: { tools: [{ slug: 'GITHUB_LIST_REPOSITORIES' }] } });
  const send = resolveTier({ serverId: 'composio', toolName: COMPOSIO_MULTI_EXECUTE_TOOL, tool: metaTool(COMPOSIO_MULTI_EXECUTE_TOOL), args: { tools: [{ slug: 'GMAIL_SEND_EMAIL' }] } });
  const mixed = resolveTier({ serverId: 'composio', toolName: COMPOSIO_MULTI_EXECUTE_TOOL, tool: metaTool(COMPOSIO_MULTI_EXECUTE_TOOL), args: { tools: [{ slug: 'GITHUB_LIST_REPOSITORIES' }, { slug: 'GMAIL_SEND_EMAIL' }] } });
  assert.equal(read.tier, TIER_ASK, 'a read on an app with no locked default is ask-once');
  assert.equal(send.tier, TIER_ALWAYS, 'sending is always-ask');
  assert.equal(mixed.tier, TIER_ALWAYS, 'one destructive action lifts the whole call');
  assert.equal(mixed.actions.length, 2);
});

test('the locked Gmail default is always-ask, so even a Gmail read is not silent', () => {
  const readMail = resolveTier({ serverId: 'composio', toolName: COMPOSIO_MULTI_EXECUTE_TOOL, tool: metaTool(COMPOSIO_MULTI_EXECUTE_TOOL), args: { tools: [{ slug: 'GMAIL_FETCH_EMAILS' }] } });
  assert.equal(readMail.tier, TIER_ALWAYS, 'mail is the highest-regret app, so the whole app starts at always-ask');
  assert.match(readMail.reason, /app rule \(gmail\)/);
});

test('the approval card names the action, never the meta-tool', () => {
  const decision = resolveTier({
    serverId: 'composio', toolName: COMPOSIO_MULTI_EXECUTE_TOOL, tool: metaTool(COMPOSIO_MULTI_EXECUTE_TOOL),
    args: { tools: [{ slug: 'GMAIL_SEND_EMAIL' }] },
  });
  assert.equal(decision.label, 'gmail: send email');
  assert.equal(decision.label.includes('COMPOSIO_MULTI_EXECUTE_TOOL'), false, 'a meta-tool name tells the user nothing');
});

test('discovery and connection management map to the documented tiers', () => {
  const search = resolveTier({ serverId: 'composio', toolName: COMPOSIO_SEARCH_TOOLS, tool: metaTool(COMPOSIO_SEARCH_TOOLS) });
  assert.equal(search.tier, TIER_AUTO, 'catalog search performs no app action');
  const add = resolveTier({ serverId: 'composio', toolName: COMPOSIO_MANAGE_CONNECTIONS, tool: metaTool(COMPOSIO_MANAGE_CONNECTIONS), args: { action: 'add' } });
  const remove = resolveTier({ serverId: 'composio', toolName: COMPOSIO_MANAGE_CONNECTIONS, tool: metaTool(COMPOSIO_MANAGE_CONNECTIONS), args: { action: 'remove' } });
  assert.equal(add.tier, TIER_ASK, 'the user is already watching the OAuth flow');
  assert.equal(remove.tier, TIER_ALWAYS, 'removing a connection is destructive to setup');
  assert.equal(add.label, 'connections: add');
});

test('a malformed meta-tool payload asks rather than auto-allowing', () => {
  const decision = resolveTier({ serverId: 'composio', toolName: COMPOSIO_MULTI_EXECUTE_TOOL, tool: metaTool(COMPOSIO_MULTI_EXECUTE_TOOL), args: { tools: [{}] } });
  assert.equal(decision.tier, TIER_ASK);
  assert.equal(enclosedActions(COMPOSIO_MULTI_EXECUTE_TOOL, null).length, 0);
});

/* -------------------------------- ordering ------------------------------ */

test('explicit per-tool rules beat per-app rules, which beat the defaults', () => {
  const policy = new TierPolicy();
  // Locked default: mail always asks before any rule exists.
  const before = resolveTier({ serverId: 'composio', toolName: COMPOSIO_MULTI_EXECUTE_TOOL, tool: metaTool(COMPOSIO_MULTI_EXECUTE_TOOL), args: { tools: [{ slug: 'GMAIL_SEND_EMAIL' }] }, policy });
  assert.equal(before.tier, TIER_ALWAYS);
  assert.match(before.reason, /app rule/);

  policy.setTier('composio', 'GMAIL_SEND_EMAIL', TIER_ASK);
  const toolRule = resolveTier({ serverId: 'composio', toolName: COMPOSIO_MULTI_EXECUTE_TOOL, tool: metaTool(COMPOSIO_MULTI_EXECUTE_TOOL), args: { tools: [{ slug: 'GMAIL_SEND_EMAIL' }] }, policy });
  assert.equal(toolRule.tier, TIER_ASK, 'an explicit tool rule wins');
  assert.equal(toolRule.reason, 'tool rule');

  policy.setTier('composio', 'app:gmail', TIER_AUTO);
  const appRule = resolveTier({ serverId: 'composio', toolName: COMPOSIO_MULTI_EXECUTE_TOOL, tool: metaTool(COMPOSIO_MULTI_EXECUTE_TOOL), args: { tools: [{ slug: 'GMAIL_SEND_EMAIL' }] }, policy });
  assert.equal(appRule.tier, TIER_ASK, 'the tool rule still outranks the app rule');
  const otherGmail = resolveTier({ serverId: 'composio', toolName: COMPOSIO_MULTI_EXECUTE_TOOL, tool: metaTool(COMPOSIO_MULTI_EXECUTE_TOOL), args: { tools: [{ slug: 'GMAIL_CREATE_DRAFT' }] }, policy });
  assert.equal(otherGmail.tier, TIER_AUTO, 'the app rule covers the rest of the app');
});

test('only a blocklist entry produces a denial', () => {
  const policy = new TierPolicy();
  policy.setTier('composio', 'app:gmail', TIER_AUTO);
  const allowed = resolveTier({ serverId: 'composio', toolName: COMPOSIO_MULTI_EXECUTE_TOOL, tool: metaTool(COMPOSIO_MULTI_EXECUTE_TOOL), args: { tools: [{ slug: 'GMAIL_SEND_EMAIL' }] }, policy });
  assert.equal(allowed.tier, TIER_AUTO);

  policy.block('composio', 'GMAIL_SEND_EMAIL');
  const blocked = resolveTier({ serverId: 'composio', toolName: COMPOSIO_MULTI_EXECUTE_TOOL, tool: metaTool(COMPOSIO_MULTI_EXECUTE_TOOL), args: { tools: [{ slug: 'GMAIL_SEND_EMAIL' }] }, policy });
  assert.equal(blocked.tier, TIER_DENY, 'the blocklist outranks an auto-allow rule');
  assert.equal(blocked.reason, 'blocked');
});

/* --------------------- the hole this replaces (regression) -------------- */

test('a trusted server no longer skips the approval gate', () => {
  const manager = composioManager();
  // Before this change `record.trusted` short-circuited needsApproval, so a
  // connected Gmail sent mail with zero prompts.
  assert.equal(
    manager.needsApproval(`mcp__composio__${COMPOSIO_MULTI_EXECUTE_TOOL}`, { tools: [{ slug: 'GMAIL_SEND_EMAIL' }] }),
    true, 'sending mail through a trusted server must still ask'
  );
  assert.equal(
    manager.needsApproval(`mcp__composio__${COMPOSIO_SEARCH_TOOLS}`),
    false, 'read-only discovery stays frictionless'
  );
  const decision = manager.tierFor(`mcp__composio__${COMPOSIO_MULTI_EXECUTE_TOOL}`, { tools: [{ slug: 'GMAIL_SEND_EMAIL' }] });
  assert.equal(decision.serverId, 'composio');
  assert.match(manager.approvalDetail(`mcp__composio__${COMPOSIO_MULTI_EXECUTE_TOOL}`, { tools: [{ slug: 'GMAIL_SEND_EMAIL' }] }), /gmail: send email/);
});

test('an unknown tool is never gated by proxy', () => {
  const manager = composioManager();
  assert.equal(manager.needsApproval('mcp__ghost__anything'), false);
  assert.equal(manager.tierFor('mcp__ghost__anything').tier, TIER_AUTO);
});

/* ---------------------------- policy persistence ------------------------ */

test('tier overrides and counters survive a reload', () => {
  const file = tempFile();
  const first = new TierPolicy(file);
  first.setTier('composio', 'app:gmail', TIER_ASK);
  first.block('composio', 'GMAIL_DELETE_MESSAGE');
  first.recordDecision('composio', 'allowed');
  first.recordDecision('composio', 'denied');
  first.recordDecision('composio', 'asked');

  const reloaded = new TierPolicy(file);
  assert.equal(reloaded.appTierFor('composio', 'gmail'), TIER_ASK);
  assert.deepEqual(reloaded.blocklistFor('composio'), ['GMAIL_DELETE_MESSAGE']);
  const { stats, explicit, blocklist } = reloaded.describe('composio');
  assert.deepEqual(stats, { allowed: 1, asked: 1, denied: 1 });
  assert.deepEqual(explicit, [{ name: 'app:gmail', tier: TIER_ASK, label: 'ask once' }]);
  assert.deepEqual(blocklist, ['GMAIL_DELETE_MESSAGE']);
  fs.rmSync(path.dirname(file), { recursive: true, force: true });
});

test('a missing or malformed policy file falls back to heuristics instead of failing open', () => {
  const file = tempFile();
  const missing = new TierPolicy(file);
  assert.equal(missing.tierFor('composio', 'anything'), null);
  assert.equal(resolveTier({ serverId: 'composio', toolName: 'GMAIL_SEND_EMAIL', tool: metaTool('GMAIL_SEND_EMAIL'), policy: missing }).tier, TIER_ALWAYS);

  fs.writeFileSync(file, '{ not json');
  const malformed = new TierPolicy(file);
  assert.equal(malformed.blocklistFor('composio').length, 0);
  assert.equal(resolveTier({ serverId: 'composio', toolName: 'GMAIL_SEND_EMAIL', tool: metaTool('GMAIL_SEND_EMAIL'), policy: malformed }).tier, TIER_ALWAYS);
  fs.rmSync(path.dirname(file), { recursive: true, force: true });
});

test('lowering protection is detectable so it can require its own approval', () => {
  const policy = new TierPolicy();
  assert.equal(policy.lowersProtection('composio', TIER_ALWAYS, TIER_AUTO), true);
  assert.equal(policy.lowersProtection('composio', TIER_ALWAYS, TIER_DENY), false, 'blocking is not lowering');
  assert.equal(policy.lowersProtection('composio', null, TIER_AUTO), true, 'an unset tier defaults to ask-once');
});

/* -------------------------------- slugs --------------------------------- */

test('slugs split into an app and an action for display', () => {
  assert.deepEqual(splitSlug('GMAIL_SEND_EMAIL'), { slug: 'GMAIL_SEND_EMAIL', app: 'gmail', action: 'send email' });
  assert.equal(splitSlug(''), null);
  assert.equal(describeCall('mcp__x__y', []), 'mcp__x__y');
});
