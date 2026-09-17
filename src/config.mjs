import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const CONFIG_DIR = process.env.CONFIG_DIR || path.join(os.homedir(), ".copilot-chat-cli");
export const GLOBAL_ENV_FILE = path.join(CONFIG_DIR, "config.env");
export const AUTH_FILE = path.join(CONFIG_DIR, "auth.json");
export const HISTORY_FILE = path.join(CONFIG_DIR, "history");
export const SESSIONS_DIR = path.join(CONFIG_DIR, "sessions");
export const AUTOSAVE_NAME = "autosave";

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
  apiBase: "",
  apiKey: "",
  inputCostPerMillion: null,
  outputCostPerMillion: null,
  groqApiKey: "",
  sttModel: "whisper-large-v3-turbo",
  ttsProvider: "edge",
  ttsModel: "canopylabs/orpheus-v1-english",
  ttsVoice: "",
  ttsRate: "+0%",
  speak: false,
  micDevice: "",
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
    maxToolChars: posInt(pick("MAX_TOOL_CHARS"), DEFAULTS.maxToolChars),
    contextWindow: posInt(pick("CONTEXT_WINDOW"), DEFAULTS.contextWindow),
    apiBase: pick("API_BASE") || DEFAULTS.apiBase,
    apiKey: pick("API_KEY") || DEFAULTS.apiKey,
    inputCostPerMillion: price(pick("INPUT_COST_PER_MILLION")),
    outputCostPerMillion: price(pick("OUTPUT_COST_PER_MILLION")),
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
  };
}

export function ensureDirs() {
  fs.mkdirSync(CONFIG_DIR, { recursive: true });
  fs.mkdirSync(SESSIONS_DIR, { recursive: true });
}
