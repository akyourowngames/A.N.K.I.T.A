import { McpClient, formatToolResult } from "./mcp-client.mjs";

/**
 * Owns every live MCP connection for the process.
 *
 * Deliberately NOT per-Agent. `freshAgent()` builds a new Agent for every
 * routine, briefing and alert, so anything living in Agent.state would spawn a
 * server per invocation and abandon it - persistent execution would be true in
 * the REPL and false in automation, which is exactly backwards.
 *
 * Agents reach it through ctx.mcp; the daemon's reconcile loop drives it
 * directly. One manager, one set of live server processes, shared.
 */

const PREFIX = "mcp__";

/**
 * How much of a request one MCP server's tool list may occupy before it is
 * held back and loaded on demand instead. Roughly the size of the whole
 * built-in core set, so a server never crowds out the basics.
 */
export const ALWAYS_ON_TOKENS = 1200;

export function slug(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 32);
}

export function toolFullName(serverId, toolName) {
  return `${PREFIX}${serverId}__${toolName}`;
}

/** The inverse. Server ids are slugs, so the first "__" is the delimiter. */
export function parseToolName(fullName) {
  const match = /^mcp__(.+?)__(.+)$/.exec(String(fullName || ""));
  return match ? { serverId: match[1], toolName: match[2] } : null;
}

/**
 * Tool specs exactly as the server advertised them - never rewritten, never
 * summarised. That is the first of the three "no hallucination" guarantees.
 */
export function toOpenAiSpec(serverId, tool) {
  return {
    type: "function",
    function: {
      name: toolFullName(serverId, tool.name),
      description: tool.description || tool.title || `${tool.name} (from MCP server ${serverId})`,
      parameters:
        tool.inputSchema && typeof tool.inputSchema === "object"
          ? tool.inputSchema
          : { type: "object", properties: {} },
    },
  };
}

/**
 * Approval follows the server's own hints, conservatively: only an explicit
 * readOnlyHint:true skips the gate. Unset or destructive means ask.
 */
export function needsApprovalFor(tool) {
  const hints = tool?.annotations || {};
  return hints.readOnlyHint !== true;
}

export class McpManager {
  constructor({ log = () => {}, onChange = null } = {}) {
    this.log = log;
    this.onChange = onChange;
    /**
     * Live connections, keyed by id. Treat as read-only: mutating this map
     * directly orphans the client and its child process, because closeAll()
     * walks it. Use connect()/disconnect().
     */
    this.servers = new Map();
    // The authoritative set of open clients, so teardown cannot be defeated by
    // anyone (including a future refactor) fiddling with `servers`.
    this._clients = new Set();
  }

  get connectedIds() {
    return [...this.servers.keys()];
  }

  has(id) {
    return this.servers.has(id);
  }

  /** Connects a server and returns its record. Idempotent per id. */
  async connect({ id, command, args = [], env = {}, cwd, transport = "stdio", requestTimeoutMs, initTimeoutMs }) {
    const serverId = slug(id || command);
    if (!serverId) throw new Error("an MCP server needs an id or a command");
    if (transport !== "stdio") {
      throw new Error(`transport "${transport}" is not supported yet (stdio only)`);
    }
    const existing = this.servers.get(serverId);
    if (existing) return existing;

    const client = new McpClient({
      id: serverId,
      command,
      args,
      env,
      cwd,
      requestTimeoutMs,
      initTimeoutMs,
      onStderr: (text) => this.log(`[${serverId}] ${text.trim().split("\n")[0]}`),
      onToolsChanged: () => {
        this.log(`${serverId} advertised a changed tool list`);
        this.onChange?.(this);
      },
    });

    await client.connect();

    const record = { id: serverId, command, args, env, transport, client, tools: client.tools };
    this.servers.set(serverId, record);
    this._clients.add(client);
    this.log(`connected ${serverId} (${client.tools.length} tool(s))`);
    this.onChange?.(this);
    return record;
  }

  async disconnect(id) {
    const serverId = String(id);
    const record = this.servers.get(serverId);
    if (!record) return false;
    this.servers.delete(serverId);
    this._clients.delete(record.client);
    await record.client.close();
    this.log(`disconnected ${serverId}`);
    this.onChange?.(this);
    return true;
  }

  findTool(fullName) {
    const parsed = parseToolName(fullName);
    if (!parsed) return null;
    const record = this.servers.get(parsed.serverId);
    if (!record) return null;
    const tool = record.tools.find((t) => t.name === parsed.toolName);
    if (!tool) return null;
    return { ...parsed, record, tool };
  }

  needsApproval(fullName) {
    const found = this.findTool(fullName);
    return found ? needsApprovalFor(found.tool) : false;
  }

  /** Human-readable description of what a call will actually do. */
  approvalDetail(fullName, args) {
    const found = this.findTool(fullName);
    if (!found) return String(fullName);
    const { record, tool } = found;
    const hints = tool.annotations || {};
    const flags = [
      hints.readOnlyHint ? "read-only" : null,
      hints.destructiveHint ? "destructive" : null,
      hints.openWorldHint ? "open-world" : null,
    ].filter(Boolean);
    return (
      `${tool.name} on MCP server "${record.id}"` +
      (flags.length ? `  [${flags.join(", ")}]` : "") +
      `\n  command: ${record.command} ${record.args.join(" ")}\n\n` +
      JSON.stringify(args, null, 2)
    );
  }

  async callTool(fullName, args = {}) {
    const found = this.findTool(fullName);
    if (!found) throw new Error(`no connected MCP server provides ${fullName}`);
    const result = await found.record.client.callTool(found.toolName, args);
    return formatToolResult(result);
  }

  /**
   * Brings live connections in line with what the store says should be on.
   *
   * Called every daemon tick, so `/mcp add` in one window reaches a running
   * daemon without a restart. Only servers whose stored approval matches their
   * current command are started - a changed command waits for a fresh yes.
   */
  async reconcile(store) {
    const wanted = new Map();
    const skipped = [];
    for (const record of store.enabled) {
      if (store.isApproved(record)) wanted.set(record.id, record);
      else skipped.push(record.id);
    }

    let changed = false;
    for (const id of [...this.servers.keys()]) {
      if (!wanted.has(id)) {
        await this.disconnect(id).catch(() => {});
        changed = true;
      }
    }

    for (const [id, record] of wanted) {
      if (this.has(id)) continue;
      try {
        await this.connect({
          id,
          command: record.command,
          args: record.args,
          env: record.env,
          transport: record.transport,
        });
        store.markConnected(id, true, null);
        changed = true;
      } catch (err) {
        // One bad server must not stop the rest, or take the daemon down.
        this.log(`could not start MCP server "${id}": ${err.message}`);
        store.markConnected(id, false, err.message);
      }
    }

    if (skipped.length) {
      this.log(`${skipped.join(", ")} need approval - run /mcp add or /mcp reload to approve`);
    }
    return { connected: this.connectedIds, skipped, changed };
  }

  /** Specs for every connected server. Gating happens in the agent. */
  specs({ only = null } = {}) {
    const out = [];
    for (const [id, record] of this.servers) {
      if (only && !only.has(id)) continue;
      for (const tool of record.tools) out.push(toOpenAiSpec(id, tool));
    }
    return out;
  }

  /** Roughly what one server's tool list costs per request. */
  estimatedTokens(id) {
    const serverId = String(id);
    if (!this.servers.has(serverId)) return 0;
    return Math.ceil(JSON.stringify(this.specs({ only: new Set([serverId]) })).length / 4);
  }

  /**
   * Servers small enough to ship with every request, and those too big to.
   *
   * A big server cannot simply be always-on: Playwright's 25 browser tools
   * are ~4.6k tokens, which alone is enough to push a request past the context
   * window and fail it outright. Those load on demand through find_tools.
   */
  alwaysOnIds() {
    return [...this.servers.keys()].filter((id) => this.estimatedTokens(id) <= ALWAYS_ON_TOKENS);
  }

  deferredIds() {
    return [...this.servers.keys()].filter((id) => this.estimatedTokens(id) > ALWAYS_ON_TOKENS);
  }

  /** One line per server, for find_tools and the system prompt. */
  summaries() {
    return [...this.servers.values()].map((r) => ({
      id: r.id,
      tools: r.tools.map((t) => t.name),
      summary: `${r.tools.length} tool(s) from MCP server "${r.id}"`,
      deferred: this.estimatedTokens(r.id) > ALWAYS_ON_TOKENS,
    }));
  }

  /**
   * Closes every open client. Walks the client set rather than `servers`, so
   * an orphaned entry (a stray map delete, a crash mid-connect) is still shut
   * down instead of leaking a child process.
   */
  async closeAll() {
    const clients = [...this._clients];
    const ids = [...this.servers.keys()];
    this.servers.clear();
    this._clients.clear();
    await Promise.all(clients.map((c) => c.close().catch(() => {})));
    return ids;
  }
}
