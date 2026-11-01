import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

/**
 * Discover the applications installed on this machine.
 *
 * The index is the ONLY source of launchable targets: the model picks a name from
 * it, never a path. That is what keeps "open notepad" from becoming an arbitrary
 * executable. Discovery is best-effort by design — a failed scan yields fewer
 * apps, never an error the assistant has to explain.
 */
export const APP_INDEX_FILE = 'apps-index.json';
export const APP_INDEX_VERSION = 1;
export const APP_INDEX_MAX_AGE_DAYS = 7;
const SCAN_TIMEOUT_MS = 20000; // One slow Start-menu enumeration must not hang a request.
const MAX_APPS = 600; // A bound on the cache and the tool result.
const MAX_SCAN_ENTRIES = 4000; // Stop walking once this many candidates were seen: a junction to C:\ can be huge.
const RESCAN_MIN_INTERVAL_MS = 30000; // Two calls in a row must not each pay a full scan.

/** @typedef {{ name: string, target: string, args: string[], source: string }} AppEntry */

const clean = value => String(value ?? '').replace(/\s+/g, ' ').trim();

function compareEntries(a, b) {
  return a.name.localeCompare(b.name, undefined, { sensitivity: 'base' });
}

/** Drop duplicates and cap the list.
 *
 * One app appears several ways (a Start-menu AppID, a .lnk shortcut, a Store
 * AppID). Deduplicating on name+target alone leaves three "Notepad" rows, so an
 * exact-name lookup is ambiguous. The earliest source wins: Start-menu AppIDs are
 * the canonical launch handle, shortcuts are the fallback.
 */
const SOURCE_PRIORITY = ['start-apps', 'desktop-entry', 'bundle', 'shortcut'];
export function finalize(entries) {
  const byName = new Map();
  for (const entry of entries) {
    if (!entry?.name || !entry.target) continue;
    const key = clean(entry.name).toLocaleLowerCase();
    // Junk from web shortcuts inside Start menu ("== Site ==" banners) and
    // separator-only rows are not launchable applications.
    if (key.length < 2 || /^[=\-_*#\s]+$/.test(key) || /^=+.*=+$/.test(clean(entry.name))) continue;
    // A URL masquerading as a shortcut name is not an app either.
    if (/^(https?:\/\/|www\.)/i.test(key)) continue;
    const existing = byName.get(key);
    if (!existing) { byName.set(key, entry); continue; }
    const rank = item => SOURCE_PRIORITY.indexOf(item.source);
    if (rank(entry) < rank(existing)) byName.set(key, entry);
  }
  return [...byName.values()].sort(compareEntries).slice(0, MAX_APPS);
}

/* ------------------------------- Windows --------------------------------- */

/**
 * `Get-StartApps` reports display name + AppID for Start-menu entries, including
 * packaged Store apps whose executable is not a normal file path. Those launch
 * through explorer's shell handler, which is the documented way to start them.
 */
export function parseStartApps(text) {
  const out = [];
  for (const raw of String(text ?? '').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    // The table is whitespace-aligned; the AppID is the last column and never
    // contains spaces, so split from the right.
    const match = line.match(/^(.*\S)\s+(\S+)$/);
    if (!match) continue;
    const [, name, appId] = match;
    if (!appId || appId === '---' || /^Name$/.test(name)) continue;
    out.push({ name: clean(name), target: appId, args: [], source: 'start-apps' });
  }
  return out;
}

function scanWindows(run) {
  const entries = [];
  try {
    const text = run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
      'Get-StartApps | Select-Object Name,AppID | ConvertTo-Csv -NoTypeInformation'], { timeout: SCAN_TIMEOUT_MS });
    // CSV is more parseable than the aligned table, but the table parser is kept
    // for builds whose ConvertTo-Csv output is unavailable.
    const csvRows = String(text ?? '').split(/\r?\n/).slice(1);
    let parsed = 0;
    for (const row of csvRows) {
      const match = row.match(/^"((?:[^"]|"")*)","((?:[^"]|"")*)"$/);
      if (!match) continue;
      const name = match[1].replace(/""/g, '"').trim();
      const appId = match[2].trim();
      if (!name || !appId) continue;
      entries.push({ name: clean(name), target: appId, args: [], source: 'start-apps' });
      parsed++;
    }
    if (!parsed) entries.push(...parseStartApps(text));
  } catch { /* No PowerShell or a blocked policy: fall through to Start-menu links. */ }
  entries.push(...scanStartMenuLinks());
  return entries;
}

/** Shortcuts under the user and all-users Start menus are ordinary launch targets. */
function scanStartMenuLinks() {
  const roots = [
    path.join(process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming'), 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
    path.join(process.env.PROGRAMDATA || 'C:\\ProgramData', 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
  ];
  return walkFor(roots, ['.lnk', '.url']);
}

/* --------------------------------- macOS --------------------------------- */

function scanMac() {
  const roots = ['/Applications', '/System/Applications', path.join(os.homedir(), 'Applications')];
  return walkFor(roots, ['.app'], { directories: true });
}

/* --------------------------------- Linux --------------------------------- */

/** Parse a freedesktop entry: Name= for the label, Exec= for the command line. */
export function parseDesktopEntry(text) {
  let name = '', exec = '', hidden = false;
  for (const raw of String(text ?? '').split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    if (line.startsWith('Name=')) name = clean(line.slice(5));
    else if (line.startsWith('Exec=')) exec = line.slice(5).trim();
    else if (line === 'NoDisplay=true' || line === 'Hidden=true') hidden = true;
  }
  if (!name || !exec || hidden) return null;
  // Field codes (%f, %U, ...) are placeholders this launcher must not pass through.
  const argv = exec.replace(/%[a-zA-Z]/g, '').trim().split(/\s+/).filter(Boolean);
  if (!argv.length) return null;
  return { name, target: argv[0], args: argv.slice(1), source: 'desktop-entry' };
}

function scanLinux() {
  const roots = ['/usr/share/applications', '/usr/local/share/applications',
    path.join(os.homedir(), '.local', 'share', 'applications')];
  const out = [];
  for (const root of roots) {
    let names;
    try { names = fs.readdirSync(root); } catch { continue; }
    for (const file of names) {
      if (!file.endsWith('.desktop')) continue;
      try { const entry = parseDesktopEntry(fs.readFileSync(path.join(root, file), 'utf8')); if (entry) out.push(entry); }
      catch { /* An unreadable entry is skipped, not fatal. */ }
    }
  }
  return out;
}

/* -------------------------------- shared --------------------------------- */

function walkFor(roots, extensions, { directories = false } = {}) {
  const out = [];
  for (const root of roots) out.push(...walk(root, extensions, directories, 0));
  return out;
}

function walk(root, extensions, directories, depth, budget = { seen: 0 }) {
  const MAX_DEPTH = 4; // Start-menu and Applications trees are shallow; bound the walk.
  if (depth > MAX_DEPTH || budget.seen >= MAX_SCAN_ENTRIES) return [];
  let names;
  try { names = fs.readdirSync(root, { withFileTypes: true }); } catch { return []; }
  const out = [];
  for (const item of names) {
    if (budget.seen >= MAX_SCAN_ENTRIES) break;
    budget.seen++;
    const full = path.join(root, item.name);
    const ext = path.extname(item.name).toLowerCase();
    // Dirent.isDirectory() is false for symlinks, so a symlinked directory is not
    // followed. Windows junctions report as directories, hence the hard budget.
    if (directories && item.isDirectory() && extensions.includes(ext)) {
      out.push({ name: clean(path.basename(item.name, ext)), target: full, args: [], source: 'bundle' });
      continue;
    }
    if (!directories && item.isFile() && extensions.includes(ext)) {
      out.push({ name: clean(path.basename(item.name, ext)), target: full, args: [], source: 'shortcut' });
      continue;
    }
    if (item.isDirectory()) out.push(...walk(full, extensions, directories, depth + 1, budget));
  }
  return out;
}

/** Scan the current platform. `run` is injectable so tests never spawn a process. */
export function scanApps({ platform = process.platform, run = execFileSync } = {}) {
  const entries = platform === 'win32' ? scanWindows(run) : platform === 'darwin' ? scanMac() : scanLinux();
  return finalize(entries);
}

/* --------------------------------- cache --------------------------------- */

export function indexPath(dir) { return path.join(dir, APP_INDEX_FILE); }

export function readIndex(dir) {
  try {
    const data = JSON.parse(fs.readFileSync(indexPath(dir), 'utf8'));
    if (data?.version !== APP_INDEX_VERSION || !Array.isArray(data.apps)) return null;
    // The cache is a launch authority, so it is validated, never trusted blindly:
    // a hand-edited or poisoned file must not be able to name an arbitrary binary.
    const apps = data.apps.filter(isSafeEntry).slice(0, MAX_APPS);
    return { apps, scannedAt: data.scannedAt || null };
  } catch { return null; }
}

/** Shell metacharacters that let `cmd` re-parse an argument into a second command. */
const UNSAFE_TARGET = /["'`;&|^<>\r\n\t]/;
const PACKAGE_ID = /^[A-Za-z0-9._-]+_[A-Za-z0-9]+![A-Za-z0-9._-]+$/;
const GBACKSLASH = String.fromCharCode(92);

/**
 * Is this a Windows shell AppID (not a file path)?
 *
 * Two shapes: a package identity ("Publisher.App_hash!Id") and a shell-namespace
 * GUID parent ("{GUID}\program.exe"). Written with string checks because the
 * brace-plus-backslash regex is easy to get subtly wrong and impossible to read.
 */
export function isAppIdTarget(target) {
  if (typeof target !== 'string' || !target) return false;
  if (PACKAGE_ID.test(target)) return true;
  if (target[0] !== '{') return false;
  const close = target.indexOf('}');
  if (close < 0) return false;
  if (!isGuid(target.slice(1, close))) return false;
  if (target[close + 1] !== GBACKSLASH) return false;
  const program = target.slice(close + 2);
  return program.length > 0 && !program.includes(GBACKSLASH);
}

/** 8-4-4-4-12 hex, validated char by char so no pattern can hide a metacharacter. */
function isGuid(value) {
  if (value.length !== 36) return false;
  for (let i = 0; i < value.length; i++) {
    const ch = value[i];
    if (i === 8 || i === 13 || i === 18 || i === 23) { if (ch !== '-') return false; continue; }
    const hex = (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f') || (ch >= 'A' && ch <= 'F');
    if (!hex) return false;
  }
  return true;
}

/**
 * A cached entry may launch something, so it must look like something this
 * scanner could have produced: a known AppID shape, or a plain absolute path.
 *
 * `%` is unsafe because cmd expands %VAR% inside a quoted argument too, so a
 * percent-containing path could launch something other than the file that was
 * checked. Backslash is allowed: a GUID AppID legitimately contains one.
 */
export function isSafeEntry(entry) {
  if (!entry || typeof entry.name !== 'string' || typeof entry.target !== 'string') return false;
  if (!entry.name.trim() || entry.name.length > 200 || entry.target.length > 1000) return false;
  if (UNSAFE_TARGET.test(entry.target) || entry.target.includes('%')) return false;
  if (isAppIdTarget(entry.target)) return true;
  return path.isAbsolute(entry.target);
}

export function writeIndex(dir, apps, now = () => new Date()) {
  try {
    fs.mkdirSync(dir, { recursive: true });
    const safe = [...apps].filter(isSafeEntry).slice(0, MAX_APPS);
    fs.writeFileSync(indexPath(dir), JSON.stringify({ version: APP_INDEX_VERSION, scannedAt: now().toISOString(), apps: safe }, null, 2), { mode: 0o600 });
  } catch { /* A read-only config directory must not break launching. */ }
  return apps;
}

export function isFresh(index, { maxAgeDays = APP_INDEX_MAX_AGE_DAYS, now = () => new Date() } = {}) {
  if (!index?.scannedAt) return false;
  const at = Date.parse(index.scannedAt);
  if (!Number.isFinite(at)) return false;
  return now().getTime() - at < maxAgeDays * 86400000;
}

/**
 * The index the tool should search. Refreshes on first use, on staleness, when
 * forced, or when a lookup missed (a newly installed app should be found without
 * waiting a week).
 */
export function loadApps(dir, { refresh = false, maxAgeDays = APP_INDEX_MAX_AGE_DAYS, now = () => new Date(), scan = scanApps } = {}) {
  const cached = readIndex(dir);
  if (!refresh && cached && isFresh(cached, { maxAgeDays, now })) return { apps: cached.apps, scannedAt: cached.scannedAt, refreshed: false };
  // A permission check and the real call both ask for the index; without this a
  // single voice turn could pay for two full scans.
  const last = lastScanAt.get(dir) || 0;
  if (Date.now() - last < RESCAN_MIN_INTERVAL_MS) {
    return cached ? { apps: cached.apps, scannedAt: cached.scannedAt, refreshed: false } : { apps: [], scannedAt: null, refreshed: false };
  }
  lastScanAt.set(dir, Date.now());
  const apps = (() => { try { return scan(); } catch { return []; } })();
  if (!apps.length && cached) return { apps: cached.apps, scannedAt: cached.scannedAt, refreshed: false }; // A failed rescan keeps the old list.
  const scannedAt = now().toISOString();
  writeIndex(dir, apps, now);
  return { apps, scannedAt, refreshed: true };
}

const lastScanAt = new Map(); // Per config directory: cheap debounce for a whole session.
