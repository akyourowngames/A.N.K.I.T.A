import fs from "node:fs";
import path from "node:path";
import { resolvePath } from "./_shared.mjs";

export const name = "delete_file";
export const description =
  "Delete a file, or a directory with recursive:true. Refuses the working directory itself.";

export const parameters = {
  type: "object",
  properties: {
    path: { type: "string", description: "Path to delete, absolute or relative to the working directory." },
    recursive: { type: "boolean", description: "Delete directories and their contents. Default false." },
  },
  required: ["path"],
};

export function approval(args, ctx) {
  return `delete  ${resolvePath(args.path, ctx)}${args.recursive ? "  (recursive)" : ""}`;
}

export function run(args, ctx = {}) {
  if (!args.path || typeof args.path !== "string") throw new Error("path is required.");
  const p = resolvePath(args.path, ctx);
  const root = path.resolve(ctx.cwd || process.cwd());
  if (p === root) throw new Error(`Refusing to delete the working directory root: ${p}`);
  if (!fs.existsSync(p)) throw new Error(`no such file or directory: ${p}`);
  const stat = fs.statSync(p);
  if (stat.isDirectory()) {
    if (!args.recursive) throw new Error(`${p} is a directory; pass recursive:true to delete it.`);
    fs.rmSync(p, { recursive: true, force: true });
  } else {
    fs.unlinkSync(p);
  }
  return `Deleted ${p}`;
}
