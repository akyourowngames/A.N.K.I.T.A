import { createHash, randomUUID } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

/**
 * Required pseudonymous usage heartbeat: one install ping per UTC day.
 *
 * Ankita sends a one-way hash of a random install ID, the app version, the
 * operating system, and the UTC day. The stable hash lets the owner recognize
 * the same install across days, but does not identify a person. The payload
 * contains no name, account, prompts, file paths, or conversation content.
 * Daily active installs = distinct install hashes per day.
 *
 * The endpoint is a Supabase table (PostgREST insert, no server code):
 * see docs/heartbeat.md for the project setup and supabase/heartbeat.sql
 * for the table. The public project endpoint is wired below; heartbeats
 * are sent automatically; Settings → Privacy explains what is collected.
 *
 * Failure behaviour: a failed ping is silent. Offline, endpoint down, or a
 * read-only profile all mean "no ping today" — never a blocked launch,
 * never an aggressive retry.
 */

// Public endpoint and publishable key for A.N.K.I.T.A's heartbeat table.
// RLS makes this key safe to ship: anon can insert, but cannot read or update.
export const HEARTBEAT_ENDPOINT = 'https://jfmsgssfeuluyvezxzic.supabase.co';
export const HEARTBEAT_ANON_KEY = 'sb_publishable_Rg_VmiUvO9BHwm2IBl6Dmw_av68hycO';

const HEARTBEAT_TIMEOUT_MS = 5000;

/** UTC calendar day, so "one ping per install per day" means the same day everywhere. */
export function heartbeatDay(now = new Date()) {
  return now.toISOString().slice(0, 10);
}

/** SHA-256 of the install ID: the server stores the hash, never the raw ID. */
export function hashInstallId(installId) {
  return createHash('sha256').update(String(installId)).digest('hex');
}

function readState(file) {
  try {
    const parsed = JSON.parse(fs.readFileSync(file, 'utf8'));
    if (parsed && typeof parsed.installId === 'string' && parsed.installId) {
      return { installId: parsed.installId, lastPingDay: typeof parsed.lastPingDay === 'string' ? parsed.lastPingDay : '' };
    }
  } catch { /* Missing or corrupt state starts fresh — never blocks launch. */ }
  return { installId: '', lastPingDay: '' };
}

function writeState(file, state) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const temp = path.join(path.dirname(file), `.${path.basename(file)}.${process.pid}.tmp`);
  try {
    fs.writeFileSync(temp, JSON.stringify(state, null, 2), { mode: 0o600 });
    fs.renameSync(temp, file);
    try { fs.chmodSync(file, 0o600); } catch { /* Windows may ignore mode changes. */ }
  } finally {
    try { fs.unlinkSync(temp); } catch {}
  }
}

/**
 * Send at most one heartbeat for today. Returns true only when a ping was
 * accepted (HTTP 2xx). Never throws: every failure path returns false.
 */
export async function sendHeartbeat({
  file,
  endpoint = HEARTBEAT_ENDPOINT,
  anonKey = HEARTBEAT_ANON_KEY,
  version = '',
  platform = process.platform,
  fetchImpl = fetch,
  now = new Date(),
} = {}) {
  if (!endpoint || !anonKey || !version) return false;
  const day = heartbeatDay(now);
  let state = readState(file);
  if (state.lastPingDay === day) return false; // Already counted today.
  if (!state.installId) {
    const installId = randomUUID();
    try {
      writeState(file, { installId, lastPingDay: '' });
      state = { installId, lastPingDay: '' };
    } catch { return false; } // Cannot persist an ID, so do not send an uncountable ping.
  }
  const body = JSON.stringify({
    install_id_hash: hashInstallId(state.installId),
    app_version: version,
    platform,
    day,
  });
  let response = null;
  try {
    response = await fetchImpl(`${String(endpoint).replace(/\/+$/, '')}/rest/v1/heartbeats`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        apikey: anonKey,
        Authorization: `Bearer ${anonKey}`,
        Prefer: 'return=minimal',
      },
      body,
      signal: AbortSignal.timeout(HEARTBEAT_TIMEOUT_MS),
    });
  } catch { return false; } // Offline or endpoint down: the app works exactly as before.
  // A duplicate means this install/day already landed (for example, the app
  // closed after the insert but before its local state file was updated).
  // Treat it as counted without granting anon any read or update access.
  if (!response?.ok && response?.status !== 409) return false;
  try { writeState(file, { ...state, lastPingDay: day }); } catch { /* The ping landed; tomorrow just sends again. */ }
  return response.ok;
}

/** Fire-and-forget wrapper for startup: never throws, never blocks launch. */
export function maybeSendHeartbeat(options = {}) {
  return Promise.resolve().then(() => sendHeartbeat(options)).catch(() => false);
}
