import { portOwners } from "../shared/_process.mjs";
import { capOutput } from "../shared/_shared.mjs";

export const name = "port_status";
export const description = "Inspect TCP listeners and bound UDP sockets on a local port, with owning PIDs. Read-only. Uses netstat on Windows and lsof/ss on POSIX.";
export const needsApproval = false;
export const readOnly = true;
export const parameters = { type: "object", properties: { port: { type: "integer", minimum: 1, maximum: 65535 } }, required: ["port"], additionalProperties: false };

export async function run(args, ctx = {}) {
  const owners = await portOwners(args.port, ctx);
  if (!owners.length) return `No listener or bound UDP process found on port ${args.port}.`;
  return capOutput(`Port ${args.port}:\n` + owners.map((owner) => `${owner.protocol} ${owner.address} ${owner.state} PID ${owner.pid ?? "unknown (insufficient permissions)"}${owner.name ? ` (${owner.name})` : ""}`).join("\n"));
}
