import { execute, commandText, integer } from "./_process.mjs";

export const name = "git";
export const description = "Run a structured Git action in the working directory. Read-only status/diff/log/show/blame/branch list/stash list run automatically. Mutations show the exact command for approval. Paths are literal; arbitrary Git arguments are not accepted.";
export const parameters = {
  type: "object",
  properties: {
    action: { type: "string", enum: ["status", "diff", "log", "show", "blame", "branch", "checkout", "stage", "unstage", "commit", "stash", "restore"] },
    operation: { type: "string", description: "branch: list (default), create, delete. stash: list (default), push, pop, apply, drop." },
    paths: { type: "array", items: { type: "string" }, description: "Literal paths. Required for stage, unstage, restore, and blame (one path)." },
    ref: { type: "string", description: "Revision for diff/log/show/blame; checkout target; stash entry for pop/apply/drop. Cannot start with '-'." },
    branch: { type: "string", description: "Branch name for branch create/delete or checkout with create:true." },
    create: { type: "boolean", description: "checkout: create branch, optionally starting at ref." },
    message: { type: "string", description: "Required commit message; optional stash push message." },
    staged: { type: "boolean", description: "diff: compare the index to HEAD." },
    include_untracked: { type: "boolean", description: "stash push: include untracked files." },
    limit: { type: "integer", description: "log: maximum commits, default 20, max 200." },
    timeout_ms: { type: "integer", description: "Timeout, default 30000, max 600000." },
    max_output_bytes: { type: "integer", description: "Output byte limit, default 65536, max 1048576." },
  },
  required: ["action"],
  additionalProperties: false,
};

function ref(value, label = "ref") {
  if (typeof value !== "string" || !value.trim() || value.startsWith("-") || /[\0\r\n]/.test(value)) throw new Error(`Invalid ${label}: must be nonempty and cannot start with '-'.`);
  return value;
}
function pathsOf(args, required = false) {
  const paths = args.paths ?? [];
  if (!Array.isArray(paths) || paths.some((p) => typeof p !== "string" || !p || p.includes("\0"))) throw new Error("paths must be an array of nonempty literal paths.");
  if (required && !paths.length) throw new Error("paths are required for this action.");
  return paths;
}

export function readOnly(args = {}) {
  return ["status", "diff", "log", "show", "blame"].includes(args.action) ||
    (["branch", "stash"].includes(args.action) && (args.operation ?? "list") === "list");
}
export function needsApproval(args) { return !readOnly(args); }

function argvFor(args) {
  const argv = ["--no-pager", "--literal-pathspecs", "-c", "color.ui=false"];
  const paths = pathsOf(args, ["stage", "unstage", "restore", "blame"].includes(args.action));
  const revision = args.ref === undefined ? undefined : ref(args.ref);
  if (args.operation !== undefined && !["branch", "stash"].includes(args.action)) throw new Error("operation is only supported for branch and stash.");
  switch (args.action) {
    case "status": argv.push("status", "--short", "--branch"); break;
    case "diff": argv.push("diff", "--no-ext-diff", "--no-textconv", ...(args.staged ? ["--cached"] : []), ...(revision ? [revision] : [])); break;
    case "log": argv.push("log", "--oneline", `-${integer(args.limit, 20, 1, 200)}`, ...(revision ? [revision] : [])); break;
    case "show": argv.push("show", "--no-ext-diff", "--no-textconv", revision || "HEAD"); break;
    case "blame":
      if (paths.length !== 1) throw new Error("blame requires exactly one path.");
      argv.push("blame", ...(revision ? [revision] : [])); break;
    case "branch": {
      const op = args.operation ?? "list";
      if (op === "list") argv.push("branch", "--list");
      else if (op === "create") argv.push("branch", ref(args.branch, "branch"), ...(revision ? [revision] : []));
      else if (op === "delete") argv.push("branch", "-d", ref(args.branch, "branch"));
      else throw new Error("Unsupported branch operation.");
      break;
    }
    case "checkout": argv.push("checkout", ...(args.create ? ["-b", ref(args.branch, "branch"), ...(revision ? [revision] : [])] : [ref(args.ref)])); break;
    case "stage": argv.push("add"); break;
    case "unstage": argv.push("reset"); break;
    case "restore": argv.push("restore", "--worktree", ...(revision ? [`--source=${revision}`] : [])); break;
    case "commit":
      if (typeof args.message !== "string" || !args.message.trim() || args.message.includes("\0")) throw new Error("A nonempty commit message is required.");
      argv.push("commit", "-m", args.message); break;
    case "stash": {
      const op = args.operation ?? "list";
      if (!["list", "push", "pop", "apply", "drop"].includes(op)) throw new Error("Unsupported stash operation.");
      argv.push("stash", op);
      if (op === "push") {
        if (args.include_untracked) argv.push("--include-untracked");
        if (args.message !== undefined) {
          if (typeof args.message !== "string" || args.message.includes("\0")) throw new Error("Invalid stash message.");
          argv.push("-m", args.message);
        }
      } else if (revision && op !== "list") argv.push(revision);
      if (paths.length && op !== "push") throw new Error("paths are supported only for stash push.");
      break;
    }
    default: throw new Error("Unsupported Git action.");
  }
  if (paths.length) {
    if (["branch", "checkout", "commit"].includes(args.action)) throw new Error(`paths are unsupported for ${args.action}; use stage or restore explicitly.`);
    argv.push("--", ...paths);
  } else if (["diff", "log", "show", "checkout"].includes(args.action)) argv.push("--");
  return argv;
}

export function approval(args, ctx = {}) {
  return `Working directory: ${ctx.cwd || process.cwd()}\n$ ${commandText("git", argvFor(args))}`;
}

export async function run(args, ctx = {}) {
  const argv = argvFor(args);
  const result = await execute("git", argv, {
    cwd: ctx.cwd || process.cwd(), signal: ctx.signal,
    timeout_ms: integer(args.timeout_ms, 30000, 1, 600000),
    max_output_bytes: integer(args.max_output_bytes, 65536, 1024, 1048576),
    env: { ...process.env, GIT_TERMINAL_PROMPT: "0", GIT_PAGER: "cat", GIT_OPTIONAL_LOCKS: readOnly(args) ? "0" : "1" },
  });
  return `$ ${commandText("git", argv)}\nexit code: ${result.code}\n${result.output || "(no output)"}`;
}
