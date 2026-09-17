import fs from "node:fs";
import path from "node:path";
import { resolvePath, readTextFile, writeTextFile } from "./_shared.mjs";
import { diffText, stats } from "./_diff.mjs";

export const name = "write_file";
export const description =
  "Create a file, or overwrite one completely. Parent directories are created as needed. " +
  "For small changes to an existing file, use edit_file or edit_lines instead.";

export const parameters = {
  type: "object",
  properties: {
    path: { type: "string", description: "File path, absolute or relative to the working directory." },
    content: { type: "string", description: "The full new contents of the file." },
  },
  required: ["path", "content"],
};

function plan(args, ctx) {
  const p = resolvePath(args.path, ctx);
  if (fs.existsSync(p)) {
    if (fs.statSync(p).isDirectory()) return { error: `${p} is a directory.` };
    const existing = readTextFile(p);
    return { p, existed: true, previous: existing.text, created: args.content ?? "" };
  }
  return { p, existed: false, previous: "", created: args.content ?? "", parent: path.dirname(p) };
}

export function approval(args, ctx, ui) {
  const info = plan(args, ctx);
  if (info.error) return `${resolvePath(args.path, ctx)}\n\n${ui.red(info.error)}`;

  if (!info.existed) {
    return `${ui.bold(info.p)}  ${ui.green("new file")}\n\n${ui.diff("", args.content ?? "")}`;
  }

  const diff = diffText(info.previous, info.created);
  if (!diff.changed) return `${ui.bold(info.p)}\n\n${ui.dim("identical to the current contents")}`;
  return `${ui.bold(info.p)}  ${ui.dim("overwrite  " + stats(diff))}\n\n${ui.diff(
    info.previous,
    info.created,
    { width: ctx.width }
  )}`;
}

export function run(args, ctx) {
  const info = plan(args, ctx);
  if (info.error) return `Error: ${info.error}`;

  if (info.parent) fs.mkdirSync(info.parent, { recursive: true });
  writeTextFile(info.p, info.created, "\n");

  const lines = (args.content ?? "").split("\n").length;
  if (!info.existed) return `Created ${info.p} (${lines} lines).`;

  const diff = diffText(info.previous, info.created);
  return `Overwrote ${info.p}\n${stats(diff)} \u00b7 now ${lines} lines`;
}
