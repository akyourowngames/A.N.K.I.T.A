import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { killTree, waitForExit } from "../../tools/process/run-command.mjs";

/**
 * Minimal MCP client: JSON-RPC 2.0 over a server's stdio.
 *
 * Hand-rolled on purpose - the protocol is newline-delimited JSON with an id
 * per request, and this repo already has the hard parts (spawn with candidate
 * resolution, tree-kill, tolerant line framing) elsewhere. Pulling the SDK
 * would break the zero-dependency rule for ~200 lines of framing.
 *
 * The installed Python SDK is the reference implementation: if this client
 * interoperates with it, the protocol is right. See scripts/fixtures/mcp_fixture.py.
 */

export const LATEST_PROTOCOL = "2025-11-25";

/**
 * The Node tool shims, and the script each one wraps.
 *
 * Windows resolves `npx` to npx.cmd, and Node refuses to spawn a .cmd without
 * a shell (the CVE-2024-27980 fix). A shell is precisely what must not be
 * used here: package names come from a registry, and interpolating them into
 * a command line is the injection class that fix closed. So we run the script
 * the shim wraps, with node, exactly as the shim would have.
 */
const NODE_SHIMS = {
  npx: ["npm", "bin", "npx-cli.js"],
  npm: ["npm", "bin", "npm-cli.js"],
};

function npmRoots() {
  const roots = [];
  if (process.execPath) roots.push(path.join(path.dirname(process.execPath), "node_modules"));
  if (process.env.APPDATA) roots.push(path.join(process.env.APPDATA, "npm", "node_modules"));
  if (process.env.ProgramFiles) roots.push(path.join(process.env.ProgramFiles, "nodejs", "node_modules"));
  return roots;
}

/** The final path segment of a command, so `C:\...\npx.cmd` matches `npx`. */
function commandBase(command) {
  return String(command || "").trim().split(/[\\/]/).pop();
}

/** The .js a `npx`/`npm` command really runs, or null if we cannot find it. */
function shimScript(command) {
  const key = commandBase(command).toLowerCase().replace(/\.(cmd|bat)$/, "");
  const rel = NODE_SHIMS[key];
  if (!rel) return null;
  for (const root of npmRoots()) {
    const candidate = path.join(root, ...rel);
    try {
      if (fs.existsSync(candidate)) return candidate;
    } catch {}
  }
  return null;
}

/**
 * Executable candidates to try, as {command, args} pairs so a candidate can
 * prepend its own arguments. On win32 the Node shims become `node <cli.js>`;
 * anything else falls back to the usual extensions, and an unresolvable batch
 * shim is reported rather than attempted (spawning one throws EINVAL).
 */
export function commandCandidates(command) {
  const cmd = String(command || "").trim();
  if (!cmd) return [];
  if (process.platform !== "win32") return [{ command: cmd, args: [] }];

  if (/\.(exe|com)$/i.test(cmd)) return [{ command: cmd, args: [] }];

  const script = shimScript(cmd);
  if (script) return [{ command: process.execPath || "node", args: [script] }];

  if (/\.(cmd|bat)$/i.test(cmd)) {
    return [
      {
        command: cmd,
        args: [],
        problem:
          `"${cmd}" is a batch shim, and Windows will not let a program start one without a ` +
          `command shell. Point the server at the underlying script instead.`,
      },
    ];
  }

  return [
    { command: `${cmd}.exe`, args: [] },
    { command: `${cmd}.cmd`, args: [] },
    { command: cmd, args: [] },
  ];
}

function npxCacheRoots() {
  const roots = [];
  if (process.env.LOCALAPPDATA) roots.push(path.join(process.env.LOCALAPPDATA, "npm-cache", "_npx"));
  if (process.env.APPDATA) roots.push(path.join(process.env.APPDATA, "npm-cache", "_npx"));
  return roots;
}

function parsePackageSpec(spec) {
  const value = String(spec || "").trim();
  if (!value) return null;
  const at = value.lastIndexOf("@");
  return at > 0 ? { name: value.slice(0, at), version: value.slice(at + 1) } : { name: value, version: "" };
}

/**
 * The entry script of a package already in the npx cache, or null.
 *
 * Running `npx` on Windows goes through npm's spawner, which does not set
 * windowsHide - so every npx MCP server flashes a console window. npx has
 * already installed the package by the time a server reconnects, so we run the
 * cached entry script with node directly and no shell is involved at all.
 */
export function resolveNpxBin(spec) {
  const parsed = parsePackageSpec(spec);
  if (!parsed?.name) return null;
  for (const root of npxCacheRoots()) {
    let entries;
    try {
      entries = fs.readdirSync(root, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (!entry.isDirectory()) continue;
      const packageDir = path.join(root, entry.name, "node_modules", ...parsed.name.split("/"));
      let manifest;
      try {
        manifest = JSON.parse(fs.readFileSync(path.join(packageDir, "package.json"), "utf8"));
      } catch {
        continue;
      }
      if (manifest.name !== parsed.name) continue;
      if (parsed.version && !String(manifest.version || "").startsWith(parsed.version.replace(/^[\^~]/, ""))) continue;
      const bin = manifest.bin;
      const relative = typeof bin === "string" ? bin : bin && (bin[parsed.name.split("/").pop()] || Object.values(bin)[0]);
      if (!relative) continue;
      const file = path.join(packageDir, relative);
      try {
        if (fs.statSync(file).isFile()) return file;
      } catch {}
    }
  }
  return null;
}

/**
 * Rewrite an `npx <pkg> ...` launch into `node <cached entry> ...` when the
 * package is cached, dropping npx's own flags. Anything else is returned as-is.
 */
export function resolveLaunch(command, args = []) {
  // Match on the basename: a server configured with a full path such as
  // `C:\Program Files\nodejs\npx.cmd` is still npx. The original command is
  // returned untouched when nothing is rewritten.
  const key = commandBase(command).toLowerCase().replace(/\.(cmd|bat|exe)$/, "");
  if (key === "uvx" || key === "uv") return resolveUvxLaunch(command, args);
  if (key !== "npx") return { command, args };
  const list = [...args];
  const index = list.findIndex((arg) => typeof arg === "string" && !arg.startsWith("-"));
  if (index < 0) return { command, args };
  const bin = resolveNpxBin(list[index]);
  return bin ? { command: process.execPath || "node", args: [bin, ...list.slice(index + 1)] } : { command, args };
}

const UV_CACHE_ROOT = () => (process.env.LOCALAPPDATA ? path.join(process.env.LOCALAPPDATA, "uv", "cache", "archive-v0") : null);

function uvxPackageName(spec) {
  return String(spec || "").trim().split(/[=<>~!]/)[0].trim();
}

/**
 * The module a cached uv console script runs, read from the launcher's own
 * embedded source (`from <module> import main`). Null when it cannot be read.
 */
function moduleOfConsoleScript(exe) {
  try {
    const bytes = fs.readFileSync(exe);
    const text = bytes.toString("utf8");
    const match = /from\s+([A-Za-z0-9_.]+)\s+import\s+main/.exec(text);
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

/**
 * A cached uv entry point for `uvx <pkg>`, or null.
 *
 * `uvx` is `uv tool run`: on Windows it always allocates a console (verified: a
 * conhost.exe child appears regardless of windowsHide or detached) because uv is
 * a console application. The package's own launcher is also a console exe, so
 * neither can be spawned without a window. The fix is to skip both: run the
 * launcher's module with the same venv's `pythonw.exe`, the windowless
 * interpreter, which starts no console at all.
 */
export function resolveUvxTool(spec) {
  const name = uvxPackageName(spec);
  if (!name) return null;
  const root = UV_CACHE_ROOT();
  if (!root) return null;
  let entries;
  try {
    entries = fs.readdirSync(root, { withFileTypes: true });
  } catch {
    return null;
  }
  let best = null;
  for (const entry of entries) {
    if (!entry.isDirectory()) continue;
    const scripts = path.join(root, entry.name, "Scripts");
    let files;
    try {
      files = fs.readdirSync(scripts);
    } catch {
      continue;
    }
    const exe = files.includes(`${name}.exe`)
      ? path.join(scripts, `${name}.exe`)
      : null;
    const pythonw = files.includes("pythonw.exe") ? path.join(scripts, "pythonw.exe") : null;
    if (!exe) continue;
    try {
      if (!fs.statSync(exe).isFile()) continue;
      const stat = fs.statSync(exe);
      // The newest archive wins: the uv cache is append-only across versions.
      if (best && stat.mtimeMs < best.mtimeMs) continue;
      best = { exe, pythonw, module: pythonw ? moduleOfConsoleScript(exe) : null, mtimeMs: stat.mtimeMs };
    } catch {}
  }
  return best;
}

function resolveUvxLaunch(command, args = []) {
  const list = [...args];
  const index = list.findIndex((arg) => typeof arg === "string" && !arg.startsWith("-"));
  if (index < 0) return { command, args: list };
  const tool = resolveUvxTool(list[index]);
  if (!tool) return { command, args: list };
  const module = tool.module ? ["-m", tool.module] : [tool.exe];
  return { command: tool.pythonw || tool.exe, args: [...module, ...list.slice(index + 1)] };
}

/** Environment a spawned server is allowed to see. Not the whole process env. */
export function serverEnv(extra = {}) {
  const keep = ["PATH", "PATHEXT", "SystemRoot", "windir", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG"];
  // MCP servers are background services, not interactive command-line apps.
  // CI discourages launchers and descendants from opening prompts or terminal
  // UI windows alongside the desktop app.
  const env = { CI: '1', NO_COLOR: '1', UV_NO_PROGRESS: '1' };
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
  const raw = String(text ?? "").trim() || "(empty result)";
  if (!isError) return raw;
  // Errors arrive in several shapes: "### Error\nError: ..." from Playwright,
  // "Error executing tool boom: ..." from the Python SDK. Normalise to a single
  // leading "Error: " so it reads as one failure and is unambiguous to match on.
  const body = raw
    .replace(/^#+\s*error\s*:?\s*/i, "")
    .replace(/^error\b[^:]*:\s*/i, "")
    .trim();
  return `Error: ${body || raw}`;
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
    transport = "stdio",
    url,
    headers = {},
    fetchImpl = fetch,
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
    this.transport = transport;
    this.url = url;
    this.headers = headers;
    this.fetchImpl = fetchImpl;
    this.httpConnected = false;
    this.mcpSessionId = null;
    this.httpRequests = new Set();
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
    if (this.transport === "http") {
      if (this.httpConnected) return this;
      if (!this.url) throw new Error("HTTP MCP server needs a URL");
      this.closed = false;
      this.httpConnected = true;
      try {
        const init = await this.request("initialize", {
          protocolVersion: LATEST_PROTOCOL,
          capabilities: {},
          clientInfo: { name: this.clientName, version: this.clientVersion },
        }, { timeoutMs: this.initTimeoutMs });
        this.serverInfo = init?.serverInfo ?? null;
        this.protocolVersion = init?.protocolVersion ?? null;
        await this.notify("notifications/initialized", {});
        await this.refreshTools();
        return this;
      } catch (err) {
        this.httpConnected = false;
        this.mcpSessionId = null;
        throw err;
      }
    }
    if (this.child) return this;
    const resolved = resolveLaunch(this.command, this.args);
    this.command = resolved.command;
    this.args = resolved.args;
    const candidates = commandCandidates(this.command);
    if (!candidates.length) throw new Error("no command to run for this MCP server");

    const errors = [];
    for (const candidate of candidates) {
      if (candidate.problem) {
        errors.push(candidate.problem);
        continue;
      }
      const exe = candidate.command;
      // A candidate may prepend its own args (node <cli.js>) ahead of ours.
      const argv = [...candidate.args, ...this.args];
      try {
        this.child = spawn(exe, argv, {
          cwd: this.cwd || process.cwd(),
          env: serverEnv(this.env),
          shell: false,
          windowsHide: true,
          // A console-subsystem server (uv's mcp-server-*.exe, a python exe)
          // still allocates a console under windowsHide alone. Detached gives
          // it no console at all on Windows, which is what stops the window.
          detached: process.platform === "win32",
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
    if (this.transport === "http") {
      if (!this.httpConnected) return Promise.reject(new Error("MCP server is not connected"));
      const id = this.nextId++;
      return this._httpPost({ jsonrpc: "2.0", id, method, params }, timeoutMs).then((message) => {
        if (message?.error) {
          const err = new Error(message.error.message || "MCP error");
          err.code = message.error.code;
          err.data = message.error.data;
          throw err;
        }
        return message?.result;
      });
    }
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
    if (this.transport === "http") {
      if (!this.httpConnected) return Promise.resolve();
      return this._httpPost({ jsonrpc: "2.0", method, params }, this.requestTimeoutMs);
    }
    if (!this.child) return;
    try {
      this.child.stdin.write(JSON.stringify({ jsonrpc: "2.0", method, params }) + "\n");
    } catch {}
  }

  async _httpPost(payload, timeoutMs) {
    const controller = new AbortController();
    this.httpRequests.add(controller);
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await this.fetchImpl(this.url, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          accept: "application/json, text/event-stream",
          ...this.headers,
          ...(this.mcpSessionId ? { "mcp-session-id": this.mcpSessionId } : {}),
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`MCP HTTP request failed (HTTP ${response.status})`);
      const sessionId = response.headers.get("mcp-session-id");
      if (sessionId) this.mcpSessionId = sessionId;
      if (payload.id === undefined || response.status === 202 || response.status === 204) return null;
      const text = await response.text();
      const contentType = response.headers.get("content-type") || "";
      let messages;
      if (contentType.includes("text/event-stream")) {
        messages = text.split(/\r?\n\r?\n/).flatMap((frame) => {
          const data = frame.split(/\r?\n/).filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trim()).join("\n");
          if (!data || data === "[DONE]") return [];
          try { return [JSON.parse(data)]; } catch { return []; }
        });
      } else {
        const parsed = JSON.parse(text);
        messages = Array.isArray(parsed) ? parsed : [parsed];
      }
      const match = messages.find((message) => message?.id === payload.id);
      if (!match) throw new Error(`MCP HTTP response omitted request id ${payload.id}`);
      return match;
    } catch (err) {
      if (controller.signal.aborted && !this.closed) throw new Error(`MCP request "${payload.method}" timed out after ${timeoutMs}ms`);
      throw err;
    } finally {
      clearTimeout(timer);
      this.httpRequests.delete(controller);
    }
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
    if (this.transport === "http") {
      for (const controller of this.httpRequests) controller.abort();
      this.httpRequests.clear();
      this.httpConnected = false;
      this.mcpSessionId = null;
      return;
    }
    if (!this.child) return;
    try {
      this.child.stdin.end();
    } catch {}
    killTree(this.child);
    await waitForExit(this.job, 3000);
    this.child = null;
  }
}
