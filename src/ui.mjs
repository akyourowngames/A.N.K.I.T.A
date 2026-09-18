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
    process.stdout.write(promptText);
    const line = await this.nextLine();
    return line === null ? null : line;
  }

  write(s) {
    process.stdout.write(s);
  }

  line(s = "") {
    process.stdout.write(s + "\n");
  }

  close() {
    this.rl.close();
  }
}

export function banner({ agentName, username, model, tools, autoApprove, cwd, envPath, count }) {
  const width = 58;
  const pad = (s, len = width) => s + " ".repeat(Math.max(0, len - visibleLen(s)));
  const visibleLen = (s) => String(s).replace(/\x1b\[[0-9;]*m/g, "").length;

  const rows = [
    `agent      ${agentName}`,
    `user       ${username}`,
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
  ${c.cyan("/brief")}             briefing now: inbox, watch changes, what needs you
  ${c.cyan("/routines")}          scheduled prompts and their last result
  ${c.cyan("/watches")}           pages being watched and their last reading
  ${c.cyan("/mic")}               dictate one message (Groq Whisper)
  ${c.cyan("/voice")}             hands-free voice loop (mic in, speech out)
  ${c.cyan("/say")} <text>        speak text aloud (Edge TTS)
  ${c.cyan("/speak")} on|off      auto-speak every reply
  ${c.cyan("/voices")} [filter]   list Edge TTS voices
  ${c.cyan("/clear")}             reset the conversation
  ${c.cyan("/exit")}              quit

${c.bold("keys")}
  ctrl-c              cancel the reply that is streaming, or quit when idle

${c.dim(`${agentName} runs shell commands and edits files on this machine. Every call asks first.`)}`;
}
