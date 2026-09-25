import fs from "node:fs";
import path from "node:path";
import { resolvePath, displayPath, SKIP_DIRS as SKIP } from "../shared/_shared.mjs";

export const name = "list_dir";
export const description = "List the files and subdirectories of a directory, with sizes.";

export const parameters = {
  type: "object",
  properties: {
    path: {
      type: "string",
      description: "Directory path, absolute or relative to the working directory. Defaults to the working directory.",
    },
    recursive: {
      type: "boolean",
      description: "Walk the whole tree and return paths relative to the directory. Default false.",
    },
    max_results: {
      type: "integer",
      description: "Maximum entries to return. Default 500.",
    },
  },
};

export const readOnly = true;
export const needsApproval = false;

export function run(args, ctx) {
  const p = resolvePath(args.path, ctx);
  if (!fs.existsSync(p)) return `Error: no such directory: ${p}`;
  if (!fs.statSync(p).isDirectory()) return `Error: ${p} is a file (use read_file).`;

  let entries;
  try {
    entries = fs.readdirSync(p, { withFileTypes: true });
  } catch (err) {
    return `Error: ${err.message}`;
  }
  if (!entries.length) return `${p}\n(empty directory)`;

  const max = Math.min(Math.max(1, Number(args.max_results) || 500), 5000);

  if (args.recursive) {
    const hits = [];
    const stack = [[p, 0]];
    const seen = new Set();
    const deadline = Date.now() + 3000;
    let inspected = 0;
    let incomplete = false;
    while (stack.length && hits.length < max) {
      if (Date.now() > deadline || inspected >= 30000) { incomplete = true; break; }
      const [dir, depth] = stack.pop();
      let dirEntries;
      try {
        dirEntries = fs.readdirSync(dir, { withFileTypes: true });
      } catch {
        continue;
      }
      for (const entry of dirEntries) {
        inspected++;
        if (Date.now() > deadline || inspected >= 30000) { incomplete = true; break; }
        if (hits.length >= max) break;
        const full = path.join(dir, entry.name);
        if (seen.has(full)) continue;
        seen.add(full);
        if (entry.isDirectory()) {
          hits.push(displayPath(ctx.cwd, full) + "/");
          if (!SKIP.has(entry.name)) {
            if (depth < 20) stack.push([full, depth + 1]);
            else incomplete = true;
          }
        } else if (entry.isFile()) {
          hits.push(displayPath(ctx.cwd, full));
        }
      }
    }
    hits.sort();
    const more = hits.length >= max ? `\n... reached ${max} entries` : incomplete ? '\n... inspection incomplete: time or entry limit reached' : "";
    return `${p}\n${hits.join("\n")}${more}`;
  }

  const lines = entries
    .sort((a, b) => Number(b.isDirectory()) - Number(a.isDirectory()) || a.name.localeCompare(b.name))
    .slice(0, max)
    .map((e) => {
      if (e.isDirectory()) return `${e.name}/`;
      try {
        return `${e.name}  ${fs.statSync(path.join(p, e.name)).size}b`;
      } catch {
        return e.name;
      }
    });

  const more = entries.length > max ? `\n... ${entries.length - max} more entries` : "";
  return `${p}\n${lines.join("\n")}${more}`;
}
