import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { CONFIG_DIR } from '../../src/core/config.mjs';
import { audit } from '../shared/_audit.mjs';
import { loadApps, isAppIdTarget } from './discover.mjs';

export const name = 'open_app';
// Launching a desktop application by name. This exists so "open notepad" never
// becomes a shell command whose child process can hold the voice queue open.
export const description = 'Open a desktop application by name (for example "notepad", "calculator", "spotify"). Names come from the installed-app index, which is scanned automatically; use list to see matches. Returns as soon as the app is started, so it never blocks the conversation.';
export const parameters = { type: 'object', properties: {
  name: { type: 'string', description: 'Application name, as shown in the Start menu or Applications folder.' },
  action: { type: 'string', enum: ['open', 'list'], description: 'open launches; list shows matching names without launching.' },
  refresh: { type: 'boolean', description: 'Rescan installed apps before matching (use after installing something new).' },
  limit: { type: 'integer', minimum: 1, maximum: 30, description: 'Maximum names returned by list.' },
}, required: ['name'] };

const MAX_RESULTS = 5;
const MAX_SUGGESTIONS = 12;
export const LAUNCH_TIMEOUT_MS = 20000; // The shell handler only reports whether the start request was accepted.
const LIST_LIMIT_DEFAULT = 10;

const normalize = value => String(value ?? '').toLocaleLowerCase().replace(/[^\p{L}\p{N}\s]/gu, ' ').replace(/\s+/g, ' ').trim();

/** Exact, then unique prefix, then substring. Never a guess between alternatives. */
export function matchApps(apps, query) {
  const wanted = normalize(query);
  if (!wanted) return { kind: 'none', matches: [] };
  const scored = apps.map(app => ({ app, key: normalize(app.name) }));
  const exact = scored.filter(item => item.key === wanted).map(item => item.app);
  if (exact.length === 1) return { kind: 'exact', match: exact[0], matches: exact };
  if (exact.length > 1) return { kind: 'ambiguous', matches: exact };
  const prefix = scored.filter(item => item.key.startsWith(wanted)).map(item => item.app);
  if (prefix.length === 1) return { kind: 'prefix', match: prefix[0], matches: prefix };
  if (prefix.length > 1) return { kind: 'ambiguous', matches: prefix.slice(0, MAX_SUGGESTIONS) };
  const partial = scored.filter(item => item.key.includes(wanted)).map(item => item.app);
  if (partial.length === 1) return { kind: 'partial', match: partial[0], matches: partial };
  if (partial.length > 1) return { kind: 'ambiguous', matches: partial.slice(0, MAX_SUGGESTIONS) };
  // A multi-word request may name the app in a different order ("photo editor").
  const tokens = wanted.split(' ').filter(token => token.length > 2);
  if (tokens.length > 1) {
    const byToken = scored.filter(item => tokens.every(token => item.key.includes(token))).map(item => item.app);
    if (byToken.length === 1) return { kind: 'tokens', match: byToken[0], matches: byToken };
    if (byToken.length > 1) return { kind: 'ambiguous', matches: byToken.slice(0, MAX_SUGGESTIONS) };
  }
  return { kind: 'none', matches: [] };
}

/**
 * Windows Start-menu AppIDs are not file paths; they launch through the shell
 * handler. The shape check lives in discover.mjs so the scanner and the launcher
 * can never disagree about what counts as an AppID.
 */
export const isShellTarget = isAppIdTarget;

/** Verify a target is something we can actually start, and came from the index. */
export function validateTarget(entry, { exists = fs.existsSync, platform = process.platform } = {}) {
  if (!entry?.target) return 'No launch target was found for that application.';
  if (isShellTarget(entry.target)) return null; // Shell namespace, launched below without a file check.
  // Anything that is not a shell AppID must be a real absolute path that exists.
  // A relative or bare name is refused: it would resolve through PATH to whatever
  // happens to be first, which is not what the index promised.
  if (!path.isAbsolute(entry.target)) return 'That application entry is not launchable.';
  if (!exists(entry.target)) return `That application is no longer installed (${path.basename(entry.target)} is missing).`;
  return null;
}

/**
 * How a target is started.
 *
 * A shell AppID must go through `cmd /c start` because Windows resolves it there.
 * `cmd` re-parses its command line, so ONLY a target that satisfies the strict
 * AppID shapes above may ever go that way — those patterns cannot contain `&`,
 * `|`, `^`, `"` or `%VAR%`. Real file paths never touch cmd: they are spawned
 * directly with shell:false, so no re-parsing happens at all.
 */
function launchCommand(entry, platform) {
  if (platform === 'darwin') {
    if (!entry.target.endsWith('.app')) return { exe: entry.target, args: safeArgs(entry.args) };
    return { exe: 'open', args: ['-a', entry.target] };
  }
  if (platform === 'win32') {
    if (isShellTarget(entry.target)) return { exe: 'cmd.exe', args: ['/c', 'start', '', `shell:AppsFolder\\${entry.target}`] };
    return { exe: entry.target, args: safeArgs(entry.args) };
  }
  return { exe: entry.target, args: safeArgs(entry.args) };
}

/** Arguments come from a .desktop file; keep only plain tokens. */
function safeArgs(args) {
  return (Array.isArray(args) ? args : []).filter(arg => typeof arg === 'string' && !/["'`;&|^<>%$\\]/.test(arg));
}

/**
 * Start detached and return immediately.
 *
 * Deliberately NOT registered in ctx.state.jobs: a background child there becomes
 * a voice resource hold, which is exactly what made "open notepad" block the next
 * request.
 */
export function launch(entry, { platform = process.platform, spawnImpl = spawn } = {}) {
  const { exe, args } = launchCommand(entry, platform);
  const child = spawnImpl(exe, args, { detached: true, stdio: 'ignore', windowsHide: false });
  child.on?.('error', () => {}); // A failed start must not crash the assistant.
  child.unref?.();
  return true;
}

function describe(app) {
  return { name: app.name, source: app.source };
}

export async function run(args = {}, ctx = {}) {
  try {
    const wanted = String(args.name || '').trim();
    if (!wanted) return 'Error: name is required.';
    const dir = ctx.configDir || CONFIG_DIR;
    let index = loadApps(dir, { refresh: args.refresh === true, maxAgeDays: ctx.appIndexMaxAgeDays });
    let found = matchApps(index.apps, wanted);
    // A miss on a fresh index often means "installed since the last scan".
    if (found.kind === 'none' && !index.refreshed) {
      index = loadApps(dir, { refresh: true, maxAgeDays: ctx.appIndexMaxAgeDays });
      found = matchApps(index.apps, wanted);
    }
    if (args.action === 'list') {
      const limit = Math.max(1, Math.min(30, Math.floor(Number(args.limit) || LIST_LIMIT_DEFAULT)));
      const matches = found.matches.length ? found.matches : index.apps.slice(0, limit);
      return JSON.stringify({ action: 'list', total: found.matches.length || index.apps.length, apps: matches.slice(0, limit).map(describe) });
    }
    if (found.kind === 'none') {
      return JSON.stringify({ action: 'open', opened: false, found: false, total: index.apps.length,
        notice: index.apps.length ? 'No installed app matches that name. Use action=list to browse.' : 'No installed apps were found. The index may be unavailable on this system.' });
    }
    if (found.kind === 'ambiguous') {
      return JSON.stringify({ action: 'open', opened: false, ambiguous: true, candidates: found.matches.slice(0, MAX_RESULTS).map(describe),
        notice: 'Several apps match. Ask which one, then call open_app with the exact name.' });
    }
    const app = found.match;
    // `ctx.exists` lets a host (or a test) supply its own file probe.
    const problem = validateTarget(app, ctx.exists ? { exists: ctx.exists } : {});
    if (problem) return JSON.stringify({ action: 'open', opened: false, found: false, notice: problem });
    launch(app, { platform: ctx.platform, spawnImpl: ctx.spawn });
    // The audit names the app and how it was found, not its absolute path: that
    // path contains the OS user name and belongs nowhere in a shared log.
    audit(ctx, { tool: name, action: 'open', command: `${app.name} (${app.source})` });
    return JSON.stringify({ action: 'open', opened: true, app: app.name, source: app.source,
      notice: 'Started. It may take a moment to appear.' });
  } catch (error) { return `Error: ${error.message}`; }
}

/** Only a brand-new app (not in the cached index) needs an explicit approval. */
export function needsApproval(args = {}, ctx = {}) {
  if (args.action === 'list') return false;
  try {
    const index = loadApps(ctx.configDir || CONFIG_DIR, { maxAgeDays: ctx.appIndexMaxAgeDays });
    return matchApps(index.apps, args.name || '').kind === 'none';
  } catch { return true; } // Unknown state is treated as risky.
}

export function approval(args = {}, ctx = {}) {
  return `Open application: ${args.name || '(name required)'}`;
}
