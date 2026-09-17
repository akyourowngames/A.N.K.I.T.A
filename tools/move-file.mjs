import fs from "node:fs";
import path from "node:path";
import { resolvePath } from "./_shared.mjs";

export const name = "move_file";
export const description = "Move or rename a file or directory. Refuses to overwrite an existing destination.";

export const parameters = {
  type: "object",
  properties: {
    source: { type: "string", description: "Existing path, absolute or relative to the working directory." },
    destination: { type: "string", description: "New path. Must not already exist." },
  },
  required: ["source", "destination"],
};

export function approval(args, ctx) {
  return `move  ${resolvePath(args.source, ctx)}\n  to  ${resolvePath(args.destination, ctx)}`;
}

export function run(args, ctx = {}) {
  if (!args.source || !args.destination) throw new Error("source and destination are required.");
  const src = resolvePath(args.source, ctx);
  const dst = resolvePath(args.destination, ctx);
  if (!fs.existsSync(src)) throw new Error(`no such file or directory: ${src}`);
  if (fs.existsSync(dst)) throw new Error(`destination already exists: ${dst} (delete it first or pick another name)`);
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.renameSync(src, dst);
  return `Moved ${src} to ${dst}`;
}
