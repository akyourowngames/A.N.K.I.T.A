import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { DEFAULT_SUMMARY_NOTE } from "./voice.mjs";

export const CONFIG_DIR = process.env.CONFIG_DIR || path.join(os.homedir(), ".copilot-chat-cli");
export const GLOBAL_ENV_FILE = path.join(CONFIG_DIR, "config.env");
export const AUTH_FILE = path.join(CONFIG_DIR, "auth.json");
export const HISTORY_FILE = path.join(CONFIG_DIR, "history");
export const SESSIONS_DIR = path.join(CONFIG_DIR, "sessions");
export const AUTOSAVE_NAME = "autosave";
export const STATE_FILE = path.join(CONFIG_DIR, "state.json");
export const PROJECTS_FILE = path.join(CONFIG_DIR, "projects.json");
export const PROFILE_FILE = path.join(CONFIG_DIR, "profile.json");
export const MEMORY_INDEX_FILE = path.join(CONFIG_DIR, "memory-index.json");
export const EMBEDDINGS_DIR = path.join(CONFIG_DIR, "embeddings");
export const JOURNAL_DIR = path.join(SESSIONS_DIR, "journal");
export const NOTIFY_QUEUE_FILE = path.join(CONFIG_DIR, "notification-queue.json");
export const MCP_FILE = path.join(CONFIG_DIR, "mcp.json");
export const COMPOSIO_FILE = path.join(CONFIG_DIR, "composio.json");
export const DAEMON_LOG = path.join(CONFIG_DIR, "daemon.log");

const DEFAULTS = {
  username: "user",
  agentName: "assistant",
  model: "",
  systemExtra: "",
  tools: true,
  autoApprove: false,
  historyMessages: 40,
  temperature: null,
  maxTokens: 4096,
  maxToolChars: 65536,
  contextWindow: 32768,
  provider: "",
  apiBase: "",
  apiKey: "",
  toolProvider: "",
  toolModel: "",
  toolApiBase: "",
  toolApiKey: "",
  inputCostPerMillion: null,
  outputCostPerMillion: null,
  webTimeout: 20,
  webMaxOutput: 8000,
  webCacheTtl: 300,
  webRetries: 1,
  webRegion: "wt-wt",
  jinaFallback: true,
  scrapeTimeout: 30,
  scrapeStealthTimeout: 30,
  scrapeMaxOutput: 8000,
  scrapeMaxPages: 20,
  scrapeRetries: 1,
  pythonBin: "",
  jinaFallback: true,
  allowPrivateHosts: false,
  pythonBin: "",
  telegramBotToken: "",
  telegramChatId: "",
  telegramAllowedChatIds: "",
  telegramVoiceReply: false,
  telegramConfirmTimeout: 300,
  daemonTick: 20,
  maxConcurrent: 4,
  watchAlertLlm: true,
  watchAlertPrompt: "",
  briefingPrompt: "",
  groqApiKey: "",
  sttModel: "whisper-large-v3-turbo",
  ttsProvider: "edge",
  ttsModel: "canopylabs/orpheus-v1-english",
  ttsVoice: "",
  ttsRate: "+0%",
  speak: false,
  micDevice: "",
  voiceVad: true,
  voiceSilenceMs: 1200,
  voiceNoiseDb: -35,
  voiceMaxUtteranceMs: 30000,
  voiceBargeIn: true,
  voiceBargeDb: -25,
  voiceHfpRouting: true,
  voiceAddress: "sir",
  voiceSpeakItems: 8,
  voiceSpeakSentences: 6,
  voiceSpeakMaxChars: 1200,
  voiceFullRead: false,
  voiceSummaryNote: DEFAULT_SUMMARY_NOTE,
};

export function parseEnv(text) {
  const out = {};
  for (const raw of String(text ?? "").split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq < 0) continue;
    const key = line.slice(0, eq).trim().replace(/^export\s+/, "");
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"') && value.length > 1) ||
      (value.startsWith("'") && value.endsWith("'") && value.length > 1)
    ) {
      value = value.slice(1, -1);
    } else {
      const hash = value.indexOf(" #");
      if (hash >= 0) value = value.slice(0, hash).trim();
    }
    out[key] = value;
  }
  return out;
}

function onOff(value, fallback) {
  if (value === undefined || value === "") return fallback;
  return !/^(0|off|false|no)$/i.test(String(value).trim());
}

/** Positive integer settings (token budgets, history depth): garbage falls back. */
function posInt(value, fallback) {
  if (value === undefined || value === null || value === "") return fallback;
  const n = Number(value);
  return Number.isInteger(n) && n > 0 ? n : fallback;
}

/** Optional per-million-token prices: negative or garbage means "unknown". */
function price(value) {
  if (value === undefined || value === null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/** Numeric setting clamped to a range; garbage falls back to the default. */
function clampNum(value, min, max, fallback) {
  if (value === undefined || value === null || value === "") return fallback;
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

/** Integer variant of clampNum. */
function clampInt(value, min, max, fallback) {
  return Math.round(clampNum(value, min, max, fallback));
}

function readVars(file) {
  try {
    return { vars: parseEnv(fs.readFileSync(file, "utf8")), path: file };
  } catch {
    return { vars: {}, path: null };
  }
}

/**
 * Loads layered configuration.
 *
 * Precedence: project .env > global config.env > process.env > defaults.
 * (File settings beat process.env because Windows already defines USERNAME
 * for the OS account, which would otherwise shadow the user's .env.)
 */
export function loadConfig(envPath = path.join(process.cwd(), ".env")) {
  const global = readVars(GLOBAL_ENV_FILE);
  const project = readVars(envPath);
  const fileVars = { ...global.vars, ...project.vars };

  const pick = (key, envKey = key) => {
    if (fileVars[key] !== undefined && fileVars[key] !== "") return fileVars[key];
    if (process.env[envKey] !== undefined && process.env[envKey] !== "") return process.env[envKey];
    return undefined;
  };

  // The alias resolves inside each layer first, so a project's HISTORY_LINES
  // still beats the global HISTORY_MESSAGES.
  const histIn = (vars) => {
    const v = vars["HISTORY_MESSAGES"] ?? vars["HISTORY_LINES"];
    return v === "" ? undefined : v;
  };
  const envHist = process.env.HISTORY_MESSAGES ?? process.env.HISTORY_LINES;
  const historyMessages = posInt(
    histIn(project.vars) ?? histIn(global.vars) ?? (envHist === "" ? undefined : envHist),
    DEFAULTS.historyMessages
  );

  return {
    envPath: project.path,
    envFiles: [global.path, project.path].filter(Boolean),
    globalEnvPath: global.path,
    username: pick("USERNAME") || DEFAULTS.username,
    agentName: pick("AGENT_NAME") || DEFAULTS.agentName,
    model: pick("MODEL") || DEFAULTS.model,
    systemExtra: pick("SYSTEM_EXTRA") || DEFAULTS.systemExtra,
    tools: onOff(pick("TOOLS"), DEFAULTS.tools),
    autoApprove: onOff(pick("AUTO_APPROVE"), DEFAULTS.autoApprove),
    historyMessages,
    historyLines: historyMessages,
    temperature: (() => {
      const v = pick("TEMPERATURE");
      if (v === undefined) return DEFAULTS.temperature;
      const n = Number(v);
      return Number.isFinite(n) ? n : DEFAULTS.temperature;
    })(),
    maxTokens: posInt(pick("MAX_TOKENS"), DEFAULTS.maxTokens),
    // Whether the output cap was chosen or just defaulted. When it is only the
    // default, no max_tokens is sent and the model/provider decides the length.
    maxTokensExplicit: pick("MAX_TOKENS") !== undefined,
    maxToolChars: posInt(pick("MAX_TOOL_CHARS"), DEFAULTS.maxToolChars),
    contextWindow: posInt(pick("CONTEXT_WINDOW"), DEFAULTS.contextWindow),
    // Whether that value was chosen or just defaulted. Providers advertise each
    // model's real window, and it is usually far above the default - but an
    // explicit CONTEXT_WINDOW is a deliberate choice and must win.
    contextWindowExplicit: pick("CONTEXT_WINDOW") !== undefined,
    provider: (pick("PROVIDER") || DEFAULTS.provider).trim().toLowerCase(),
    apiBase: pick("API_BASE") || DEFAULTS.apiBase,
    apiKey: pick("API_KEY") || DEFAULTS.apiKey,
    composioApiKey: pick("COMPOSIO_API_KEY") || "",
    composioBrokerUrl: pick("COMPOSIO_BROKER_URL") || "",
    composioBrokerToken: pick("COMPOSIO_BROKER_TOKEN") || "",
    composioApi: pick("COMPOSIO_API") || "",
    composioToolkitsApi: pick("COMPOSIO_TOOLKITS_API") || "",
    // Optional tool-loop model. The primary model (above) handles chat and the
    // first tool decision; once a turn uses a tool, this model runs the rest of
    // the loop, and the primary writes the user-facing reply. Empty = one model.
    toolProvider: (pick("TOOL_PROVIDER") || "").trim().toLowerCase(),
    toolModel: pick("TOOL_MODEL") || "",
    toolApiBase: pick("TOOL_API_BASE") || "",
    toolApiKey: pick("TOOL_API_KEY") || "",
    inputCostPerMillion: price(pick("INPUT_COST_PER_MILLION")),
    outputCostPerMillion: price(pick("OUTPUT_COST_PER_MILLION")),
    webTimeout: posInt(pick("WEB_TIMEOUT"), 20),
    webMaxOutput: posInt(pick("WEB_MAX_OUTPUT"), 8000),
    webCacheTtl: (() => {
      const v = pick("WEB_CACHE_TTL");
      if (v === undefined) return 300;
      const n = Number(v);
      return Number.isFinite(n) && n >= 0 ? n : 300;
    })(),
    webRetries: Math.max(0, Math.min(3, Math.floor(Number(pick("WEB_RETRIES") ?? 1)) || 0)),
    webRegion: String(pick("WEB_REGION") || "wt-wt").trim() || "wt-wt",
    jinaFallback: onOff(pick("JINA_FALLBACK"), true),
    scrapeTimeout: posInt(pick("SCRAPE_TIMEOUT"), 30),
    scrapeStealthTimeout: posInt(pick("SCRAPE_STEALTH_TIMEOUT"), 30),
    scrapeMaxOutput: posInt(pick("SCRAPE_MAX_OUTPUT"), 8000),
    scrapeMaxPages: Math.max(1, Math.min(50, Math.floor(Number(pick("SCRAPE_MAX_PAGES") ?? 20)) || 20)),
    scrapeRetries: Math.max(0, Math.min(3, Math.floor(Number(pick("SCRAPE_RETRIES") ?? 1)) || 0)),
    pythonBin: pick("PYTHON_BIN") || "",
    jinaFallback: onOff(pick("JINA_FALLBACK"), true),
    // Opt-in: lets web tools reach loopback/LAN, e.g. your own dev dashboard.
    allowPrivateHosts: onOff(pick("ALLOW_PRIVATE_HOSTS"), false),
    pythonBin: pick("PYTHON_BIN") || "",
    telegramBotToken: pick("TELEGRAM_BOT_TOKEN") || "",
    telegramChatId: pick("TELEGRAM_CHAT_ID") || "",
    telegramAllowedChatIds: pick("TELEGRAM_ALLOWED_CHAT_IDS") || pick("TELEGRAM_CHAT_ID") || "",
    telegramVoiceReply: onOff(pick("TELEGRAM_VOICE_REPLY"), false),
    telegramConfirmTimeout: posInt(pick("TELEGRAM_CONFIRM_TIMEOUT"), 300),
    maxConcurrent: Math.min(12, posInt(pick("MAX_CONCURRENT"), 4)),
    watchAlertLlm: onOff(pick("WATCH_ALERT_LLM"), true),
    watchAlertPrompt: pick("WATCH_ALERT_PROMPT") || "",
    daemonTick: posInt(pick("DAEMON_TICK"), 20),
    timeZone: pick("TIMEZONE") || "",
    quietHours: pick("QUIET_HOURS") || "",
    desktopNotifications: onOff(pick("DESKTOP_NOTIFICATIONS"), true),
    ntfyUrl: pick("NTFY_URL") || "",
    ntfyToken: pick("NTFY_TOKEN") || "",
    discordWebhookUrl: pick("DISCORD_WEBHOOK_URL") || "",
    pushoverToken: pick("PUSHOVER_TOKEN") || "",
    pushoverUser: pick("PUSHOVER_USER") || "",
    notifyTimeout: posInt(pick("NOTIFY_TIMEOUT"), 10),
    memoryConsolidation: onOff(pick("MEMORY_CONSOLIDATION"), true),
    embeddings: onOff(pick("EMBEDDINGS"), true),
    cloudflareAccountId: pick("CLOUDFLARE_ACCOUNT_ID") || "",
    cloudflareApiToken: pick("CLOUDFLARE_API_TOKEN") || pick("CLOUDFLARE_AUTH_TOKEN") || "",
    embedModel: pick("EMBED_MODEL") || "@cf/qwen/qwen3-embedding-0.6b",
    embedQueryInstruction: pick("EMBED_QUERY_INSTRUCTION"),
    embedTimeoutMs: Math.min(30000, posInt(pick("EMBED_TIMEOUT_MS"), 2000)),
    embedIndexTimeoutMs: Math.min(120000, posInt(pick("EMBED_INDEX_TIMEOUT_MS"), 30000)),
    memoryRecallChars: (() => {
      const n = Number(pick('MEMORY_RECALL_CHARS') ?? 1600);
      return Number.isFinite(n) && n >= 0 ? Math.min(4096, Math.floor(n)) : 1600;
    })(),
    // How long the automatic pre-turn recall may block the reply on a slow
    // embedding provider before falling back to local lexical candidates. The
    // query embedding keeps running in the background and stays cached, so an
    // explicit recall by the model is still semantic and fast. 0 disables the
    // foreground wait entirely (local candidates only).
    memoryRecallBudgetMs: (() => {
      const n = Number(pick('MEMORY_RECALL_BUDGET_MS') ?? 300);
      return Number.isFinite(n) && n >= 0 ? Math.min(10000, Math.floor(n)) : 300;
    })(),
    memoryConsolidationHour: Math.min(23, Math.max(0, Math.floor(Number(pick("MEMORY_CONSOLIDATION_HOUR") ?? 3)) || 0)),
    memoryBatchSize: Math.min(20, posInt(pick("MEMORY_BATCH_SIZE"), 4)),
    memoryChunkChars: Math.min(24000, posInt(pick("MEMORY_CHUNK_CHARS"), 12000)),
    memoryTimeout: posInt(pick("MEMORY_TIMEOUT"), 60),
    briefingPrompt: pick("BRIEFING_PROMPT") || "",
    groqApiKey: pick("GROQ_API_KEY") || DEFAULTS.groqApiKey,
    sttModel: pick("STT_MODEL") || DEFAULTS.sttModel,
    ttsProvider: (() => {
      const v = String(pick("TTS_PROVIDER") || DEFAULTS.ttsProvider).toLowerCase();
      return ["auto", "groq", "edge"].includes(v) ? v : DEFAULTS.ttsProvider;
    })(),
    ttsModel: pick("TTS_MODEL") || DEFAULTS.ttsModel,
    ttsVoice: pick("TTS_VOICE") || DEFAULTS.ttsVoice,
    ttsRate: (() => {
      const v = String(pick("TTS_RATE") || DEFAULTS.ttsRate).trim();
      return /^[-+]?\d+%$/.test(v) ? (v.startsWith("-") || v.startsWith("+") ? v : `+${v}`) : DEFAULTS.ttsRate;
    })(),
    speak: onOff(pick("SPEAK"), DEFAULTS.speak),
    micDevice: pick("MIC_DEVICE") || DEFAULTS.micDevice,
    voiceVad: onOff(pick("VOICE_VAD"), DEFAULTS.voiceVad),
    voiceSilenceMs: clampInt(pick("VOICE_SILENCE_MS"), 200, 10000, DEFAULTS.voiceSilenceMs),
    voiceNoiseDb: clampNum(pick("VOICE_NOISE_DB"), -80, 0, DEFAULTS.voiceNoiseDb),
    voiceMaxUtteranceMs: clampInt(pick("VOICE_MAX_UTTERANCE_MS"), 2000, 300000, DEFAULTS.voiceMaxUtteranceMs),
    voiceBargeIn: onOff(pick("VOICE_BARGE_IN"), DEFAULTS.voiceBargeIn),
    voiceBargeDb: clampNum(pick("VOICE_BARGE_DB"), -80, 0, DEFAULTS.voiceBargeDb),
    // Route playback to a Bluetooth headset's Hands-Free endpoint while its mic
    // is open, so barge-in doesn't silence replies (A2DP drops during capture).
    voiceHfpRouting: onOff(pick("VOICE_HFP_ROUTING"), DEFAULTS.voiceHfpRouting),
    // An empty address is useful ("off" / "none" disables the salutation).
    voiceAddress: (() => {
      const v = pick("VOICE_ADDRESS");
      if (v === undefined) return DEFAULTS.voiceAddress;
      return /^(off|none|no)$/i.test(v) ? "" : v;
    })(),
    voiceSpeakItems: clampInt(pick("VOICE_SPEAK_ITEMS"), 1, 100, DEFAULTS.voiceSpeakItems),
    voiceSpeakSentences: clampInt(pick("VOICE_SPEAK_SENTENCES"), 1, 100, DEFAULTS.voiceSpeakSentences),
    voiceSpeakMaxChars: clampInt(pick("VOICE_SPEAK_MAX_CHARS"), 100, 10000, DEFAULTS.voiceSpeakMaxChars),
    voiceFullRead: onOff(pick("VOICE_FULL_READ"), DEFAULTS.voiceFullRead),
    voiceSummaryNote: pick("VOICE_SUMMARY_NOTE") || DEFAULTS.voiceSummaryNote,
  };
}

export function ensureDirs() {
  fs.mkdirSync(CONFIG_DIR, { recursive: true });
  fs.mkdirSync(SESSIONS_DIR, { recursive: true });
}
