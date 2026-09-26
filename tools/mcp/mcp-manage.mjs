import { MCP_FILE } from "../../src/core/config.mjs";
import { McpStore, describeServer, describeSource, enableMessage, disableMessage } from "../../src/integrations/mcp-store.mjs";
import { collapseToLatest, commandFor, describeCandidate, resolveServer, searchRegistry, shortName } from "../../src/integrations/mcp-registry.mjs";

export const name = "mcp_manage";
export const description =
  "Manage MCP (Model Context Protocol) servers - extra tools provided by external processes. " +
  "Use this when the user asks to add, list, remove, enable, disable or reload an MCP server, " +
  "or to find one (search the official MCP registry for browser automation, databases, " +
  "design tools and so on, then install it). " +
  "Adding or installing a server records the exact command that will run; nothing executes " +
  "until the user approves it. " +
  "Actions: search, install, add, list, remove, enable, disable, reload.";

export const parameters = {
  type: "object",
  properties: {
    action: {
      type: "string",
      description: "search, install, add, list, remove, enable, disable, or reload.",
    },
    query: {
      type: "string",
      description: "For search: what to look for, e.g. 'playwright', 'postgres', 'figma'.",
    },
    server: {
      type: "string",
      description:
        "For install: the registry name from search results, e.g. io.github.microsoft/playwright-mcp.",
    },
    version: { type: "string", description: "For install: a specific version. Defaults to latest." },
    as: { type: "string", description: "For install: a short local id. Defaults to the package name." },
    name: { type: "string", description: "For add: a short name for the server." },
    command: {
      type: "string",
      description: "For add: the executable to run, e.g. 'npx' or 'python'. Pin versions in the args.",
    },
    args: {
      type: "array",
      description: "For add: arguments, e.g. ['-y','@modelcontextprotocol/server-everything'].",
      items: { type: "string" },
    },
    env: {
      type: "object",
      description: "For add: extra environment variables for the server. The process env is not inherited.",
      additionalProperties: { type: "string" },
    },
    id: { type: "string", description: "For remove/enable/disable/reload: which server." },
  },
  required: ["action"],
};

// Approval policy belongs here; an empty preview must never suppress a gate.
export const needsApproval = (args = {}) => String(args.action || 'list').toLowerCase() === 'reload';

/**
 * Only `reload` runs third-party code. It shows the exact command that will be
 * spawned - approving a server *name* would not be informed consent.
 */
export function approval(args = {}) {
  const action = String(args.action || "list").toLowerCase();
  if (action !== "reload") return null;
  const record = new McpStore(MCP_FILE).load().find(args.id || args.name);
  if (!record) return null;
  return (
    `Start MCP server "${record.id}"\n\n` +
    `  command: ${record.command} ${(record.args || []).join(" ")}\n\n` +
    "This runs third-party code on your machine and its tools become callable.\n" +
    "Approval is remembered for this exact command; changing the version or args asks again."
  );
}

function store() {
  return new McpStore(MCP_FILE).load();
}

/** The live manager, when one is attached to this session. */
function manager(ctx) {
  return ctx?.mcp || null;
}

export async function run(args = {}, ctx = {}) {
  const s = store();
  const mcp = manager(ctx);
  const action = String(args.action || "list").toLowerCase();

  if (action === "search") {
    const query = String(args.query || args.name || "").trim();
    if (!query) {
      return "Error: 'query' is required. Ask the user what kind of server they want (browser automation, a database, a design tool) and search for that.";
    }
    let entries;
    try {
      entries = await searchRegistry(query, { signal: ctx.signal, fetchImpl: ctx.fetchImpl });
    } catch (err) {
      return `Error: could not reach the MCP registry: ${err.message}`;
    }
    const latest = collapseToLatest(entries);
    if (!latest.length) {
      return `Nothing in the official MCP registry matches "${query}". Try a broader word.`;
    }

    // Usable ones first: a wall of remote-only entries would bury the two the
    // user can actually install.
    const described = latest.map(describeCandidate);
    const usable = described.filter((c) => c.usable);
    const rest = described.filter((c) => !c.usable);

    const lines = [
      `${usable.length} installable match(es) for "${query}" (official MCP registry):`,
      "",
      ...usable.slice(0, 8).map((c) => c.line),
    ];
    if (rest.length) {
      lines.push("", `Also matched, but ankita cannot launch these:`, ...rest.slice(0, 4).map((c) => c.line));
    }
    lines.push(
      "",
      "Installing records the command; nothing runs until the user approves it.",
      "Call again with action 'install' and the registry name to install one - ask the user which first."
    );
    return lines.join("\n");
  }

  if (action === "install") {
    const wanted = String(args.server || args.id || "").trim();
    if (!wanted) {
      return "Error: 'server' is required. Run a search first and use the registry name it returned.";
    }
    let info;
    try {
      info = await resolveServer(wanted, {
        version: args.version,
        signal: ctx.signal,
        fetchImpl: ctx.fetchImpl,
      });
    } catch (err) {
      return `Error: could not reach the MCP registry: ${err.message}`;
    }
    if (info.error) return `Error: ${info.error}`;

    let record;
    try {
      record = s.add({
        id: args.as,
        name: args.as || shortName(info.registryName),
        command: info.command,
        args: info.args,
        env: args.env,
        source: { registryName: info.registryName, version: info.version, repository: info.repository },
      });
    } catch (err) {
      return `Error: ${err.message}`;
    }

    const missing = info.env.filter((v) => v.required && !(record.env || {})[v.name]);
    const lines = [
      `Installed "${record.id}" from ${info.registryName} @ ${info.version}.`,
      `  command: ${record.command} ${(record.args || []).join(" ")}`,
    ];
    if (missing.length) {
      lines.push(
        "",
        `This server expects ${missing.map((v) => v.name).join(", ")}. It may refuse to start without ` +
          `${missing.length > 1 ? "them" : "it"} - ask the user for the value and pass it as 'env'.`
      );
    }
    lines.push(
      "",
      "It has NOT been started. Run action 'reload' with this id to start it - that asks the user to",
      "approve the exact command above before anything executes."
    );
    return lines.join("\n");
  }

  if (action === "add") {
    if (!args.command) {
      return (
        "Error: 'command' is required. Ask the user what to run, then call again.\n" +
        "Common forms: npx -y <package>@<version>  |  python /path/to/server.py  |  uvx <package>"
      );
    }
    try {
      const record = s.add({
        name: args.name,
        command: args.command,
        args: args.args,
        env: args.env,
      });
      return (
        `Registered MCP server "${record.id}".\n` +
        `  command: ${record.command} ${(record.args || []).join(" ")}\n\n` +
        "It has NOT been started and will not be until the user approves that exact command.\n" +
        "Tell the user what will run, and that a version change will ask again."
      );
    } catch (err) {
      return `Error: ${err.message}`;
    }
  }

  if (action === "list") {
    if (!s.servers.length) {
      return "No MCP servers configured. Ask the user whether to add one (a command to run).";
    }
    const lines = s.servers.map((r) => {
      const row = describeServer(r, mcp ? mcp.has(r.id) : false);
      const from = describeSource(r);
      return from ? `${row}\n       from ${from}` : row;
    });
    return (
      lines.join("\n") +
      "\n\n(state: off = disabled, live = connected and callable, idle = approved but not started)" +
      (mcp ? "" : "\n(no manager attached in this process, so nothing is connected)")
    );
  }

  if (action === "remove") {
    const record = s.remove(args.id || args.name);
    if (!record) return `Error: no MCP server "${args.id || args.name}".`;
    return `Removed MCP server "${record.id}". Its tools are no longer offered.`;
  }

  if (action === "enable" || action === "disable") {
    const record = s.setEnabled(args.id || args.name, action === "enable");
    if (!record) return `Error: no MCP server "${args.id || args.name}".`;
    return action === "enable"
      ? enableMessage(record, s.isApproved(record))
      : disableMessage(record);
  }

  if (action === "reload") {
    const wanted = args.id || args.name;
    if (!wanted) return "Error: 'id' is required to reload. Which server?";
    const record = s.find(wanted);
    if (!record) return `Error: no MCP server "${wanted}".`;
    if (!mcp) return "Error: no MCP manager is attached to this session.";

    // Reaching here means the approval gate above already passed with this
    // command on screen, so this is where the grant is recorded.
    s.markApproved(record.id);
    return withReconnect(mcp, s, record);
  }

  return `Error: unknown action "${action}". Use search, install, add, list, remove, enable, disable, or reload.`;
}

/** Async part kept separate so run() stays a plain function for the registry. */
async function withReconnect(mcp, s, record) {
  try {
    if (mcp.has(record.id)) await mcp.disconnect(record.id);
    await mcp.connect({
      id: record.id,
      command: record.command,
      args: record.args,
      env: record.env,
      transport: record.transport,
    });
    s.markConnected(record.id, true, null);
    const tools = mcp.servers.get(record.id)?.tools?.map((t) => t.name) || [];
    return `Reloaded "${record.id}". Tools now available: ${tools.join(", ") || "(none advertised)"}`;
  } catch (err) {
    s.markConnected(record.id, false, err.message);
    return `Error: could not start "${record.id}": ${err.message}`;
  }
}
