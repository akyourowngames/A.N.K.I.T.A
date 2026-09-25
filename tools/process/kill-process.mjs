import { commandText, execute, integer, portOwners, processIdentity, processTable } from "../shared/_process.mjs";

export const name = "kill_process";
export const description = "Terminate an explicitly approved PID or the processes listening on a port. Previews commands and process identities; verifies the same owners immediately before termination. Windows uses taskkill /T; force:true adds /F (POSIX SIGKILL instead of SIGTERM).";
export const needsApproval = true;
export const readOnly = false;
export const parameters = { type: "object", properties: {
  pid: { type: "integer", minimum: 2, description: "PID to terminate; specify exactly one of pid or port." },
  port: { type: "integer", minimum: 1, maximum: 65535, description: "Terminate TCP listeners/bound UDP owners on this port." },
  force: { type: "boolean", description: "Force termination. Default false." },
}, additionalProperties: false };
const approvals = new WeakMap();
const bornAt = identity => {
  const match = String(identity).match(/^\/Date\((\d+)/);
  return match ? Number(match[1]) : Date.parse(identity);
};

function target(args) {
  if ((args.pid !== undefined) === (args.port !== undefined)) throw new Error("Specify exactly one of pid or port.");
  if (args.pid !== undefined) integer(args.pid, undefined, 2, 2147483647);
  if (args.port !== undefined) integer(args.port, undefined, 1, 65535);
  if (args.force !== undefined && typeof args.force !== "boolean") throw new Error("force must be a boolean.");
  if (args.pid === process.pid || args.pid === process.ppid) throw new Error("Refusing to terminate this agent or its parent process.");
  return JSON.stringify({ pid: args.pid, port: args.port, force: args.force === true });
}
async function identities(args, ctx) {
  const owners = args.port !== undefined ? await portOwners(args.port, ctx) : [{ pid: args.pid }];
  if (!owners.length) throw new Error(`No listener found on port ${args.port}.`);
  const pids = [...new Set(owners.map((owner) => owner.pid))].sort((a, b) => a - b);
  const table = await processTable(ctx);
  const byId = new Map(table.map(row => [row.pid, row]));
  const protectedPids = new Set();
  let ancestor = process.pid;
  while (ancestor > 1 && !protectedPids.has(ancestor)) {
    protectedPids.add(ancestor);
    ancestor = byId.get(ancestor)?.parent || 0;
  }
  const children = new Map();
  for (const row of table) {
    if (!children.has(row.parent)) children.set(row.parent, []);
    children.get(row.parent).push(row);
  }
  const selected = [], seen = new Set();
  const visit = (pid, parentBorn = 0) => {
    const row = byId.get(pid), born = row && bornAt(row.identity);
    if (!row || !Number.isFinite(born) || born < parentBorn) throw new Error(`Cannot verify process PID ${pid}.`);
    if (protectedPids.has(pid) || pid <= 1) throw new Error('Refusing to terminate this agent or an ancestor process.');
    if (seen.has(pid)) return;
    seen.add(pid);
    for (const child of children.get(pid) || []) visit(child.pid, born);
    selected.push(row); // descendants first, root last
  };
  for (const pid of pids) visit(pid);
  return selected;
}
function killCommand(pid, force) {
  return process.platform === "win32"
    ? ["taskkill", ["/PID", String(pid), "/T", ...(force ? ["/F"] : [])]]
    : ["kill", [force ? "-KILL" : "-TERM", String(pid)]];
}

export async function approval(args, ctx = {}) {
  const key = target(args);
  const processes = await identities(args, ctx);
  approvals.set(ctx, { key, processes, time: Date.now() });
  return processes.map((p) => `PID ${p.pid}: ${p.name} (started ${p.identity})\n$ ${commandText(...killCommand(p.pid, args.force))}`).join("\n") + (args.port ? `\nPort: ${args.port}` : "");
}

export async function run(args, ctx = {}) {
  const key = target(args);
  const approved = approvals.get(ctx);
  if (!approved || approved.key !== key || Date.now() - approved.time > 300000) throw new Error("A fresh approval preview and process snapshot are required before termination.");
  approvals.delete(ctx);
  const current = await identities(args, ctx);
  if (JSON.stringify(current) !== JSON.stringify(approved.processes)) throw new Error("Process identity or port ownership changed since approval; request a fresh preview.");
  const results = [];
  for (const p of current) {
    if (ctx.signal?.aborted) throw new Error("Termination cancelled.");
    // Check again immediately before each kill to narrow the PID-reuse race.
    let latest;
    try { latest = await processIdentity(p.pid, ctx); }
    catch { results.push(`PID ${p.pid} already exited.`); continue; }
    if (latest.identity !== p.identity || latest.name !== p.name) throw new Error(`PID ${p.pid} changed since approval; refusing termination.`);
    const [exe, argv] = killCommand(p.pid, args.force);
    if (process.platform === "win32") {
      const result = await execute(exe, argv, { signal: ctx.signal, timeout_ms: 15000 });
      results.push(`$ ${commandText(exe, argv)}\nexit code: ${result.code}\n${result.output}`);
    } else {
      process.kill(p.pid, args.force ? "SIGKILL" : "SIGTERM");
      results.push(`Sent ${args.force ? "SIGKILL" : "SIGTERM"} to PID ${p.pid} (${p.name}).`);
    }
  }
  return results.join("\n");
}
