import fs from "node:fs";
import path from "node:path";
import { NotificationDelivery } from './notify.mjs';
import { MemoryConsolidator } from './consolidate.mjs';
import { extractMemory } from './memory-extract.mjs';
import { recordTurn, saveSession } from './sessions.mjs';
import {
  loadConfig,
  ensureDirs,
  AUTH_FILE,
  HISTORY_FILE,
  SESSIONS_DIR,
  AUTOSAVE_NAME,
  STATE_FILE,
  PROJECTS_FILE,
  MCP_FILE,
  DAEMON_LOG,
  NOTIFY_QUEUE_FILE,
} from "./config.mjs";
import { ProjectStore, describeProject, describeProjectFull } from "./projects.mjs";
import { McpManager } from "./mcp-manager.mjs";
import { McpStore, describeServer, enableMessage, disableMessage } from "./mcp-store.mjs";
import { RoutineStore, describeRoutine, describeWatch } from "./routines.mjs";
import { TelegramBot, parseChatIds } from "./telegram.mjs";
import { Daemon } from "./daemon.mjs";
import { describeCron } from "./cron.mjs";
import { readAuth, writeAuth, deviceLogin, CopilotClient } from "./auth.mjs";
import { pickModel, CompatibleClient, resolveProvider } from "./provider.mjs";
import { sanitizeMessages } from "./history.mjs";
import { Agent } from "./agent.mjs";
import { Terminal, banner, helpText, c, spinner, preview, short, clip, setColorEnabled } from "./ui.mjs";
import { LiveRenderer } from "./markdown.mjs";
import { names as toolNames, cleanupJobs } from "../tools/index.mjs";
import {
  voiceRuntimeCheck,
  audioDeps,
  tmpVoiceFile,
  detectMic,
  startRecording,
  transcribeGroq,
  synthesizeEdge,
  synthesizeGroq,
  listEdgeVoices,
  GROQ_VOICES,
  resolveTtsProvider,
  resolveTtsVoice,
  playMp3,
  stopPlayback,
  stripForSpeech,
} from "./voice.mjs";

function packageVersion() {
  try {
    const pkg = JSON.parse(fs.readFileSync(new URL("../package.json", import.meta.url), "utf8"));
    return pkg.version || "dev";
  } catch {
    return "dev";
  }
}

const VERSION = packageVersion();

const USAGE = `${c.bold("ankita")} ${c.dim("·")} GitHub Copilot chat in your terminal

${c.bold("usage")}
  ankita [options] [message...]

${c.bold("options")}
  -p, --prompt <text>   send one message and exit (non-interactive)
  -m, --model <id>      model to use
      --max-tokens <n>  cap generated tokens per reply
      --list-models     print available models and exit
      --config          print resolved configuration and exit
      --continue [name] resume a saved session (default: autosave)
  -y, --yes             auto-approve every tool call
      --no-tools        disable tool use
      --no-banner       hide the startup banner
      --plain           no colors or markdown boxes (best for pipes)
      --json            print one JSON result (requires -p)
      --api-base <url>  use an OpenAI-compatible endpoint instead of Copilot
      --api-key <key>   credentials for --api-base
      --speak           read replies aloud (Edge TTS)
      --voice           start in voice mode (mic in, speech out)
      --daemon          run in the background: schedules, watches, Telegram inbox
      --brief           print a briefing now and exit
  -h, --help            show this
  -v, --version         show version

${c.bold("config")}
  Read from ${c.cyan(".env")} in the working directory, falling back to
  ${c.cyan("~/.copilot-chat-cli/config.env")} (USERNAME, AGENT_NAME, MODEL, ...).
  Edit it and run ${c.cyan("/reload")} inside the chat to apply changes live.

${c.bold("examples")}
  ankita
  ankita -p "summarise what this repo does"
  ankita --model claude-sonnet-5
  ankita -p "add a LICENSE file" -y
`;

function parseArgs(argv) {
  const opts = {
    prompt: null,
    model: null,
    maxTokens: null,
    listModels: false,
    showConfig: false,
    continueName: null,
    yes: false,
    tools: null,
    banner: true,
    plain: false,
    json: false,
    apiBase: null,
    apiKey: null,
    speak: false,
    voiceLoop: false,
    daemon: false,
    brief: false,
    help: false,
    version: false,
  };
  const rest = [];

  const takeValue = (flag, i) => {
    const v = argv[i + 1];
    if (v === undefined || v.startsWith("-")) {
      console.error(`${flag} needs a value (try --help)`);
      process.exit(2);
    }
    return v;
  };

  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case "-h":
      case "--help":
        opts.help = true;
        break;
      case "-v":
      case "--version":
        opts.version = true;
        break;
      case "-p":
      case "--prompt":
        opts.prompt = takeValue(a, i++);
        break;
      case "-m":
      case "--model":
        opts.model = takeValue(a, i++);
        break;
      case "--max-tokens": {
        const n = Number(takeValue(a, i++));
        if (!Number.isInteger(n) || n <= 0) {
          console.error("--max-tokens needs a positive integer");
          process.exit(2);
        }
        opts.maxTokens = n;
        break;
      }
      case "--list-models":
        opts.listModels = true;
        break;
      case "--config":
        opts.showConfig = true;
        break;
      case "--continue": {
        const next = argv[i + 1];
        opts.continueName = next !== undefined && !next.startsWith("-") ? argv[++i] : AUTOSAVE_NAME;
        break;
      }
      case "-y":
      case "--yes":
        opts.yes = true;
        break;
      case "--no-tools":
        opts.tools = false;
        break;
      case "--no-banner":
        opts.banner = false;
        break;
      case "--plain":
        opts.plain = true;
        break;
      case "--json":
        opts.json = true;
        break;
      case "--api-base":
        opts.apiBase = takeValue(a, i++);
        break;
      case "--api-key":
        opts.apiKey = takeValue(a, i++);
        break;
      case "--speak":
        opts.speak = true;
        break;
      case "--voice":
        opts.voiceLoop = true;
        break;
      case "--daemon":
        opts.daemon = true;
        break;
      case "--brief":
        opts.brief = true;
        break;
      default:
        if (a.startsWith("-")) {
          console.error(`unknown option: ${a} (try --help)`);
          process.exit(2);
        }
        rest.push(a);
    }
  }

  if (!opts.prompt && rest.length) opts.prompt = rest.join(" ");
  return opts;
}

function resolveGithubToken() {
  const auth = readAuth();
  const token = process.env.GITHUB_TOKEN || auth.github_token;
  if (token) return token;
  return null;
}

function sessionPath(name) {
  const safe = String(name).replace(/[^a-z0-9._-]/gi, "_").slice(0, 60) || "session";
  return path.join(SESSIONS_DIR, `${safe}.json`);
}

const fmtTokens = (n) => (n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n || 0));
const fmtCost = (u) => (u.estimated_cost > 0 ? `  ($${u.estimated_cost.toFixed(4)})` : "");

function usageLine(label, u) {
  return `  ${label.padEnd(9)} ${fmtTokens(u.prompt_tokens)} in / ${fmtTokens(u.completion_tokens)} out${fmtCost(u)}`;
}

function completePath(prefix) {
  const frag = prefix || "";
  const dirPart = frag.endsWith("/") || frag.endsWith("\\") ? frag : path.dirname(frag);
  const base = frag.endsWith("/") || frag.endsWith("\\") || frag === "" ? "" : path.basename(frag);
  const dirAbs = path.resolve(process.cwd(), dirPart === "" || dirPart === "." ? "." : dirPart);
  let entries;
  try {
    entries = fs.readdirSync(dirAbs, { withFileTypes: true });
  } catch {
    return [[], prefix];
  }
  const head = frag.slice(0, frag.length - base.length);
  const hits = entries
    .filter((e) => e.name.startsWith(base))
    .map((e) => head + e.name + (e.isDirectory() ? "/" : ""));
  return [hits, prefix];
}

const COMMANDS = [
  "/help", "/config", "/reload", "/models", "/model", "/tools", "/auto", "/cd",
  "/save", "/load", "/sessions", "/paste", "/usage", "/mic", "/voice", "/say",
  "/speak", "/voices", "/brief", "/routines", "/watches", "/daemon",
  "/project", "/projects", "/mcp", "/clear", "/exit", "/quit",
];

const MCP_ACTIONS = ["list", "add", "remove", "enable", "disable", "reload"];

function makeCompleter(models) {
  return (line) => {
    try {
      if (line.startsWith("/")) {
        const space = line.indexOf(" ");
        if (space === -1) {
          const hits = COMMANDS.filter((cmd) => cmd.startsWith(line));
          return [hits.length ? hits : COMMANDS, line];
        }
        const cmd = line.slice(0, space);
        const arg = line.slice(space + 1);
        if (cmd === "/model") {
          const hits = models.map((m) => `${cmd} ${m.id}`).filter((s) => s.startsWith(line));
          return [hits, line];
        }
        if (cmd === "/project") {
          const names = new ProjectStore(PROJECTS_FILE).load().projects.map((p) => p.id);
          const hits = names.map((n) => `${cmd} ${n}`).filter((s) => s.startsWith(line));
          return [hits, line];
        }
        if (cmd === "/mcp") {
          if (!arg.includes(" ")) {
            const hits = MCP_ACTIONS.map((a) => `${cmd} ${a}`).filter((s) => s.startsWith(line));
            return [hits, line];
          }
          const action = arg.split(/\s+/)[0];
          if (action === "reload" || action === "remove" || action === "enable" || action === "disable") {
            const ids = new McpStore(MCP_FILE).load().servers.map((s) => s.id);
            const used = `${cmd} ${action}`;
            const hits = ids.map((id) => `${used} ${id}`).filter((s) => s.startsWith(line));
            return [hits, line];
          }
          return [[], line];
        }
        if (cmd === "/load" || cmd === "/cd" || cmd === "/save") {
          const [hits, frag] = completePath(arg);
          return [hits.map((h) => `${cmd} ${h}`), line];
        }
        return [[], line];
      }
      return [[], line];
    } catch {
      return [[], line];
    }
  };
}

export async function main() {
  const opts = parseArgs(process.argv.slice(2));

  if (opts.help) {
    process.stdout.write(USAGE);
    return;
  }
  if (opts.version) {
    console.log(VERSION);
    return;
  }
  if (opts.json && opts.prompt === null) {
    console.error("--json requires -p/--prompt");
    process.exit(2);
  }

  const plain = opts.plain || opts.json || (opts.prompt !== null && !process.stdout.isTTY);
  if (plain) setColorEnabled(false);

  ensureDirs();

  let config = loadConfig();
  if (opts.model) config.model = opts.model;
  if (opts.maxTokens) config.maxTokens = opts.maxTokens;
  if (opts.tools === false) config.tools = false;
  if (opts.yes) config.autoApprove = true;
  if (opts.apiBase) config.apiBase = opts.apiBase;
  if (opts.apiKey) config.apiKey = opts.apiKey;

  // A named PROVIDER fills in a base URL and default model unless the user
  // pinned their own. Copilot needs no preset; anything unknown fails loudly
  // rather than quietly sending requests to the wrong place.
  const provider = resolveProvider(config.provider);
  if (!provider) {
    console.error(c.red(`  unknown PROVIDER "${config.provider}" (try copilot or kilo)`));
    process.exit(2);
  }
  if (provider.name !== "copilot" && !config.apiBase) {
    config.apiBase = provider.apiBase;
    if (!config.apiKey && provider.apiKey) config.apiKey = provider.apiKey;
    if (!config.model && provider.defaultModel) config.model = provider.defaultModel;
  }

  if (opts.showConfig) {
    const rows = [
      ["USERNAME", config.username],
      ["AGENT_NAME", config.agentName],
      ["MODEL", config.model || "(auto)"],
      ["TOOLS", config.tools ? "on" : "off"],
      ["AUTO_APPROVE", config.autoApprove ? "on" : "off"],
      ["HISTORY_MESSAGES", config.historyMessages],
      ["MAX_TOKENS", config.maxTokens],
      ["MAX_TOOL_CHARS", config.maxToolChars],
      ["CONTEXT_WINDOW", config.contextWindow],
      ["PROVIDER", provider.name],
      ["API_BASE", config.apiBase || "(copilot)"],
      ["API_KEY", config.apiKey ? "(set)" : "(not set)"],
      ["GROQ_API_KEY", config.groqApiKey ? "(set)" : "(not set)"],
      ["STT_MODEL", config.sttModel],
      ["TTS_PROVIDER", config.ttsProvider],
      ["TTS_MODEL", config.ttsModel],
      ["TTS_VOICE", config.ttsVoice || "(provider default)"],
      ["TTS_RATE", config.ttsRate],
      ["SPEAK", config.speak ? "on" : "off"],
      ["MIC_DEVICE", config.micDevice || "(auto)"],
      ["TIMEZONE", config.timeZone || "(system local)"],
      ["QUIET_HOURS", config.quietHours || "(off)"],
      ["DESKTOP_NOTIFICATIONS", config.desktopNotifications ? "on" : "off"],
      ["NTFY_URL", config.ntfyUrl ? "(set)" : "(not set)"],
      ["DISCORD_WEBHOOK_URL", config.discordWebhookUrl ? "(set)" : "(not set)"],
      ["PUSHOVER", config.pushoverToken && config.pushoverUser ? "(set)" : "(not set)"],
      ["MEMORY_CONSOLIDATION", config.memoryConsolidation ? "on" : "off"],
      ["MEMORY_RECALL_CHARS", config.memoryRecallChars],
      ["MEMORY_CONSOLIDATION_HOUR", config.memoryConsolidationHour],
      ["MEMORY_BATCH_SIZE", config.memoryBatchSize],
      ["MEMORY_CHUNK_CHARS", config.memoryChunkChars],
      ["MEMORY_TIMEOUT", config.memoryTimeout],
      ["SYSTEM_EXTRA", config.systemExtra || ""],
    ];
    console.log(c.bold("\nresolved config"));
    for (const [k, v] of rows) console.log(`  ${String(k).padEnd(18)} ${v}`);
    console.log(c.dim(`\n  project env  ${config.envPath || "(none found)"}`));
    console.log(c.dim(`  global env   ${config.globalEnvPath || "(none found)"}`));
    console.log(c.dim(`  auth file    ${AUTH_FILE}`));
    console.log(c.dim(`  sessions     ${SESSIONS_DIR}`));
    console.log(c.dim(`  tools        ${toolNames().join(", ")}`));
    console.log(c.dim(`  cwd          ${process.cwd()}\n`));
    return;
  }

  let client;
  if (config.apiBase) {
    if (!config.apiKey && !provider.keyless) console.log(c.yellow("  note: no API_KEY set - trying without credentials"));
    client = new CompatibleClient({
      apiBase: config.apiBase,
      apiKey: config.apiKey,
      model: config.model,
      contextWindow: config.contextWindow,
    });
  } else {
    let githubToken = resolveGithubToken();
    if (!githubToken) {
      console.log(c.dim("\n  no saved credentials - starting GitHub device login"));
      githubToken = await deviceLogin();
      writeAuth({ github_token: githubToken, saved_at: new Date().toISOString() });
    }
    client = new CopilotClient(githubToken);
    await client.ensureToken();
  }

  let models;
  try {
    models = await client.models();
  } catch (err) {
    console.error(c.red(`  could not list models: ${err.message}`));
    if (config.apiBase && !config.model) {
      console.error(c.red("  set MODEL (or -m) when model discovery is unavailable."));
    }
    process.exit(1);
  }

  if (opts.listModels) {
    console.log(c.bold(`\n${models.length} models\n`));
    for (const m of models) {
      const flags = [
        m.vendor,
        m.context ? `${fmtTokens(m.context)} ctx` : null,
        m.tools === false ? "no-tools" : null,
        m.default ? "default" : null,
      ]
        .filter(Boolean)
        .join("  ");
      console.log(`  ${m.id.padEnd(30)} ${c.dim(flags)}`);
    }
    console.log("");
    return;
  }
  if (!models.length) throw new Error("No models returned for this account.");

  let picked;
  try {
    picked = pickModel(models, config.model, config.tools);
  } catch (err) {
    console.error(c.red(`  ${err.message}`));
    process.exit(1);
  }
  if (config.model && !picked.matched) {
    console.log(c.yellow(`  unknown model "${config.model}", using ${picked.id} instead`));
  }
  const model = picked.id;

  // Adopt the model's advertised context window unless CONTEXT_WINDOW was set
  // deliberately. The 32768 default is well below what a current model offers,
  // and a small window is what makes a large MCP server fail outright: the
  // request cannot fit its tools plus the reserved output. Set on the shared
  // config so routine workers, which build their own Agents, get it too.
  if (!config.contextWindowExplicit && picked.context) {
    config.contextWindow = picked.context;
  }

  const term = new Terminal({ completer: makeCompleter(models) });
  term.loadHistory(HISTORY_FILE);

  // Projects: which one is active shapes the system prompt from here on.
  let projects = new ProjectStore(PROJECTS_FILE).load();

  // Process-level, not per-Agent: every freshAgent worker must share these
  // live connections, or a routine would spawn a server for one call.
  const mcp = new McpManager({
    log: (m) => term.line(c.dim(`  mcp: ${m}`)),
    onChange: () => agent?.refreshPrompt?.(),
  });
  const activeProject = () => projects.active;
  const projectBlock = () => projects.promptBlock();

  const agent = new Agent({
    client,
    config,
    journal: turn => recordTurn(turn, { timeZone: config.timeZone }),
    project: projectBlock(),
    projectId: activeProject()?.id || null,
    mcp,
    print: (s) => term.line(s),
    write: (s) => term.write(s),
    confirm: async (toolName, detail) => {
      term.line("");
      term.line(c.yellow(`  ── ${toolName} ` + "─".repeat(Math.max(0, 40 - toolName.length))));
      term.line(
        detail
          .split("\n")
          .map((l) => "  " + l)
          .join("\n")
      );
      term.line(c.yellow("  " + "─".repeat(44)));
      const answer = (await term.ask("  allow? [y]es / [n]o / [a]lways / [q]uit > ")) ?? "";
      const a = answer.trim().toLowerCase();
      if (a === "a" || a === "always") {
        agent.autoApprove = true;
        term.line(c.dim("  auto-approve on"));
        return true;
      }
      if (a === "q" || a === "quit") {
        term.line(c.dim("bye"));
        process.exit(0);
      }
      return a === "y" || a === "yes";
    },
  });
  agent.model = model;

  // Connect any MCP servers the user has already approved, so their tools are
  // in the very first request. Only approved servers start, so this cannot
  // execute anything new without a fresh yes. Cold uvx/npx pulls make the
  // first run of a server slow; after that it is cached.
  if (agent.useTools) {
    const mcpStore = new McpStore(MCP_FILE).load();
    if (mcpStore.enabled.some((s) => mcpStore.isApproved(s))) {
      term.write(c.dim("  connecting MCP servers..."));
      await mcp.reconcile(mcpStore).catch(() => {});
      term.write("\r\x1b[K");
      agent.refreshPrompt();
    }
  }

  const writeSession = (name) => {
    const file = sessionPath(name);
    saveSession(file, { name, model: agent.model, savedAt: new Date().toISOString(), messages: agent.messages, projectId: agent.projectId, journaled: agent.journalComplete });
    return file;
  };

  const restoreSession = (data, label) => {
    if (!data || !Array.isArray(data.messages)) {
      throw new Error(`"${label}" is not a readable session file.`);
    }
    const restored = sanitizeMessages(data.messages.filter((m) => m.role !== "system"));
    agent.clear();
    agent.messages.push(...restored);
    if (data.model) agent.model = data.model;
    return restored.length;
  };

  const shutdown = async (code = 0) => {
    try {
      writeSession(AUTOSAVE_NAME);
    } catch {}
    term.saveHistory(HISTORY_FILE);
    try {
      await cleanupJobs(agent.state);
    } catch {}
    try {
      await mcp.closeAll();
    } catch {}
    term.line(code === 0 ? c.dim("bye") : "");
    process.exit(code);
  };

  if (opts.banner && opts.prompt === null && !opts.brief && !opts.daemon) {
    banner({
      agentName: config.agentName,
      username: config.username,
      model,
      tools: agent.useTools,
      autoApprove: agent.autoApprove,
      cwd: process.cwd(),
      envPath: config.envPath || config.globalEnvPath,
      count: models.length,
      project: activeProject() ? `${activeProject().name}${activeProject().path ? "  " + activeProject().path : ""}` : null,
    });
    if (config.apiBase) console.log(c.dim(`  endpoint: ${config.apiBase}\n`));
  }

  if (opts.continueName) {
    const file = sessionPath(opts.continueName);
    if (!fs.existsSync(file)) {
      console.error(c.red(`  no saved session "${opts.continueName}" (see /sessions)`));
      process.exit(1);
    }
    try {
      const data = JSON.parse(fs.readFileSync(file, "utf8"));
      const n = restoreSession(data, opts.continueName);
      console.log(c.dim(`  resumed ${n} messages from ${opts.continueName}  (model ${agent.model})`));
    } catch (err) {
      console.error(c.red(`  cannot resume: ${err.message}`));
      process.exit(1);
    }
  }

  const voice = { speak: Boolean(opts.speak || config.speak) };

  let busy = false;
  let voiceActive = false;
  let cancelHook = null;
  process.on("SIGINT", () => {
    if (busy || voiceActive) {
      agent.cancel();
      const hook = cancelHook;
      cancelHook = null;
      term.cancelPending();
      hook?.();
      term.line(c.dim("\n  cancelling..."));
      return;
    }
    stopPlayback();
    shutdown(0);
  });

  const promptLabel = () => `${c.magenta(config.agentName)} ${c.dim("›")} `;

  const runTurn = async (text) => {
    busy = true;
    const started = Date.now();
    const outcome = { text: "", thinking: "", toolCalls: [], error: null };
    const show = !opts.json;
    let spin = null;
    let renderer = null;
    let spoke = false;

    try {
      await agent.send(text, {
        onMessageStart: () => {
          if (show && !spoke && !opts.prompt) spin = spinner("thinking");
          if (!plain) renderer = new LiveRenderer({ write: (s) => term.write(s) });
        },
        onDelta: (d) => {
          outcome.text += d;
          if (!show) return;
          if (plain) {
            if (d) {
              spin?.stop();
              spin = null;
              term.write(d);
              spoke = true;
            }
            return;
          }
          spin?.stop();
          spin = null;
          renderer?.push(d);
        },
        onReasoning: (r) => {
          outcome.thinking += r;
          if (!show) return;
          spin?.stop();
          spin = null;
          term.write(c.dim(r));
          spoke = true;
        },
        onMessageEnd: () => {
          spin?.stop();
          spin = null;
          if (renderer?.buf) spoke = true;
          renderer?.finish();
          renderer = null;
        },
        onToolCall: (call) => {
          let parsed = call.function.arguments;
          try {
            parsed = JSON.parse(call.function.arguments);
          } catch {}
          outcome.toolCalls.push({ ref: call, name: call.function.name, args: parsed });
          if (!show) return;
          term.line(c.cyan(`  → ${call.function.name}(${short(call.function.arguments, 140)})`));
        },
        onToolResult: (call, result) => {
          const entry = outcome.toolCalls.find((e) => e.ref === call);
          if (entry) entry.result = result;
          if (!show) return;
          term.line(c.dim(preview(clip(result, 4000, "result"), 8).replace(/^/gm, "    ")));
        },
        onUsage: () => {},
      });
      if (spoke && show) {
        const secs = ((Date.now() - started) / 1000).toFixed(1);
        const u = agent.turnUsage;
        const use = u.total_tokens > 0 ? ` · ${fmtTokens(u.prompt_tokens)} in / ${fmtTokens(u.completion_tokens)} out` : "";
        term.line(c.dim(`  · ${secs}s · ${agent.model}${use}`));
      }
    } catch (err) {
      spin?.stop();
      if (err.name === "AbortError") {
        if (show) term.line(c.dim("  (cancelled)"));
        outcome.error = "cancelled";
      } else if (err.status === 401 || err.status === 403) {
        try {
          await client.ensureToken(true);
        } catch {}
        if (show) term.line(c.yellow("  token refreshed - send that again."));
        outcome.error = "unauthorized (token refreshed, resend)";
      } else {
        if (show) term.line(c.red("  error: " + err.message));
        outcome.error = err.message;
      }
    } finally {
      busy = false;
    }
    return outcome;
  };

  const speakText = async (text) => {
    const clean = stripForSpeech(text);
    if (!clean) return;
    const provider = resolveTtsProvider(config);
    if (provider === "groq" && !config.groqApiKey) {
      term.line(c.dim("  (tts: set GROQ_API_KEY in .env, or TTS_PROVIDER=edge)"));
      return;
    }
    try {
      const audio =
        provider === "groq"
          ? await synthesizeGroq({
              apiKey: config.groqApiKey,
              model: config.ttsModel,
              voice: resolveTtsVoice(config, "groq"),
              text: clean,
            })
          : await synthesizeEdge({
              voice: resolveTtsVoice(config, "edge"),
              rate: config.ttsRate,
              text: clean,
            });
      await playMp3(audio);
    } catch (err) {
      term.line(c.dim(`  (tts: ${err.message})`));
    }
  };

  const voiceReady = () => {
    const rt = voiceRuntimeCheck();
    if (rt) {
      term.line(c.red(`  ${rt}`));
      return false;
    }
    const deps = audioDeps();
    if (!deps.ffmpeg || !deps.ffplay) {
      term.line(c.red("  voice needs ffmpeg + ffplay on PATH."));
      term.line(c.dim("  install: winget install Gyan.FFmpeg   (then restart the terminal)"));
      return false;
    }
    // Re-read .env: adding a key should not require /reload or a restart.
    config = loadConfig();
    if (opts.model) config.model = opts.model;
    if (opts.maxTokens) config.maxTokens = opts.maxTokens;
    agent.config = config;
    if (!config.groqApiKey) {
      term.line(c.red("  voice needs GROQ_API_KEY in .env (free key at console.groq.com)."));
      term.line(c.dim("  add it, then run /voice again - no restart needed."));
      return false;
    }
    return true;
  };

  /** Record until Enter, transcribe with Groq. null = cancelled, "" = nothing usable. */
  const voiceTurn = async () => {
    const wav = tmpVoiceFile("wav");
    let rec;
    try {
      const mic = await detectMic(config.micDevice);
      if (!mic) {
        term.line(c.red("  no microphone found (set MIC_DEVICE in .env to pick one)."));
        return "";
      }
      rec = await startRecording(wav, mic.name);
    } catch (err) {
      term.line(c.red(`  mic: ${err.message}`));
      return "";
    }

    const started = Date.now();
    const tick = setInterval(() => {
      term.write(
        `\r  listening… ${Math.floor((Date.now() - started) / 1000)}s  (Enter to send, Ctrl+C to cancel)\x1b[K`
      );
    }, 250);
    cancelHook = () => {
      rec.stop().catch(() => {});
    };
    const line = await term.ask("");
    cancelHook = null;
    clearInterval(tick);
    term.write("\r\x1b[K");
    const ok = await rec.stop();
    try {
      if (line === null) return null;
      if (!ok) {
        term.line(c.red("  recording failed (nothing captured)."));
        return "";
      }
      term.write(c.dim("  transcribing…"));
      const text = await transcribeGroq({
        apiKey: config.groqApiKey,
        model: config.sttModel,
        wavPath: wav,
      });
      term.write("\r\x1b[K");
      return text;
    } catch (err) {
      term.write("\r\x1b[K");
      term.line(c.red(`  stt: ${err.message}`));
      return "";
    } finally {
      try {
        fs.unlinkSync(wav);
      } catch {}
    }
  };

  const voiceLoop = async () => {
    if (!voiceReady()) return;
    voiceActive = true;
    term.line(c.dim('  voice mode — speak, press Enter to send each turn. Say "exit" to leave.'));
    try {
      while (true) {
        const said = await voiceTurn();
        if (said === null) {
          term.line(c.dim("  (cancelled)"));
          break;
        }
        const clean = said.trim();
        if (!clean) continue;
        if (/^(exit|quit|stop|goodbye|bye)[.!]?$/i.test(clean)) {
          term.line(c.dim("  leaving voice mode."));
          break;
        }
        term.line(`${c.magenta(config.username)} ${c.dim("›")} ${clean}`);
        const outcome = await runTurn(clean);
        term.line("");
        try {
          writeSession(AUTOSAVE_NAME);
        } catch {}
        if (outcome && !outcome.error && outcome.text) await speakText(outcome.text);
      }
    } finally {
      voiceActive = false;
      cancelHook = null;
    }
  };

  if (opts.prompt !== null) {
    if (!opts.prompt.trim()) {
      if (opts.json) console.log(JSON.stringify({ ok: false, error: "empty prompt" }));
      else console.error("empty prompt");
      process.exit(2);
    }
    if (opts.json) {
      const started = Date.now();
      const outcome = await runTurn(opts.prompt);
      console.log(
        JSON.stringify({
          ok: !outcome.error,
          model: agent.model,
          ms: Date.now() - started,
          text: outcome.text,
          ...(outcome.thinking ? { thinking: outcome.thinking } : {}),
          toolCalls: outcome.toolCalls.map(({ name, args, result }) => ({ name, args, result })),
          usage: agent.turnUsage,
          ...(outcome.error ? { error: outcome.error } : {}),
        })
      );
      await cleanupJobs(agent.state).catch(() => {});
      term.saveHistory(HISTORY_FILE);
      process.exit(outcome.error ? 1 : 0);
    }
    const outcome = await runTurn(opts.prompt);
    if (opts.speak && outcome.text) await speakText(outcome.text);
    await cleanupJobs(agent.state).catch(() => {});
    term.saveHistory(HISTORY_FILE);
    process.exit(0);
  }

  /* ---------------------- proactive: schedule/watch/inbox ---------------------- */

  const BRIEFING_PROMPT =
    config.briefingPrompt ||
    "Give me a short briefing for right now. Cover, in this order and only if there is " +
      "something to say: (1) my GitHub inbox via github_notifications - mentions, review " +
      "requests, invitations; (2) any watch reports via watch action=check where something " +
      "moved; (3) anything that needs a decision from me today. " +
      "Be specific and brief: a few lines, no preamble, no restating this request.";

  const store = new RoutineStore(STATE_FILE).load();
  const bot = new TelegramBot({
    token: config.telegramBotToken,
    allowedChatIds: parseChatIds(config.telegramAllowedChatIds),
    ownerChatId: config.telegramChatId,
  });

  const ownerChat = () => {
    if (config.telegramChatId) return config.telegramChatId;
    const allowed = parseChatIds(config.telegramAllowedChatIds);
    return allowed.length ? allowed[0] : null;
  };

  const notifications = new NotificationDelivery({
    config, file: NOTIFY_QUEUE_FILE,
    telegram: async text => {
      if (!bot.enabled || !ownerChat()) return false;
      await bot.send(ownerChat(), text);
    },
    print: text => { term.line(''); term.line(text.replace(/^/gm, '  ')); term.line(''); },
    log: text => term.line(c.dim(`  ${text}`)),
  });
  const deliver = text => opts.daemon ? notifications.queueMessage(text) : notifications.send(text);

  // Set once the daemon exists, so routine/brief work can ask for approval in
  // Telegram instead of being silently denied.
  let daemonRef = null;

  const freshAgent = (purpose) =>
    new Agent({
      client,
      config,
      // One-shot agents for routines, briefings and alerts always carry every
      // tool: there is no session to amortise a find_tools round trip across,
      // and the briefing prompt needs github_notifications and watch every time.
      deferTools: false,
      // The same manager the REPL uses, so a routine reaches the live servers
      // instead of spawning its own and abandoning it.
      mcp,
      confirm:
        purpose === "alert"
          ? // An unattended alert may look things up, but must never change
            // anything behind the user's back.
            async () => false
          : (toolName, detail) =>
              daemonRef
                ? daemonRef.confirmOwner(toolName, detail)
                : Promise.resolve(Boolean(config.autoApprove)),
      print: () => {},
      write: () => {},
    });

  const runPrompt = async (prompt, meta = {}) => {
    if (meta.purpose === 'consolidation') return extractMemory(prompt, { client, config, model: agent.model });
    const worker = freshAgent(meta.purpose);
    worker.model = agent.model;
    try {
      return await worker.send(prompt, {});
    } finally {
      // The worker's state dies with it. A background job it started would
      // otherwise be orphaned the moment this returns - the child outlives the
      // Map that tracked it, and no shutdown path ever sees it.
      await cleanupJobs(worker.state).catch(() => {});
    }
  };

  if (opts.brief) {
    const text = String((await runPrompt(BRIEFING_PROMPT)) || "").trim() || "(nothing to report)";
    const channel = await notifications.send(`Briefing\n\n${text}`);
    if (channel !== 'terminal') term.line(c.dim(`  briefing ${channel === 'queued' ? 'queued for delivery' : `submitted via ${channel}`}`));
    process.exit(0);
  }

  if (opts.daemon) {
    banner({
      agentName: `${config.agentName} \u25d7 daemon`,
      username: config.username,
      model,
      tools: agent.useTools,
      autoApprove: agent.autoApprove,
      cwd: process.cwd(),
      envPath: config.envPath || config.globalEnvPath,
      count: 0,
    });
    const daemon = new Daemon({
      store,
      bot,
      config,
      client,
      model,
      runPrompt,
      deliver,
      flushNotifications: () => notifications.flush(),
      consolidator: new MemoryConsolidator({ config, extract: runPrompt, log: m => term.line(c.dim(`  ${m}`)) }),
      log: (m) => term.line(c.dim(`  ${m}`)),
      logFile: DAEMON_LOG,
      tickMs: config.daemonTick * 1000,
      maxConcurrent: config.maxConcurrent,
      mcp,
    });
    daemonRef = daemon;
    process.on("SIGINT", () => {
      term.line(c.dim("\n  stopping..."));
      daemon.stop();
    });
    await daemon.run();
    // The daemon's own agents are gone by now, so anything they left running
    // - background commands, MCP servers - has to be shut down here or it
    // outlives the process that owns it.
    await cleanupJobs(agent.state).catch(() => {});
    await mcp.closeAll().catch(() => {});
    term.line(c.dim("bye"));
    process.exit(0);
  }

  if (opts.voiceLoop) {
    await voiceLoop();
  }

  while (true) {
    const raw = await term.ask(promptLabel());
    if (raw === null) break;
    const input = raw.trim();
    if (!input) continue;

    if (!input.startsWith("/")) {
      const outcome = await runTurn(input);
      term.line("");
      try {
        writeSession(AUTOSAVE_NAME);
      } catch {}
      // The agent can switch projects with the project tool; keep in step.
      const fresh = new ProjectStore(PROJECTS_FILE).load();
      if (fresh.activeId !== projects.activeId) {
        projects = fresh;
        if (projects.active?.path) {
          try {
            process.chdir(projects.active.path);
          } catch {}
        }
        agent.setProject(projectBlock(), projects.activeId);
        term.line(c.dim(`  project → ${projects.active ? projects.active.name : "(none)"}`));
      }
      if (voice.speak && outcome.text) await speakText(outcome.text);
      continue;
    }

    const [cmd, ...restArgs] = input.split(/\s+/);
    const arg = restArgs.join(" ").trim();

    switch (cmd) {
      case "/exit":
      case "/quit":
        await shutdown(0);
        break;

      case "/help":
        term.line("");
        term.line(helpText({ agentName: config.agentName }));
        term.line("");
        break;

      case "/config": {
        const fresh = loadConfig();
        term.line("");
        term.line(`  ${"USERNAME".padEnd(16)} ${c.bold(fresh.username)}${fresh.username !== config.username ? c.dim("  (restart or /reload)") : ""}`);
        term.line(`  ${"AGENT_NAME".padEnd(16)} ${c.bold(fresh.agentName)}${fresh.agentName !== config.agentName ? c.dim("  (restart or /reload)") : ""}`);
        term.line(`  ${"MODEL".padEnd(16)} ${agent.model}`);
        term.line(`  ${"TOOLS".padEnd(16)} ${agent.useTools ? "on" : "off"}`);
        term.line(`  ${"AUTO_APPROVE".padEnd(16)} ${agent.autoApprove ? "on" : "off"}`);
        term.line(`  ${"HISTORY_MESSAGES".padEnd(16)} ${config.historyMessages}`);
        term.line(`  ${"MAX_TOKENS".padEnd(16)} ${config.maxTokens}`);
        term.line(
          `  ${"SPEAK".padEnd(16)} ${voice.speak ? "on" : "off"}${config.speak !== voice.speak ? c.dim(`  (.env: ${config.speak ? "on" : "off"})`) : ""}`
        );
        term.line(`  ${"TTS_PROVIDER".padEnd(16)} ${resolveTtsProvider(config)}${config.ttsProvider !== "auto" ? "" : c.dim("  (auto)")}`);
        term.line(`  ${"TTS_VOICE".padEnd(16)} ${resolveTtsVoice(config, resolveTtsProvider(config))}`);
        term.line(`  ${"TTS_MODEL".padEnd(16)} ${config.ttsModel}`);
        term.line(`  ${"STT_MODEL".padEnd(16)} ${config.sttModel}`);
        term.line(`  ${"GROQ_API_KEY".padEnd(16)} ${config.groqApiKey ? "(set)" : "(not set)"}`);
        term.line(`  ${"MIC_DEVICE".padEnd(16)} ${config.micDevice || "(auto)"}`);
        term.line(c.dim(`  project env: ${config.envPath || "(no .env found)"}`));
        term.line(c.dim(`  global env:  ${config.globalEnvPath || "(none)"}`));
        term.line("");
        break;
      }

      case "/reload": {
        config = loadConfig();
        if (opts.model) config.model = opts.model;
        if (opts.maxTokens) config.maxTokens = opts.maxTokens;
        agent.config = config;
        agent.rebase();
        voice.speak = Boolean(opts.speak || config.speak);
        term.line(
          c.dim(
            `  reloaded  ·  user ${c.bold(config.username)}  ·  agent ${c.bold(config.agentName)}` +
              (config.envPath || config.globalEnvPath ? "" : "  (no .env found)")
          )
        );
        break;
      }

      case "/models":
        term.line("");
        for (const m of models) {
          const marks = [
            m.tools === false ? c.dim("no-tools") : "",
            m.context ? c.dim(`${fmtTokens(m.context)} ctx`) : "",
            m.id === agent.model ? c.green("← current") : "",
          ]
            .filter(Boolean)
            .join("  ");
          term.line(`  ${m.id.padEnd(30)} ${c.dim((m.vendor || "").padEnd(12))} ${marks}`);
        }
        term.line("");
        break;

      case "/model": {
        if (!arg) {
          term.line(c.dim(`  current: ${agent.model}`));
          break;
        }
        try {
          const next = pickModel(models, arg, agent.useTools);
          agent.model = next.id;
          term.line(
            c.dim(`  model → ${agent.model}`) +
              (next.matched ? "" : c.yellow(`  (no match for "${arg}")`))
          );
        } catch (err) {
          term.line(c.red(`  ${err.message}`));
        }
        break;
      }

      case "/tools":
        agent.useTools = arg === "on" ? true : arg === "off" ? false : !agent.useTools;
        term.line(c.dim(`  tools ${agent.useTools ? "on" : "off"}`));
        break;

      case "/auto":
        agent.autoApprove = arg === "on" ? true : arg === "off" ? false : !agent.autoApprove;
        term.line(c.dim(`  auto-approve ${agent.autoApprove ? "on" : "off"}`));
        break;

      case "/cd": {
        const dir = path.isAbsolute(arg) ? arg : path.resolve(process.cwd(), arg);
        try {
          process.chdir(dir);
          agent.rebase();
          term.line(c.dim(`  cwd → ${process.cwd()}`));
        } catch (err) {
          term.line(c.red(`  cannot cd: ${err.message}`));
        }
        break;
      }

      case "/clear":
        agent.clear();
        term.line(c.dim("  conversation cleared"));
        break;

      case "/paste": {
        term.line(c.dim("  paste lines, end with a single . on its own line:"));
        const buf = [];
        while (true) {
          const pasted = await term.ask("  ... ");
          if (pasted === null || pasted === ".") break;
          buf.push(pasted);
        }
        const text = buf.join("\n").trim();
        if (!text) {
          term.line(c.dim("  (empty paste, ignored)"));
          break;
        }
        const pasteOutcome = await runTurn(text);
        term.line("");
        try {
          writeSession(AUTOSAVE_NAME);
        } catch {}
        if (voice.speak && pasteOutcome.text) await speakText(pasteOutcome.text);
        break;
      }

      case "/mic": {
        if (!voiceReady()) break;
        voiceActive = true;
        let said;
        try {
          said = await voiceTurn();
        } finally {
          voiceActive = false;
        }
        if (said === null) {
          term.line(c.dim("  (cancelled)"));
          break;
        }
        if (!said.trim()) break;
        term.line(`${c.magenta(config.username)} ${c.dim("›")} ${said.trim()}`);
        const micOutcome = await runTurn(said.trim());
        term.line("");
        try {
          writeSession(AUTOSAVE_NAME);
        } catch {}
        if (voice.speak && micOutcome && !micOutcome.error && micOutcome.text) {
          await speakText(micOutcome.text);
        }
        break;
      }

      case "/voice":
        await voiceLoop();
        break;

      case "/say": {
        if (!arg) {
          term.line(c.red("  usage: /say <text>"));
          break;
        }
        const rt = voiceRuntimeCheck();
        if (rt) {
          term.line(c.red(`  ${rt}`));
          break;
        }
        if (!audioDeps().ffplay) {
          term.line(c.red("  /say needs ffplay on PATH (winget install Gyan.FFmpeg)."));
          break;
        }
        await speakText(arg);
        break;
      }

      case "/speak": {
        voice.speak = arg === "on" ? true : arg === "off" ? false : !voice.speak;
        const provider = resolveTtsProvider(config);
        term.line(
          c.dim(`  auto-speak replies ${voice.speak ? "on" : "off"} (${provider}: ${resolveTtsVoice(config, provider)})`)
        );
        break;
      }

      case "/voices": {
        try {
          const provider = resolveTtsProvider(config);
          const q = arg.toLowerCase();
          term.line("");
          if (provider === "groq") {
            const hits = GROQ_VOICES.filter(
              (v) => !q || `${v.id} ${v.gender}`.toLowerCase().includes(q)
            );
            const current = resolveTtsVoice(config, "groq");
            for (const v of hits) {
              term.line(
                `  ${v.id.padEnd(12)} ${c.dim(`${v.gender}  orpheus-english`)} ${
                  v.id === current ? c.green("← current") : ""
                }`
              );
            }
            term.line(c.dim(`  model: ${config.ttsModel}`));
          } else {
            const all = await listEdgeVoices();
            const hits = all.filter(
              (v) =>
                !q ||
                `${v.ShortName || ""} ${v.Gender || ""} ${v.LocaleName || v.Locale || ""}`
                  .toLowerCase()
                  .includes(q)
            );
            const current = resolveTtsVoice(config, "edge");
            for (const v of hits.slice(0, 40)) {
              const mark = v.ShortName === current ? c.green("← current") : "";
              term.line(
                `  ${(v.ShortName || "").padEnd(28)} ${c.dim(
                  `${v.Gender || ""}  ${v.LocaleName || v.Locale || ""}`
                )} ${mark}`
              );
            }
            if (hits.length > 40) term.line(c.dim(`  … ${hits.length - 40} more (narrow with /voices <filter>)`));
          }
          term.line(c.dim(`  provider: ${provider}  ·  set TTS_VOICE / TTS_PROVIDER in .env to switch.`));
          term.line("");
        } catch (err) {
          term.line(c.red(`  voices: ${err.message}`));
        }
        break;
      }

      case "/usage": {
        term.line("");
        term.line(usageLine("turn", agent.turnUsage));
        term.line(usageLine("session", agent.sessionUsage));
        term.line("");
        break;
      }

      case "/brief": {
        term.line(c.dim("  gathering..."));
        try {
          const text = await runPrompt(BRIEFING_PROMPT);
          term.line("");
          term.line(String(text || "(nothing to report)").replace(/^/gm, "  "));
          term.line("");
        } catch (err) {
          term.line(c.red(`  briefing failed: ${err.message}`));
        }
        break;
      }

      case "/mcp": {
        const [sub, ...rest] = arg.split(/\s+/).filter(Boolean);
        const target = rest.join(" ").trim();
        const store = new McpStore(MCP_FILE).load();

        if (!sub || sub === "list") {
          term.line("");
          if (!store.servers.length) {
            term.line(c.dim("  no MCP servers configured"));
            term.line(c.dim("  add one with:  /mcp add <name> <command> [args...]"));
            term.line(c.dim("  example:       /mcp add everything npx -y @modelcontextprotocol/server-everything"));
          }
          for (const rec of store.servers) {
            term.line(`  ${describeServer(rec, mcp.has(rec.id))}`);
          }
          if (store.servers.length) {
            term.line("");
            term.line(c.dim(`  ${mcp.connectedIds.length} live · ${store.enabled.length} enabled`));
          }
          term.line("");
          break;
        }

        if (sub === "add") {
          const [name, command, ...cmdArgs] = target.split(/\s+/).filter(Boolean);
          if (!name || !command) {
            term.line(c.red("  usage: /mcp add <name> <command> [args...]"));
            break;
          }
          try {
            const record = store.add({ name, command, args: cmdArgs });
            term.line(c.dim(`  registered "${record.id}"`));
            term.line(c.dim(`  command: ${record.command} ${(record.args || []).join(" ")}`));
            term.line(c.dim(`  start it with:  /mcp reload ${record.id}   (asks for approval first)`));
          } catch (err) {
            term.line(c.red(`  ${err.message}`));
          }
          break;
        }

        if (sub === "remove" || sub === "enable" || sub === "disable") {
          if (!target) {
            term.line(c.red(`  usage: /mcp ${sub} <id>`));
            break;
          }
          if (sub === "remove") {
            const gone = store.remove(target);
            if (gone) await mcp.disconnect(gone.id).catch(() => {});
            term.line(gone ? c.dim(`  removed "${gone.id}"`) : c.red(`  no server "${target}"`));
          } else {
            const rec = store.setEnabled(target, sub === "enable");
            if (!rec) {
              term.line(c.red(`  no server "${target}"`));
              break;
            }
            // Disabling takes effect here and now; enabling waits for reload,
            // because starting a process is what approval is for.
            if (sub === "disable") await mcp.disconnect(rec.id).catch(() => {});
            const msg = rec.enabled ? enableMessage(rec, store.isApproved(rec)) : disableMessage(rec);
            term.line(c.dim(`  ${msg}`));
          }
          break;
        }

        if (sub === "reload") {
          if (!target) {
            term.line(c.red("  usage: /mcp reload <id>"));
            break;
          }
          const record = store.find(target);
          if (!record) {
            term.line(c.red(`  no server "${target}"`));
            break;
          }
          const cmdline = `${record.command} ${(record.args || []).join(" ")}`.trim();
          term.line(c.yellow(`  ── start MCP server "${record.id}" ─────────────`));
          term.line(`  command: ${cmdline}`);
          term.line(c.dim("  runs third-party code; approval is remembered for this exact command"));
          term.line(c.yellow("  " + "─".repeat(44)));
          const yes = ((await term.ask("  allow? [y/n] > ")) || "").trim().toLowerCase();
          if (yes !== "y" && yes !== "yes") {
            term.line(c.dim("  not started"));
            break;
          }
          store.markApproved(record.id);
          term.write(c.dim("  starting..."));
          try {
            if (mcp.has(record.id)) await mcp.disconnect(record.id);
            await mcp.connect({
              id: record.id,
              command: record.command,
              args: record.args,
              env: record.env,
              transport: record.transport,
            });
            const tools = mcp.servers.get(record.id)?.tools?.map((t) => t.name) || [];
            store.markConnected(record.id, true, null);
            term.write("\r\x1b[K");
            term.line(c.green(`  live · ${tools.length} tool(s): ${tools.join(", ") || "(none)"}`));
            agent.refreshPrompt();
          } catch (err) {
            term.write("\r\x1b[K");
            store.markConnected(record.id, false, err.message);
            term.line(c.red(`  failed: ${err.message}`));
          }
          break;
        }

        term.line(c.red(`  unknown action "${sub}" - try: ${MCP_ACTIONS.join(", ")}`));
        break;
      }

      case "/projects": {
        projects = new ProjectStore(PROJECTS_FILE).load();
        term.line("");
        if (!projects.projects.length) {
          term.line(c.dim("  no projects yet - ask me to add one, e.g. \"add zumba to my projects\""));
        } else {
          for (const p of projects.projects) term.line(`  ${describeProject(p, projects.activeId)}`);
        }
        term.line("");
        break;
      }

      case "/project": {
        projects = new ProjectStore(PROJECTS_FILE).load();
        if (!arg) {
          const current = projects.active;
          term.line("");
          term.line(current ? describeProjectFull(current, projects) : c.dim("  no active project"));
          term.line("");
          break;
        }
        const picked = projects.use(arg);
        if (!picked) {
          term.line(c.red(`  no project "${arg}" - try /projects`));
          break;
        }
        projects = new ProjectStore(PROJECTS_FILE).load();
        if (picked.path) {
          try {
            process.chdir(picked.path);
          } catch (err) {
            term.line(c.yellow(`  (could not cd to ${picked.path}: ${err.message})`));
          }
        }
        agent.setProject(projectBlock(), projects.activeId);
        term.line(
          c.dim(`  project → ${picked.name}`) + (picked.path ? c.dim(`  ·  cwd ${process.cwd()}`) : "")
        );
        const unknown = projects.missingFor(picked);
        if (unknown.length) term.line(c.dim(`  still unknown: ${unknown.join(", ")}`));
        break;
      }

      case "/routines": {
        store.load();
        term.line("");
        if (!store.routines.length) {
          term.line(c.dim("  no routines scheduled - ask me to set one up, e.g."));
          term.line(c.dim('  "every morning at 8, brief me on my GitHub inbox"'));
        }
        for (const routine of store.routines) {
          term.line(`  ${describeRoutine(routine)}`);
          if (routine.lastRun) {
            term.line(
              c.dim(
                `      last run ${routine.lastRun.slice(0, 16).replace("T", " ")} (${routine.lastStatus})` +
                  (routine.lastSummary ? ` - ${routine.lastSummary.slice(0, 60)}` : "")
              )
            );
          }
        }
        term.line("");
        term.line(c.dim(`  ${bot.enabled ? "telegram delivery on" : "no TELEGRAM_BOT_TOKEN - alerts print here"}`));
        term.line(c.dim("  run them with: ankita --daemon"));
        term.line("");
        break;
      }

      case "/watches": {
        store.load();
        term.line("");
        if (!store.watches.length) term.line(c.dim("  no watches - ask me to watch a page, e.g."));
        for (const w of store.watches) term.line(`  ${describeWatch(w)}`);
        term.line("");
        break;
      }

      case "/daemon": {
        term.line(c.dim("  daemon runs as its own process: ankita --daemon"));
        term.line(c.dim(`  routines ${store.routines.length}, watches ${store.watches.length}`));
        break;
      }

      case "/sessions": {
        const files = fs.existsSync(SESSIONS_DIR) ? fs.readdirSync(SESSIONS_DIR).filter((f) => f.endsWith(".json")) : [];
        term.line("");
        if (!files.length) term.line(c.dim("  no saved sessions"));
        for (const f of files) {
          try {
            const data = JSON.parse(fs.readFileSync(path.join(SESSIONS_DIR, f), "utf8"));
            term.line(
              `  ${path.basename(f, ".json").padEnd(24)} ${c.dim(
                `${data.savedAt}  ${data.model}  ${(data.messages || []).length} msgs`
              )}`
            );
          } catch {
            term.line(`  ${path.basename(f, ".json")} ${c.dim("(unreadable)")}`);
          }
        }
        term.line("");
        break;
      }

      case "/save": {
        const name = arg || new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
        try {
          const file = writeSession(name);
          term.line(c.dim(`  saved → ${file}`));
        } catch (err) {
          term.line(c.red(`  could not save: ${err.message}`));
        }
        break;
      }

      case "/load": {
        if (!arg) {
          term.line(c.red("  usage: /load <name>"));
          break;
        }
        const file = sessionPath(arg);
        if (!fs.existsSync(file)) {
          term.line(c.red(`  no session named "${arg}" (see /sessions)`));
          break;
        }
        try {
          const data = JSON.parse(fs.readFileSync(file, "utf8"));
          const n = restoreSession(data, arg);
          term.line(c.dim(`  loaded ${n} messages from ${arg}  (model ${agent.model})`));
        } catch (err) {
          term.line(c.red(`  could not load: ${err.message}`));
        }
        break;
      }

      default:
        term.line(c.red(`  unknown command "${cmd}" - try /help`));
    }
  }

  await shutdown(0);
}
