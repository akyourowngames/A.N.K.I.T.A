import { execFileSync } from "node:child_process";
import { readAuth } from "../../src/core/auth.mjs";

export const name = "github_notifications";
export const description =
  "Read your GitHub inbox: unread notifications, mentions, review requests, and repository " +
  "invitations. Uses the same GitHub token ankita already holds. Use it for a morning sweep " +
  "of what needs your attention.";

export const parameters = {
  type: "object",
  properties: {
    all: { type: "boolean", description: "Include already-read notifications. Default false." },
    limit: { type: "integer", description: "Maximum notifications. Default 30, max 100." },
    include_invitations: { type: "boolean", description: "Also list repository invitations. Default true." },
  },
};

export const readOnly = true;
export const needsApproval = false;

/**
 * Candidate tokens, best-scoped first. The Copilot device-flow token only
 * carries read:user, so /notifications needs either GITHUB_TOKEN or the
 * gh CLI's token (which has repo). Invitations work with any of them.
 */
export function tokenCandidates() {
  const list = [];
  if (process.env.GITHUB_TOKEN) list.push(process.env.GITHUB_TOKEN);
  if (process.env.GH_TOKEN) list.push(process.env.GH_TOKEN);
  try {
    const fromCli = execFileSync("gh", ["auth", "token"], {
      encoding: "utf8",
      windowsHide: true,
      timeout: 10000,
      stdio: ["ignore", "pipe", "ignore"],
    }).trim();
    if (fromCli) list.push(fromCli);
  } catch {}
  const stored = readAuth()?.github_token;
  if (stored) list.push(stored);
  return [...new Set(list)];
}

async function api(path, tok) {
  const res = await fetch(`https://api.github.com${path}`, {
    headers: {
      Authorization: `Bearer ${tok}`,
      Accept: "application/vnd.github+json",
      "User-Agent": "ankita/2.0",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    signal: AbortSignal.timeout(20000),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`GitHub ${path} -> ${res.status}${body ? `: ${body.slice(0, 200)}` : ""}`);
  }
  return res.json();
}

/** Groups notifications into the buckets a person actually triages. */
export function bucketNotifications(items) {
  const buckets = { review_requested: [], mention: [], assign: [], ci: [], other: [] };
  for (const item of items) {
    const reason = String(item.reason || "other");
    const key = Object.prototype.hasOwnProperty.call(buckets, reason) ? reason : "other";
    buckets[key].push(item);
  }
  return buckets;
}

export function formatNotification(item) {
  const repo = item.repository?.full_name || "(unknown repo)";
  const type = item.subject?.type || "Item";
  return `  [${item.reason}] ${type} - ${item.subject?.title || "(no title)"}\n      ${repo}`;
}

/** Tries each candidate token until one is allowed to read `path`. */
async function apiWithAnyToken(path, tokens) {
  let lastError = null;
  for (const tok of tokens) {
    try {
      return { data: await api(path, tok), token: tok };
    } catch (err) {
      lastError = err;
      // 401/403 means this token lacks scope; anything else is real.
      if (!/\b(401|403)\b/.test(err.message)) throw err;
    }
  }
  throw lastError || new Error("no usable GitHub token");
}

export async function run(args = {}) {
  const tokens = tokenCandidates();
  if (!tokens.length) {
    return "Error: no GitHub token available (run ankita once to log in, or set GITHUB_TOKEN).";
  }

  const limit = Math.min(Math.max(1, Number(args.limit) || 30), 100);
  const lines = [];

  try {
    const query = args.all ? `?all=true&per_page=${limit}` : `?per_page=${limit}`;
    const { data: items } = await apiWithAnyToken(`/notifications${query}`, tokens);
    if (!items.length) {
      lines.push("GitHub: no unread notifications.");
    } else {
      const buckets = bucketNotifications(items);
      lines.push(`GitHub: ${items.length} unread notification(s)`);
      const labels = {
        review_requested: "review requested",
        mention: "mentions",
        assign: "assigned",
        ci: "CI activity",
        other: "other",
      };
      for (const [key, label] of Object.entries(labels)) {
        const group = buckets[key];
        if (!group.length) continue;
        lines.push(`\n${label} (${group.length}):`);
        lines.push(...group.slice(0, 10).map(formatNotification));
      }
    }
  } catch (err) {
    const scopeHint = /\b403\b/.test(err.message)
      ? " (needs a token with the notifications or repo scope - `gh auth login` or set GITHUB_TOKEN)"
      : "";
    lines.push(`GitHub notifications: ERROR ${err.message}${scopeHint}`);
  }

  if (args.include_invitations !== false) {
    try {
      const { data: invites } = await apiWithAnyToken("/user/repository_invitations", tokens);
      lines.push(
        invites.length
          ? `\nrepository invitations (${invites.length}):\n` +
              invites
                .slice(0, 10)
                .map((i) => `  ${i.repository?.full_name} from ${i.inviter?.login || "?"}`)
                .join("\n")
          : "\nrepository invitations: none"
      );
    } catch (err) {
      lines.push(`\nrepository invitations: ERROR ${err.message}`);
    }
  }

  return lines.join("\n");
}
