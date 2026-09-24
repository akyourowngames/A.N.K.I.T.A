import fs from "node:fs";
import { resolvePath, walkProjectFiles, relativeTo, displayPath, globToRegExp, isBinary } from "./_shared.mjs";

export const name = "search_files";
export const description =
  "Search file contents with a regular expression. Returns matching lines as path:line: text. " +
  "Use this to find where something is defined or used before editing.";

export const parameters = {
  type: "object",
  properties: {
    pattern: { type: "string", description: "JavaScript regular expression to search for." },
    path: { type: "string", description: "File or directory to search. Defaults to the working directory." },
    include: {
      type: "string",
      description: "Only search files matching this glob, e.g. \"*.mjs\" or \"src/**/*.ts\".",
    },
    exclude: {
      type: "string",
      description: "Skip files matching this glob, e.g. \"**/skip*\" or \"**/*.min.js\".",
    },
    ignore_case: { type: "boolean", description: "Case-insensitive search. Default false." },
    max_results: { type: "integer", description: "Maximum matches to return. Default 60, max 300." },
  },
  required: ["pattern"],
};

export const readOnly = true;
export const needsApproval = false;

function collectFiles(target, onIncomplete) {
  const stat = fs.statSync(target);
  if (stat.isFile()) return [target];
  return [...walkProjectFiles(target, { onIncomplete })].sort();
}

function matchesAny(res, rel, base) {
  return res.some((re) => re.test(rel) || re.test(base));
}

export function run(args, ctx) {
  const target = resolvePath(args.path, ctx);
  if (!fs.existsSync(target)) return `Error: no such path: ${target}`;

  const max = Math.min(Math.max(1, Number(args.max_results) || 60), 300);
  let re;
  try {
    re = new RegExp(args.pattern, args.ignore_case ? "gi" : "g");
  } catch (err) {
    return `Error: invalid regular expression: ${err.message}`;
  }

  const include = args.include ? [globToRegExp(args.include)] : [];
  const exclude = args.exclude ? [globToRegExp(args.exclude)] : [];
  const root = fs.statSync(target).isDirectory() ? target : resolvePath(".", ctx);

  const matches = [];
  let scanned = 0;
  let incomplete = false;
  let bytesRead = 0;
  const deadline = Date.now() + 3000;

  for (const file of collectFiles(target, () => { incomplete = true; })) {
    if (Date.now() > deadline || bytesRead >= 32_000_000) { incomplete = true; break; }
    const rel = relativeTo(root, file);
    const base = file.split(/[/\\]/).pop();
    if (include.length && !matchesAny(include, rel, base)) continue;
    if (exclude.length && matchesAny(exclude, rel, base)) continue;

    let buf;
    try {
      const size = fs.statSync(file).size;
      if (size > 2_000_000) continue;
      if (bytesRead + size > 32_000_000) { incomplete = true; break; }
      buf = fs.readFileSync(file);
    } catch {
      continue;
    }
    bytesRead += buf.length;
    if (isBinary(buf)) continue;
    scanned++;

    const lines = buf.toString("utf8").split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
      re.lastIndex = 0;
      if (!re.test(lines[i])) continue;
      const text = lines[i].length > 200 ? lines[i].slice(0, 200) + "\u2026" : lines[i];
      matches.push(`${displayPath(ctx.cwd, file)}:${i + 1}: ${text.trim()}`);
      if (matches.length >= max) {
        return `${matches.join("\n")}\n\n[stopped at ${max} matches - narrow the search]`;
      }
    }
  }

  const partial = incomplete ? ' [inspection incomplete: limit reached]' : '';
  if (!matches.length) return `No matches for /${args.pattern}/ in ${scanned} file(s).${partial}`;
  return `${matches.join("\n")}\n\n[${matches.length} match${matches.length === 1 ? "" : "es"} in ${scanned} file(s)]${partial}`;
}
