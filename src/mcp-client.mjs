import { spawn } from "node:child_process";
import { killTree, waitForExit } from "../tools/run-command.mjs";

/**
 * Minimal MCP client: JSON-RPC 2.0 over a server's stdio.
 *
 * Hand-rolled on purpose - the protocol is newline-delimited JSON with an id
 * per request, and this repo already has the hard parts (spawn with candidate
 * resolution, tree-kill, tolerant line framing) elsewhere. Pulling the SDK
 * would break the zero-dependency rule for ~200 lines of framing.
 *
 * The installed Python SDK is the reference implementation: if this client
 * interoperates with it, the protocol is right. See scripts/mcp_fixture.py.
 */

export const LATEST_PROTOCOL = "2025-11-25";

/**
 * On Windows a bare `npx` is not spawnable - CreateProcess wants npx.cmd.
 * Same shape as pythonCandidates() in tools/_web.mjs.
 */
export function commandCandidates(command) {
  const cmd = String(command || "").trim();
  if (!cmd) return [];
  if (process.platform !== "win32") return [cmd];
  if (/\.(cmd|exe|bat|com)$/i.test(cmd)) return [cmd];
  return [`${cmd}.cmd`, cmd];
}

/** Environment a spawned server is allowed to see. Not the whole process env. */
export function serverEnv(extra = {}) {
  const keep = ["PATH", "PATHEXT", "SystemRoot", "windir", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG"];
  const env = {};
  for (const key of keep) {
    if (process.env[key] !== undefined) env[key] = process.env[key];
  }
  for (const [k, v] of Object.entries(extra || {})) env[k] = String(v);
  return env;
}

/**
 * MCP reports a *tool* failure inside a successful JSON-RPC response, as
 * result.isError with the message in content - not as a JSON-RPC error.
 * Verified against the Python SDK: a raising tool returns
 *   { content: [{type:"text", text:"Error executing tool boom: ..."}], isError: true }
 * with no `error` member at all.
 *
 * So it has to be turned into "Error: ..." here, or the model reads a failed
 * call as a successful one.
 */
export function formatToolResult({ text, isError } = {}) {
  const body = String(text ?? "").trim() || "(empty result)";
  return isError ? `Error: ${body}` : body;
}

/** Flattens an MCP tool result into text the model can read. */
export function toolResultText(result) {
  if (!result) return "(no result)";
  if (Array.isArray(result.content)) {
    const parts = result.content
      .map((c) => (c?.type === "text" ? c.text : c?.type ? `[${c.type}]` : ""))
      .filter(Boolean);
    if (parts.length) return parts.join("\n");
  }
  if (result.structuredContent !== undefined) return JSON.stringify(result.structuredContent);
  return "(empty result)";
}

export class McpClient {
  constructor({
    id,
    command,
    args = [],
    env = {},
    cwd,
    requestTimeoutMs = 30000,
    initTimeoutMs = 90000,
    onToolsChanged = null,
    onStderr = null,
    clientName = "ankita",
    clientVersion = "2.0.0",
  } = {}) {
    this.id = id;
    this.command = command;
    this.args = args;
    this.env = env;
    this.cwd = cwd;
    this.requestTimeoutMs = requestTimeoutMs;
    this.initTimeoutMs = initTimeoutMs;
    this.onToolsChanged = onToolsChanged;
    this.onStderr = onStderr;
    this.clientName = clientName;
    this.clientVersion = clientVersion;

    this.child = null;
    this.nextId = 1;
    this.pending = new Map();
    this.buffer = "";
    this.tools = [];
    this.serverInfo = null;
    this.protocolVersion = null;
    this.closed = false;
    this.job = null;
  }

  /** Spawn the server, negotiate, and fetch its tool list. */
  async connect() {
    if (this.child) return this;
    const candidates = commandCandidates(this.command);
    if (!candidates.length) throw new Error("no command to run for this MCP server");

    const errors = [];
    for (const exe of candidates) {
      try {
        this.child = spawn(exe, this.args, {
          cwd: this.cwd || process.cwd(),
          env: serverEnv(this.env),
          windowsHide: true,
          stdio: ["pipe", "pipe", "pipe"],
        });
      } catch (err) {
        errors.push(`${exe}: ${err.message}`);
        continue;
      }

      // A missing binary surfaces asynchronously, not as a throw.
      const spawnFailed = await new Promise((resolve) => {
        const timer = setTimeout(() => resolve(null), 300);
        this.child.once("error", (err) => {
          clearTimeout(timer);
          resolve(err);
        });
        this.child.once("spawn", () => {
          clearTimeout(timer);
          resolve(null);
        });
      });
      if (spawnFailed) {
        errors.push(`${exe}: ${spawnFailed.message}`);
        try {
          this.child.kill("SIGKILL");
        } catch {}
        this.child = null;
        continue;
      }
      break;
    }

    if (!this.child) {
      throw new Error(`could not start the MCP server (${errors.join("; ") || "no candidates"})`);
    }

    this.job = { child: this.child, done: false, code: null };
    this.child.on("close", (code) => {
      this.job.done = true;
      this.job.code = code;
      // Anything still waiting will never be answered.
      for (const [id, entry] of this.pending) {
        clearTimeout(entry.timer);
        entry.reject(new Error(`MCP server exited (code ${code}) while waiting for ${entry.method}`));
        this.pending.delete(id);
      }
    });

    this.child.stdout.on("data", (chunk) => this._onStdout(chunk));
    this.child.stderr.on("data", (chunk) => {
      const text = chunk.toString("utf8");
      this.onStderr?.(text);
    });

    const init = await this.request(
      "initialize",
      {
        protocolVersion: LATEST_PROTOCOL,
        capabilities: {},
        clientInfo: { name: this.clientName, version: this.clientVersion },
      },
      { timeoutMs: this.initTimeoutMs }
    );
    this.serverInfo = init?.serverInfo ?? null;
    this.protocolVersion = init?.protocolVersion ?? null;

    // Required by the spec before any other request.
    this.notify("notifications/initialized", {});

    await this.refreshTools();
    return this;
  }

  _onStdout(chunk) {
    this.buffer += chunk.toString("utf8");
    let index;
    while ((index = this.buffer.indexOf("\n")) >= 0) {
      const line = this.buffer.slice(0, index).trim();
      this.buffer = this.buffer.slice(index + 1);
      if (!line) continue;
      let message;
      try {
        message = JSON.parse(line);
      } catch {
        // Not JSON: launchers like npx write install progress to stdout, which
        // the transport forbids for servers but which we cannot control.
        continue;
      }
      this._dispatch(message);
    }
  }

  _dispatch(message) {
    if (message.id !== undefined && this.pending.has(message.id)) {
      const entry = this.pending.get(message.id);
      this.pending.delete(message.id);
      clearTimeout(entry.timer);
      if (message.error) {
        const err = new Error(message.error.message || "MCP error");
        err.code = message.error.code;
        err.data = message.error.data;
        entry.reject(err);
      } else {
        entry.resolve(message.result);
      }
      return;
    }
    if (message.method === "notifications/tools/list_changed") {
      this.refreshTools().catch(() => {});
      this.onToolsChanged?.(this);
    }
  }

  /** Sends a request and waits for its matching id. */
  request(method, params = {}, { timeoutMs = this.requestTimeoutMs } = {}) {
    if (!this.child) return Promise.reject(new Error("MCP server is not connected"));
    const id = this.nextId++;
    const payload = { jsonrpc: "2.0", id, method, params };
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`MCP request "${method}" timed out after ${timeoutMs}ms`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer, method });
      try {
        this.child.stdin.write(JSON.stringify(payload) + "\n");
      } catch (err) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(err);
      }
    });
  }

  /** Fire-and-forget. Notifications have no id and expect no reply. */
  notify(method, params = {}) {
    if (!this.child) return;
    try {
      this.child.stdin.write(JSON.stringify({ jsonrpc: "2.0", method, params }) + "\n");
    } catch {}
  }

  async refreshTools() {
    const result = await this.request("tools/list", {});
    this.tools = Array.isArray(result?.tools) ? result.tools : [];
    return this.tools;
  }

  async callTool(name, args = {}) {
    const result = await this.request("tools/call", { name, arguments: args });
    return {
      text: toolResultText(result),
      isError: Boolean(result?.isError),
      raw: result,
    };
  }

  async close() {
    if (this.closed) return;
    this.closed = true;
    for (const entry of this.pending.values()) clearTimeout(entry.timer);
    this.pending.clear();
    if (!this.child) return;
    try {
      this.child.stdin.end();
    } catch {}
    killTree(this.child);
    await waitForExit(this.job, 3000);
    this.child = null;
  }
}
