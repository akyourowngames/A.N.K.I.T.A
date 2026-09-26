import readline from "node:readline";
import fs from "node:fs";
import path from "node:path";

export let colorEnabled =
  process.stdout.isTTY && !process.env.NO_COLOR && process.env.TERM !== "dumb";

/** Force colors on/off after startup (e.g. --plain). Live for all importers. */
export function setColorEnabled(value) {
  colorEnabled = Boolean(value);
}

const wrap = (code) => (s) => (colorEnabled ? `\x1b[${code}m${s}\x1b[0m` : String(s));

export const c = {
  dim: wrap("90"),
  red: wrap("31"),
  green: wrap("32"),
  yellow: wrap("33"),
  blue: wrap("34"),
  magenta: wrap("35"),
  cyan: wrap("36"),
  bold: wrap("1"),
};

export function clip(text, max = 24000, label = "output") {
  const s = String(text ?? "");
  if (s.length <= max) return s;
  return s.slice(0, max) + `\n\n[${label} truncated: ${s.length - max} more characters]`;
}

export function preview(text, maxLines = 20) {
  const lines = String(text ?? "").split(/\r?\n/);
  if (lines.length <= maxLines) return text;
  return lines.slice(0, maxLines).join("\n") + `\n... (${lines.length - maxLines} more lines)`;
}

export function short(value, n = 160) {
  const s = typeof value === "string" ? value : JSON.stringify(value ?? "");
  return s.length > n ? s.slice(0, n) + "..." : s;
}

const FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

export function spinner(text) {
  if (!process.stdout.isTTY) return { stop() {} };
  let i = 0;
  const id = setInterval(() => {
    process.stdout.write(`\r${c.dim(FRAMES[i++ % FRAMES.length] + " " + text)}\x1b[K`);
  }, 90);
  return {
    stop() {
      clearInterval(id);
      process.stdout.write("\r\x1b[K");
    },
  };
}

export class Terminal {
  constructor({ input = process.stdin, output = process.stdout, completer } = {}) {
    this.output = output;
    this.promptText = '';
    this.queue = [];
    this.waiter = null;
    this.closed = false;
    this.rl = readline.createInterface({
      input,
      output,
      historySize: 500,
      ...(completer ? { completer } : {}),
    });
    this.rl.on("line", (line) => {
      if (this.interceptLine?.(line)) return;
      if (this.waiter) {
        const w = this.waiter;
        this.waiter = null;
        w(line);
      } else {
        this.queue.push(line);
      }
    });
    this.rl.on("close", () => {
      this.closed = true;
      if (this.waiter) {
        const w = this.waiter;
        this.waiter = null;
        w(null);
      }
    });
  }

  loadHistory(file) {
    try {
      const lines = fs.readFileSync(file, "utf8").split(/\r?\n/).filter(Boolean);
      this.rl.history = [...new Set(lines.reverse())].slice(0, 500);
    } catch {}
  }

  saveHistory(file) {
    try {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      const history = [...new Set((this.rl.history || []).filter(Boolean))].slice(0, 500);
      fs.writeFileSync(file, history.reverse().join("\n") + (history.length ? "\n" : ""));
    } catch {}
  }

  nextLine() {
    if (this.queue.length) return Promise.resolve(this.queue.shift());
    if (this.closed) return Promise.resolve(null);
    return new Promise((resolve) => (this.waiter = resolve));
  }

  /** Resolve a pending ask() with null (used to cancel a wait, e.g. recording). */
  cancelPending() {
    if (this.waiter) {
      const w = this.waiter;
      this.waiter = null;
      w(null);
    }
  }

  async ask(promptText) {
    this.promptText = promptText;
    this.rl.setPrompt(promptText);
    this.output.write(promptText);
    const line = await this.nextLine();
    return line === null ? null : line;
  }

  write(s) {
    this.output.write(s);
  }

  line(s = "") {
    this.output.write(s + "\n");
  }

  /** Print asynchronous job events without destroying the line being typed. */
  notify(s) {
    if (this.waiter && this.output.isTTY) {
      readline.clearLine(this.output, 0);
      readline.cursorTo(this.output, 0);
      this.line(s);
      this.rl.prompt(true);
    } else this.line(s);
  }

  close() {
    this.rl.close();
  }
}

export function banner({ agentName, username, model, tools, autoApprove, cwd, envPath, count, project = null }) {
  const width = 58;
  const pad = (s, len = width) => s + " ".repeat(Math.max(0, len - visibleLen(s)));
  const visibleLen = (s) => String(s).replace(/\x1b\[[0-9;]*m/g, "").length;

  const rows = [
    `agent      ${agentName}`,
    `user       ${username}`,
    project ? `project    ${project}` : null,
    `model      ${model}`,
    `tools      ${tools ? "on" : "off"}${autoApprove ? "  (auto-approve)" : ""}`,
    `cwd        ${cwd}`,
    count ? `models     ${count} available` : null,
  ].filter(Boolean);

  const lines = rows.map((r) => c.dim("  ") + r);

  process.stdout.write("\n");
  process.stdout.write(c.cyan("  ╭" + "─".repeat(width) + "╮") + "\n");
  process.stdout.write(
    c.cyan("  │") +
      pad(" " + c.bold(agentName) + c.dim("  ·  github copilot cli chat")) +
      c.cyan("│") +
      "\n"
  );
  process.stdout.write(c.cyan("  ├" + "─".repeat(width) + "┤") + "\n");
  for (const l of lines) process.stdout.write(c.cyan("  │") + pad(" " + l) + c.cyan("│") + "\n");
  process.stdout.write(c.cyan("  ╰" + "─".repeat(width) + "╯") + "\n");
  if (envPath) process.stdout.write(c.dim(`  config: ${envPath}\n`));
  process.stdout.write("\n");
}

export function helpText({ agentName }) {
  return `${c.bold("commands")}
  ${c.cyan("/help")}              this
  ${c.cyan("/config")}            show .env values and where they come from
  ${c.cyan("/reload")}            re-read .env without restarting
  ${c.cyan("/skills")}            list built-in skills
  ${c.cyan("/models")}            list available models
  ${c.cyan("/model")} <id>        switch model
  ${c.cyan("/tools")} on|off      enable/disable tool use
  ${c.cyan("/auto")} on|off       toggle auto-approving tool calls
  ${c.cyan("/cd")} <dir>          change the working directory tools use
  ${c.cyan("/save")} [name]       save this conversation
  ${c.cyan("/load")} <name>       load a saved conversation
  ${c.cyan("/sessions")}          list saved conversations
  ${c.cyan("/paste")}             paste multiple lines (end with a single .)
  ${c.cyan("/usage")}             show token usage for this turn and session
  ${c.cyan("/jobs")}              list running and completed commands
  ${c.cyan("/job")} <id> [offset]  read new output (offset 0 replays retained output)
  ${c.cyan("/input")} <id> <text>  send a line to a running command
  ${c.cyan("/eof")} <id>           close a job's stdin
  ${c.cyan("/stop")} <id>          stop a job and its child processes
  ${c.cyan("/wait")} <id> [ms]     wait briefly for a job
  ${c.cyan("/bg")} <command>       run a command in the background
  ${c.cyan("/project")} [name]    switch project (no name = show the active one)
  ${c.cyan("/projects")}          list the projects I know about
  ${c.cyan("/brief")}             briefing now: inbox, watch changes, what needs you
  ${c.cyan("/routines")}          scheduled prompts and their last result
  ${c.cyan("/watches")}           pages being watched and their last reading
  ${c.cyan("/browser")}           list, enable, or disable browser plugins
  ${c.cyan("/mic")}               dictate one message (auto-sends on pause)
  ${c.cyan("/voice")}             hands-free loop: VAD, barge-in, spoken replies
  ${c.cyan("/say")} <text>        speak text aloud (Edge TTS)
  ${c.cyan("/speak")} on|off      auto-speak every reply
  ${c.cyan("/voices")} [filter]   list Edge TTS voices
  ${c.cyan("/clear")}             reset the conversation
  ${c.cyan("/exit")}              quit

${c.bold("keys")}
  ctrl-c              cancel the reply that is streaming, or quit when idle

${c.dim(`${agentName} runs shell commands and edits files on this machine. Every call asks first.`)}`;
}
