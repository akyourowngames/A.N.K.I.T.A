import { spawn, spawnSync } from "node:child_process";
import { BoundedOutput } from "./_shared.mjs";

export const name = "run_command";
export const description =
  "Run a shell command on the user's machine and return its combined stdout and stderr, " +
  "bounded so huge logs cannot flood the conversation. " +
  (process.platform === "win32"
    ? "On Windows this runs in PowerShell (pwsh when installed, else powershell.exe) via -Command, so use PowerShell syntax."
    : "Runs via /bin/sh -c.") +
  " Pass background:true for long-running processes (servers, watchers); read them with job_status and stop them with job_stop.";

export const parameters = {
  type: "object",
  properties: {
    command: { type: "string", description: "The command line to execute." },
    timeout_ms: {
      type: "integer",
      description: "Kill a foreground command after this many milliseconds (default 60000, max 600000).",
    },
    stdin: {
      type: "string",
      description: "Text piped to the command's standard input.",
    },
    env: {
      type: "object",
      description: "Extra environment variables merged over the process environment.",
      additionalProperties: { type: "string" },
    },
    max_output_bytes: {
      type: "integer",
      description: "Keep at most this many output bytes (head+tail). Default 65536.",
    },
    background: {
      type: "boolean",
      description: "Start the command as a background job and return immediately with a job id.",
    },
  },
  required: ["command"],
};

let shellExe = null;
function shell() {
  if (shellExe) return shellExe;
  if (process.platform === "win32") {
    try {
      const found = spawnSync("where", ["pwsh"], { windowsHide: true, stdio: "ignore" });
      shellExe = found.status === 0 ? "pwsh" : "powershell.exe";
    } catch {
      shellExe = "powershell.exe";
    }
  } else {
    shellExe = "/bin/sh";
  }
  return shellExe;
}

function argvFor(command) {
  return process.platform === "win32"
    ? ["-NoProfile", "-NonInteractive", "-Command", command]
    : ["-c", command];
}

/** Kill a child and everything it spawned (Windows grandchildren need /T). */
export function killTree(child) {
  if (!child || child.exitCode !== null || child.signalCode !== null) return;
  if (process.platform === "win32") {
    try {
      spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true });
    } catch {}
  }
  try {
    child.kill("SIGKILL");
  } catch {}
}

/** Resolves when the job's process exits (or the wait times out). */
export function waitForExit(job, timeoutMs = 5000) {
  if (!job || job.done) return Promise.resolve(true);
  return new Promise((resolve) => {
    const timer = setTimeout(() => {
      try {
        job.child?.off?.("close", onClose);
      } catch {}
      resolve(job.done);
    }, Math.max(0, timeoutMs));
    const onClose = () => {
      clearTimeout(timer);
      resolve(true);
    };
    try {
      job.child?.once?.("close", onClose);
    } catch {
      clearTimeout(timer);
      resolve(job.done);
    }
  });
}

export function jobSummary(job) {
  const secs = ((Date.now() - job.startedAt) / 1000).toFixed(1);
  const state = job.done ? `done (exit ${job.code ?? "?"})` : job.stopped ? "stopped" : "running";
  return `job ${job.id}: ${state} after ${secs}s\n$ ${job.command}`;
}

function jobsOf(ctx) {
  const state = ctx.state || (ctx.state = {});
  return state.jobs || (state.jobs = new Map());
}

function nextJobId(ctx) {
  const state = ctx.state || (ctx.state = {});
  state._jobSeq = (state._jobSeq || 0) + 1;
  return String(state._jobSeq);
}

export function approval(args) {
  return `$ ${args.command}${args.background ? "  (background job)" : ""}`;
}

function clampInt(value, fallback, min, max) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, Math.floor(n)));
}

function feedStdin(child, stdin) {
  if (stdin === undefined || stdin === null || !child.stdin) return;
  try {
    child.stdin.on("error", () => {});
    child.stdin.write(String(stdin));
    child.stdin.end();
  } catch {}
}

function startBackground({ exe, argv, env, cwd, maxBytes, ctx, command }) {
  const jobs = jobsOf(ctx);
  const id = nextJobId(ctx);
  let child;
  try {
    child = spawn(exe, argv, {
      cwd,
      env,
      windowsHide: true,
      detached: process.platform !== "win32",
    });
  } catch (err) {
    return `failed to start background job: ${err.message}`;
  }
  const job = {
    id,
    command,
    child,
    out: new BoundedOutput(maxBytes),
    startedAt: Date.now(),
    done: false,
    stopped: false,
    code: null,
  };
  jobs.set(id, job);
  child.stdout?.on("data", (d) => job.out.append(d));
  child.stderr?.on("data", (d) => job.out.append(d));
  feedStdin(child, undefined);
  child.on("error", () => {
    job.done = true;
  });
  child.on("close", (code) => {
    job.done = true;
    job.code = code;
  });
  if (process.platform !== "win32") child.unref?.();
  return `started background job ${id}\n$ ${command}\n(use job_status to read its output, job_stop to end it)`;
}

export function run(args, ctx = {}) {
  const command = args.command;
  if (typeof command !== "string" || !command.trim()) {
    return "Error: command must be a non-empty string.";
  }
  const exe = shell();
  const argv = argvFor(command);
  const cwd = ctx.cwd || process.cwd();
  const env = { ...process.env };
  if (args.env && typeof args.env === "object") {
    for (const [k, v] of Object.entries(args.env)) env[k] = String(v);
  }
  const maxBytes = clampInt(args.max_output_bytes, 65536, 1024, 4 * 1024 * 1024);

  if (args.background) return startBackground({ exe, argv, env, cwd, maxBytes, ctx, command });

  const timeoutMs = clampInt(args.timeout_ms, 60000, 1000, 600000);

  return new Promise((resolve) => {
    let child;
    try {
      child = spawn(exe, argv, { cwd, env, windowsHide: true });
    } catch (err) {
      return resolve(`failed to spawn: ${err.message}`);
    }

    const out = new BoundedOutput(maxBytes);
    let settled = false;
    const finish = (text) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      ctx.signal?.removeEventListener("abort", onAbort);
      resolve(text);
    };

    const timer = setTimeout(() => {
      killTree(child);
      finish(`exit code: -1\n${out.toString() || "(no output)"}\n[killed after ${timeoutMs}ms]`);
    }, timeoutMs);

    const onAbort = () => {
      killTree(child);
      finish(`Command cancelled by user.\n${out.toString()}`);
    };
    if (ctx.signal?.aborted) return onAbort();
    ctx.signal?.addEventListener("abort", onAbort, { once: true });

    child.stdout.on("data", (d) => out.append(d));
    child.stderr.on("data", (d) => out.append(d));
    feedStdin(child, args.stdin);

    child.on("error", (err) => {
      finish(`failed to run: ${err.message}`);
    });

    child.on("close", (code) => {
      const body = out.toString() || "(no output)";
      finish(`exit code: ${code ?? 0}\n${body}`);
    });
  });
}
