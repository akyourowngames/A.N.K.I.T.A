import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { DEFAULT_SUMMARY_NOTE, DEFAULT_SARVAM_STT_MODEL, DEFAULT_SARVAM_STT_MODE, DEFAULT_SARVAM_TTS_MODEL, DEFAULT_SARVAM_SPEAKER_HI, DEFAULT_SARVAM_SPEAKER_EN, DEFAULT_SARVAM_TTS_LANGUAGE, parseKeyterms } from "../channels/voice.mjs";
import { SUBAGENT_DEFAULTS, SUBAGENT_LIMITS } from "./subagents/registry.mjs";
import { HEARTBEAT_COOLDOWN_MINUTES, HEARTBEAT_DAILY_LIMIT } from "../automation/job-policy.mjs";
import { BASETEN_BASE_URL, BASETEN_DEFAULT_MODEL, BASETEN_DEFAULT_TOKENS, BASETEN_MIN_TOKENS, BASETEN_REASONING_EFFORT, BASETEN_REASONING_LEVELS, MODAL_BASE_URL, MODAL_DEFAULT_MODEL, MODAL_DEFAULT_TOKENS, MODAL_MIN_TOKENS, MODAL_REASONING_EFFORT, MODAL_REASONING_LEVELS } from './provider.mjs';
import { VOICE_TASK_LIMIT, VOICE_JOB_SPEAK_MIN_INTERVAL_MS, VOICE_SPEECH_GAP_MS, VOICE_JOB_WAIT_UPDATE_MS, VOICE_MAX_PARALLEL_JOBS, VOICE_PARALLEL_JOBS_LIMIT } from '../automation/voice-task-policy.mjs';

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
export const MCP_TIERS_FILE = path.join(CONFIG_DIR, "mcp-tiers.json");
export const COMPOSIO_FILE = path.join(CONFIG_DIR, "composio.json");
export const COMPOSIO_GRANTS_FILE = path.join(CONFIG_DIR, "composio-grants.json");
export const DAEMON_LOG = path.join(CONFIG_DIR, "daemon.log");
export const DEFAULT_TOOL_OUTPUT_BYTES = 64 * 1024; // UTF-8 bytes/tool reply; shared by config and bounded observation formatting.

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
  maxToolChars: DEFAULT_TOOL_OUTPUT_BYTES,
  maxToolSteps: 100,
  maxToolCalls: 60,
  // Sub-agent delegation: one level deep by default. Read-only research agents
  // overlap through the existing read-only batch; write-capable workers remain
  // serialized barriers so two agents never edit the same workspace at once.
  subagentsEnabled: SUBAGENT_DEFAULTS.enabled,
  maxSubagentDepth: SUBAGENT_DEFAULTS.maxDepth,
  maxConcurrentSubagents: SUBAGENT_DEFAULTS.concurrency,
  maxSubagentsPerTurn: SUBAGENT_DEFAULTS.perTurn,
  subagentMaxToolSteps: SUBAGENT_DEFAULTS.toolSteps,
  subagentMaxToolCalls: SUBAGENT_DEFAULTS.toolCalls,
  subagentTimeoutMs: SUBAGENT_DEFAULTS.timeoutMs,
  subagentMaxTokens: SUBAGENT_DEFAULTS.tokens,
  subagentMaxResultBytes: SUBAGENT_DEFAULTS.resultBytes,
  browserToolFocus: false, // Boolean: opt-in until repeated live capability parity clears the browser-lab gate.
  browserHistoryCompaction: false, // Boolean: opt-in request projection; mixed-page evidence retention still needs live parity.
  browserRuntimeV2: false, // Boolean: experimental structured browser runtime; enable only after paired capability/speed gates.
  browserEvidenceRetention: false, // Boolean: opt-in grounded task quotes; requires structured runtime observations.
  browserProgressTracking: false, // Boolean: opt-in state-aware recovery guidance; existing hard limits still apply.
  agentDebug: false,
  contextWindow: 32768,
  provider: "",
  apiBase: "",
  apiKey: "",
  imageApiBase: "",
  imageApiKey: "",
  imageModel: "gpt-image-1",
  unsplashAccessKey: "",
  pixabayApiKey: "",
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
  heartbeatDailyLimit: HEARTBEAT_DAILY_LIMIT,
  heartbeatCooldownMinutes: HEARTBEAT_COOLDOWN_MINUTES,
  groqApiKey: "",
  sarvamApiKey: "",
  basetenApiKey: "",
  modalApiKey: "",
  // Voice turns may use a different provider/model for latency; empty = same.
  voiceProvider: "",
  voiceModel: "",
  voiceApiBase: "",
  // "auto" keeps Groq (existing behaviour) unless Sarvam is the only key set.
  sttProvider: "auto",
  sttModel: "whisper-large-v3-turbo",
  sarvamSttModel: DEFAULT_SARVAM_STT_MODEL,
  sarvamSttMode: DEFAULT_SARVAM_STT_MODE,
  sarvamKeyterms: [],
  ttsProvider: "edge",
  ttsModel: "canopylabs/orpheus-v1-english",
  sarvamTtsModel: DEFAULT_SARVAM_TTS_MODEL,
  sarvamSpeakerHi: DEFAULT_SARVAM_SPEAKER_HI,
  sarvamSpeakerEn: DEFAULT_SARVAM_SPEAKER_EN,
  // Used only when neither the reply text nor the transcript settles a language.
  sarvamTtsLanguage: DEFAULT_SARVAM_TTS_LANGUAGE,
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
export function loadConfig(envPath = path.join(process.cwd(), ".env"), { globalEnvFile = GLOBAL_ENV_FILE } = {}) {
  // Read-only provider/config source override for hermetic callers. Runtime storage
  // remains bound to CONFIG_DIR; no credentials are copied into test artifacts.
  const global = readVars(globalEnvFile);
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
    // Rounds of tool calling per request before the runtime stops the loop and
    // asks for a summary. Clamped, with no "unlimited": an unbounded loop is the
    // bug this bound exists to prevent, so garbage falls back to the default.
    maxToolSteps: clampInt(pick("MAX_TOOL_STEPS"), 1, 200, DEFAULTS.maxToolSteps),
    maxToolCalls: clampInt(pick("MAX_TOOL_CALLS"), 1, 500, DEFAULTS.maxToolCalls),
    subagentsEnabled: onOff(pick("SUBAGENTS_ENABLED"), DEFAULTS.subagentsEnabled),
    maxSubagentDepth: clampInt(pick("MAX_SUBAGENT_DEPTH"), 0, SUBAGENT_LIMITS.maxDepth, DEFAULTS.maxSubagentDepth),
    maxConcurrentSubagents: clampInt(pick("MAX_CONCURRENT_SUBAGENTS"), 1, SUBAGENT_LIMITS.maxConcurrent, DEFAULTS.maxConcurrentSubagents),
    maxSubagentsPerTurn: clampInt(pick("MAX_SUBAGENTS_PER_TURN"), 1, SUBAGENT_LIMITS.maxPerTurn, DEFAULTS.maxSubagentsPerTurn),
    subagentMaxToolSteps: clampInt(pick("SUBAGENT_MAX_TOOL_STEPS"), 1, SUBAGENT_LIMITS.maxToolSteps, DEFAULTS.subagentMaxToolSteps),
    subagentMaxToolCalls: clampInt(pick("SUBAGENT_MAX_TOOL_CALLS"), 1, SUBAGENT_LIMITS.maxToolCalls, DEFAULTS.subagentMaxToolCalls),
    subagentTimeoutMs: clampInt(pick("SUBAGENT_TIMEOUT_MS"), SUBAGENT_LIMITS.minTimeoutMs, SUBAGENT_LIMITS.maxTimeoutMs, DEFAULTS.subagentTimeoutMs),
    subagentMaxTokens: clampInt(pick("SUBAGENT_MAX_TOKENS"), SUBAGENT_LIMITS.minTokens, SUBAGENT_LIMITS.maxTokens, DEFAULTS.subagentMaxTokens),
    subagentMaxResultBytes: clampInt(pick("SUBAGENT_MAX_RESULT_BYTES"), SUBAGENT_LIMITS.minResultBytes, SUBAGENT_LIMITS.maxResultBytes, DEFAULTS.subagentMaxResultBytes),
    browserToolFocus: onOff(pick("BROWSER_TOOL_FOCUS"), DEFAULTS.browserToolFocus),
    browserHistoryCompaction: onOff(pick("BROWSER_HISTORY_COMPACTION"), DEFAULTS.browserHistoryCompaction),
    browserRuntimeV2: onOff(pick("BROWSER_RUNTIME_V2"), DEFAULTS.browserRuntimeV2),
    browserEvidenceRetention: onOff(pick("BROWSER_EVIDENCE_RETENTION"), DEFAULTS.browserEvidenceRetention),
    browserProgressTracking: onOff(pick("BROWSER_PROGRESS_TRACKING"), DEFAULTS.browserProgressTracking),
    agentDebug: onOff(pick("ANKITA_AGENT_DEBUG"), DEFAULTS.agentDebug),
    contextWindow: posInt(pick("CONTEXT_WINDOW"), DEFAULTS.contextWindow),
    // Whether that value was chosen or just defaulted. Providers advertise each
    // model's real window, and it is usually far above the default - but an
    // explicit CONTEXT_WINDOW is a deliberate choice and must win.
    contextWindowExplicit: pick("CONTEXT_WINDOW") !== undefined,
    provider: (pick("PROVIDER") || DEFAULTS.provider).trim().toLowerCase(),
    apiBase: pick("API_BASE") || DEFAULTS.apiBase,
    apiKey: pick("API_KEY") || DEFAULTS.apiKey,
    imageApiBase: pick("IMAGE_API_BASE") || DEFAULTS.imageApiBase,
    imageApiKey: pick("IMAGE_API_KEY") || DEFAULTS.imageApiKey,
    imageModel: pick("IMAGE_MODEL") || DEFAULTS.imageModel,
    unsplashAccessKey: pick("UNSPLASH_ACCESS_KEY") || DEFAULTS.unsplashAccessKey,
    pixabayApiKey: pick("PIXABAY_API_KEY") || DEFAULTS.pixabayApiKey,
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
    // Project work capture. Detection and the work log are free; the inline
    // extraction pass spends a model call, so it stays off unless asked for.
    projectAutoDetect: onOff(pick("PROJECT_AUTO_DETECT"), true),
    projectWorkCapture: onOff(pick("PROJECT_WORK_CAPTURE"), true),
    projectAutoMaintenance: onOff(pick("PROJECT_AUTO_MAINTENANCE"), true),
    projectInlineConsolidation: onOff(pick("PROJECT_INLINE_CONSOLIDATION"), false),
    projectAuditMaxTools: Math.min(100, posInt(pick("PROJECT_AUDIT_MAX_TOOLS"), 20)),
    projectAuditMaxFiles: Math.min(100, posInt(pick("PROJECT_AUDIT_MAX_FILES"), 20)),
    projectWorklogMax: Math.min(1000, posInt(pick("PROJECT_WORKLOG_MAX"), 100)),
    projectTodoSyncMax: Math.min(20, posInt(pick("PROJECT_TODO_SYNC_MAX"), 5)),
    projectInlineMinChars: Math.min(100000, posInt(pick("PROJECT_INLINE_MIN_CHARS"), 400)),
    briefingPrompt: pick("BRIEFING_PROMPT") || "",
    heartbeatDailyLimit: Math.min(24, Math.max(1, posInt(pick("HEARTBEAT_DAILY_LIMIT"), DEFAULTS.heartbeatDailyLimit))),
    heartbeatCooldownMinutes: (() => {
      const n = Number(pick("HEARTBEAT_COOLDOWN_MINUTES") ?? DEFAULTS.heartbeatCooldownMinutes);
      return Number.isFinite(n) && n >= 0 ? Math.min(1440, Math.floor(n)) : DEFAULTS.heartbeatCooldownMinutes;
    })(),
    groqApiKey: pick("GROQ_API_KEY") || DEFAULTS.groqApiKey,
    sarvamApiKey: pick("SARVAM_API_KEY") || DEFAULTS.sarvamApiKey,
    basetenApiKey: pick("BASETEN_API_KEY") || DEFAULTS.basetenApiKey,
    basetenBaseUrl: pick("BASETEN_BASE_URL") || BASETEN_BASE_URL,
    basetenModel: pick("BASETEN_MODEL") || BASETEN_DEFAULT_MODEL,
    basetenMaxTokens: Math.max(BASETEN_MIN_TOKENS, posInt(pick("BASETEN_MAX_TOKENS"), BASETEN_DEFAULT_TOKENS)),
    basetenReasoningEffort: (() => {
      const value = String(pick("BASETEN_REASONING_EFFORT") || '').trim().toLowerCase();
      return BASETEN_REASONING_LEVELS.includes(value) ? value : BASETEN_REASONING_EFFORT;
    })(),
    // Modal proxy auth arrives as two parts and is joined into the one bearer
    // token the endpoint expects; a combined MODAL_PROXY_TOKEN wins so rotation
    // needs a single variable.
    modalApiKey: pick("MODAL_PROXY_TOKEN") || (() => {
      const id = String(pick("MODAL_PROXY_TOKEN_ID") || '').trim();
      const secret = String(pick("MODAL_PROXY_TOKEN_SECRET") || '').trim();
      return id && secret ? `${id}.${secret}` : '';
    })(),
    modalBaseUrl: pick("MODAL_BASE_URL") || MODAL_BASE_URL,
    modalModel: pick("MODAL_MODEL") || MODAL_DEFAULT_MODEL,
    modalMaxTokens: Math.max(MODAL_MIN_TOKENS, posInt(pick("MODAL_MAX_TOKENS"), MODAL_DEFAULT_TOKENS)),
    modalReasoningEffort: (() => {
      const value = String(pick("MODAL_REASONING_EFFORT") || '').trim().toLowerCase();
      return MODAL_REASONING_LEVELS.includes(value) ? value : MODAL_REASONING_EFFORT;
    })(),
    // A named provider preset for voice-only turns (see VOICE_PROVIDER).
    voiceProvider: (pick("VOICE_PROVIDER") || DEFAULTS.voiceProvider).trim().toLowerCase(),
    voiceModel: pick("VOICE_MODEL") || DEFAULTS.voiceModel,
    voiceApiBase: pick("VOICE_API_BASE") || DEFAULTS.voiceApiBase,
    voiceContextWindow: posInt(pick('VOICE_CONTEXT_WINDOW'), 0), // Tokens; zero uses the selected provider's window.
    voiceTaskLimit: posInt(pick('VOICE_TASK_LIMIT'), VOICE_TASK_LIMIT),
    voiceMaxParallelJobs: clampInt(pick('VOICE_MAX_PARALLEL_JOBS'), 1, VOICE_PARALLEL_JOBS_LIMIT, VOICE_MAX_PARALLEL_JOBS), // Independent voice workers, plus one status/stop-only turn at capacity.
    voiceJobSpeakMinIntervalMs: posInt(pick('VOICE_JOB_SPEAK_MIN_INTERVAL_MS'), VOICE_JOB_SPEAK_MIN_INTERVAL_MS),
    voiceJobWaitUpdateMs: posInt(pick('VOICE_JOB_WAIT_UPDATE_MS'), VOICE_JOB_WAIT_UPDATE_MS),
    voiceSpeechGapMs: posInt(pick('VOICE_SPEECH_GAP_MS'), VOICE_SPEECH_GAP_MS),
    voiceVerbose: onOff(pick('VOICE_VERBOSE'), false), // Quiet spoken interaction; detailed records remain under /task.
    sttProvider: (() => {
      const v = String(pick("STT_PROVIDER") || DEFAULTS.sttProvider).toLowerCase();
      return ["auto", "groq", "sarvam"].includes(v) ? v : DEFAULTS.sttProvider;
    })(),
    sttModel: pick("STT_MODEL") || DEFAULTS.sttModel,
    sarvamSttModel: pick("SARVAM_STT_MODEL") || DEFAULTS.sarvamSttModel,
    // `translit` keeps Hinglish in Latin script; `transcribe`/`verbatim` are the
    // other documented modes, so anything unknown falls back to the default.
    sarvamSttMode: (() => {
      const v = String(pick("SARVAM_STT_MODE") || DEFAULTS.sarvamSttMode).toLowerCase();
      return ["translit", "transcribe", "verbatim", "codemix"].includes(v) ? v : DEFAULTS.sarvamSttMode;
    })(),
    // Bias recognition toward the assistant's own name unless the user
    // overrides the list; names are the words recognisers mangle most.
    sarvamKeyterms: parseKeyterms(pick("SARVAM_KEYTERMS") ?? (pick("AGENT_NAME") || DEFAULTS.agentName)),
    ttsProvider: (() => {
      const v = String(pick("TTS_PROVIDER") || DEFAULTS.ttsProvider).toLowerCase();
      return ["auto", "groq", "edge", "sarvam"].includes(v) ? v : DEFAULTS.ttsProvider;
    })(),
    ttsModel: pick("TTS_MODEL") || DEFAULTS.ttsModel,
    sarvamTtsModel: pick("SARVAM_TTS_MODEL") || DEFAULTS.sarvamTtsModel,
    sarvamSpeakerHi: pick("SARVAM_TTS_SPEAKER_HI") || DEFAULTS.sarvamSpeakerHi,
    sarvamSpeakerEn: pick("SARVAM_TTS_SPEAKER_EN") || DEFAULTS.sarvamSpeakerEn,
    // A BCP-47-ish tag like hi-IN / en-IN; anything malformed falls back.
    sarvamTtsLanguage: (() => {
      const v = String(pick("SARVAM_TTS_LANGUAGE") || DEFAULTS.sarvamTtsLanguage).trim();
      return /^[a-z]{2}-[A-Z]{2}$/.test(v) ? v : DEFAULTS.sarvamTtsLanguage;
    })(),
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
