import fs from "node:fs";
import path from "node:path";
import { exec } from "node:child_process";
import { AUTH_FILE } from "./config.mjs";
import { fetchWithRetry } from "./net.mjs";

const CLIENT_ID = "Iv1.b507a08c87ecfe98";
const OAUTH_SCOPE = "read:user";
const DEVICE_CODE_URL = "https://github.com/login/device/code";
const ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token";
const COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token";
const FALLBACK_API = "https://api.githubcopilot.com";

const HEADERS_BASE = {
  "Editor-Version": "vscode/1.99.3",
  "Editor-Plugin-Version": "copilot-chat/0.26.0",
  "Copilot-Integration-Id": "vscode-chat",
  "User-Agent": "GitHubCopilotChat/0.26.0",
  "X-GitHub-Api-Version": "2025-04-01",
};

export function readAuth() {
  try {
    return JSON.parse(fs.readFileSync(AUTH_FILE, "utf8"));
  } catch {
    return {};
  }
}

export function resolveGithubToken() {
  return process.env.GITHUB_TOKEN || readAuth().github_token || null;
}

export function writeAuth(data) {
  fs.mkdirSync(path.dirname(AUTH_FILE), { recursive: true });
  fs.writeFileSync(AUTH_FILE, JSON.stringify(data, null, 2), { mode: 0o600 });
}

async function postForm(url, body) {
  const res = await fetchWithRetry(url, {
    method: "POST",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const text = await res.text();
  try {
    return JSON.parse(text);
  } catch {
    return Object.fromEntries(new URLSearchParams(text));
  }
}

export async function deviceLogin({ log = console.log, write = (s) => process.stdout.write(s), onDeviceCode = null } = {}) {
  const dc = await postForm(DEVICE_CODE_URL, { client_id: CLIENT_ID, scope: OAUTH_SCOPE });

  if (dc.error) throw new Error(`${dc.error}: ${dc.error_description || ""}`);
  if (!dc.device_code) throw new Error("Failed to start device flow: " + JSON.stringify(dc));

  if (onDeviceCode) {
    onDeviceCode({ user_code: dc.user_code, verification_uri: dc.verification_uri });
  } else {
    log("");
    log("  Open:  " + dc.verification_uri);
    log("  Code:  " + dc.user_code);
    log("  (opening your browser...)");
    log("");
    try { exec(`start "" "${dc.verification_uri}"`); } catch {}
  }

  const intervalMs = Math.max(1, dc.interval || 5) * 1000;
  const deadline = Date.now() + (dc.expires_in || 900) * 1000;

  write("  waiting for authorization");

  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, intervalMs));
    const out = await postForm(ACCESS_TOKEN_URL, {
      client_id: CLIENT_ID,
      device_code: dc.device_code,
      grant_type: "urn:ietf:params:oauth:grant-type:device_code",
    });

    if (out.access_token) {
      write("\n");
      log("  authorized.");
      return out.access_token;
    }
    if (out.error === "authorization_pending") {
      write(".");
      continue;
    }
    if (out.error === "slow_down") {
      await new Promise((r) => setTimeout(r, intervalMs));
      continue;
    }
    if (out.error === "access_denied") throw new Error("Access denied by user.");
    if (out.error === "expired_token") throw new Error("Device code expired, run again.");
    if (out.error) throw new Error(`${out.error}: ${out.error_description || ""}`);
  }
  throw new Error("Timed out waiting for authorization.");
}

export class CopilotClient {
  constructor(githubToken) {
    this.githubToken = githubToken;
    this.token = null;
  }

  async ensureToken(force = false) {
    if (!force && this.token && this.token.expires_at * 1000 - Date.now() > 60_000) {
      return this.token;
    }
    const res = await fetchWithRetry(COPILOT_TOKEN_URL, {
      headers: {
        Authorization: `token ${this.githubToken}`,
        Accept: "application/json",
        ...HEADERS_BASE,
      },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.token) {
      const err = new Error(
        `Could not get a Copilot token (${res.status}). Does this account have Copilot access?`
      );
      err.status = res.status;
      err.detail = data;
      throw err;
    }
    this.token = data;
    return data;
  }

  get baseUrl() {
    return (this.token?.endpoints?.api || FALLBACK_API).replace(/\/$/, "");
  }

  headers(stream) {
    return {
      ...HEADERS_BASE,
      Authorization: `Bearer ${this.token.token}`,
      "Content-Type": "application/json",
      Accept: stream ? "text/event-stream" : "application/json",
    };
  }

  async models() {
    const res = await fetchWithRetry(`${this.baseUrl}/models`, { headers: this.headers(false) });
    if (!res.ok) throw new Error(`Model list failed (${res.status}): ${await res.text()}`);
    const data = await res.json();
    return (data.data || []).map((m) => ({
      id: m.id,
      name: m.name || m.id,
      vendor: m.vendor || m.publisher || "",
      tools: m.capabilities?.supports?.tool_calls ?? null,
      context: m.capabilities?.limits?.max_context_window_tokens ?? null,
      default: m.default ?? null,
    }));
  }
}
