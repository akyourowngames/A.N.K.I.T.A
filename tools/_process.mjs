import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import { BoundedOutput } from "./_shared.mjs";

export function integer(value, fallback, min, max) {
  if (value === undefined) return fallback;
  if (!Number.isInteger(value) || value < min || value > max) throw new Error(`Value must be an integer between ${min} and ${max}.`);
  return value;
}

export function commandText(exe, args) {
  return [exe, ...args].map((s) => /^[\w./:=@{}+-]+$/.test(s) ? s : JSON.stringify(s)).join(" ");
}

/** Shell-free execution with bounded collection and cancellable process trees. */
export function execute(exe, args, { cwd, signal, timeout_ms = 30000, max_output_bytes = 65536, env } = {}) {
  if (signal?.aborted) return Promise.reject(new Error("Command cancelled."));
  return new Promise((resolve, reject) => {
    const out = new BoundedOutput(max_output_bytes);
    const child = spawn(exe, args, { cwd, env: env || process.env, shell: false, windowsHide: true, detached: process.platform !== "win32", stdio: ["ignore", "pipe", "pipe"] });
    let done = false;
    let stopped = null;
    let grace;
    const finish = (error, code) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      clearTimeout(grace);
      signal?.removeEventListener("abort", onAbort);
      if (error) reject(error);
      else resolve({ code, output: out.toString(), truncated: out.total > max_output_bytes });
    };
    const stop = (reason) => {
      if (stopped) return;
      stopped = new Error(reason);
      if (child.pid && process.platform === "win32") {
        const killer = spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { shell: false, windowsHide: true, stdio: "ignore" });
        killer.on("error", () => { try { child.kill("SIGKILL"); } catch {} });
      } else {
        try { process.kill(-child.pid, "SIGKILL"); } catch { try { child.kill("SIGKILL"); } catch {} }
      }
      grace = setTimeout(() => { child.stdout?.destroy(); child.stderr?.destroy(); finish(stopped); }, 3000);
    };
    const timer = setTimeout(() => stop(`Command timed out after ${timeout_ms}ms.`), timeout_ms);
    const onAbort = () => stop("Command cancelled.");
    signal?.addEventListener("abort", onAbort, { once: true });
    child.stdout.on("data", (data) => out.append(data));
    child.stderr.on("data", (data) => out.append(data));
    child.on("error", (error) => finish(error));
    child.on("close", (code) => finish(stopped, code));
    if (signal?.aborted) onAbort();
  });
}

function endpointPort(endpoint) { return Number(endpoint?.match(/:(\d+)$/)?.[1]); }

export function parseNetstat(text, port) {
  const rows = [];
  for (const line of text.split(/\r?\n/)) {
    const cells = line.trim().split(/\s+/);
    const protocol = cells[0]?.toUpperCase();
    if (!['TCP', 'UDP'].includes(protocol) || endpointPort(cells[1]) !== port) continue;
    if (protocol === "TCP" && cells[3] !== "LISTENING") continue;
    const pid = Number(cells[protocol === "TCP" ? 4 : 3]);
    if (Number.isInteger(pid)) rows.push({ pid, protocol, address: cells[1], state: protocol === "TCP" ? "LISTEN" : "BOUND" });
  }
  return rows;
}

export function parseLsof(text, port) {
  const rows = [];
  let pid, name, socket;
  const flush = () => {
    if (socket && endpointPort(socket.address?.split("->")[0]) === port && (!socket.state || socket.state === "LISTEN")) rows.push({ pid, name, protocol: socket.state ? "TCP" : "UDP", state: socket.state || "BOUND", address: socket.address });
    socket = null;
  };
  for (const line of text.split(/\r?\n/)) {
    if (line[0] === "p") { flush(); pid = Number(line.slice(1)); name = undefined; }
    if (line[0] === "c") name = line.slice(1);
    if (line[0] === "f") { flush(); socket = {}; }
    if (line[0] === "n") { socket ||= {}; socket.address = line.slice(1); }
    if (line.startsWith("TST=")) { socket ||= {}; socket.state = line.slice(4); }
  }
  flush();
  return rows;
}

export function parseSs(text, port) {
  const rows = [];
  for (const line of text.split(/\r?\n/)) {
    const cells = line.trim().split(/\s+/);
    if (endpointPort(cells[4]) !== port) continue;
    for (const match of line.matchAll(/\("([^"]+)",pid=(\d+),/g)) rows.push({ pid: Number(match[2]), name: match[1], protocol: cells[0].toUpperCase(), state: cells[1], address: cells[4] });
    if (!/pid=\d+/.test(line)) rows.push({ pid: null, protocol: cells[0].toUpperCase(), state: cells[1], address: cells[4] });
  }
  return rows;
}

export async function portOwners(port, ctx = {}) {
  integer(port, undefined, 1, 65535);
  if (port === undefined) throw new Error("port is required.");
  const options = { signal: ctx.signal, timeout_ms: 15000, max_output_bytes: 2 * 1024 * 1024 };
  let result;
  if (process.platform === "win32") {
    result = await execute("netstat", ["-ano"], options);
    if (result.code !== 0 || result.truncated) throw new Error(`Could not inspect port: ${result.output}`);
    return parseNetstat(result.output, port);
  }
  try {
    result = await execute("lsof", ["-nP", `-i:${port}`, "-FpcfnT"], options);
    if (result.truncated || (result.code !== 0 && result.code !== 1)) throw new Error(`Could not inspect port: ${result.output}`);
    return parseLsof(result.output, port);
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
    result = await execute("ss", ["-H", "-lntup", "sport", "=", `:${port}`], options);
    if (result.code !== 0 || result.truncated) throw new Error(`Could not inspect port: ${result.output}`);
    return parseSs(result.output, port);
  }
}

/** Creation time prevents approving one PID and later terminating its replacement. */
export async function processIdentity(pid, ctx = {}) {
  integer(pid, undefined, 2, 2147483647);
  const options = { signal: ctx.signal, timeout_ms: 15000, max_output_bytes: 65536 };
  if (process.platform === "win32") {
    const script = `Get-CimInstance Win32_Process -Filter 'ProcessId = ${pid}' | Select-Object ProcessId,ParentProcessId,CreationDate,Name | ConvertTo-Json -Compress`;
    const result = await execute("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], options);
    if (result.code !== 0 || result.truncated) throw new Error(`Cannot inspect PID ${pid}: ${result.output}`);
    const value = result.output.trim() ? JSON.parse(result.output) : null;
    if (!value?.CreationDate) throw new Error(`PID ${pid} is no longer running or its identity is unavailable.`);
    return { pid, parent: value.ParentProcessId, name: value.Name, identity: String(value.CreationDate) };
  }
  if (process.platform === "linux") {
    try {
      const stat = await fs.readFile(`/proc/${pid}/stat`, "utf8");
      const end = stat.lastIndexOf(")");
      const fields = stat.slice(end + 2).trim().split(/\s+/);
      return { pid, parent: Number(fields[1]), name: stat.slice(stat.indexOf("(") + 1, end), identity: fields[19] };
    } catch (error) { throw new Error(`Cannot inspect PID ${pid}: ${error.message}`); }
  }
  const result = await execute("ps", ["-p", String(pid), "-o", "ppid=", "-o", "lstart=", "-o", "comm="], options);
  const match = result.output.trim().match(/^(\d+)\s+(.{24})\s+(.+)$/);
  if (result.code !== 0 || !match) throw new Error(`PID ${pid} is no longer running or its identity is unavailable.`);
  return { pid, parent: Number(match[1]), identity: match[2], name: match[3] };
}
