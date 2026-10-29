import fs from "node:fs";
import path from "node:path";
import { randomUUID } from 'node:crypto';
import { NotificationDelivery } from '../automation/notify.mjs';
import { MemoryConsolidator } from '../memory/consolidate.mjs';
import { extractMemory } from '../memory/memory-extract.mjs';
import { recordTurn, saveSession } from './sessions.mjs';
import {
  loadConfig,
  CONFIG_DIR,
  ensureDirs,
  AUTH_FILE,
  HISTORY_FILE,
  SESSIONS_DIR,
  AUTOSAVE_NAME,
  STATE_FILE,
  PROJECTS_FILE,
  MCP_FILE,
  COMPOSIO_FILE,
  MCP_TIERS_FILE,
  DAEMON_LOG,
  NOTIFY_QUEUE_FILE,
  CHANNELS_FILE,
} from "./config.mjs";
import { ProjectStore, describeProject, describeProjectFull } from "../memory/projects.mjs";
import { detectProject } from "../memory/project-resolver.mjs";
import { maintainTurn } from "../memory/project-maintenance.mjs";
import { McpManager } from "../integrations/mcp-manager.mjs";
import { TierPolicy } from "../integrations/mcp-tiers.mjs";
import { McpStore, describeServer, enableMessage, disableMessage } from "../integrations/mcp-store.mjs";
import { BrowserPluginStore, CHROME_MCP_ID, browserPluginOverview } from '../integrations/browser-plugins.mjs';
import { ComposioStore } from "../integrations/composio-store.mjs";
import * as composioTool from "../../tools/connectors/composio.mjs";
import { RoutineStore, describeRoutine, describeWatch } from "../automation/routines.mjs";
import { parseChatIds } from "../channels/telegram.mjs";
import { ChannelTelegramBot as TelegramBot } from '../channels/telegram-adapter.mjs';
import { ChannelStore } from '../channels/core/store.mjs';
import { environmentForConfig } from '../channels/core/registry.mjs';
import { createCliChannelHost } from '../channels/cli-host.mjs';
import { runChannelCommand } from '../channels/commands.mjs';
import { TELEGRAM_CHANNEL_ID } from '../channels/manifests/telegram.mjs';
import { Daemon } from "../automation/daemon.mjs";
import { SchedulerOwnership } from '../automation/scheduler-ownership.mjs';
import { SCHEDULER_LOCK_FILENAME, SCHEDULER_TICK_MS } from '../automation/job-policy.mjs';
import { describeCron } from "../automation/cron.mjs";
import { pickModel, resolveProvider } from "./provider.mjs";
import { createVoiceBrain, createAcknowledgements, createVoiceMicrophone, createVoiceReportSpeech, voiceReplyForSpeech } from './voice-session.mjs';
import { captureVoiceContext, runVoiceWorker } from './voice-worker.mjs';
import { VoiceJobs } from '../automation/voice-jobs.mjs';
import { VoiceSpeechQueue } from '../automation/voice-speech-queue.mjs';
import { createVoiceNarrator } from './voice-narrator.mjs';
import { VoiceTaskStore, renderVoiceTask, voiceTaskReport, voiceTaskCommand, VOICE_TASK_COMMAND } from '../automation/voice-task.mjs';
import { VOICE_TASK_DIRECTORY, VOICE_PROGRESS_POLL_MS, VOICE_FINAL_STATES, VOICE_BARGE_GUARD_MS } from '../automation/voice-task-policy.mjs';
import { configuredSecrets } from './redact.mjs';
import { createSession } from "./bootstrap.mjs";
import { sanitizeMessages } from "./history.mjs";
import { Agent } from "./agent.mjs";
import { SUBAGENT_EVENT } from './subagents/registry.mjs';
import { loadSkills, reloadSkills } from './skills.mjs';
import { runLocalCommand } from './local-commands.mjs';
import { startupProfile } from './startup-profile.mjs';
import { deliverTemplateResult } from '../automation/templates.mjs';
import { Terminal, banner, helpText, c, spinner, preview, short, clip, setColorEnabled } from "./ui.mjs";
import {
  FLAGS, LOCAL_COMMANDS, USAGE_LABEL_WIDTH, COMPOSIO_ACTIONS, TOOL_SLUG_PATTERN, FALLBACK_HINT,
  commandNames, itemFor, unknownActionMessage, closestCommand,
} from "./commands.mjs";
import { LiveRenderer } from "./markdown.mjs";
import { names as toolNames, cleanupJobs, displayArgs } from "../../tools/index.mjs";
import { JOB_COMMANDS, isJobCommand, runJobCommand, runningJobCount, jobEventText } from '../tooling/job-ui.mjs';
import * as voiceChannel from '../channels/voice.mjs';
import { useHandsFreePlayback } from "../channels/audio-device.mjs";

function packageVersion() {
  try {
    const pkg = JSON.parse(fs.readFileSync(new URL("../../package.json", import.meta.url), "utf8"));
    return pkg.version || "dev";
  } catch {
    return "dev";
  }
}

const VERSION = packageVersion();

const USAGE_OPTIONS = FLAGS.map((f) => {
  const left = f.short ? `${f.short}, ${f.long}` : `    ${f.long}`;
  const label = f.value ? `${left} ${f.value}` : left;
  return `  ${label.padEnd(USAGE_LABEL_WIDTH)}${f.desc}`;
}).join("\n");

const USAGE = `${c.bold("ankita")} ${c.dim("·")} GitHub Copilot chat in your terminal

${c.bold("usage")}
  ankita [options] [message...]

${c.bold("options")}
${USAGE_OPTIONS}

${c.bold("offline commands")}
${LOCAL_COMMANDS.map(item => `  ankita ${item.name} ${item.args || ''} — ${item.desc}`).join('\n')}

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
      case '--takeover':
        opts.takeover = true;
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

const COMMANDS = [...JOB_COMMANDS, ...commandNames()];

function skillsListText() {
  const skills = loadSkills();
  return skills.length
    ? skills.map(skill => `  ${skill.name} — ${skill.description}`).join('\n')
    : '  No built-in skills installed.';
}

export function makeCompleter(models) {
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
        const item = itemFor(cmd);
        if (item?.actions?.length) {
          if (!arg.includes(" ")) {
            const hits = item.actions.map((a) => `${cmd} ${a}`).filter((s) => s.startsWith(line));
            return [hits, line];
          }
          const action = arg.split(/\s+/)[0];
          if (item.idActions?.includes(action)) {
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

export async function main({ voiceIO = {} } = {}) {
  let channelHostRef = null;
  // Injectable device boundary lets the full terminal loop run in tests without
  // recording a person, playing sound, or spending speech-provider credits.
  const {
    voiceRuntimeCheck, audioDeps, tmpVoiceFile, detectMic, openVoiceInput,
    createTurnDetector, transcribeAudio, synthesizeSarvam, synthesizeEdge,
    synthesizeGroq, listEdgeVoices, GROQ_VOICES, resolveTtsProvider,
    resolveTtsVoice, resolveSarvamSpeaker, chooseSarvamLanguage,
    resolveSttProvider, sttKeysMissing, playMp3, stopPlayback,
    stripForSpeech, summarizeForSpeech,
  } = { ...voiceChannel, ...voiceIO };
  try { if (await runLocalCommand(process.argv.slice(2))) return; }
  catch (error) { console.error(error.message); process.exitCode = 2; return; }
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
  if (opts.prompt?.trim() === '/skills' && !opts.json) {
    console.log(skillsListText());
    return;
  }

  const plain = opts.plain || opts.json || (opts.prompt !== null && !process.stdout.isTTY);
  if (plain) setColorEnabled(false);

  ensureDirs();

  let config = loadConfig();
  if (opts.model) config.model = opts.model;
  if (opts.maxTokens) { config.maxTokens = opts.maxTokens; config.maxTokensExplicit = true; }
  if (opts.tools === false) config.tools = false;
  if (opts.yes) config.autoApprove = true;
  if (opts.apiBase) config.apiBase = opts.apiBase;
  if (opts.apiKey) config.apiKey = opts.apiKey;

  // A named PROVIDER fills in a base URL and default model unless the user
  // pinned their own. Copilot needs no preset; anything unknown fails loudly
  // rather than quietly sending requests to the wrong place.
  const provider = resolveProvider(config.provider);
  if (!provider) {
    console.error(c.red(`  unknown PROVIDER "${config.provider}" (try copilot, kilo or groq)`));
    process.exit(2);
  }
  if (provider.name !== "copilot" && !config.apiBase) {
    config.apiBase = (provider.name === 'baseten' && config.basetenBaseUrl) || provider.apiBase;
    if (!config.apiKey && provider.apiKey) config.apiKey = provider.apiKey;
    // Some gateways reuse an existing key (Groq shares GROQ_API_KEY with voice).
    if (!config.apiKey && provider.keyConfig && config[provider.keyConfig]) config.apiKey = config[provider.keyConfig];
    if (!config.model && provider.defaultModel) config.model = (provider.name === 'baseten' && config.basetenModel) || provider.defaultModel;
  }

  if (opts.showConfig) {
    const rows = [
      ["USERNAME", config.username],
      ["AGENT_NAME", config.agentName],
      ["MODEL", config.model || "(auto)"],
      ["TOOLS", config.tools ? "on" : "off"],
      ["AUTO_APPROVE", config.autoApprove ? "on" : "off"],
      ["HISTORY_MESSAGES", config.historyMessages],
      ["MAX_TOKENS", config.maxTokensExplicit ? config.maxTokens : "(model default)"],
      ["MAX_TOOL_CHARS", config.maxToolChars],
      ["CONTEXT_WINDOW", config.contextWindow],
      ["PROVIDER", provider.name],
      ["API_BASE", config.apiBase || "(copilot)"],
      ["API_KEY", config.apiKey ? "(set)" : "(not set)"],
      ["TOOL", (config.toolProvider || config.toolModel)
        ? `${config.toolProvider || provider.name} · ${config.toolModel || "(provider default)"}`
        : "(off)"],
      ["GROQ_API_KEY", config.groqApiKey ? "(set)" : "(not set)"],
      ["BASETEN_API_KEY", config.basetenApiKey ? "(set)" : "(not set)"],
      ["VOICE_PROVIDER", config.voiceProvider || "(same as chat)"],
      ["VOICE_MODEL", config.voiceModel || "(provider default)"],
      ["VOICE_API_BASE", config.voiceApiBase || "(provider default)"],
      ["SARVAM_API_KEY", config.sarvamApiKey ? "(set)" : "(not set)"],
      ["STT_PROVIDER", config.sttProvider],
      ["STT_MODEL", config.sttModel],
      ["SARVAM_STT", `${config.sarvamSttModel} · ${config.sarvamSttMode}`],
      ["SARVAM_KEYTERMS", config.sarvamKeyterms.length ? config.sarvamKeyterms.join(", ") : "(none)"],
      ["TTS_PROVIDER", config.ttsProvider],
      ["TTS_MODEL", config.ttsModel],
      ["SARVAM_TTS", `${config.sarvamTtsModel} · ${config.sarvamTtsLanguage}`],
      ["TTS_VOICE", config.ttsVoice || "(provider default)"],
      ["TTS_RATE", config.ttsRate],
      ["SPEAK", config.speak ? "on" : "off"],
      ["MIC_DEVICE", config.micDevice || "(auto)"],
      ["VOICE_VAD", config.voiceVad ? "on" : "off"],
      ["VOICE_SILENCE_MS", config.voiceSilenceMs],
      ["VOICE_NOISE_DB", config.voiceNoiseDb],
      ["VOICE_BARGE_IN", config.voiceBargeIn ? "on" : "off"],
      ["VOICE_HFP_ROUTING", config.voiceHfpRouting ? "on" : "off"],
      ["VOICE_ADDRESS", config.voiceAddress || "(none)"],
      ["VOICE_SPEAK_ITEMS", config.voiceSpeakItems],
      ["VOICE_SPEAK_SENTENCES", config.voiceSpeakSentences],
      ["VOICE_FULL_READ", config.voiceFullRead ? "on" : "off"],
      ["TIMEZONE", config.timeZone || "(system local)"],
      ["QUIET_HOURS", config.quietHours || "(off)"],
      ["DESKTOP_NOTIFICATIONS", config.desktopNotifications ? "on" : "off"],
      ["NTFY_URL", config.ntfyUrl ? "(set)" : "(not set)"],
      ["DISCORD_WEBHOOK_URL", config.discordWebhookUrl ? "(set)" : "(not set)"],
      ["PUSHOVER", config.pushoverToken && config.pushoverUser ? "(set)" : "(not set)"],
      ["MEMORY_CONSOLIDATION", config.memoryConsolidation ? "on" : "off"],
      ["MEMORY_RECALL_CHARS", config.memoryRecallChars],
      ["EMBEDDINGS", config.embeddings ? "on (when configured)" : "off"],
      ["EMBED_MODEL", config.embedModel],
      ["CLOUDFLARE_ACCOUNT_ID", config.cloudflareAccountId || "(not set)"],
      ["CLOUDFLARE_API_TOKEN", config.cloudflareApiToken ? "(set)" : "(not set)"],
      ["EMBED_TIMEOUT_MS", config.embedTimeoutMs],
      ["EMBED_INDEX_TIMEOUT_MS", config.embedIndexTimeoutMs],
      ["MEMORY_CONSOLIDATION_HOUR", config.memoryConsolidationHour],
      ["MEMORY_BATCH_SIZE", config.memoryBatchSize],
      ["MEMORY_CHUNK_CHARS", config.memoryChunkChars],
      ["MEMORY_TIMEOUT", config.memoryTimeout],
      ["PROJECT_AUTO_DETECT", config.projectAutoDetect ? "on" : "off"],
      ["PROJECT_WORK_CAPTURE", config.projectWorkCapture ? "on" : "off"],
      ["PROJECT_AUTO_MAINTENANCE", config.projectAutoMaintenance ? "on" : "off"],
      ["PROJECT_INLINE_CONSOLIDATION", config.projectInlineConsolidation ? "on" : "off"],
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

  if (config.apiBase && !config.apiKey && !provider.keyless) console.log(c.yellow("  note: no API_KEY set - trying without credentials"));
  let session;
  try {
    session = await createSession({ config });
  } catch (err) {
    console.error(c.red(`  could not start the model: ${err.message}`));
    process.exit(1);
  }
  const { client, tool, models, model, picked } = session;

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
  if (config.model && !picked.matched) {
    console.log(c.yellow(`  unknown model "${config.model}", using ${picked.id} instead`));
  }

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

  // Projects: which one is active shapes the system prompt from here on. An
  // explicit choice always wins; otherwise the working directory can identify
  // the project without changing the saved active project.
  let projects = new ProjectStore(PROJECTS_FILE).load();
  const pathProject = () => (projects.activeId ? null : detectProject(projects, process.cwd(), config));
  const detectedProject = pathProject();

  // Process-level, not per-Agent: every freshAgent worker must share these
  // live connections, or a routine would spawn a server for one call.
  const mcp = new McpManager({
    log: (m) => term.line(c.dim(`  mcp: ${m}`)),
    onChange: () => agent?.refreshPrompt?.(),
    // File-backed: tier overrides outlive the process. Heuristics apply either way.
    tiers: new TierPolicy(MCP_TIERS_FILE),
  });
  const activeProject = () => projects.active;
  const projectBlock = (project = activeProject() || pathProject()) =>
    project ? [projects.promptBlock(project), projects.workBlock(project)].filter(Boolean).join("\n") : "";
  // Inline extraction costs a model call, so it is built only when asked for.
  let turnConsolidator = null;
  const onTurnComplete = (info) => maintainTurn({ ...info, config, projectsFile: PROJECTS_FILE, consolidator: turnConsolidator,
    log: (message) => term.line(c.dim(`  ${message}`)) });
  if (detectedProject) term.line(c.dim(`  project ~ ${detectedProject.name} (from cwd)`));

  // The REPL is one session at a time, so a single slot is enough to attach
  // sub-agent progress to the turn currently streaming.
  let activeOutcome = null;
  let voiceJobs = null;
  let voiceAudio = null;
  let voiceOwner = randomUUID();
  const voiceMail = new Map();
  const detachedVoiceOwners = new Map();
  let pendingVoiceApproval = null;
  let approvalTail = Promise.resolve();
  const taskStore = () => new VoiceTaskStore({ directory: path.join(CONFIG_DIR, VOICE_TASK_DIRECTORY), limit: config.voiceTaskLimit, secrets: configuredSecrets(config) });
  const queueApproval = ask => {
    const work = approvalTail.then(ask);
    approvalTail = work.catch(() => {});
    return work;
  }; // One prompt owner across typed and voice requests, including work continuing after End voice.


  function detachVoiceOwner() {
    if (voiceJobs?.list(voiceOwner).length) detachedVoiceOwners.set(voiceOwner, {
      messages: sanitizeMessages(agent.messages), model: agent.model, projectId: agent.projectId,
    });
    voiceOwner = randomUUID();
  }
  function flushVoiceMail() {
    for (const task of voiceMail.values()) {
      if (task.ownerId === voiceOwner && busy) continue;
      const detached = task.ownerId !== voiceOwner ? detachedVoiceOwners.get(task.ownerId) : null;
      if (task.ownerId !== voiceOwner && !detached) continue;
      const messages = detached?.messages || agent.messages;
      messages.push({ role: 'user', content: task.transcript }, { role: 'assistant', content: voiceTaskReport(task) });
      if (detached) saveSession(sessionPath(`voice-${task.ownerId}`), { ...detached, messages, savedAt: new Date().toISOString() });
      else writeSession(AUTOSAVE_NAME);
      voiceMail.delete(task.id);
      if (detached && !voiceJobs.list(task.ownerId).some(job => !VOICE_FINAL_STATES.includes(job.status))) detachedVoiceOwners.delete(task.ownerId);
    }
  }

  const agent = new Agent({
    client,
    skillsEnabled: !opts.daemon,
    tool,
    config,
    journal: turn => recordTurn(turn, { timeZone: config.timeZone }),
    project: activeProject() ? projectBlock(activeProject()) : "",
    projectId: activeProject()?.id || null,
    onTurnComplete,
    mcp,
    onSubagentEvent: event => {
      if (activeOutcome && event.type === SUBAGENT_EVENT.end) {
        activeOutcome.subagents.push({
          type: event.subagentType, description: event.description, status: event.status,
          durationMs: event.durationMs, usage: event.usage, toolsUsed: event.toolsUsed, transcript: event.transcript,
        });
      }
      if (opts.json) return;
      if (event.type === SUBAGENT_EVENT.start) {
        term.line(c.magenta(`  ⇢ ${event.subagentType}: ${event.description}`));
      } else if (event.type === SUBAGENT_EVENT.toolCall) {
        term.line(c.dim(`      ${event.call?.function?.name || 'tool'}`));
      } else if (event.type === SUBAGENT_EVENT.end) {
        const secs = (event.durationMs / 1000).toFixed(1);
        term.line(c.dim(`      ${event.status} · ${secs}s${event.transcript ? '' : ' · no transcript'}`));
      }
    },
    print: (s) => term.line(s),
    write: (s) => term.write(s),
    confirm: (toolName, detail) => {
      const signal = agent.abort?.signal;
      return queueApproval(async () => {
        if (signal?.aborted) return false;
        term.line('');
        term.line(c.yellow(`  ── ${toolName} ` + '─'.repeat(Math.max(0, 40 - toolName.length))));
        term.line(detail.split('\n').map(line => '  ' + line).join('\n'));
        const answer = (await term.ask('  allow? [y]es / [n]o / [a]lways / [q]uit > ')) ?? '';
        if (signal?.aborted) return false;
        const value = answer.trim().toLowerCase();
        if (value === 'a' || value === 'always') { agent.autoApprove = true; term.line(c.dim('  auto-approve on')); return true; }
        if (value === 'q' || value === 'quit') { await shutdown(0); return false; }
        return value === 'y' || value === 'yes';
      });
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
    if (config.composioApiKey || config.composioBrokerUrl) {
      try {
        await mcp.ensureComposio(config, new ComposioStore(COMPOSIO_FILE).load());
        agent.refreshPrompt();
      } catch (err) {
        term.line(c.red(`  connected apps: ${err.message}`));
      }
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
    detachVoiceOwner();
    agent.clear();
    agent.messages.push(...restored);
    if (data.model) agent.model = data.model;
    return restored.length;
  };

  const shutdown = async (code = 0) => {
    await channelHostRef?.stopAll();
    await voiceJobs?.close();
    flushVoiceMail();
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
      version: VERSION,
      provider: provider.name,
      tools: agent.useTools,
      autoApprove: agent.autoApprove,
      cwd: process.cwd(),
      envPath: config.envPath || config.globalEnvPath,
      count: models.length,
      project: activeProject() ? `${activeProject().name}${activeProject().path ? "  " + activeProject().path : ""}` : null,
    });
    if (config.apiBase) console.log(c.dim(`  endpoint: ${config.apiBase}\n`));
    term.line(c.dim(startupProfile.format()));
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
  const jobNotices = [];
  const showJobNotices = () => {
    for (const text of jobNotices.splice(0)) term.notify(c.dim(`  ${text}`));
  };
  agent.state.onJobEvent = event => {
    if (opts.json || opts.prompt !== null || opts.daemon) return;
    jobNotices.push(jobEventText(event));
    if (!busy) showJobNotices();
  };
  // Job controls remain usable during model/tool work and do not become chat input.
  term.interceptLine = line => {
    const approvalAnswer = String(line).trim().toLowerCase();
    if (pendingVoiceApproval && ['y', 'yes', 'n', 'no', 'a', 'always', 'q', 'quit'].includes(approvalAnswer)) {
      pendingVoiceApproval.resolve(approvalAnswer); return true;
    }
    if (busy && String(line).trim().split(/\s+/, 1)[0] === VOICE_TASK_COMMAND) {
      try { term.notify(voiceTaskCommand(line, taskStore())); }
      catch (error) { term.notify(`Voice task: ${error.message}`); }
      return true;
    }
    if (!busy || !isJobCommand(line)) return false;
    void runJobCommand(line, { state: agent.state, cwd: agent.cwd, config: agent.config })
      .then(result => term.notify(result)).catch(err => term.notify(`Error: ${err.message}`));
    return true;
  };
  let voiceActive = false;
  let cancelHook = null;
  if (!opts.daemon) process.on("SIGINT", () => {
    if (busy || voiceActive) {
      if (voiceActive) voiceJobs?.cancelOwner(voiceOwner);
      agent.cancel();
      const hook = cancelHook;
      cancelHook = null;
      term.cancelPending();
      stopPlayback();
      hook?.();
      term.line(c.dim("\n  cancelling..."));
      return;
    }
    stopPlayback();
    shutdown(0);
  });

  const promptLabel = () => {
    const count = runningJobCount(agent.state);
    return `${c.magenta(config.agentName)}${count ? c.dim(` [${count} running | /jobs]`) : ''} ${c.dim("›")} `;
  };

  const runTurn = async (text, observer = null) => {
    busy = true;
    const started = Date.now();
    const outcome = { text: "", thinking: "", toolCalls: [], subagents: [], error: null };
    activeOutcome = outcome;
    const show = !opts.json && (!observer || config.voiceVerbose);
    let spin = null;
    let renderer = null;
    let spoke = false;

    try {
      const reply = await agent.send(text, {
        onMessageStart: () => {
          if (show && !spoke && !opts.prompt) spin = spinner("thinking");
          if (!plain) {
            renderer?.finish();
            renderer = new LiveRenderer({ write: (s) => term.write(s) });
          }
        },
        onDelta: (d) => {
          if (!observer) outcome.text += d;
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
          observer?.onToolCall(call);
          let parsed = call.function.arguments;
          try {
            parsed = JSON.parse(call.function.arguments);
          } catch {}
          parsed = displayArgs(call.function.name, parsed);
          outcome.toolCalls.push({ ref: call, name: call.function.name, args: parsed });
          if (!show) return;
          term.line(c.cyan(`  → ${call.function.name}(${short(parsed, 140)})`));
        },
        onToolResult: (call, result, verdict) => {
          observer?.onToolResult(call, result, verdict);
          const entry = outcome.toolCalls.find((e) => e.ref === call);
          if (entry) entry.result = result;
          if (!show) return;
          term.line(c.dim(preview(clip(result, 4000, "result"), 8).replace(/^/gm, "    ")));
        },
        onUsage: () => {},
      });
      // The agent's returned final message excludes intermediate tool preambles.
      if (observer && typeof reply === 'string') outcome.text = reply;
      if (agent.cancelled()) outcome.error = 'cancelled';
      if (spoke && show) {
        const secs = ((Date.now() - started) / 1000).toFixed(1);
        const u = agent.turnUsage;
        const use = u.total_tokens > 0 ? ` · ${fmtTokens(u.prompt_tokens)} in / ${fmtTokens(u.completion_tokens)} out` : "";
        const replyModel = agent.replyModel || agent.model;
        const toolModel = agent.toolLoopUsed && agent.tool ? agent.tool.model : null;
        const label = toolModel && toolModel !== replyModel ? `${toolModel} \u25b8 ${replyModel}` : replyModel;
        term.line(c.dim(`  · ${secs}s · ${label}${use}`));
      }
    } catch (err) {
      spin?.stop();
      renderer?.finish();
      renderer = null;
      if (err.name === "AbortError") {
        if (show) term.line(c.dim("  (cancelled)"));
        outcome.error = "cancelled";
      } else if (!observer && provider.name === 'copilot' && (err.status === 401 || err.status === 403)) {
        try {
          await client.ensureToken(true);
        } catch {}
        if (show) term.line(c.yellow("  token refreshed - send that again."));
        outcome.error = "unauthorized (token refreshed, resend)";
      } else {
        outcome.error = `${err.status ? `${err.status}: ` : ''}${err.message}`;
        if (show) term.line(c.red("  error: " + outcome.error));
      }
    } finally {
      spin?.stop();
      renderer?.finish();
      renderer = null;
      activeOutcome = null;
      busy = false;
      flushVoiceMail();
      showJobNotices();
    }
    return outcome;
  };

  // Language the last transcription reported, so a reply is spoken in the
  // language the user actually used rather than a fixed one.
  let speechLanguage = "";
  let speechConfidence = null;
  let voiceMicrophone = null;
  const selectedMicrophone = () => voiceMicrophone ? voiceMicrophone.get() : detectMic(config.micDevice);

  const speechOpts = () => ({
    address: config.voiceAddress,
    maxItems: config.voiceSpeakItems,
    maxSentences: config.voiceSpeakSentences,
    maxChars: config.voiceSpeakMaxChars,
    fullRead: config.voiceFullRead,
    noteTemplate: config.voiceSummaryNote,
  });

  const synthesizeSpeech = async (clean, detected = speechLanguage) => {
    const provider = resolveTtsProvider(config);
    const edge = () => synthesizeEdge({ voice: resolveTtsVoice(config, 'edge'), rate: config.ttsRate, text: clean });
    if (provider === "groq" && !config.groqApiKey) {
      term.line(c.dim("  (tts: set GROQ_API_KEY in .env, or TTS_PROVIDER=edge)"));
      return null;
    }
    if (provider === "sarvam") {
      if (!config.sarvamApiKey) {
        term.line(c.dim("  (tts: SARVAM_API_KEY missing; using Edge)"));
        return edge();
      }
      // The reply's script decides the voice; the transcript language is only a
      // hint, because Hinglish auto-detect is not stable between runs.
      const languageCode = chooseSarvamLanguage({
        text: clean,
        detected,
        fallback: config.sarvamTtsLanguage,
      });
      try {
        return await synthesizeSarvam({
          apiKey: config.sarvamApiKey,
          model: config.sarvamTtsModel,
          speaker: resolveSarvamSpeaker(config, languageCode),
          languageCode,
          text: clean,
        });
      } catch (error) {
        term.line(c.dim(`  (tts: ${error.message}; using Edge)`));
        return edge();
      }
    }
    return provider === "groq"
      ? synthesizeGroq({
          apiKey: config.groqApiKey,
          model: config.ttsModel,
          voice: resolveTtsVoice(config, "groq"),
          text: clean,
        })
      : edge();
  };

  /** Speak a reply. Long lists/paragraphs are summarized unless `full`. */
  const speakText = async (text, { full = false } = {}) => {
    const clean = full ? stripForSpeech(text) : summarizeForSpeech(text, speechOpts());
    if (!clean) return;
    try {
      const audio = await synthesizeSpeech(clean);
      if (audio) await playMp3(audio);
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
    if (opts.maxTokens) { config.maxTokens = opts.maxTokens; config.maxTokensExplicit = true; }
    agent.config = config;
    const missing = sttKeysMissing(config);
    if (missing) {
      term.line(c.red(`  voice needs ${missing} in .env for speech-to-text (STT_PROVIDER=${resolveSttProvider(config)}).`));
      term.line(c.dim("  sarvam: SARVAM_API_KEY + STT_PROVIDER=sarvam (best for Hinglish)"));
      term.line(c.dim("  groq:   GROQ_API_KEY   + STT_PROVIDER=groq   (free at console.groq.com)"));
      term.line(c.dim("  add it, then run /voice again - no restart needed."));
      return false;
    }
    return true;
  };

  const transcribeWav = async (wav) => {
    term.write(c.dim("  transcribing…"));
    try {
      const result = await transcribeAudio({ config, wavPath: wav });
      term.write("\r\x1b[K");
      if (result.languageCode) speechLanguage = result.languageCode;
      speechConfidence = result.confidence ?? null;
      return result.text;
    } catch (err) {
      term.write("\r\x1b[K");
      term.line(c.red(`  stt: ${err.message}`));
      return "";
    }
  };

  /**
   * Capture one turn. Hands-free stops on a pause (ffmpeg silencedetect);
   * otherwise Enter sends. Enter always force-sends, Ctrl+C cancels.
   * Returns the transcript, "" (nothing usable), or null (cancelled).
   */
  const CAPTURE_PAUSED = Symbol('voice permission or interruption');
  const CAPTURE_RETRY_MS = 400; // Milliseconds: let the audio device release before retrying a failed startup.
  const CAPTURE_POLL_MS = 120; // Milliseconds: existing VAD deadline/cancel responsiveness.
  const CAPTURE_TICK_MS = 250; // Milliseconds: terminal meter refresh without excessive output.
  const captureTurn = async ({ handsFree = false, session } = {}) => {
    const wav = tmpVoiceFile('wav');
    let input, reason = null, enterPending = false, finished, speechTurn, usable = false;
    if (session) session.captureSpeechTurn = undefined;
    const stopped = new Promise(resolve => { finished = resolve; });
    const capture = { stopped, pause() { reason = 'approval'; if (enterPending) term.cancelPending(); } };
    if (session) session.capture = capture;
    let tick, poll;
    try {
      if (session?.approvals) return CAPTURE_PAUSED;
      for (let attempt = 0; attempt < 2 && !input; attempt++) {
        try {
          const mic = await selectedMicrophone();
          if (!mic) { term.line(c.red('  no microphone found (set MIC_DEVICE in .env).')); return ''; }
          const candidate = openVoiceInput({ device: mic.name, outFile: wav, noiseDb: config.voiceNoiseDb,
            silenceSec: config.voiceSilenceMs / 1000 });
          input = candidate;
          await candidate.ready;
        } catch (error) {
          voiceMicrophone?.invalidate();
          await input?.stop().catch(() => {}); input = null;
          if (attempt === 0) { await new Promise(resolve => setTimeout(resolve, CAPTURE_RETRY_MS)); continue; }
          term.line(c.red(`  mic: ${error.message}`)); return '';
        }
      }
      if (reason === 'approval' || session?.approvals) return CAPTURE_PAUSED;
      const started = Date.now(), detector = createTurnDetector();
      input.onEvent = event => {
        if (reason !== null) return;
        if (session?.playingAt && (!config.voiceBargeIn || Date.now() - session.playingAt < VOICE_BARGE_GUARD_MS)) return;
        const action = detector.feed(event);
        if (action === 'speech' && session && speechTurn === undefined) speechTurn = session.speech.interrupt();
        if (action === 'end') reason = 'silence';
      };
      const hint = handsFree ? 'pause to send' : 'Enter to send';
      tick = setInterval(() => term.write(`\r  listening… ${Math.floor((Date.now() - started) / 1000)}s  (${hint}, Ctrl+C to stop work)\x1b[K`), CAPTURE_TICK_MS);
      cancelHook = () => {
        reason = voiceJobs?.list(voiceOwner).some(job => !VOICE_FINAL_STATES.includes(job.status) || job.resourcesHeld) ? 'interrupted' : 'cancel';
      };
      await new Promise(resolve => {
        poll = setInterval(() => {
          if (reason !== null) resolve();
          else if (handsFree && Date.now() - started > config.voiceMaxUtteranceMs) { reason = 'max'; resolve(); }
        }, CAPTURE_POLL_MS);
        enterPending = true;
        term.ask('').then(line => { if (reason === null) reason = line === null ? 'cancel' : 'enter'; resolve(); });
      });
      enterPending = false; term.cancelPending();
      if (reason === 'approval' || reason === 'interrupted') return CAPTURE_PAUSED;
      if (reason === 'cancel') return null;
      const ok = await input.stop(); input = null;
      if (!ok) { term.line(c.red('  recording failed (nothing captured).')); return ''; }
      const transcript = await transcribeWav(wav);
      if (session && transcript?.trim()) {
        speechTurn ??= session.speech.interrupt();
        session.captureSpeechTurn = speechTurn; usable = true;
      }
      return transcript;
    } finally {
      if (session && !usable && speechTurn !== undefined) {
        if (reason === 'approval') session.pendingFalseTurn = speechTurn;
        else if (reason !== 'cancel') await session.speech.falseInterruption(speechTurn);
      }
      clearInterval(tick); clearInterval(poll); cancelHook = null;
      await input?.stop().catch(() => {});
      if (session?.capture === capture) session.capture = null;
      fs.rmSync(wav, { force: true }); finished();
    }
  };

  const voiceConfirm = (toolName, detail, entry, signal) => {
    return queueApproval(async () => {
      if (signal.aborted) return false;
      const audio = voiceAudio;
      if (audio) { audio.approvals++; audio.capture?.pause(); await audio.capture?.stopped; audio.speech.resume(); }
      let answer;
      try {
        const line = `Permission chahiye · ${toolName}`;
        term.line(c.yellow(`  [voice task ${entry.id}] ${line}`));
        if (audio && !audio.controller.signal.aborted) await audio.speech.offer({ jobId: entry.id, kind: 'receipt',
          signal: AbortSignal.any([signal, audio.controller.signal]),
          prepare: () => synthesizeSpeech(line), line: { text: line } });
        if (signal.aborted) return false;
        term.line(detail);
        answer = await new Promise(resolve => {
          const abort = () => resolve('no');
          pendingVoiceApproval = { id: entry.id, resolve };
          signal.addEventListener('abort', abort, { once: true });
          entry.clearApproval = () => signal.removeEventListener('abort', abort);
          if (signal.aborted) resolve('no');
          else term.line('  allow? [y]es / [n]o / [a]lways / [q]uit > ');
        });
        if (signal.aborted) return false;
        if (answer === 'a' || answer === 'always') { agent.autoApprove = true; return true; }
        if (answer === 'q' || answer === 'quit') { voiceJobs.cancel(entry.id, { ownerId: entry.ownerId }); return false; }
        return answer === 'y' || answer === 'yes';
      } finally {
        entry.clearApproval?.(); delete entry.clearApproval;
        if (pendingVoiceApproval?.id === entry.id) pendingVoiceApproval = null;
        if (audio) {
          audio.approvals--;
          if (!audio.approvals && audio.pendingFalseTurn !== undefined) {
            const turn = audio.pendingFalseTurn; delete audio.pendingFalseTurn;
            await audio.speech.falseInterruption(turn);
          }
        }
      }
    });
  };

  const voiceLoop = async () => {
    if (!voiceReady()) return;
    let brain;
    try { brain = createVoiceBrain(config, { client: agent.client, model: agent.model }); }
    catch (error) { term.line(c.red(`  ${error.message}`)); return; }
    const session = { brain, controller: new AbortController(), approvals: 0, capture: null, playingAt: 0 };
    voiceAudio = session;
    const owns = () => voiceAudio === session && !session.controller.signal.aborted;
    session.speech = new VoiceSpeechQueue({ gapMs: config.voiceSpeechGapMs, historyLimit: config.voiceTaskLimit,
      play: (audio, { signal }) => playMp3(audio, { signal, rejectOnFailure: true }), stop: stopPlayback,
      onStart: () => { session.playingAt = Date.now(); }, onFinish: () => { session.playingAt = 0; },
      onError: error => term.line(c.red(`  speech: ${error.message}`)),
    });
    voiceJobs ||= new VoiceJobs({ store: taskStore(), concurrency: config.voiceMaxParallelJobs,
      run: (entry, options) => runVoiceWorker(entry, options, { brain: entry.context.audioSession.brain,
        acquire: (...args) => voiceJobs.acquire(...args), autoApprove: () => agent.autoApprove,
        confirm: voiceConfirm,
      }),
      onUpdate: record => {
        if (config.voiceVerbose || ['queued', 'waiting_for_resource', 'waiting_for_approval'].includes(record.status)) term.notify(c.dim(`  [voice task ${record.id}] ${record.status}${record.waitingFor ? ' · ' + record.waitingFor : ''}`));
      },
      onComplete: (task, result) => {
        voiceMail.set(task.id, task); flushVoiceMail();
        term.notify(config.voiceVerbose ? renderVoiceTask(task) : `[voice task ${task.id}] ${task.status} · ${task.label}\n${voiceTaskReport(task)}`);
        const context = voiceJobs.entries.get(task.id)?.context;
        const audio = context?.audioSession;
        if (audio && voiceAudio === audio && !audio.controller.signal.aborted) {
          const report = createVoiceReportSpeech({ jobId: task.id, label: task.label, text: voiceTaskReport(task),
            maxChars: config.voiceSpeakMaxChars, signal: audio.controller.signal, turn: context.speech?.turn,
            synthesize: text => synthesizeSpeech(text, task.language) });
          if (report && !(task.status === 'done' && result.outcome.speechHandled)) void audio.speech.offer(report);
          audio.speech.finishTurn(context.speech?.turn);
        }
      },
      onError: error => term.notify(c.red(`  voice job: ${error.message}`)),
    });
    const acks = createAcknowledgements({ synthesize: synthesizeSpeech });
    const narrate = voiceIO.narrate || createVoiceNarrator({ client: brain?.client || agent.client, model: brain?.model || agent.model, secrets: configuredSecrets(config) });
    voiceMicrophone = createVoiceMicrophone({ detect: detectMic, preferred: config.micDevice });
    voiceActive = true;
    term.line(c.dim(config.voiceVad ? '  voice mode — just speak; pause to send. Jobs run together. Say exit to leave.' : '  voice mode — speak, press Enter to send. Jobs run together. Say exit to leave.'));
    if (brain) term.line(c.dim(`  voice answers use ${brain.label} · ${brain.model}`));
    let routing;
    try {
      let cancelled = false;
      cancelHook = () => { cancelled = true; };
      await acks.prewarm(); cancelHook = null;
      if (cancelled) return;
      if (config.voiceBargeIn && config.voiceHfpRouting) {
        const mic = await selectedMicrophone();
        if (mic) routing = useHandsFreePlayback(mic.name);
      }
      while (owns()) {
        if (session.approvals) { await new Promise(resolve => setTimeout(resolve, VOICE_PROGRESS_POLL_MS)); continue; }
        const said = await captureTurn({ handsFree: config.voiceVad, session });
        if (said === CAPTURE_PAUSED) { session.speech.resume(); continue; }
        if (said === null) { term.line(c.dim('  leaving voice mode.')); break; }
        const clean = String(said || '').trim();
        if (!clean) { session.speech.resume(); continue; }
        if (/^(exit|quit|end voice|goodbye|bye)[.!?]?$/i.test(clean)) { term.line(c.dim('  leaving voice mode.')); break; }
        term.line(`${c.magenta(config.username)} ${c.dim('›')} ${clean}`);
        const language = speechLanguage, turn = session.captureSpeechTurn;
        session.speech.acceptTurn(turn);
        try {
          const context = { ...captureVoiceContext(agent), audioSession: session,
            speech: { queue: session.speech, turn, signal: session.controller.signal } };
          const record = await voiceJobs.submit({ ownerId: voiceOwner, transcript: clean, language, confidence: speechConfidence, context,
            speech: { minIntervalMs: config.voiceJobSpeakMinIntervalMs, gapMs: 0, waitUpdateMs: config.voiceJobWaitUpdateMs },
            speak: (event, { signal, beginPlayback }) => {
              const line = { text: '' };
              return session.speech.offer({ jobId: event.taskId, kind: 'progress', turn, line,
                signal: AbortSignal.any([signal, session.controller.signal]),
                prepare: async queueSignal => {
                  line.text = await narrate(event, { signal: queueSignal });
                  return line.text ? synthesizeSpeech(line.text, language) : null;
                }, beginPlayback: () => {
                  if (!owns() || !beginPlayback(line.text)) return false;
                  term.line(c.dim(`  ${line.text}`)); return true;
                } });
            },
          });
          const ack = acks.next(language);
          if (ack) { term.line(c.dim(`  ${ack.text}`)); void session.speech.offer({ jobId: record.id, kind: 'receipt', turn, prepare: async () => ack.audio, signal: session.controller.signal }); }
        } catch (error) { session.speech.finishTurn(turn); term.line(c.red(`  Voice request: ${error.message}`)); }
        session.speech.resume();
      }
    } finally {
      session.controller.abort(); await session.speech.close();
      routing?.restore(); voiceActive = false; cancelHook = null; voiceMicrophone = null;
      if (voiceAudio === session) voiceAudio = null;
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
          ...(outcome.subagents.length ? { subagents: outcome.subagents } : {}),
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
  const channelStore = new ChannelStore(CHANNELS_FILE, { env: environmentForConfig(config) }).load();
  const telegramSettings = channelStore.get(TELEGRAM_CHANNEL_ID);
  const bot = new TelegramBot({
    token: telegramSettings.token,
    allowedChatIds: parseChatIds(telegramSettings.allowedChatIds),
    ownerChatId: telegramSettings.ownerChatId,
  });

  const ownerChat = () => {
    if (!channelStore.doctor().ok) return null;
    const settings = channelStore.get(TELEGRAM_CHANNEL_ID);
    if (settings.ownerChatId) return settings.ownerChatId;
    const allowed = parseChatIds(settings.allowedChatIds);
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
  const deliver = (text, meta = {}) => deliverTemplateResult(text, meta, {
    log: value => daemonRef ? daemonRef.log(value) : term.line(value),
    deliver: value => opts.daemon ? notifications.queueMessage(value) : notifications.send(value),
  });

  // Set once the daemon exists, so routine/brief work can ask for approval in
  // Telegram instead of being silently denied.
  let daemonRef = null;

  const freshAgent = (purpose) =>
    new Agent({
      client,
      skillsEnabled: false,
      tool,
      // Routines, briefings and alerts run unattended: no nested agents.
      config: { ...config, subagentsEnabled: false },
      // Background work never claims a project from the daemon's directory.
      autoProject: false,
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
                : Promise.resolve(config.autoApprove === true),
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

  // The interactive turn hook was wired before this existed; point it at the
  // extractor now, and only when the opt-in flag is on.
  if (config.projectInlineConsolidation) {
    turnConsolidator = new MemoryConsolidator({ config, extract: runPrompt, log: m => term.line(c.dim(`  ${m}`)) });
  }

  if (opts.brief) {
    const text = String((await runPrompt(BRIEFING_PROMPT)) || "").trim() || "(nothing to report)";
    const channel = await notifications.send(`Briefing\n\n${text}`);
    if (channel !== 'terminal') term.line(c.dim(`  briefing ${channel === 'queued' ? 'queued for delivery' : `submitted via ${channel}`}`));
    process.exit(0);
  }

  if (opts.daemon) {
    const ownership = new SchedulerOwnership(path.join(path.dirname(STATE_FILE), SCHEDULER_LOCK_FILENAME), { host: 'cli' });
    await ownership.acquire({ takeover: opts.takeover === true });
    const ownershipTimer = setInterval(() => { if (!ownership.heartbeat()) daemonRef?.stop(); }, SCHEDULER_TICK_MS);
    ownershipTimer.unref();
    banner({
      agentName: `${config.agentName} \u25d7 daemon`,
      username: config.username,
      model,
      version: VERSION,
      provider: provider.name,
      tools: agent.useTools,
      autoApprove: agent.autoApprove,
      cwd: process.cwd(),
      envPath: config.envPath || config.globalEnvPath,
      count: 0,
      hint: false,
    });
    const daemon = new Daemon({
      store,
      channelStore,
      bot,
      config,
      client,
      model,
      tool,
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
    try { await daemon.run(); }
    finally { clearInterval(ownershipTimer); ownership.release(); }
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
    if (input.split(/\s+/, 1)[0] === VOICE_TASK_COMMAND) {
      try { term.line(voiceTaskCommand(input, taskStore())); }
      catch (error) { term.line(`Voice task: ${error.message}`); }
      continue;
    }
    if (isJobCommand(input)) {
      try { term.line(await runJobCommand(input, { state: agent.state, cwd: agent.cwd, config: agent.config })); }
      catch (err) { term.line(`Error: ${err.message}`); }
      continue;
    }

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

      case "/commands":
        term.line("");
        term.line(helpText({ agentName: config.agentName, groupsOnly: true }));
        term.line(c.dim("  tab-completion works on every command and subcommand above."));
        term.line("");
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
        term.line(
          `  ${"VOICE_VAD".padEnd(16)} ${config.voiceVad ? "on" : "off"}${c.dim(
            `  silence ${config.voiceSilenceMs}ms @ ${config.voiceNoiseDb}dB`
          )}`
        );
        term.line(
          `  ${"VOICE_BARGE_IN".padEnd(16)} ${config.voiceBargeIn ? "on" : "off"}${c.dim(
            `  threshold ${config.voiceBargeDb}dB`
          )}`
        );
        term.line(
          `  ${"VOICE_HFP_ROUTING".padEnd(16)} ${config.voiceHfpRouting ? "on" : "off"}${c.dim(
            "  keep speech audible with the mic open (Bluetooth)"
          )}`
        );
        term.line(
          `  ${"VOICE_SUMMARY".padEnd(16)} ${config.voiceFullRead ? "full read" : `${config.voiceSpeakItems} items / ${config.voiceSpeakSentences} sentences`}${c.dim(
            `  address: ${config.voiceAddress || "(none)"}`
          )}`
        );
        term.line(c.dim(`  project env: ${config.envPath || "(no .env found)"}`));
        term.line(c.dim(`  global env:  ${config.globalEnvPath || "(none)"}`));
        term.line("");
        break;
      }

      case "/reload": {
        reloadSkills();
        config = loadConfig();
        if (opts.model) config.model = opts.model;
        if (opts.maxTokens) { config.maxTokens = opts.maxTokens; config.maxTokensExplicit = true; }
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

      case "/skills": {
        term.line("");
        term.line(skillsListText());
        term.line("");
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
        detachVoiceOwner();
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
          said = await captureTurn({ handsFree: config.voiceVad });
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
        await speakText(arg, { full: true });
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

      case "/browser": {
        const [action = 'list', asked] = arg.split(/\s+/).filter(Boolean);
        const store = new BrowserPluginStore().load();
        if (action === 'list') {
          const overview = await browserPluginOverview(store, mcp);
          term.line('');
          for (const mode of ['isolated', 'local']) {
            const plugin = overview[mode];
            term.line(`  ${plugin.enabled ? 'on ' : 'off'}  ${plugin.name}  ${plugin.ready ? 'ready' : plugin.reason}`);
          }
          term.line(c.dim('  Enable with /browser enable isolated or /browser enable local.'));
          term.line('');
        } else if (action === 'enable' || action === 'disable') {
          const mode = asked === 'playwright' ? 'isolated' : asked === 'chrome' ? 'local' : asked;
          if (!['isolated', 'local'].includes(mode)) { term.line(c.red('  usage: /browser enable|disable isolated|local')); break; }
          const enabled = action === 'enable';
          store.setEnabled(mode, enabled);
          if (mode === 'local') {
            const configured = new McpStore(MCP_FILE).load();
            if (configured.find(CHROME_MCP_ID)) configured.setEnabled(CHROME_MCP_ID, enabled);
            if (!enabled) await mcp.disconnect(CHROME_MCP_ID).catch(() => {});
          }
          term.line(c.dim(`  ${mode === 'local' ? 'Chrome local' : 'Playwright Browser'} ${enabled ? 'enabled' : 'disabled'}.`));
          if (enabled && mode === 'local') term.line(c.dim('  Configure and start the Chrome connection in desktop Plugins → By Ankita.'));
        } else term.line(c.red(`  ${unknownActionMessage("/browser", action)}`));
        break;
      }

      case "/composio": {
        const [action = "status", service, ...rest] = arg.split(/\s+/).filter(Boolean);
        if (action !== "status" && !COMPOSIO_ACTIONS.includes(action)) {
          term.line(c.red(`  ${unknownActionMessage("/composio", action)}`));
          break;
        }
        const options = { action, service };
        if (action === "search") options.query = [service, ...rest].filter(Boolean).join(" ");
        if (action === "connect") options.alias = rest.length ? rest.join(" ") : undefined;
        if (action === "disconnect") options.accountId = rest[0];
        // allow/always/deny take either a tool slug (GMAIL_SEND_EMAIL) or a
        // service (gmail); a slug with uppercase or an underscore is a tool.
        if (action === "allow" || action === "always" || action === "deny") {
          if (service && TOOL_SLUG_PATTERN.test(service)) options.tool = service;
        }
        try {
          const result = await composioTool.run(options, { config, mcp });
          term.line("");
          term.line(String(result).replace(/^/gm, "  "));
          term.line("");
          agent.refreshPrompt();
        } catch (err) {
          term.line(c.red(`  connected apps: ${err.message}`));
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
              hidden: record.hidden === true,
              allowedTools: record.allowedTools,
              terminateTree: record.terminateTree,
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

        term.line(c.red(`  ${unknownActionMessage("/mcp", sub)}`));
        break;
      }

      case "/projects": {
        projects = new ProjectStore(PROJECTS_FILE).load();
        term.line("");
        if (!projects.projects.length) {
          term.line(c.dim("  no projects yet - ask me to add one, e.g. \"add zumba to my projects\""));
        } else {
          const detected = pathProject();
          for (const p of projects.projects) {
            term.line(`  ${describeProject(p, projects.activeId)}${detected?.id === p.id ? c.dim("  (from cwd)") : ""}`);
          }
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
        if (arg.trim().toLowerCase() === "undo") {
          const target = projects.active || pathProject();
          const removed = target ? projects.removeAutoEntries(target.id, { sessionId: agent.sessionId }) : null;
          if (!removed) {
            term.line(c.red("  no active or detected project to undo"));
            break;
          }
          if (agent.projectSource !== 'path') {
            const refreshed = projects.find(target.id);
            agent.project = refreshed ? [projects.promptBlock(refreshed), projects.workBlock(refreshed)].filter(Boolean).join("\n") : "";
          }
          agent.rebase();
          term.line(c.dim(`  undid ${removed.total} automatic entr${removed.total === 1 ? "y" : "ies"} on ${removed.project.name}` +
            `  (work log ${removed.worklog}, todos ${removed.todos}, reopened ${removed.reopened}, notes ${removed.notes}, decisions ${removed.decisions})`));
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

      case "/channels": {
        try {
          channelHostRef ||= createCliChannelHost({ store, channelStore, config, client, model, tool, mcp, runPrompt, deliver, log: text => term.line(c.dim(`  ${text}`)) });
          term.line(await runChannelCommand(arg, { host: channelHostRef }));
        } catch (error) { term.line(c.red(`  ${error.message}`)); }
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

      default: {
        const near = closestCommand(cmd);
        term.line(c.red(`  unknown command "${cmd}"${near ? ` - did you mean ${near}?` : ` - ${FALLBACK_HINT}`}`));
      }
    }
  }

  await shutdown(0);
}
