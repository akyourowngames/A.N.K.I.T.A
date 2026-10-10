/**
 * Single source of truth for CLI command metadata (USAGE, /help, /commands,
 * autocomplete and usage hints all render from these tables).
 * Pure data: must stay import-free so any module can use it without cycles.
 */

/** Column where flag descriptions start in USAGE (label padded to this). */
export const USAGE_LABEL_WIDTH = 22;

/** Discoverability line printed under the startup banner. */
export const BANNER_HINT = "type /help · /commands for everything";

/** Offline entry points; shared by terminal help and the generated cheat sheet. */
export const LOCAL_COMMANDS = [
  { name: 'new skill', args: '[name] [--permissions domains] [--example input] [--directory path]', desc: 'create a documented skill with an offline fixture' },
  { name: 'commands', args: '[search]', desc: 'print a generated terminal and desktop cheat sheet' },
];

export const FLAGS = [
  { short: "-p", long: "--prompt", value: "<text>", desc: "send one message and exit (non-interactive)" },
  { short: "-m", long: "--model", value: "<id>", desc: "model to use" },
  { long: "--max-tokens", value: "<n>", desc: "cap generated tokens per reply" },
  { long: "--list-models", desc: "print available models and exit" },
  { long: "--config", desc: "print resolved configuration and exit" },
  { long: "--continue", value: "[name]", desc: "resume a saved session (default: autosave)" },
  { short: "-y", long: "--yes", desc: "auto-approve every tool call" },
  { long: "--no-tools", desc: "disable tool use" },
  { long: "--no-banner", desc: "hide the startup banner" },
  { long: "--plain", desc: "no colors or markdown boxes (best for pipes)" },
  { long: "--json", desc: "print one JSON result (requires -p)" },
  { long: "--api-base", value: "<url>", desc: "use an OpenAI-compatible endpoint instead of Copilot" },
  { long: "--api-key", value: "<key>", desc: "credentials for --api-base" },
  { long: "--speak", desc: "read replies aloud (Edge TTS)" },
  { long: "--voice", desc: "start hands-free voice mode (VAD + barge-in)" },
  { long: "--daemon", desc: "run in the background: schedules, watches, Telegram inbox" },
  { long: "--takeover", desc: "request the desktop scheduler to stop before owning routines" },
  { long: "--brief", desc: "print a briefing now and exit" },
  { short: "-h", long: "--help", desc: "show this" },
  { short: "-v", long: "--version", desc: "show version" },
];

export const MCP_ACTIONS = ["list", "add", "remove", "enable", "disable", "reload"];
/** Sub-actions that take a configured server id as their argument. */
export const MCP_ID_ACTIONS = ["remove", "enable", "disable", "reload"];
export const BROWSER_ACTIONS = ["list", "enable isolated", "enable local", "disable isolated", "disable local"];
export const COMPOSIO_ACTIONS = ["status", "list", "accounts", "search", "connect", "disconnect", "reload", "tiers", "allow", "always", "deny"];

export const SLASH_GROUPS = [
  {
    title: "General",
    items: [
      { name: "/help", desc: "this" },
      { name: "/commands", desc: "everything: all commands and subcommands grouped" },
      { name: "/config", desc: "show .env values and where they come from", desktopCommand: 'settings' },
      { name: "/reload", desc: "re-read .env without restarting" },
      { name: "/skills", desc: "list built-in skills", desktopCommand: 'plugins' },
      { name: "/usage", desc: "show token usage for this turn and session" },
      { name: "/clear", desc: "reset the conversation" },
      { name: "/exit", desc: "quit", aliases: ["/quit"] },
    ],
  },
  {
    title: "Models & tools",
    items: [
      { name: "/models", desc: "list available models", desktopCommand: 'settings' },
      { name: "/model", args: "<id>", desc: "switch model", desktopCommand: 'settings' },
      { name: "/tools", args: "on|off", desc: "enable/disable tool use" },
      { name: "/auto", args: "on|off", desc: "toggle auto-approving tool calls" },
      { name: "/cd", args: "<dir>", desc: "change the working directory tools use" },
    ],
  },
  {
    title: "Sessions",
    items: [
      { name: "/save", args: "[name]", desc: "save this conversation" },
      { name: "/load", args: "<name>", desc: "load a saved conversation" },
      { name: "/sessions", desc: "list saved conversations" },
      { name: "/paste", desc: "paste multiple lines (end with a single .)" },
    ],
  },
  {
    title: "Connectors",
    items: [
      { name: "/mcp", args: MCP_ACTIONS.join("|"), desc: "manage MCP servers", actions: MCP_ACTIONS, idActions: MCP_ID_ACTIONS },
      { name: "/browser", args: "list|enable|disable [isolated|local]", desc: "list, enable, or disable browser plugins", actions: BROWSER_ACTIONS },
      { name: "/composio", args: COMPOSIO_ACTIONS.join("|"), desc: "manage connected apps and approval tiers", actions: COMPOSIO_ACTIONS },
    ],
  },
  {
    title: "Voice",
    items: [
      { name: "/mic", desc: "dictate one message (auto-sends on pause)" },
      { name: "/voice", desc: "hands-free loop: VAD, barge-in, spoken replies" },
      { name: "/say", args: "<text>", desc: "speak text aloud (Edge TTS)" },
      { name: "/speak", args: "on|off", desc: "auto-speak every reply" },
      { name: "/voices", args: "[filter]", desc: "list Edge TTS voices" },
    ],
  },
  {
    title: "Automation",
    items: [
      { name: "/brief", desc: "briefing now: inbox, watch changes, what needs you" },
      { name: "/routines", desc: "scheduled prompts and their last result", desktopCommand: 'jobs' },
      { name: "/watches", desc: "pages being watched and their last reading" },
      { name: "/daemon", desc: "show daemon state (runs as: ankita --daemon)" },
      { name: "/project", args: "[name]", desc: "switch project (no name = show the active one)" },
      { name: "/projects", desc: "list the projects I know about" },
    ],
  },
  {
    title: "Background jobs",
    items: [
      { name: "/jobs", desc: "list running and completed commands" },
      { name: "/job", args: "<id> [offset]", desc: "read new output (offset 0 replays retained output)" },
      { name: "/input", args: "<id> <text>", desc: "send a line to a running command" },
      { name: "/eof", args: "<id>", desc: "close a job's stdin" },
      { name: "/stop", args: "<id>", desc: "stop a job and its child processes" },
      { name: "/wait", args: "<id> [ms]", desc: "wait briefly for a job" },
      { name: "/bg", args: "<command>", desc: "run a command in the background" },
    ],
  },
];

/** Composio tool slugs are uppercase with underscores (GMAIL_SEND_EMAIL); anything else is a service name. */
export const TOOL_SLUG_PATTERN = /^[A-Z0-9_]*[A-Z_][A-Z0-9_]*$/;

export function commandNames() {
  const names = [];
  for (const group of SLASH_GROUPS) {
    for (const item of group.items) names.push(item.name, ...(item.aliases || []));
  }
  return names;
}

/** Registry entry for a command name (with or without leading slash). */
export function itemFor(name) {
  const wanted = String(name).toLowerCase();
  for (const group of SLASH_GROUPS) {
    for (const item of group.items) {
      if (item.name === wanted || (item.aliases || []).includes(wanted)) return item;
    }
  }
  return null;
}

/** Shared nudge when no closer hint exists. */
export const FALLBACK_HINT = "try /help";

/** One-line hint listing the valid subcommands of a command. */
export function subcommandHint(name) {
  const item = itemFor(name);
  if (!item?.actions?.length) return null;
  return `try: ${item.actions.join(", ")}`;
}

/** Shared message for an unrecognized subcommand: unknown action "x" - try: a, b, c */
export function unknownActionMessage(command, sub) {
  const hint = subcommandHint(command);
  return `unknown action "${sub}"${hint ? ` - ${hint}` : ` - ${FALLBACK_HINT}`}`;
}

/** Closest registered command to a typo (for "did you mean" hints). */
export function closestCommand(input) {
  const wanted = String(input).toLowerCase();
  if (!wanted.startsWith("/")) return null;
  const names = commandNames();
  const prefixes = names.filter((n) => n.startsWith(wanted));
  if (prefixes.length) return prefixes.sort((a, b) => a.length - b.length)[0];
  let best = null;
  let bestDistance = Infinity;
  for (const name of names) {
    const d = editDistance(wanted, name);
    if (d < bestDistance) {
      bestDistance = d;
      best = name;
    }
  }
  const threshold = Math.max(2, Math.floor(wanted.length / 3));
  return bestDistance <= threshold ? best : null;
}

/** Damerau-Levenshtein (adjacent transpositions count as one edit). */
function editDistance(a, b) {
  const dp = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0));
  for (let i = 0; i <= a.length; i++) dp[i][0] = i;
  for (let j = 0; j <= b.length; j++) dp[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        dp[i][j] = Math.min(dp[i][j], dp[i - 2][j - 2] + 1);
      }
    }
  }
  return dp[a.length][b.length];
}
