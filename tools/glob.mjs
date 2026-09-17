import fs from "node:fs";
import path from "node:path";
import { resolvePath, walkFiles, relativeTo, globToRegExp } from "./_shared.mjs";

export const name = "glob";
export const description =
  "Find files by glob pattern, e.g. \"*.mjs\", \"src/**/*.ts\", \"**/*test*\". " +
  "Use it to locate files when you do not know where they live.";

export const parameters = {
  type: "object",
  properties: {
    pattern: { type: "string", description: "Glob matched against the path relative to the search root." },
    path: { type: "string", description: "Directory to search. Defaults to the working directory." },
    exclude: {
      type: "string",
      description: "Skip paths matching this glob, e.g. \"**/skip*\".",
    },
    max_results: { type: "integer", description: "Maximum paths to return. Default 100, max 500." },
  },
  required: ["pattern"],
};

export const readOnly = true;
export const needsApproval = false;

export function run(args, ctx) {
  const root = resolvePath(args.path, ctx);
  if (!fs.existsSync(root)) return `Error: no such directory: ${root}`;
  if (!fs.statSync(root).isDirectory()) return `Error: ${root} is a file (use read_file).`;

  const max = Math.min(Math.max(1, Number(args.max_results) || 100), 500);
  const re = globToRegExp(args.pattern);
  const exclude = args.exclude ? globToRegExp(args.exclude) : null;
  const hits = [];

  for (const file of walkFiles(root)) {
    const rel = relativeTo(root, file);
    const base = path.basename(file);
    if (!re.test(rel) && !re.test(base)) continue;
    if (exclude && (exclude.test(rel) || exclude.test(base))) continue;
    hits.push(rel);
    if (hits.length >= max) {
      return `${hits.sort().join("\n")}\n\n[stopped at ${max} - narrow the pattern]`;
    }
  }

  if (!hits.length) return `No files matching "${args.pattern}" under ${root}.`;
  return `${hits.sort().join("\n")}\n\n[${hits.length} file${hits.length === 1 ? "" : "s"}]`;
}
