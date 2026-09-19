import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { writeTextFile } from "../tools/_shared.mjs";
import { slug } from "./mcp-manager.mjs";

/**
 * Configured MCP servers, on disk.
 *
 * Same shape as RoutineStore/ProjectStore: atomic write, and every mutation
 * re-reads first so two writers (the REPL, a running daemon) never clobber
 * each other.
 */

export const MCP_VERSION = 1;

/**
 * Approval is granted to a *command*, not to a name.
 *
 * "npx -y pkg@1.2.3" being approved must not silently authorise
 * "npx -y pkg@9.9.9" later. The hash is what gets remembered.
 */
export function commandHash(command, args = []) {
  const blob = JSON.stringify({ command: String(command || ""), args: args.map(String) });
  return crypto.createHash("sha256").update(blob, "utf8").digest("hex").slice(0, 16);
}

export class McpStore {
  constructor(file) {
    this.file = file;
    this.data = { version: MCP_VERSION, servers: [] };
  }

  load() {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.file, "utf8"));
      this.data = {
        version: MCP_VERSION,
        servers: Array.isArray(parsed.servers) ? parsed.servers.filter((s) => s && s.id) : [],
      };
    } catch {
      // Missing or malformed: start empty rather than break the CLI on boot.
      this.data = { version: MCP_VERSION, servers: [] };
    }
    return this;
  }

  save() {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    writeTextFile(this.file, JSON.stringify(this.data, null, 2), "\n");
    return this;
  }

  /** Re-read before writing: the REPL and the daemon each hold their own. */
  _fresh() {
    this.load();
    return this;
  }

  get servers() {
    return this.data.servers;
  }

  get enabled() {
    return this.servers.filter((s) => s.enabled !== false);
  }

  find(idOrName) {
    const key = String(idOrName ?? "").trim().toLowerCase();
    if (!key) return null;
    return (
      this.servers.find((s) => s.id === key) ||
      this.servers.find((s) => String(s.name || "").toLowerCase() === key) ||
      null
    );
  }

  add({ name, command, args = [], env = {}, transport = "stdio", id }) {
    this._fresh();
    const cmd = String(command ?? "").trim();
    if (!cmd) throw new Error("a command is required (e.g. 'npx' or 'python')");
    const serverId = slug(id || name || cmd);
    if (this.find(serverId)) throw new Error(`an MCP server called "${serverId}" already exists`);

    const record = {
      id: serverId,
      name: String(name || serverId),
      command: cmd,
      args: Array.isArray(args) ? args.map(String) : String(args).split(/\s+/).filter(Boolean),
      env: env && typeof env === "object" ? env : {},
      transport,
      enabled: true,
      // Nothing runs until the user approves this exact command.
      approvedAt: null,
      approvedHash: null,
      commandHash: commandHash(cmd, args),
      addedAt: new Date().toISOString(),
      lastConnectedAt: null,
      lastError: null,
    };
    this.servers.push(record);
    this.save();
    return record;
  }

  remove(idOrName) {
    this._fresh();
    const record = this.find(idOrName);
    if (!record) return null;
    this.data.servers = this.servers.filter((s) => s !== record);
    this.save();
    return record;
  }

  setEnabled(idOrName, enabled) {
    this._fresh();
    const record = this.find(idOrName);
    if (!record) return null;
    record.enabled = Boolean(enabled);
    this.save();
    return record;
  }

  /** Records that the user approved this exact command. */
  markApproved(idOrName, at = new Date().toISOString()) {
    this._fresh();
    const record = this.find(idOrName);
    if (!record) return null;
    record.approvedAt = at;
    record.approvedHash = record.commandHash;
    this.save();
    return record;
  }

  /** True when this server may be started without asking again. */
  isApproved(record) {
    return Boolean(record && record.approvedHash && record.approvedHash === record.commandHash);
  }

  markConnected(idOrName, ok, error = null) {
    this._fresh();
    const record = this.find(idOrName);
    if (!record) return null;
    if (ok) record.lastConnectedAt = new Date().toISOString();
    record.lastError = error;
    this.save();
    return record;
  }
}

export function describeServer(record, connected) {
  const state = record.enabled === false ? "off" : connected ? "live" : "idle";
  const approved = record.approvedHash === record.commandHash ? "" : "  (needs approval)";
  const err = record.lastError ? `  ! ${String(record.lastError).slice(0, 60)}` : "";
  return `${state.padEnd(4)} ${record.id.padEnd(16)} ${(record.command + " " + (record.args || []).join(" ")).slice(0, 50)}${approved}${err}`;
}
