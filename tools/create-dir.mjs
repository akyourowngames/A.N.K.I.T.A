import fs from "node:fs";
import path from "node:path";
import { resolvePath } from "./_shared.mjs";

export const name = "create_dir";
export const description = "Create a directory and any missing parents (like mkdir -p).";

export const parameters = {
  type: "object",
  properties: {
    path: { type: "string", description: "Directory to create, absolute or relative to the working directory." },
  },
  required: ["path"],
};

export function approval(args, ctx) {
  return `create directory  ${resolvePath(args.path, ctx)}`;
}

export function run(args, ctx = {}) {
  if (!args.path || typeof args.path !== "string") throw new Error("path is required.");
  const p = resolvePath(args.path, ctx);
  fs.mkdirSync(p, { recursive: true });
  return `Directory ready: ${p}`;
}
