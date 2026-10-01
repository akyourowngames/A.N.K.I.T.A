import fs from "node:fs";
import path from "node:path";
import { writeTextFile } from "../../tools/shared/_shared.mjs";

/**
 * Approval tiers for MCP tool calls.
 *
 * The old rule was binary - `readOnlyHint:true` skipped the gate, everything
 * else asked - and a *trusted* server skipped it entirely. Composio was
 * trusted, so a connected Gmail could send mail with no prompt at all.
 *
 * Tiers replace that single flag with an explicit, inspectable decision:
 *
 *   tier 0  auto-allow   read-only tools
 *   tier 1  ask once     default for an unclassified tool
 *   tier 2  always ask   destructive verbs (send, delete, publish, pay, ...)
 *   tier 3  deny         explicit blocklist entry only
 *
 * Composio exposes a handful of *meta-tools* (`COMPOSIO_MULTI_EXECUTE_TOOL`)
 * whose arguments name the real action, so classification has to read the
 * arguments. A meta-tool is never shown to the user; the parsed `app: action`
 * is.
 */

export const TIER_AUTO = 0;
export const TIER_ASK = 1;
export const TIER_ALWAYS = 2;
export const TIER_DENY = 3;

export const TIER_LABELS = {
  [TIER_AUTO]: "auto-allow",
  [TIER_ASK]: "ask once",
  [TIER_ALWAYS]: "always ask",
  [TIER_DENY]: "denied",
};

/**
 * Highest-regret verbs, matched as substrings so `payment` and `resend` count.
 *
 * A false positive only costs an extra prompt, and asking is already the
 * default, so there is no reason to risk a false negative with word
 * boundaries. This is a heuristic only - it can never deny.
 */
export const DESTRUCTIVE_VERBS = /(send|delete|publish|pay|transfer|remove|destroy|revoke)/i;

/** Composio meta-tools: read-only discovery is always safe to run. */
export const COMPOSIO_SEARCH_TOOLS = "COMPOSIO_SEARCH_TOOLS";
export const COMPOSIO_GET_TOOL_SCHEMAS = "COMPOSIO_GET_TOOL_SCHEMAS";
export const COMPOSIO_MULTI_EXECUTE_TOOL = "COMPOSIO_MULTI_EXECUTE_TOOL";
export const COMPOSIO_MANAGE_CONNECTIONS = "COMPOSIO_MANAGE_CONNECTIONS";
const READ_ONLY_META_TOOLS = new Set([COMPOSIO_SEARCH_TOOLS, COMPOSIO_GET_TOOL_SCHEMAS]);

/**
 * Mail is the highest-regret action in the default toolset: sending is
 * irreversible and the recipient sees it. New Composio connections therefore
 * start with Gmail at "always ask" instead of inheriting the generic default.
 * Reads stay harmless.
 */
const DEFAULT_APP_TIERS = { composio: { gmail: TIER_ALWAYS } };

export function isTier(value) {
  return value === TIER_AUTO || value === TIER_ASK || value === TIER_ALWAYS || value === TIER_DENY;
}

/**
 * `GMAIL_SEND_EMAIL` -> { app: "gmail", action: "send email", slug }.
 * The app is the first segment; everything after it is the action.
 */
export function splitSlug(slug) {
  const text = String(slug || "").trim();
  if (!text) return null;
  const [app, ...rest] = text.split(/[_/.:-]+/).filter(Boolean);
  if (!app) return null;
  return { slug: text, app: app.toLowerCase(), action: rest.join(" ").toLowerCase() };
}

/**
 * The concrete app actions a call will perform.
 *
 * A plain tool is its own action. A meta-tool wraps one or more real actions in
 * its arguments, and the tier that matters is the worst one enclosed.
 */
export function enclosedActions(toolName, args = {}) {
  const name = String(toolName || "");
  if (READ_ONLY_META_TOOLS.has(name)) return [];
  if (name === COMPOSIO_MULTI_EXECUTE_TOOL) {
    const entries = Array.isArray(args?.tools) ? args.tools : [];
    return entries.map((entry) => splitSlug(entry?.slug || entry?.tool_slug || entry?.name)).filter(Boolean);
  }
  if (name === COMPOSIO_MANAGE_CONNECTIONS) {
    // Connecting opens an OAuth flow the user is already watching; removing a
    // connection is destructive to working setup.
    const mode = String(args?.action || args?.operation || "add").toLowerCase();
    const tier = mode === "remove" || mode === "delete" ? TIER_ALWAYS : TIER_ASK;
    return [{ slug: name, app: "connections", action: mode, syntheticTier: tier }];
  }
  return [];
}

/** read-only -> 0, destructive verb -> 2, anything unknown -> 1. */
export function heuristicTier({ tool, subject }) {
  if (tool?.annotations?.readOnlyHint === true) return TIER_AUTO;
  const text = [tool?.name, subject?.slug, subject?.action].filter(Boolean).join(" ");
  if (DESTRUCTIVE_VERBS.test(text)) return TIER_ALWAYS;
  return TIER_ASK;
}

/**
 * Resolution order, per §4:
 *   blocklist -> explicit per-tool rule -> per-app rule -> app defaults -> heuristic.
 * Tier 3 is only reachable through an explicit blocklist entry, so a heuristic
 * can never silently deny.
 */
export function resolveTier({ serverId, toolName, tool, args = {}, policy = null } = {}) {
  const blocklist = policy?.blocklistFor?.(serverId) || [];
  const explicit = (name) => {
    const value = policy?.tierFor?.(serverId, name);
    return isTier(value) ? value : null;
  };
  const perApp = (app) => {
    const value = policy?.appTierFor?.(serverId, app);
    if (isTier(value)) return value;
    const fallback = DEFAULT_APP_TIERS[serverId]?.[app];
    return isTier(fallback) ? fallback : null;
  };

  const actions = enclosedActions(toolName, args).map((action) => {
    if (isTier(action.syntheticTier)) return { ...action, tier: action.syntheticTier, reason: "meta-tool action" };
    if (blocklist.includes(action.slug)) return { ...action, tier: TIER_DENY, reason: "blocked" };
    const rule = explicit(action.slug);
    if (rule !== null) return { ...action, tier: rule, reason: "tool rule" };
    const app = perApp(action.app);
    if (app !== null) return { ...action, tier: app, reason: `app rule (${action.app})` };
    return { ...action, tier: heuristicTier({ tool, subject: action }), reason: "heuristic" };
  });

  if (!actions.length) {
    // The blocklist outranks everything, including the read-only shortcuts.
    if (blocklist.includes(toolName)) {
      return { tier: TIER_DENY, reason: "blocked", actions: [], label: describeCall(toolName, []) };
    }
    // A catalog search reads metadata and performs no app action, so there is
    // nothing for the user to meaningfully approve.
    if (READ_ONLY_META_TOOLS.has(String(toolName))) {
      return { tier: TIER_AUTO, reason: "read-only discovery", actions: [], label: describeCall(toolName, []) };
    }
    const rule = explicit(toolName);
    const tier = rule !== null ? rule : heuristicTier({ tool });
    return { tier, reason: rule !== null ? "tool rule" : "heuristic", actions: [], label: describeCall(toolName, []) };
  }

  const worst = actions.reduce((max, action) => (action.tier > max.tier ? action : max), actions[0]);
  return { tier: worst.tier, reason: worst.reason, actions, label: describeCall(toolName, actions) };
}

/**
 * What the user is shown. A meta-tool name is never surfaced - the plan is
 * explicit that "COMPOSIO_MULTI_EXECUTE_TOOL" tells the user nothing, while
 * "gmail: send email" tells them what they are approving.
 */
export function describeCall(toolName, actions = []) {
  if (!actions.length) return String(toolName || "MCP tool");
  return actions.map((action) => `${action.app}: ${action.action || action.slug}`).join(", ");
}

export const TIERS_VERSION = 1;

/**
 * Explicit tier overrides, per server, on disk.
 *
 * Deliberately NOT stored in the MCP server record: `composio` is a synthetic
 * connection that never appears in `mcp.json`, and adding a command-less
 * record there would make reconcile try to spawn a process that does not
 * exist. A separate file keeps the policy generic across every server.
 */
export class TierPolicy {
  constructor(file = null) {
    this.file = file;
    this.data = { version: TIERS_VERSION, servers: {} };
    if (file) this.load();
  }

  load() {
    if (!this.file) return this;
    try {
      const parsed = JSON.parse(fs.readFileSync(this.file, "utf8"));
      this.data = {
        version: TIERS_VERSION,
        servers: parsed && typeof parsed.servers === "object" && parsed.servers ? parsed.servers : {},
      };
    } catch {
      // Missing or malformed: heuristics still apply, so this is not unsafe.
      this.data = { version: TIERS_VERSION, servers: {} };
    }
    return this;
  }

  save() {
    if (!this.file) return this;
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    writeTextFile(this.file, JSON.stringify(this.data, null, 2), "\n");
    return this;
  }

  /** Re-read before writing: the CLI and a running daemon each hold their own. */
  _fresh() {
    if (!this.file) return this;
    this.load();
    return this;
  }

  _server(serverId, create = false) {
    const id = String(serverId || "");
    if (!id) return null;
    if (!this.data.servers[id]) {
      if (!create) return null;
      this.data.servers[id] = { tiers: {}, blocklist: [], stats: { allowed: 0, asked: 0, denied: 0 } };
    }
    const record = this.data.servers[id];
    if (!record.tiers || typeof record.tiers !== "object") record.tiers = {};
    if (!Array.isArray(record.blocklist)) record.blocklist = [];
    if (!record.stats) record.stats = { allowed: 0, asked: 0, denied: 0 };
    return record;
  }

  tierFor(serverId, name) {
    return this._server(serverId)?.tiers?.[String(name)] ?? null;
  }

  appTierFor(serverId, app) {
    return this._server(serverId)?.tiers?.[`app:${String(app).toLowerCase()}`] ?? null;
  }

  blocklistFor(serverId) {
    return this._server(serverId)?.blocklist || [];
  }

  setTier(serverId, name, tier) {
    const record = this._server(serverId, true);
    record.tiers[String(name)] = tier;
    this.save();
    return tier;
  }

  block(serverId, name) {
    const record = this._server(serverId, true);
    if (!record.blocklist.includes(String(name))) record.blocklist.push(String(name));
    this.save();
    return record.blocklist;
  }

  unblock(serverId, name) {
    const record = this._server(serverId, true);
    record.blocklist = record.blocklist.filter((entry) => entry !== String(name));
    this.save();
    return record.blocklist;
  }

  stats(serverId) {
    const record = this._server(serverId, true);
    this.save();
    return record.stats;
  }

  /** Tier changes that lower protection are themselves approval-worthy. */
  lowersProtection(serverId, previousTier, nextTier) {
    const before = isTier(previousTier) ? previousTier : TIER_ASK;
    return nextTier < before;
  }

  /** Audit counter for "why did it send that mail?". */
  recordDecision(serverId, decision) {
    const record = this._server(serverId, true);
    const key = decision === "allowed" ? "allowed" : decision === "denied" ? "denied" : "asked";
    record.stats[key] += 1;
    this.save();
    return record.stats;
  }

  /** Effective view for the UI and `/composio tiers`. */
  describe(serverId, tools = []) {
    const record = this._server(serverId, false);
    const explicit = Object.entries(record?.tiers || {}).map(([name, tier]) => ({ name, tier, label: TIER_LABELS[tier] }));
    return { explicit, blocklist: [...(record?.blocklist || [])], stats: { ...(record?.stats || { allowed: 0, asked: 0, denied: 0 }) }, tools };
  }
}
