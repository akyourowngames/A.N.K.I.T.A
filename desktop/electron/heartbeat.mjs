import { createHash, randomUUID } from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

/**
 * Anonymous usage heartbeat: opt-in only, default off.
 *
 * When the user turns it on in Settings → Privacy, Ankita sends at most one
 * small ping per install per day: a one-way hash of a random install ID, the
 * app version, and the operating system. That is the whole payload — no
 * prompts, no file paths, no conversation content, no IP address stored.
 * Daily active users = distinct install hashes per day.
 *
 * The endpoint is a Supabase table (PostgREST insert, no server code):
 * see docs/heartbeat.md for the project setup and supabase/heartbeat.sql
 * for the table. Until the endpoint is wired up the constants below stay
 * empty and the heartbeat is inert — the app behaves exactly as before.
 *
 * Failure behaviour: a failed ping is silent. Offline, endpoint down, or a
 * read-only profile all mean "no ping today" — never a blocked launch,
 * never an aggressive retry.
 */

// Supabase project URL, e.g. 'https://abcdefghijklm.supabase.co'.
// Fill these in after creating the project (docs/heartbeat.md, step 2).
// The anon key is public by design: row-level security allows inserts only,
// and the table has no select policy for anon, so counts stay dashboard-only.
export const HEARTBEAT_ENDPOINT = '';
export const HEARTBEAT_ANON_KEY = '';

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
  enabled = false,
  fetchImpl = fetch,
  now = new Date(),
} = {}) {
  if (!enabled || !endpoint || !anonKey || !version) return false;
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
    response = await fetchImpl(`${String(endpoint).replace(/\/+$/, '')}/rest/v1/heartbeats?on_conflict=install_id_hash,day`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        apikey: anonKey,
        Authorization: `Bearer ${anonKey}`,
        Prefer: 'resolution=merge-duplicates',
      },
      body,
      signal: AbortSignal.timeout(HEARTBEAT_TIMEOUT_MS),
    });
  } catch { return false; } // Offline or endpoint down: the app works exactly as before.
  if (!response?.ok) return false;
  try { writeState(file, { ...state, lastPingDay: day }); } catch { /* The ping landed; tomorrow just sends again. */ }
  return true;
}

/** Fire-and-forget wrapper for startup: never throws, never blocks launch. */
export function maybeSendHeartbeat(options = {}) {
  return Promise.resolve().then(() => sendHeartbeat(options)).catch(() => false);
}
