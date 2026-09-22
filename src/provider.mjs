import { fetchWithRetry } from "./net.mjs";

/**
 * Default picks when the user did not pin a model. Ordered by preference;
 * refreshed against the live model list rather than frozen in time.
 */
/**
 * Auto-pick order.
 *
 * gpt-4o leads on measured throughput, not reputation. Same prompt set,
 * streamed, 4 rounds each (median): gpt-4o 194 tok/s vs gpt-4.1 58.5 tok/s,
 * with time-to-first-token a wash (1048ms vs 1066ms). A 300-token answer
 * projects to 2.6s on gpt-4o against 6.2s on gpt-4.1.
 *
 * Do not reorder without re-measuring - see docs/benchmark notes in the PR.
 */
const PREFERRED = [
  "gpt-4o",
  "gpt-4.1",
  "gpt-4o-mini",
  "claude-sonnet-5",
  "gemini-3.5-flash",
  "gpt-5-mini",
  "gpt-5.4",
];

const capable = (m, useTools) => !useTools || m.tools !== false;

/**
 * Choose a model id from a provider model list.
 *
 * - An explicit request for a tool-less model while tools are on throws
 *   instead of silently degrading the session.
 * - An explicit id with an empty list is trusted (offline / custom endpoint).
 * - Otherwise: server-marked default, then the preference list, then the
 *   largest known context window.
 */
export function pickModel(models, wanted = "", useTools = true) {
  const list = Array.isArray(models) ? models : [];
  const name = String(wanted || "").trim();

  if (name) {
    const exact = list.find((m) => m.id === name) || list.find((m) => m.id.includes(name));
    if (exact) {
      if (!capable(exact, useTools)) {
        throw new Error(
          `Model "${exact.id}" does not support tool calls. Disable tools (/tools off) or pick another model.`
        );
      }
      return { ...exact, matched: true };
    }
    if (!list.length) {
      return { id: name, name, vendor: "", tools: null, context: null, default: null, matched: true };
    }
  }

  const pool = list.filter((m) => capable(m, useTools));
  if (useTools && list.length && !pool.length) {
    throw new Error(
      "None of the available models support tool calls. Run with tools disabled (/tools off) or pick a compatible model."
    );
  }
  const from = pool.length ? pool : list;
  if (!from.length) throw new Error("No models are available from this provider.");

  // Two passes: all exact ids first, then partial. A single pass lets the
  // loose match cross models - "gpt-4o" would hit "gpt-4o-mini" before the
  // preference list ever reached "gpt-4.1".
  const auto =
    from.find((m) => m.default) ||
    PREFERRED.map((p) => from.find((m) => m.id === p)).find(Boolean) ||
    PREFERRED.map((p) => from.find((m) => m.id.includes(p))).find(Boolean) ||
    [...from].sort((a, b) => (b.context || 0) - (a.context || 0))[0] ||
    from[0];
  return { ...auto, matched: !name };
}

/**
 * Named OpenAI-compatible gateways. "copilot" is handled by the CLI's GitHub
 * device flow; every other entry is a plain CompatibleClient target. A preset
 * only supplies defaults, so an explicit API_BASE / API_KEY / MODEL still wins.
 *
 * `keyless: true` means the gateway serves its free models with no credentials
 * at all - the CLI then skips its "no API_KEY set" note.
 */
export const PROVIDERS = {
  kilo: {
    label: "Kilo AI Gateway",
    apiBase: "https://api.kilo.ai/api/gateway",
    // Fastest free model that streams normal content (not reasoning-only) and
    // supports tool calls - measured, see docs/benchmark notes in the PR.
    defaultModel: "nex-agi/nex-n2.5-mini:free",
    keyless: true,
  },
};

/**
 * Resolve a PROVIDER name to its preset. Unknown names return null so the CLI
 * can fail loudly instead of silently falling back to Copilot. The default
 * (empty or "copilot") is GitHub Copilot itself.
 */
export function resolveProvider(name) {
  const key = String(name || "").trim().toLowerCase();
  if (!key || key === "copilot") {
    return { name: "copilot", label: "GitHub Copilot", apiBase: "", apiKey: "", defaultModel: "", keyless: false };
  }
  const preset = PROVIDERS[key];
  if (!preset) return null;
  return { name: key, apiKey: "", keyless: false, ...preset };
}

/**
 * Minimal client for any OpenAI-compatible `/chat/completions` endpoint
 * (Ollama, LM Studio, OpenRouter, ...). Same surface as CopilotClient:
 * baseUrl, headers(stream), ensureToken(), models().
 */
export class CompatibleClient {
  constructor({ apiBase, apiKey = "", model = "", contextWindow = null } = {}) {
    if (!apiBase) throw new Error("API_BASE is required for a custom endpoint.");
    this._base = String(apiBase).replace(/\/$/, "");
    this.apiKey = apiKey;
    this.configuredModel = model;
    this.contextWindow = contextWindow;
  }

  get baseUrl() {
    return this._base;
  }

  async ensureToken() {
    return null;
  }

  headers(stream) {
    const headers = {
      "Content-Type": "application/json",
      Accept: stream ? "text/event-stream" : "application/json",
    };
    if (this.apiKey) headers.Authorization = `Bearer ${this.apiKey}`;
    return headers;
  }

  async models() {
    try {
      const res = await fetchWithRetry(`${this._base}/models`, { headers: this.headers(false) });
      if (!res.ok) throw new Error(`Model list failed (${res.status})`);
      const data = await res.json();
      const list = (data.data || []).map((m) => ({
        id: m.id,
        name: m.name || m.id,
        vendor: m.vendor || m.publisher || m.owned_by || "",
        tools: Array.isArray(m.supported_parameters)
          ? m.supported_parameters.includes("tools")
          : (m.capabilities?.supports?.tool_calls ?? null),
        context: m.context_length ?? m.capabilities?.limits?.max_context_window_tokens ?? null,
        default: m.default ?? null,
      }));
      if (!list.length) throw new Error("Model list is empty.");
      return list;
    } catch (err) {
      if (this.configuredModel) {
        return [
          {
            id: this.configuredModel,
            name: this.configuredModel,
            vendor: "",
            tools: null,
            context: this.contextWindow ?? null,
            default: true,
          },
        ];
      }
      throw err;
    }
  }
}
